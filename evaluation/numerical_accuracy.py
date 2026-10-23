#!/usr/bin/env python3
"""H27/k9 figure-eight or unchanged constrained-star solver comparison.

    python evaluation/numerical_accuracy.py

Runs the simulations on first use; caches results in ignored output/numerical.npz.
Writes output/numerical_accuracy.txt and output/numerical_convergence.{pdf,png}.
For figure-eight runs, also writes numerical_command_distribution.csv (summary statistics) and
numerical_command_errors.csv (per-instant errors). Fixed–float uses all 25,600
instants; new OSQP replays also use all instants. Older caches retain their
original OSQP sample count until refreshed with --replay-osqp.
Subsequent runs regenerate the numbers/plot from that local cache.

First run, or to rerun all simulations:
    HLS_INCLUDE=/path/to/Vitis/include OPENBLAS_NUM_THREADS=1 \
        python evaluation/numerical_accuracy.py --simulate

Add --trajectory star for the recorded star geometry and feasible-reference RMSE.
The existing output files hold the most recently simulated trajectory.

The star comparison uses independent closed-loop trajectories.
For figure-eight, the fixed rollout supplies outputs for the replay input sequence.
Float replays those same inputs with persistent solver memory. The OSQP rollout
uses the selected plant and float32 sensor/command interfaces.
Use --plant matched to regenerate the MPC's linearized model at a 1 ms timestep.
Dependencies: numpy, matplotlib; simulation also needs scipy, osqp, autograd,
scikit-sparse/SuiteSparse, g++, and Vitis headers.
"""
import argparse
import csv
import json
import os
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
OUT = HERE / "output"
DATA = OUT / "numerical.npz"
HOVER = 0.048 * 9.81 / (4 * 2.90e-6 * 65535)
OSQP_TOLERANCE = 1e-5
STAR_TRACKING_OFFSET_S = 0.140

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


def matched_plant(problem):
    """Use the same RK4/hover-linearization/drag procedure at the plant timestep."""
    step = np.eye(16)
    step[:12, :12] = problem["plant_A"]
    step[:12, 12:] = problem["plant_B"]
    rows = ",\n".join("{" + ",".join(f"{v:.17g}" for v in row) + "}" for row in step[:12])
    header = """#include <array>
std::array<double,12> matched_step(const std::array<double,12>& x,
                                  const std::array<double,4>& command) {
    static const double transition[12][16] = {ROWS};
    std::array<double,12> next = {};
    for (int i=0; i<12; ++i) {
        for (int j=0; j<12; ++j) next[i] += transition[i][j]*x[j];
        for (int j=0; j<4; ++j) next[i] += transition[i][12+j]*(command[j]-HOVER);
    }
    return next;
}
""".replace("ROWS", rows).replace("HOVER", repr(HOVER))
    return step, header


def generate_rollouts(include, trajectory="fig8", plant="nonlinear"):
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
    d = {"trajectory": trajectory, "plant": plant, "settings": json.dumps({"source_sha256": {
        f: hashlib.sha256((root / "vitis_projects/ADMM" / f).read_bytes()).hexdigest()
        for f in sources}})}
    with tempfile.TemporaryDirectory(prefix="admm-rollouts-") as directory:
        work = Path(directory)
        scripts = work / "scripts"
        project = work / "vitis_projects/ADMM"
        scripts.mkdir()
        project.mkdir(parents=True)
        (work / "vivado_project/vivado_project.srcs/sources_1/new").mkdir(parents=True)
        for name in ("parameters.py", "crazyflie_model.py", "trajectory_generator.py",
                     "header_generator.py"):
            shutil.copy2(root / "scripts" / name, scripts / name)
        for name in sources:
            shutil.copy2(root / "vitis_projects/ADMM" / name, project / name)
        env = {k: v for k, v in os.environ.items() if not k.startswith("ADMM_")}
        env.update(ADMM_HORIZON_LENGTH="27", ADMM_ITERATIONS="9",
                   ADMM_ENABLE_TRAJECTORY="1", ADMM_SOLVER_ARCH="staged_a",
                   ADMM_SIM_FREQ="1000", ADMM_SIM_DURATION_S="25.6",
                   ADMM_TRAJ_SHAPE="star_hold" if trajectory == "star" else "fig8",
                   ADMM_TRAJ_AMP_X="2" if trajectory == "star" else "1",
                   ADMM_TRAJ_AMP_Y="2" if trajectory == "star" else "1",
                   ADMM_TRAJ_STAR_POINTS="12", ADMM_TRAJ_STAR_INNER_RATIO="0.25",
                   ADMM_TRAJ_STAR_INNER_HOLD="0.25", ADMM_XY_MIN="-1", ADMM_XY_MAX="1",
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
plant = g.CrazyFlieModel(freq=1000.0)
plant_A, plant_B = plant.get_linearized_dynamics(g.xg, plant.hover_thrust)
plant_A[6, 6] -= (p.MPC_LINEAR_DRAG_XY / plant.mass) / 1000.0
plant_A[7, 7] -= (p.MPC_LINEAR_DRAG_XY / plant.mass) / 1000.0
plant_A[8, 8] -= (p.MPC_LINEAR_DRAG_Z / plant.mass) / 1000.0
np.savez('problem.npz', P=g.P_sparse.toarray(), A=g.A_full.toarray(),
         l=g.l, u=g.u, rho_eq=g.rho_eq, rho_ineq=g.rho_ineq, reference=ref, q=q,
         plant_A=plant_A, plant_B=plant_B)
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
        if plant == "matched":
            marker = "state = step12(state, actuator, dt, cfg, motor_gains);"
            assert tb.read_text().count(marker) == 1
            tb.write_text('#include "matched_plant.h"\n' + tb.read_text().replace(
                marker, "state = matched_step(state, control); actuator = control;"))
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
                    if command == commands[0] and plant == "matched":
                        d["plant_step"], d["matched_plant.h"] = matched_plant(np.load(work / "problem.npz"))
                        (project / "matched_plant.h").write_text(d["matched_plant.h"])
            p = dict(np.load(work / "problem.npz"))
            if trajectory == "star":
                recorded_star = np.loadtxt(HERE / "data/flight_metrics/star_reference.csv",
                                           delimiter=",", skiprows=1)
                np.testing.assert_allclose(p["reference"][28:, :3], recorded_star[:, 1:4],
                                           rtol=0, atol=1e-8)
                from flight_metrics import STAR_BOUNDS
                np.testing.assert_allclose([p["l"][444], p["u"][444]], STAR_BOUNDS,
                                           rtol=0, atol=1e-12)
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


def osqp_reference(d):
    """Construct the same reference QP for replay and closed-loop evaluation."""
    import osqp
    from scipy import sparse

    solver = osqp.OSQP()
    solver.setup(P=sparse.csc_matrix(d["P"]), A=sparse.csc_matrix(d["A"]),
                 q=np.zeros(len(d["P"])), l=d["l"], u=d["u"],
                 eps_abs=OSQP_TOLERANCE, eps_rel=OSQP_TOLERANCE, max_iter=1000000,
                 polish=True, verbose=False, adaptive_rho_interval=25)

    def reference(state, index, float_interface=False, statuses=None):
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
        if statuses is not None:
            statuses.append(r.info.status)
            if r.info.status_val != 1:
                return np.full(4, np.nan), [np.nan, np.nan]
        if r.info.status_val != 1:
            raise RuntimeError(f"OSQP reference failed at reference index {index}: {r.info.status}")
        residuals = [getattr(r.info, "prim_res", getattr(r.info, "pri_res", np.nan)),
                     getattr(r.info, "dual_res", getattr(r.info, "dua_res", np.nan))]
        return r.x[12:16], residuals

    return solver, reference


def replay_osqp(d):
    """Evaluate figure-eight fixed-rollout inputs without rerunning the plant."""
    import time
    import osqp

    _, reference = osqp_reference(d)
    steps = np.arange(len(d["state"]))
    commands, residuals, statuses = [], [], []
    started = time.monotonic()
    for step in steps:
        u, residual = reference(d["state"][step], d["reference_index"][step], statuses=statuses)
        if statuses[-1] == "solved" and (not np.isfinite(u).all() or not np.isfinite(residual).all()):
            raise RuntimeError(f"Non-finite OSQP replay result at step {step}")
        commands.append(u + HOVER)
        residuals.append(residual)
        if (step + 1) % 1000 == 0 or step + 1 == len(steps):
            print(f"OSQP replay: {step+1}/{len(steps)} "
                  f"({time.monotonic()-started:.1f} s)", flush=True)
    d["osqp_steps"], d["osqp_command"] = steps, np.array(commands)
    d["osqp_reference_residuals"] = np.array(residuals)
    d["osqp_replay_status"] = np.array(statuses)
    settings = json.loads(str(d["settings"]))
    settings["osqp_replay"] = dict(samples=len(steps), osqp=osqp.__version__,
        numpy=np.__version__, eps_abs=OSQP_TOLERANCE, eps_rel=OSQP_TOLERANCE, max_iter=1000000,
        polish=True, elapsed_seconds=time.monotonic()-started)
    d["settings"] = json.dumps(settings, indent=2)


def save_cache(d):
    OUT.mkdir(exist_ok=True)
    temporary = DATA.with_suffix(".partial.npz")
    np.savez_compressed(temporary, **d)
    temporary.replace(DATA)


def simulate(d, include):
    import ctypes
    import hashlib
    import shutil
    import subprocess
    import tempfile
    import osqp

    if not include:
        raise SystemExit("--simulate requires HLS_INCLUDE=/path/to/Vitis/include")
    settings = json.loads(str(d["settings"]))
    d.pop("osqp_failure", None)
    with tempfile.TemporaryDirectory(prefix="admm-numerical-") as tmp:
        tmp = Path(tmp)
        for name, expected in settings["source_sha256"].items():
            source = HERE.parent / "vitis_projects/ADMM" / name
            assert hashlib.sha256(source.read_bytes()).hexdigest() == expected, name
            shutil.copy2(source, tmp / name)
        for name in ("data.h", "traj_data.h", "admm_runtime_config.h"):
            (tmp / name).write_text(str(d[f"float_{name}"]))
        bridge = BRIDGE
        if str(d.get("plant", "nonlinear")) == "matched":
            (tmp / "matched_plant.h").write_text(str(d["matched_plant.h"]))
            bridge = '#include "matched_plant.h"\n' + BRIDGE.split('extern "C" void advance')[0] + r'''
extern "C" void advance(double *state, double *actuator, const double *command) {
    std::array<double,12> x;
    std::array<double,4> u;
    for (int i=0; i<12; ++i) x[i]=state[i];
    for (int i=0; i<4; ++i) u[i]=actuator[i]=command[i];
    auto next=matched_step(x,u);
    for (int i=0; i<12; ++i) state[i]=next[i];
}
'''
        (tmp / "bridge.cpp").write_text(bridge)
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
        if str(d.get("trajectory", "fig8")) != "star":
            # Fixed outputs are already recorded for exactly this input sequence.
            replay = np.empty_like(d["command_fixed"])
            for i, state in enumerate(d["state"]):
                lib.solve(state, int(i == 0), replay[i])
            np.testing.assert_array_equal(replay[0], d["command_float"][0])
            d["replay_float"] = replay

            replay_osqp(d)
        settings = json.loads(str(d["settings"]))
        solver, reference = osqp_reference(d)

        state, actuator = recorded[0, 1:13].copy(), recorded[0, 13:17].copy()
        trajectory = [recorded[0].copy()]
        commands, residuals = [], []
        previous = actuator.copy()
        solver.warm_start(x=np.zeros(len(d["P"])), y=np.zeros(len(d["l"])))
        for step, index in enumerate(d["reference_index"]):
            try:
                u, residual = reference(state, index, float_interface=True)
            except RuntimeError as error:
                d["osqp_failure"] = f"t={step/1000:.3f} s: {error}"
                break
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
        d["osqp_hard_bounds"] = True
        d["osqp_tolerance"] = OSQP_TOLERANCE
        settings["reproduction"] = dict(osqp=osqp.__version__, numpy=np.__version__,
            compiler=subprocess.check_output(["g++", "--version"], text=True).splitlines()[0],
            bridge_sha256=hashlib.sha256(bridge.encode()).hexdigest())
        d["settings"] = json.dumps(settings, indent=2)
        save_cache(d)


def report_commands(d):
    """Figure-eight matched-input command comparison; separate from star tracking."""
    steps = d["osqp_steps"]
    fixed, floating = d["command_fixed"], d["replay_float"]
    assert fixed.shape == floating.shape == (25600, 4), "Incomplete matched-input replay"
    solved = np.isfinite(d["osqp_command"]).all(axis=1)
    lines = [f"OSQP replay: {solved.sum()} solved; {(~solved).sum()} unsolved inputs excluded.",
             "First-command error distribution (normalized motor units):",
             "Per-instant error = max absolute difference across the four motor commands.",
             "Inputs match across solvers at each instant; instants come from one trajectory.",
             "Std is population standard deviation; percentiles use linear interpolation.",
             "Comparison       Samples          Min         Mean          Std       Median          P95          P99          Max"]
    if "osqp_replay_status" in d:
        statuses, counts = np.unique(d["osqp_replay_status"], return_counts=True)
        lines.insert(-1, "Replay status: " + ", ".join(f"{s}: {n}" for s, n in zip(statuses, counts)))
    summaries, errors = [], []
    for name, a, b, indices in (
            ("fixed–float", fixed, floating, np.arange(len(fixed))),
            ("fixed–OSQP", fixed[steps], d["osqp_command"], steps),
            ("float–OSQP", floating[steps], d["osqp_command"], steps)):
        if "OSQP" in name:
            a, b, indices = a[solved], b[solved], indices[solved]
        error = np.max(abs(a-b), axis=1)
        assert np.isfinite(error).all(), f"Non-finite {name} errors"
        if len(error):
            median, p95, p99 = np.percentile(error, [50, 95, 99])
            stats = dict(min=error.min(), mean=error.mean(), std=error.std(),
                         median=median, p95=p95, p99=p99, max=error.max())
        else:
            stats = dict.fromkeys(("min", "mean", "std", "median", "p95", "p99", "max"), np.nan)
        summaries.append(dict(comparison=name, samples=len(error), **stats))
        errors.extend((name, int(step), float(value)) for step, value in zip(indices, error))
        lines.append(f"  {name:13s} {len(error):7d} " +
                     " ".join(f"{value:12.6g}" for value in stats.values()))
    with (OUT / "numerical_command_distribution.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(summaries[0]))
        writer.writeheader()
        writer.writerows(summaries)
    with (OUT / "numerical_command_errors.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["comparison", "step", "command_error_inf"])
        writer.writerows(errors)
    return lines


def report(d):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    OUT.mkdir(exist_ok=True)
    is_star = str(d.get("trajectory", "fig8")) == "star"
    label = "constrained star" if is_star else "figure-eight"
    lines = [f"H27 / 9 iterations / {label} / persistent warm start", "",
             f"Plant: {d.get('plant', 'nonlinear')}; hard XY bounds, dynamics and motor limits for all controllers."]
    if not is_star:
        lines += report_commands(d)
    lines += ["", "All rollout samples, including entry and infeasible reference points:",
              "Controller   Tracking RMSE (m)   Max XY-bound violation (m)"]
    target = d["reference"][np.r_[d["reference_index"], d["reference_index"][-1]], :3]
    lo, hi = d["l"][444:446], d["u"][444:446]
    feasible = np.all((target[:, :2] >= lo) & (target[:, :2] <= hi), axis=1)
    # Score one full cycle after the 28-sample entry prefix; use exact playback indices.
    score = (d["trajectory_fixed"][:, 0] >= 0.56) & (d["trajectory_fixed"][:, 0] < 25.56)
    if is_star:
        cycle_reference = d["reference"][28:, :3]
        phase = d["trajectory_fixed"][:, 0] - 0.56 - STAR_TRACKING_OFFSET_S
        indices = np.floor(phase / 0.02 + 1e-8).astype(int) % len(cycle_reference)
        aligned_target = cycle_reference[indices]
        aligned_feasible = np.all((aligned_target[:, :2] >= lo) & (aligned_target[:, :2] <= hi), axis=1)
    rmses, raw_rmses = {}, {}
    for mode in ("fixed", "float", "osqp"):
        trajectory = d[f"trajectory_{mode}"]
        if mode == "osqp" and "osqp_failure" in d:
            lines.append(f"  osqp       unavailable: {d['osqp_failure']}")
            continue
        assert len(trajectory) == 25601, f"Incomplete {mode} run"
        position = trajectory[:, 1:4]
        rmse = np.sqrt(np.mean(np.sum((position-target)**2, axis=1)))
        violation = np.maximum(np.maximum(lo-position[:, :2], position[:, :2]-hi), 0).max()
        lines.append(f"  {mode:6s}     {rmse:.8f}          {violation:.6g}")
        if is_star:
            squared = np.sum((position-target)**2, axis=1)
            raw_rmses[mode] = np.sqrt(np.mean(squared[score & feasible]))
            squared = np.sum((position-aligned_target)**2, axis=1)
            rmses[mode] = np.sqrt(np.mean(squared[score & aligned_feasible]))

    if is_star:
        lines += ["", "One 25 s cycle; feasible-reference tracking (3D):",
                  f"  Scored samples: {np.sum(score & aligned_feasible)} / {np.sum(score)}",
                  "  Controller   Raw RMSE (cm)   Lag-corrected RMSE (cm)   Difference vs OSQP (%)"]
        for mode, rmse in rmses.items():
            excess = f"{100*(rmse/rmses['osqp']-1):+.3f}" if "osqp" in rmses else "unavailable"
            lines.append(f"  {mode:6s}       {100*raw_rmses[mode]:.4f}         {100*rmse:.4f}                  {excess}")
        residuals = d["osqp_rollout_residuals"]
        if len(residuals):
            lines.append(f"  OSQP maximum primal / dual residual over completed solves: "
                         f"{residuals[:, 0].max():.3g} / {residuals[:, 1].max():.3g}")
        lines += [f"  OSQP: eps_abs=eps_rel={float(d['osqp_tolerance']):g}; max_iter=1000000; polishing enabled.",
                  "  Identical plant; OSQP solve time does not advance simulated time.",
                  "  Reference matches bundled STAR CSV; lag correction affects scoring only."]
        if str(d.get("plant", "nonlinear")) == "matched":
            lines.append("  Matched plant: same RK4/hover-linearization/drag procedure at 1 ms; MPC remains at 20 ms.")
        if "osqp_failure" in d:
            lines.append("  No full-cycle OSQP RMSE or relative tracking claim: baseline did not complete.")

    plt.rcParams.update({"font.size": 12, "axes.labelsize": 13})
    fig, axes = plt.subplots(1, 3 if is_star else 2,
                             figsize=(14 if is_star else 9, 3.5), layout="constrained")
    common = d["iterations_fixed"][d["iterations_fixed"][:, 1] == 1, 0]
    for mode, color, style in (("fixed", "#00693E", "-o"), ("float", "#666666", "--")):
        rows, medians = d[f"iterations_{mode}"], []
        for k in range(1, 10):
            subset = rows[rows[:, 1] == k]
            np.testing.assert_array_equal(subset[:, 0], common)
            medians.append(np.median(subset[:, 2:4], axis=0))
        for col, ax in enumerate(axes[:2]):
            ax.semilogy(range(1, 10), np.array(medians)[:, col], style,
                        color=color, label=mode.capitalize())
    for ax, ylabel in zip(axes, ("Median equality residual", "Median stationarity residual")):
        ax.set(xlabel="ADMM iteration", ylabel=ylabel, xticks=[1, 3, 5, 7, 9])
        ax.grid(True, which="both", alpha=.2)
        ax.legend()
    if is_star:
        from matplotlib.patches import Rectangle
        ax = axes[2]
        ax.plot(target[score, 0], target[score, 1], "--", color="0.6", lw=.8, label="Reference")
        ax.add_patch(Rectangle(lo, *(hi-lo), fill=False, edgecolor="0.4"))
        for mode, color in (("fixed", "#00693E"), ("osqp", "#a12b2b")):
            trajectory = d[f"trajectory_{mode}"]
            position = trajectory[score[:len(trajectory)], 1:3]
            label = ("OSQP" + (" (stopped)" if "osqp_failure" in d else "")) if mode == "osqp" else mode.upper()
            ax.plot(position[:, 0], position[:, 1], color=color, lw=1, label=label)
        ax.set(xlabel="x (m)", ylabel="y (m)",
               title=f"Constrained star — {d.get('plant', 'nonlinear')} plant", aspect="equal")
        ax.legend()
        ax.grid(alpha=.2)
    fig.savefig(OUT / "numerical_convergence.pdf")
    fig.savefig(OUT / "numerical_convergence.png", dpi=200)
    plt.close(fig)
    lines += ["", "Plot: the same 256 solves at every iteration; residuals have mixed model units.",
              "Zero XY violation does not imply exact QP feasibility.",
              "Scope: warm-started tracking."]
    text = "\n".join(lines) + "\n"
    (OUT / "numerical_accuracy.txt").write_text(text)
    print(text, end="")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--simulate", action="store_true")
    modes.add_argument("--replay-osqp", action="store_true",
                       help="Solve OSQP at every cached input; preserve existing rollouts")
    parser.add_argument("--trajectory", choices=("fig8", "star"), default="fig8")
    parser.add_argument("--plant", choices=("nonlinear", "matched"), default="nonlinear")
    args = parser.parse_args()
    if args.replay_osqp and args.trajectory == "star":
        parser.error("--replay-osqp is only used for the figure-eight command comparison")
    if args.replay_osqp and not DATA.exists():
        parser.error("--replay-osqp requires an existing numerical.npz cache")
    if args.simulate or not DATA.exists():
        data = generate_rollouts(os.environ.get("HLS_INCLUDE"), args.trajectory, args.plant)
        OUT.mkdir(exist_ok=True)
        np.savez_compressed(DATA, **data)
    else:
        data = dict(np.load(DATA, allow_pickle=False))
        if str(data.get("trajectory", "fig8")) != args.trajectory:
            parser.error("Cached trajectory differs; rerun with --simulate.")
        if str(data.get("plant", "nonlinear")) != args.plant:
            parser.error("Cached plant differs; rerun with --simulate.")
    if args.replay_osqp:
        replay_osqp(data)
        save_cache(data)
    elif (args.simulate or "trajectory_osqp" not in data
            or not bool(data.get("osqp_hard_bounds", False))
            or float(data.get("osqp_tolerance", 0)) != OSQP_TOLERANCE):
        simulate(data, os.environ.get("HLS_INCLUDE"))
    report(data)
