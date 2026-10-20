#!/usr/bin/env python3
"""H27/k9 figure-eight numerical accuracy: two small tables and one plot.

    python evaluation/numerical_accuracy.py

Runs the simulations on first use; caches results in ignored output/numerical.npz.
Writes output/numerical_accuracy.txt and output/numerical_convergence.{pdf,png}.
Subsequent runs regenerate the numbers/plot from that local cache.

First run, or to rerun all simulations:
    HLS_INCLUDE=/path/to/Vitis/include OPENBLAS_NUM_THREADS=1 \
        python evaluation/numerical_accuracy.py --simulate

The fixed rollout supplies outputs for the replay input sequence.
Float replays those same inputs with persistent solver memory. The OSQP rollout
uses the existing C++ nonlinear plant and float32 sensor/command interfaces.
Dependencies: numpy, matplotlib; simulation also needs scipy, osqp, autograd,
scikit-sparse/SuiteSparse, g++, and Vitis headers.
"""
import argparse
import json
import os
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
OUT = HERE / "output"
DATA = OUT / "numerical.npz"
HOVER = 0.048 * 9.81 / (4 * 2.90e-6 * 65535)

# Temporary C interface to the existing solver and plant; no production edits.
BRIDGE = r"""
#define main unused_testbench_main
#include "ADMM_closed_loop_tb.cpp"
#undef main
extern "C" void solve(const double *state, int first, double *command) {
    current_state_t in = {};
    for (int i=0; i<12; ++i) in.state[i] = (fp_t)state[i];
    in.constraints = 0;
    in.traj_cmd = first ? 3 : 0;
    ap_uint<128> bits = 0;
    ADMM_solver(pack_current_state_bits(in), bits);
    auto out = unpack_command_out(bits);
    command[0]=out.u0; command[1]=out.u1; command[2]=out.u2; command[3]=out.u3;
}
extern "C" void advance(double *state, double *actuator, const double *command) {
    const SimConfig cfg;
    constexpr double dt=0.001;
    std::array<double,12> x;
    std::array<double,4> u;
    for (int i=0; i<12; ++i) x[i]=state[i];
    for (int i=0; i<4; ++i) {
        actuator[i]=clamp(actuator[i]+dt/(cfg.motor_time_constant_s+dt)
                         *(command[i]-actuator[i]),0.0,1.0);
        u[i]=actuator[i];
    }
    const std::array<double,4> gains = {
        1-cfg.rotor_imbalance, 1+cfg.rotor_imbalance,
        1-0.5*cfg.rotor_imbalance, 1+0.5*cfg.rotor_imbalance};
    auto next=step12(x,u,dt,cfg,gains);
    for (int i=0; i<12; ++i) state[i]=next[i];
    state[5]+=cfg.yaw_drift_rate_rad_s*dt;
}
"""


def generate_rollouts(include):
    """Generate inputs and run actual fixed/float C++ in an isolated directory."""
    import hashlib
    import shutil
    import subprocess
    import sys
    import tempfile
    import time
    from scipy import sparse

    if not include:
        raise SystemExit("Set HLS_INCLUDE=/path/to/Vitis/include for the first run.")
    root = HERE.parent
    sources = ("ADMM.cpp", "ADMM.h", "data_types.h", "ADMM_closed_loop_tb.cpp")
    d = {"settings": json.dumps({"source_sha256": {
        f: hashlib.sha256((root / "vitis_projects/ADMM" / f).read_bytes()).hexdigest()
        for f in sources}})}
    with tempfile.TemporaryDirectory(prefix="admm-rollouts-") as directory:
        work = Path(directory)
        scripts = work / "scripts"
        project = work / "vitis_projects/ADMM"
        scripts.mkdir()
        project.mkdir(parents=True)
        (work / "vivado_project/vivado_project.srcs/sources_1/new").mkdir(parents=True)
        for name in ("parameters.py", "crazyloihimodel.py", "trajectory_generator.py",
                     "header_generator.py"):
            shutil.copy2(root / "scripts" / name, scripts / name)
        for name in sources:
            shutil.copy2(root / "vitis_projects/ADMM" / name, project / name)
        env = {k: v for k, v in os.environ.items() if not k.startswith("ADMM_")}
        env.update(ADMM_HORIZON_LENGTH="27", ADMM_ITERATIONS="9",
                   ADMM_ENABLE_TRAJECTORY="1", ADMM_SOLVER_ARCH="staged_a",
                   ADMM_SIM_FREQ="1000", ADMM_SIM_DURATION_S="25.6",
                   ADMM_TRAJ_SHAPE="fig8", ADMM_TRAJ_AMP_X="1", ADMM_TRAJ_AMP_Y="1",
                   ADMM_REPETITIONS="1", ADMM_STEP_X="0", ADMM_STEP_Y="0",
                   ADMM_STEP_Z="0", ADMM_STEP_YAW="0", ADMM_FAIL_ON_EARLY_STOP="1",
                   ADMM_CSIM_TRAJ_PATH=str(work / "trajectory.csv"),
                   OPENBLAS_NUM_THREADS="1", MPLCONFIGDIR=str(work / "mpl"))
        generation = """
import sys, numpy as np
sys.path.insert(0, 'scripts')
import trajectory_generator as tg
assert tg.main() == 0
import header_generator as g
import parameters as p
ref = np.genfromtxt('vitis_projects/ADMM/trajectory_refs.csv', delimiter=',', names=True)
ref = np.column_stack([ref['x'+str(i)] for i in range(12)])
q = tg.build_traj_q_packed(ref, np.zeros((len(ref),4)), np.array(p.Q_DIAG),
                         np.array(p.R_DIAG), p.HORIZON_LENGTH, p.TRAJ_ENTRY_ZERO_PAD)
np.savez('problem.npz', P=g.P_sparse.toarray(), A=g.A_full.toarray(),
         l=g.l, u=g.u, rho_eq=g.rho_eq, rho_ineq=g.rho_ineq, reference=ref, q=q)
"""
        # Observe outputs and sampled iterations without changing solver arithmetic.
        solver = project / "ADMM.cpp"
        text = solver.read_text()
        marker = "        ADMM_iteration(x, b, y, current_state_vec, use_traj_q, traj_idx, dynamic_min, dynamic_max);"
        assert text.count(marker) == 1
        observer = r"""
        static std::ofstream finals("final.csv"), samples("samples.csv");
        static int call = 0;
        finals.precision(17); samples.precision(17);
        if (call % 100 == 0) {
            samples << call << ',' << iter+1;
            for (int j=0;j<N_VAR;++j) samples << ',' << (double)x[j];
            for (int j=0;j<N_CONSTR;++j) samples << ',' << (double)y[j];
            samples << '\n';
        }
        if (iter == ADMM_ITERATIONS-1) {
            for (int j=0;j<12;++j) finals << (double)current_state_vec[j] << ',';
            for (int j=12;j<16;++j) finals << (double)(fp_t)(x[j]+(fp_t)U_HOVER) << ',';
            finals << traj_idx << '\n';
            ++call;
        }
"""
        solver.write_text("#include <fstream>\n" + text.replace(marker, marker+observer))
        tb = project / "ADMM_closed_loop_tb.cpp"
        tb.write_text(tb.read_text().replace("    f << \"t\";", "    f.precision(17);\n    f << \"t\";")
                      .replace("static_cast<double>(U_HOVER)", repr(HOVER)))
        for mode in ("fixed", "float"):
            started = time.monotonic()
            print(f"Generating and running {mode} H27/k9 rollout...", flush=True)
            env["ADMM_USE_FLOAT"] = str(int(mode == "float"))
            commands = [[sys.executable, "-c", generation],
                        ["g++", "-O2", "-std=c++14", "-Wno-unknown-pragmas", "-I"+include,
                         str(solver), str(tb), "-o", str(work / "rollout")],
                        [str(work / "rollout")]]
            with (work / "run.log").open("w+") as log:
                for command in commands:
                    result = subprocess.run(command, cwd=work, env=env,
                                            stdout=log, stderr=subprocess.STDOUT)
                    if result.returncode:
                        log.seek(0)
                        raise RuntimeError(log.read()[-8000:])
            p = dict(np.load(work / "problem.npz"))
            d.update(p)
            for name in ("data.h", "traj_data.h", "admm_runtime_config.h"):
                d[f"{mode}_{name}"] = (project / name).read_text()
            d[f"trajectory_{mode}"] = np.loadtxt(work / "trajectory.csv",
                                                delimiter=",", skiprows=1)[:, :17]
            final = np.loadtxt(work / "final.csv", delimiter=",")
            d[f"command_{mode}"] = final[:, 12:16].copy()
            if mode == "fixed":
                d["state"] = final[:, :12].copy()
                d["reference_index"] = final[:, -1].astype(int)
            samples = np.loadtxt(work / "samples.csv", delimiter=",")
            A, P = sparse.csc_matrix(p["A"]), sparse.csc_matrix(p["P"])
            rho = np.r_[np.full(336, p["rho_eq"]), np.full(162, p["rho_ineq"])]
            residuals = []
            for row in samples:
                step, iteration = map(int, row[:2])
                x, y = row[2:446], row[446:]
                q = np.zeros(444)
                values = np.round(p["q"][int(final[step, -1]):int(final[step, -1])+28], 8)
                values = (np.clip(np.floor(values*2**22+.5)/2**22, -512, 512-2**-22)
                          if mode == "fixed" else values.astype(np.float32).astype(float))
                for k in range(28):
                    q[16*k:16*k+3] = values[k]
                equality = A[:336] @ x - np.r_[final[step, :12], p["l"][12:336]]
                residuals.append([step, iteration, max(abs(equality)),
                                  max(abs(P@x + q + A.T@(rho*y)))])
            d[f"iterations_{mode}"] = np.array(residuals)
            print(f"{mode} rollout completed in {time.monotonic()-started:.1f} s.", flush=True)
    return d


def simulate(d, include):
    import ctypes
    import hashlib
    import shutil
    import subprocess
    import tempfile
    import osqp
    from scipy import sparse

    if not include:
        raise SystemExit("--simulate requires HLS_INCLUDE=/path/to/Vitis/include")
    settings = json.loads(str(d["settings"]))
    with tempfile.TemporaryDirectory(prefix="admm-numerical-") as tmp:
        tmp = Path(tmp)
        for name, expected in settings["source_sha256"].items():
            source = HERE.parent / "vitis_projects/ADMM" / name
            assert hashlib.sha256(source.read_bytes()).hexdigest() == expected, name
            shutil.copy2(source, tmp / name)
        for name in ("data.h", "traj_data.h", "admm_runtime_config.h"):
            (tmp / name).write_text(str(d[f"float_{name}"]))
        (tmp / "bridge.cpp").write_text(BRIDGE)
        subprocess.run(["g++", "-O2", "-std=c++14", "-shared", "-fPIC",
                        "-Wno-unknown-pragmas", "-I"+include,
                        "-DDYNAMIC_CONSTRAINT_AXIS=0", "-DDYNAMIC_CONSTRAINT_START_STAGE=10",
                        str(tmp / "ADMM.cpp"), str(tmp / "bridge.cpp"),
                        "-o", str(tmp / "solver.so")], check=True)
        lib = ctypes.CDLL(str(tmp / "solver.so"))
        array = np.ctypeslib.ndpointer(dtype=np.float64, flags="C_CONTIGUOUS")
        lib.solve.argtypes = [array, ctypes.c_int, array]
        lib.advance.argtypes = [array, array, array]
        lib.solve.restype = lib.advance.restype = None

        recorded = d["trajectory_float"]
        # Fixed outputs are already recorded for exactly this input sequence.
        replay = np.empty_like(d["command_fixed"])
        for i, state in enumerate(d["state"]):
            lib.solve(state, int(i == 0), replay[i])
        np.testing.assert_array_equal(replay[0], d["command_float"][0])
        d["replay_float"] = replay

        solver = osqp.OSQP()
        solver.setup(P=sparse.csc_matrix(d["P"]), A=sparse.csc_matrix(d["A"]),
                     q=np.zeros(len(d["P"])), l=d["l"], u=d["u"],
                     eps_abs=1e-7, eps_rel=1e-7, max_iter=100000, polish=True, verbose=False)

        def reference(state, index, float_interface=False):
            q = np.zeros(len(d["P"]))
            values = np.round(d["q"][index:index+28], 8)
            if float_interface:
                values = values.astype(np.float32).astype(float)
                state = state.astype(np.float32).astype(float)
            for k in range(28):
                q[k*16:k*16+3] = values[k]
            lo, hi = d["l"].copy(), d["u"].copy()
            lo[:12] = hi[:12] = state
            solver.update(q=q, l=lo, u=hi)
            r = solver.solve()
            if r.info.status_val != 1:
                raise RuntimeError(f"OSQP reference failed: {r.info.status}")
            residuals = [getattr(r.info, "prim_res", getattr(r.info, "pri_res", np.nan)),
                         getattr(r.info, "dual_res", getattr(r.info, "dua_res", np.nan))]
            return r.x[12:16], residuals

        steps = np.unique(np.r_[np.arange(0, 25600, 100), 25599])
        commands, residuals = [], []
        for step in steps:
            u, residual = reference(d["state"][step], d["reference_index"][step])
            commands.append(u+HOVER)
            residuals.append(residual)
        d["osqp_steps"], d["osqp_command"] = steps, np.array(commands)
        d["osqp_reference_residuals"] = np.array(residuals)

        state, actuator = recorded[0, 1:13].copy(), recorded[0, 13:17].copy()
        trajectory = [recorded[0].copy()]
        commands, residuals = [], []
        previous = actuator.copy()
        solver.warm_start(x=np.zeros(len(d["P"])), y=np.zeros(len(d["l"])))
        for step, index in enumerate(d["reference_index"]):
            u, residual = reference(state, index, float_interface=True)
            command = (u.astype(np.float32)+np.float32(HOVER)).astype(float)
            if (not np.isfinite(command).all() or np.any(command < -.02)
                    or np.any(command > 1.02) or max(abs(command-previous)) > .45):
                raise RuntimeError(f"OSQP command stop at {step}")
            previous = command
            lib.advance(state, actuator, command)
            trajectory.append(np.r_[recorded[step+1, 0], state, actuator])
            commands.append(command); residuals.append(residual)
            if (not np.isfinite(state).all() or np.any(abs(state[:3]) > [3, 3, 1])
                    or np.any(abs(state[3:5]) > .45) or np.any(abs(state[9:]) > 8)):
                raise RuntimeError(f"OSQP state stop at {step+1}")
            if step % 5000 == 0:
                print(f"OSQP rollout: {step}/25600", flush=True)
        d["trajectory_osqp"] = np.array(trajectory)
        d["command_osqp"] = np.array(commands)
        d["osqp_rollout_residuals"] = np.array(residuals)
        settings["reproduction"] = dict(osqp=osqp.__version__, numpy=np.__version__,
            compiler=subprocess.check_output(["g++", "--version"], text=True).splitlines()[0],
            bridge_sha256=hashlib.sha256(BRIDGE.encode()).hexdigest())
        d["settings"] = json.dumps(settings, indent=2)
        OUT.mkdir(exist_ok=True)
        temporary = DATA.with_suffix(".partial.npz")
        np.savez_compressed(temporary, **d)
        temporary.replace(DATA)


def report(d):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    OUT.mkdir(exist_ok=True)
    steps = d["osqp_steps"]
    fixed, floating = d["command_fixed"][steps], d["replay_float"][steps]
    lines = ["H27 / 9 iterations / figure-eight / persistent warm start", "",
             "First-command error, p95 (normalized motor units; 257 identical-input samples):"]
    for name, a, b in (("fixed–float", fixed, floating),
                       ("fixed–OSQP", fixed, d["osqp_command"]),
                       ("float–OSQP", floating, d["osqp_command"])):
        lines.append(f"  {name}: {np.percentile(np.max(abs(a-b), axis=1), 95):.6g}")
    lines += ["", "Controller   Tracking RMSE (m)   Max XY-bound violation (m)"]
    target = d["reference"][np.r_[d["reference_index"], d["reference_index"][-1]], :3]
    lo, hi = d["l"][444:446], d["u"][444:446]
    for mode in ("fixed", "float", "osqp"):
        trajectory = d[f"trajectory_{mode}"]
        assert len(trajectory) == 25601, f"Incomplete {mode} run"
        position = trajectory[:, 1:4]
        rmse = np.sqrt(np.mean(np.sum((position-target)**2, axis=1)))
        violation = np.maximum(np.maximum(lo-position[:, :2], position[:, :2]-hi), 0).max()
        lines.append(f"  {mode:6s}     {rmse:.8f}          {violation:.6g}")

    plt.rcParams.update({"font.size": 12, "axes.labelsize": 13})
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.5), layout="constrained")
    common = d["iterations_fixed"][d["iterations_fixed"][:, 1] == 1, 0]
    for mode, color, style in (("fixed", "#00693E", "-o"), ("float", "#666666", "--")):
        rows, medians = d[f"iterations_{mode}"], []
        for k in range(1, 10):
            subset = rows[rows[:, 1] == k]
            np.testing.assert_array_equal(subset[:, 0], common)
            medians.append(np.median(subset[:, 2:4], axis=0))
        for col, ax in enumerate(axes):
            ax.semilogy(range(1, 10), np.array(medians)[:, col], style,
                        color=color, label=mode.capitalize())
    for ax, ylabel in zip(axes, ("Median equality residual", "Median stationarity residual")):
        ax.set(xlabel="ADMM iteration", ylabel=ylabel, xticks=[1, 3, 5, 7, 9])
        ax.grid(True, which="both", alpha=.2)
        ax.legend()
    fig.savefig(OUT / "numerical_convergence.pdf")
    fig.savefig(OUT / "numerical_convergence.png", dpi=200)
    plt.close(fig)
    lines += ["", "Plot: the same 256 solves at every iteration; residuals have mixed model units.",
              "Zero XY violation does not imply exact QP feasibility.",
              "Scope: warm-started tracking. Existing higher-iteration cold-start tests show",
              "fixed-point failures; these results do not establish general convergence."]
    text = "\n".join(lines) + "\n"
    (OUT / "numerical_accuracy.txt").write_text(text)
    print(text, end="")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--simulate", action="store_true")
    args = parser.parse_args()
    if args.simulate or not DATA.exists():
        data = generate_rollouts(os.environ.get("HLS_INCLUDE"))
        simulate(data, os.environ.get("HLS_INCLUDE"))
    else:
        data = dict(np.load(DATA, allow_pickle=False))
    report(data)
