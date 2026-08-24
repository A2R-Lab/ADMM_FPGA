#!/usr/bin/env python3
"""Vitis-backed ADMM precision and suboptimality benchmark."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
HLS_DIR = REPO_ROOT / "vitis_projects" / "ADMM"
DEFAULT_HORIZONS = [10, 20, 30, 40, 50, 70, 80, 90]
DEFAULT_ITERS = [5, 10, 20, 30]
STATE_SIZE = 12
INPUT_SIZE = 4
STAGE_SIZE = STATE_SIZE + INPUT_SIZE
DEFAULT_OSQP_MAX_ITER = 100_000
OSQP_MAX_ITER = DEFAULT_OSQP_MAX_ITER

os.environ.setdefault("MPLCONFIGDIR", "/tmp/admm_precision_mpl")


def maybe_reexec_into_venv() -> None:
    venv_python = Path.home() / "venv" / "bin" / "python"
    if os.environ.get("ADMM_PRECISION_NO_REEXEC") == "1":
        return
    if not venv_python.exists() or sys.prefix == str(venv_python.parents[1]):
        return
    env = os.environ.copy()
    env["ADMM_PRECISION_NO_REEXEC"] = "1"
    os.execve(str(venv_python), [str(venv_python), *sys.argv], env)


maybe_reexec_into_venv()

import numpy as np
import osqp
from scipy import sparse


def patch_sksparse_cholesky_compat() -> None:
    try:
        import inspect
        import sksparse.cholmod as cholmod
    except Exception:
        return
    try:
        params = inspect.signature(cholmod.cholesky).parameters
    except Exception:
        return
    if "lower" in params and "order" in params:
        return
    original = cholmod.cholesky

    def compat_cholesky(A: Any, *args: Any, lower: bool = True, order: str | None = None, **kwargs: Any) -> Any:
        del lower
        if order is not None and "ordering_method" not in kwargs:
            kwargs["ordering_method"] = order
        return original(A, *args, **kwargs)

    cholmod.cholesky = compat_cholesky


@dataclass
class Instance:
    sample_idx: int
    state: np.ndarray
    q_vec: np.ndarray
    l: np.ndarray
    u: np.ndarray
    dynamic_min: float
    dynamic_max: float
    scenario: str


def parse_int_list(text: str) -> list[int]:
    vals = [int(tok.strip()) for tok in text.split(",") if tok.strip()]
    if not vals:
        raise ValueError(f"Invalid empty integer list: {text!r}")
    return vals


def require_python_deps() -> None:
    missing: list[str] = []
    for name in ["osqp", "sksparse", "autograd"]:
        try:
            __import__(name)
        except Exception:
            missing.append(name)
    if missing:
        raise SystemExit(
            "Missing Python dependencies in the active interpreter: "
            + ", ".join(missing)
            + ". Activate/install into ~/venv before running this benchmark."
        )


def run_cmd(
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    stdout_log: Path | None = None,
    stderr_log: Path | None = None,
) -> None:
    print("+ " + " ".join(cmd), flush=True)
    try:
        proc = subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True)
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"Required executable not found: {cmd[0]}. Source the Vitis environment before running C-sim."
        ) from exc
    if stdout_log is not None:
        stdout_log.parent.mkdir(parents=True, exist_ok=True)
        stdout_log.write_text(proc.stdout)
    if stderr_log is not None:
        stderr_log.parent.mkdir(parents=True, exist_ok=True)
        stderr_log.write_text(proc.stderr)
    if proc.returncode != 0:
        if proc.stdout:
            print(proc.stdout[-4000:])
        if proc.stderr:
            print(proc.stderr[-4000:], file=sys.stderr)
        raise subprocess.CalledProcessError(proc.returncode, cmd)


def read_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def load_header_generator(horizon: int, iterations: int, use_float: bool) -> Any:
    patch_sksparse_cholesky_compat()
    env_updates = {
        "ADMM_HORIZON_LENGTH": str(horizon),
        "ADMM_ITERATIONS": str(iterations),
        "ADMM_USE_FLOAT": "1" if use_float else "0",
        "ADMM_ENABLE_TRAJECTORY": "0",
    }
    old_env = {key: os.environ.get(key) for key in env_updates}
    os.environ.update(env_updates)
    sys.path.insert(0, str(SCRIPTS_DIR))
    for module_name in ["parameters", "header_generator"]:
        sys.modules.pop(module_name, None)
    try:
        module_name = f"_admm_header_generator_h{horizon}_k{iterations}_{int(use_float)}_{time.time_ns()}"
        spec = importlib.util.spec_from_file_location(module_name, SCRIPTS_DIR / "header_generator.py")
        if spec is None or spec.loader is None:
            raise RuntimeError("Could not load scripts/header_generator.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if sys.path and sys.path[0] == str(SCRIPTS_DIR):
            sys.path.pop(0)
        for key, old_value in old_env.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value


def import_trajectory_generator() -> Any:
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        import trajectory_generator  # type: ignore

        return trajectory_generator
    finally:
        if sys.path and sys.path[0] == str(SCRIPTS_DIR):
            sys.path.pop(0)


def make_reference_bank(length: int, dt: float) -> list[tuple[str, np.ndarray, np.ndarray]]:
    tg = import_trajectory_generator()
    fig_x, fig_u = tg.generate_figure8_rollout_trajectory(
        length=length,
        dt=dt,
        amp_x=1.0,
        amp_y=1.0,
        z0=0.0,
        cycles=max(1.0, length * dt / 18.0),
    )
    ch_x, ch_u = tg.generate_planar_shape_rollout_trajectory(
        length=length,
        dt=dt,
        amp_x=0.85,
        amp_y=0.85,
        z0=0.0,
        cycles=max(1.0, length * dt / 20.0),
        shape="chicane",
        square_sharpness=2.8,
        star_points=12,
        star_inner_ratio=0.25,
        star_inner_hold=0.25,
        rose_petals=3,
        rose_mod=0.2,
        chicane_mix=0.2,
        hubstar_vertices=8,
    )
    star_x, star_u = tg.generate_planar_shape_rollout_trajectory(
        length=length,
        dt=dt,
        amp_x=0.75,
        amp_y=0.75,
        z0=0.0,
        cycles=max(1.0, length * dt / 22.0),
        shape="star_hold",
        square_sharpness=2.8,
        star_points=8,
        star_inner_ratio=0.35,
        star_inner_hold=0.2,
        rose_petals=3,
        rose_mod=0.2,
        chicane_mix=0.2,
        hubstar_vertices=8,
    )
    return [("figure8", fig_x, fig_u), ("chicane", ch_x, ch_u), ("star_hold", star_x, star_u)]


def idx_x(stage: int) -> int:
    return stage * STAGE_SIZE


def idx_u(stage: int) -> int:
    return stage * STAGE_SIZE + STATE_SIZE


def build_q_vec(
    *,
    horizon: int,
    q_diag: np.ndarray,
    r_diag: np.ndarray,
    x_ref: np.ndarray,
    u_ref: np.ndarray,
) -> np.ndarray:
    q_vec = np.zeros((horizon + 1) * STATE_SIZE + horizon * INPUT_SIZE, dtype=np.float64)
    for k in range(horizon):
        q_vec[idx_x(k) : idx_x(k) + STATE_SIZE] = -q_diag * x_ref[k]
        q_vec[idx_u(k) : idx_u(k) + INPUT_SIZE] = -r_diag * u_ref[k]
    q_vec[idx_x(horizon) : idx_x(horizon) + STATE_SIZE] = -q_diag * x_ref[horizon]
    return q_vec


def apply_instance_bounds(
    base_l: np.ndarray,
    base_u: np.ndarray,
    state: np.ndarray,
    dynamic_min: float,
    dynamic_max: float,
    horizon: int,
) -> tuple[np.ndarray, np.ndarray]:
    l = np.array(base_l, dtype=np.float64, copy=True)
    u = np.array(base_u, dtype=np.float64, copy=True)
    l[:STATE_SIZE] = state
    u[:STATE_SIZE] = state

    start_xy = (horizon + 1) * STATE_SIZE + horizon * INPUT_SIZE
    dynamic_axis = 0
    dynamic_start_stage = 10
    for stage in range(max(dynamic_start_stage, 1), horizon + 1):
        row = start_xy + (stage - 1) * 2 + dynamic_axis
        l[row] = dynamic_min
        u[row] = dynamic_max
    return l, u


def make_instances(gen: Any, horizon: int, samples: int) -> list[Instance]:
    bank = make_reference_bank(samples + horizon + 64, float(gen.quad.dt))
    q_diag = np.asarray(gen.Q_DIAG, dtype=np.float64)
    r_diag = np.asarray(gen.R_DIAG, dtype=np.float64)
    base_l = np.asarray(gen.l, dtype=np.float64)
    base_u = np.asarray(gen.u, dtype=np.float64)
    xy_min = float(gen.xy_min_eff)
    xy_max = float(gen.xy_max_eff)
    u_min = float(gen.u_min[0])
    u_max = float(gen.u_max[0])
    instances: list[Instance] = []

    for sample_idx in range(samples):
        name, x_path, u_path = bank[sample_idx % len(bank)]
        offset = (sample_idx * 7) % (x_path.shape[0] - horizon - 1)
        x_ref = np.array(x_path[offset : offset + horizon + 1], dtype=np.float64, copy=True)
        u_ref = np.array(u_path[offset : offset + horizon], dtype=np.float64, copy=True)
        scenario = name

        phase = 0.11 * sample_idx
        state = np.array(x_ref[0], dtype=np.float64, copy=True)
        state[0] += 0.025 * np.sin(phase)
        state[1] += 0.025 * np.cos(phase * 0.7)
        state[2] += 0.010 * np.sin(phase * 1.3)
        state[6] += 0.015 * np.cos(phase * 0.9)
        state[7] += 0.015 * np.sin(phase * 1.1)

        dynamic_min = xy_min
        dynamic_max = xy_max
        xy_margin = 0.15
        state[0] = np.clip(state[0], xy_min + xy_margin, xy_max - xy_margin)
        state[1] = np.clip(state[1], xy_min + xy_margin, xy_max - xy_margin)
        if sample_idx % 4 == 1:
            scenario += "+active_bounds"
            side = 1.0 if (sample_idx // 4) % 2 == 0 else -1.0
            x_ref[:, 0] = side * (0.92 * xy_max if side > 0 else 0.92 * abs(xy_min))
            u_ref[:, :] = np.clip(u_ref + 0.85 * (u_max if side > 0 else u_min), u_min, u_max)
        elif sample_idx % 4 == 2:
            scenario += "+dynamic_obstacle"
            half_width = 0.45
            center = state[0] + 0.08 * np.sin(phase)
            center = float(np.clip(center, xy_min + half_width, xy_max - half_width))
            dynamic_min = center - half_width
            dynamic_max = center + half_width
            if horizon >= 10:
                x_ref[10:, 0] = dynamic_max + 0.25
        elif sample_idx % 4 == 3:
            scenario += "+waypoint_push"
            x_ref[:, 1] = np.linspace(x_ref[0, 1], 0.90 * xy_max, horizon + 1)
            u_ref[:, :] = np.clip(u_ref + 0.25 * np.sin(np.arange(horizon)[:, None]), u_min, u_max)

        q_vec = build_q_vec(
            horizon=horizon,
            q_diag=q_diag,
            r_diag=r_diag,
            x_ref=x_ref,
            u_ref=u_ref,
        )
        l, u = apply_instance_bounds(base_l, base_u, state, dynamic_min, dynamic_max, horizon)
        instances.append(
            Instance(
                sample_idx=sample_idx,
                state=state,
                q_vec=q_vec,
                l=l,
                u=u,
                dynamic_min=dynamic_min,
                dynamic_max=dynamic_max,
                scenario=scenario,
            )
        )
    return instances


def write_csim_input(path: Path, instances: list[Instance]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        f.write(f"{len(instances)}\n")
        for inst in instances:
            vals = [
                *inst.state.tolist(),
                inst.dynamic_min,
                inst.dynamic_max,
                *inst.q_vec.tolist(),
            ]
            f.write(" ".join(f"{v:.17g}" for v in vals) + "\n")


def parse_csim_output(path: Path, expected_samples: int, expected_n_var: int) -> dict[int, np.ndarray]:
    with path.open() as f:
        header = f.readline().strip().split()
        if len(header) != 2:
            raise ValueError(f"Invalid C-sim output header in {path}")
        samples = int(header[0])
        n_var = int(header[1])
        if samples != expected_samples or n_var != expected_n_var:
            raise ValueError(
                f"C-sim output shape mismatch: got samples={samples}, n_var={n_var}; "
                f"expected samples={expected_samples}, n_var={expected_n_var}"
            )
        out: dict[int, np.ndarray] = {}
        for line in f:
            parts = line.strip().split()
            if not parts:
                continue
            sample_idx = int(parts[0])
            vals = np.asarray([float(v) for v in parts[1:]], dtype=np.float64)
            if vals.size != expected_n_var:
                raise ValueError(f"Invalid vector length for sample {sample_idx}: {vals.size}")
            out[sample_idx] = vals
    if len(out) != expected_samples:
        raise ValueError(f"Expected {expected_samples} C-sim rows, found {len(out)}")
    return out


def run_csim_mode(
    *,
    horizon: int,
    iterations: int,
    use_float: bool,
    instances: list[Instance],
    out_dir: Path,
) -> dict[int, np.ndarray]:
    gen = load_header_generator(horizon, iterations, use_float)
    n_var = int(gen.num_var)
    mode = "float" if use_float else "fixed"
    mode_dir = out_dir / f"H{horizon}_k{iterations}_{mode}"
    input_path = mode_dir / "precision_inputs.txt"
    output_path = mode_dir / "precision_outputs.txt"
    write_csim_input(input_path, instances)

    env = os.environ.copy()
    env["ADMM_PRECISION_INPUT"] = str(input_path)
    env["ADMM_PRECISION_OUTPUT"] = str(output_path)
    run_cmd(
        ["vitis-run", "--mode", "hls", "--csim", "--config", "./hls_precision_config.cfg", "--work_dir", "ADMM_precision"],
        cwd=HLS_DIR,
        env=env,
        stdout_log=mode_dir / "csim.stdout.log",
        stderr_log=mode_dir / "csim.stderr.log",
    )
    return parse_csim_output(output_path, len(instances), n_var)


def solve_osqp(P: Any, A_full: Any, q: np.ndarray, l: np.ndarray, u: np.ndarray) -> np.ndarray:
    prob = osqp.OSQP()
    prob.setup(
        sparse.csc_matrix(P),
        q,
        sparse.csc_matrix(A_full),
        l,
        u,
        eps_abs=1e-6,
        eps_rel=1e-6,
        max_iter=OSQP_MAX_ITER,
        verbose=False,
        polish=True,
    )
    res = prob.solve()
    if res.info.status_val not in (1, 2):
        raise RuntimeError(f"OSQP failed: {res.info.status}")
    return np.asarray(res.x, dtype=np.float64)


def unpack_x(w: np.ndarray, horizon: int) -> np.ndarray:
    return np.vstack([w[idx_x(k) : idx_x(k) + STATE_SIZE] for k in range(horizon + 1)])


def unpack_u(w: np.ndarray, horizon: int) -> np.ndarray:
    return np.vstack([w[idx_u(k) : idx_u(k) + INPUT_SIZE] for k in range(horizon)])


def objective(P: Any, q: np.ndarray, w: np.ndarray) -> float:
    return float(0.5 * w.dot(P @ w) + q.dot(w))


def compute_metrics(
    *,
    horizon: int,
    P: Any,
    A_full: Any,
    inst: Instance,
    w_star: np.ndarray,
    w_solver: np.ndarray,
    control_accel_scale: float,
) -> dict[str, float]:
    f_star = objective(P, inst.q_vec, w_star)
    f_solver = objective(P, inst.q_vec, w_solver)
    denom = max(abs(f_star), 1e-12)
    subopt_pct = abs(f_solver - f_star) / denom * 100.0

    u_err = unpack_u(w_solver, horizon) - unpack_u(w_star, horizon)
    x_err = unpack_x(w_solver, horizon) - unpack_x(w_star, horizon)
    mw = A_full @ w_solver
    violation = max(0.0, float(np.max(inst.l - mw)), float(np.max(mw - inst.u)))

    return {
        "suboptimality_pct": subopt_pct,
        "control_rmse": float(np.sqrt(np.mean(np.sum((u_err * control_accel_scale) ** 2, axis=1)))),
        "state_rmse": float(np.sqrt(np.mean(np.sum(x_err**2, axis=1)))),
        "state_pos_rmse_mm": float(np.sqrt(np.mean(np.sum(x_err[:, :3] ** 2, axis=1))) * 1000.0),
        "max_violation": violation,
    }


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    metrics = ["suboptimality_pct", "control_rmse", "state_rmse", "state_pos_rmse_mm", "max_violation"]
    groups: dict[tuple[int, int, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = (int(row["horizon"]), int(row["iterations"]), str(row["solver"]))
        groups.setdefault(key, []).append(row)

    summary: list[dict[str, Any]] = []
    for (horizon, iterations, solver), items in sorted(groups.items()):
        out: dict[str, Any] = {"horizon": horizon, "iterations": iterations, "solver": solver, "samples": len(items)}
        for metric in metrics:
            vals = np.asarray([float(item[metric]) for item in items], dtype=np.float64)
            out[f"{metric}_mean"] = float(np.mean(vals))
            out[f"{metric}_median"] = float(np.median(vals))
            out[f"{metric}_p95"] = float(np.percentile(vals, 95))
            out[f"{metric}_max"] = float(np.max(vals))
        summary.append(out)
    return summary


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def print_summary_table(summary_rows: list[dict[str, Any]], horizon: int, iterations: int) -> None:
    requested_horizon = horizon
    requested_iterations = iterations
    labels = {
        "OSQP": "OSQP (Double GT)",
        "ADMM_FPGA_Float": "ADMM_FPGA (Float)",
        "ADMM_FPGA_FixedPoint": "ADMM_FPGA (Fixed)",
    }
    by_solver = {
        row["solver"]: row
        for row in summary_rows
        if int(row["horizon"]) == horizon and int(row["iterations"]) == iterations
    }
    if not by_solver and summary_rows:
        available = sorted({(int(row["horizon"]), int(row["iterations"])) for row in summary_rows})
        same_iter = [pair for pair in available if pair[1] == iterations]
        same_horizon = [pair for pair in available if pair[0] == horizon]
        if same_iter:
            horizon, iterations = same_iter[-1]
        elif same_horizon:
            horizon, iterations = same_horizon[-1]
        else:
            horizon, iterations = available[-1]
        print(
            f"\nRequested summary H={requested_horizon}, k={requested_iterations} was not run; "
            f"showing H={horizon}, k={iterations} instead."
        )
        by_solver = {
            row["solver"]: row
            for row in summary_rows
            if int(row["horizon"]) == horizon and int(row["iterations"]) == iterations
        }
    print(f"\nPrecision summary for H={horizon}, k={iterations}")
    print("| Solver Variant | Mean Primal Suboptimality (%) | Control RMSE (m/s^2) | State RMSE (mm) | Max Violation (m) |")
    print("| :--- | ---: | ---: | ---: | ---: |")
    for solver in ["OSQP", "ADMM_FPGA_Float", "ADMM_FPGA_FixedPoint"]:
        row = by_solver.get(solver)
        if row is None:
            continue
        print(
            f"| {labels[solver]} | "
            f"{float(row['suboptimality_pct_mean']):.4f}% | "
            f"{float(row['control_rmse_mean']):.6f} | "
            f"{float(row['state_pos_rmse_mm_mean']):.4f} | "
            f"{float(row['max_violation_mean']):.6f} |"
        )


def make_worktree(repo_root: Path, worktree_path: Path) -> None:
    if worktree_path.exists():
        shutil.rmtree(worktree_path)
    run_cmd(
        ["git", "worktree", "add", "--detach", str(worktree_path), "HEAD"],
        cwd=repo_root,
        env=os.environ.copy(),
    )


def remove_worktree(repo_root: Path, worktree_path: Path) -> None:
    if not worktree_path.exists():
        return
    run_cmd(
        ["git", "worktree", "remove", "--force", str(worktree_path)],
        cwd=repo_root,
        env=os.environ.copy(),
    )


def run_config_subprocess(
    *,
    worktree_path: Path,
    output_dir: Path,
    horizon: int,
    iterations: int,
    samples: int,
    osqp_max_iter: int,
) -> tuple[int, int]:
    config_out = output_dir / "configs" / f"H{horizon}_k{iterations}"
    config_out.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(worktree_path / "benchmark_precision.py"),
        "--samples",
        str(samples),
        "--horizons",
        str(horizon),
        "--iters",
        str(iterations),
        "--output-dir",
        str(config_out),
        "--summary-horizon",
        str(horizon),
        "--summary-iters",
        str(iterations),
        "--jobs",
        "1",
        "--osqp-max-iter",
        str(osqp_max_iter),
    ]
    run_cmd(
        cmd,
        cwd=worktree_path,
        env=os.environ.copy(),
        stdout_log=config_out / "driver.stdout.log",
        stderr_log=config_out / "driver.stderr.log",
    )
    return horizon, iterations


def run_parallel_configs(
    *,
    args: argparse.Namespace,
    horizons: list[int],
    iter_counts: list[int],
) -> int:
    configs = [(horizon, iterations) for horizon in horizons for iterations in iter_counts]
    jobs = max(1, min(int(args.jobs), len(configs)))
    worker_root = Path(tempfile.gettempdir()) / f"admm_precision_worktrees_{os.getpid()}"
    if worker_root.exists():
        shutil.rmtree(worker_root)
    worker_root.mkdir(parents=True)

    worktrees: dict[tuple[int, int], Path] = {}
    try:
        print(f"Preparing {len(configs)} isolated worktrees in {worker_root}", flush=True)
        for horizon, iterations in configs:
            worktree_path = worker_root / f"H{horizon}_k{iterations}"
            make_worktree(REPO_ROOT, worktree_path)
            worktrees[(horizon, iterations)] = worktree_path

        print(f"Running {len(configs)} configurations with jobs={jobs}", flush=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as executor:
            future_map = {
                executor.submit(
                    run_config_subprocess,
                    worktree_path=worktrees[(horizon, iterations)],
                    output_dir=args.output_dir,
                    horizon=horizon,
                    iterations=iterations,
                    samples=args.samples,
                    osqp_max_iter=args.osqp_max_iter,
                ): (horizon, iterations)
                for horizon, iterations in configs
            }
            for future in concurrent.futures.as_completed(future_map):
                horizon, iterations = future_map[future]
                try:
                    future.result()
                except Exception as exc:
                    raise RuntimeError(f"Configuration H={horizon}, k={iterations} failed") from exc
                print(f"Completed H={horizon}, k={iterations}", flush=True)

        all_rows: list[dict[str, Any]] = []
        for horizon, iterations in configs:
            config_out = args.output_dir / "configs" / f"H{horizon}_k{iterations}"
            all_rows.extend(read_csv_rows(config_out / "precision_instances.csv"))

        summary_rows = summarize(all_rows)
        write_csv(args.output_dir / "precision_instances.csv", all_rows)
        write_csv(args.output_dir / "precision_summary.csv", summary_rows)
        (args.output_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "horizons": horizons,
                    "iterations": iter_counts,
                    "samples": args.samples,
                    "jobs": jobs,
                    "output_dir": str(args.output_dir),
                    "mode": "parallel_config_worktrees",
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        print_summary_table(summary_rows, args.summary_horizon, args.summary_iters)
        print(f"\nSaved merged results to {args.output_dir}")
        return 0
    finally:
        if not args.keep_worktrees:
            for worktree_path in worktrees.values():
                try:
                    remove_worktree(REPO_ROOT, worktree_path)
                except Exception as exc:
                    print(f"WARNING: failed to remove worktree {worktree_path}: {exc}", file=sys.stderr)
            try:
                worker_root.rmdir()
            except OSError:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark Vitis ADMM float/fixed precision against OSQP.")
    parser.add_argument("--horizons", default=",".join(map(str, DEFAULT_HORIZONS)))
    parser.add_argument("--iters", default=",".join(map(str, DEFAULT_ITERS)))
    parser.add_argument("--samples", type=int, default=1000)
    parser.add_argument("--output-dir", type=Path, default=REPO_ROOT / "results" / "precision_benchmark")
    parser.add_argument("--summary-horizon", type=int, default=40)
    parser.add_argument("--summary-iters", type=int, default=10)
    parser.add_argument(
        "--jobs",
        type=int,
        default=min(24, os.cpu_count() or 1),
        help="Parallel configuration jobs. Use 1 for sequential execution.",
    )
    parser.add_argument(
        "--keep-worktrees",
        action="store_true",
        help="Keep temporary per-configuration Git worktrees after a parallel run.",
    )
    parser.add_argument(
        "--osqp-max-iter",
        type=int,
        default=DEFAULT_OSQP_MAX_ITER,
        help="Maximum OSQP iterations for double-precision ground-truth solves.",
    )
    args = parser.parse_args()

    global OSQP_MAX_ITER
    OSQP_MAX_ITER = args.osqp_max_iter
    require_python_deps()
    horizons = parse_int_list(args.horizons)
    iter_counts = parse_int_list(args.iters)
    if args.samples <= 0:
        raise ValueError("--samples must be > 0")
    if args.jobs <= 0:
        raise ValueError("--jobs must be > 0")
    if args.osqp_max_iter <= 0:
        raise ValueError("--osqp-max-iter must be > 0")
    if not args.output_dir.is_absolute():
        args.output_dir = (REPO_ROOT / args.output_dir).resolve()
    else:
        args.output_dir = args.output_dir.resolve()

    if args.jobs > 1 and len(horizons) * len(iter_counts) > 1:
        return run_parallel_configs(args=args, horizons=horizons, iter_counts=iter_counts)

    all_rows: list[dict[str, Any]] = []
    args.output_dir.mkdir(parents=True, exist_ok=True)

    for horizon in horizons:
        for iterations in iter_counts:
            print(f"\n=== H={horizon} k={iterations} ===", flush=True)
            gen = load_header_generator(horizon, iterations, use_float=True)
            instances = make_instances(gen, horizon, args.samples)
            P = gen.P_sparse
            A_full = gen.A_full
            n_var = int(gen.num_var)
            control_accel_scale = float(gen.quad.kt / gen.quad.mass)

            print("Solving OSQP ground truth...", flush=True)
            w_star_by_idx: dict[int, np.ndarray] = {}
            for inst in instances:
                w_star = solve_osqp(P, A_full, inst.q_vec, inst.l, inst.u)
                if w_star.size != n_var:
                    raise RuntimeError(f"OSQP returned n={w_star.size}, expected {n_var}")
                w_star_by_idx[inst.sample_idx] = w_star
                metrics = compute_metrics(
                    horizon=horizon,
                    P=P,
                    A_full=A_full,
                    inst=inst,
                    w_star=w_star,
                    w_solver=w_star,
                    control_accel_scale=control_accel_scale,
                )
                all_rows.append(
                    {
                        "horizon": horizon,
                        "iterations": iterations,
                        "sample_idx": inst.sample_idx,
                        "scenario": inst.scenario,
                        "solver": "OSQP",
                        **metrics,
                    }
                )

            for solver, use_float in [("ADMM_FPGA_Float", True), ("ADMM_FPGA_FixedPoint", False)]:
                print(f"Running Vitis C-sim for {solver}...", flush=True)
                csim_outputs = run_csim_mode(
                    horizon=horizon,
                    iterations=iterations,
                    use_float=use_float,
                    instances=instances,
                    out_dir=args.output_dir / "csim",
                )
                for inst in instances:
                    w_solver = csim_outputs[inst.sample_idx]
                    metrics = compute_metrics(
                        horizon=horizon,
                        P=P,
                        A_full=A_full,
                        inst=inst,
                        w_star=w_star_by_idx[inst.sample_idx],
                        w_solver=w_solver,
                        control_accel_scale=control_accel_scale,
                    )
                    all_rows.append(
                        {
                            "horizon": horizon,
                            "iterations": iterations,
                            "sample_idx": inst.sample_idx,
                            "scenario": inst.scenario,
                            "solver": solver,
                            **metrics,
                        }
                    )

            write_csv(args.output_dir / "precision_instances.csv", all_rows)
            summary_rows = summarize(all_rows)
            write_csv(args.output_dir / "precision_summary.csv", summary_rows)

    summary_rows = summarize(all_rows)
    write_csv(args.output_dir / "precision_instances.csv", all_rows)
    write_csv(args.output_dir / "precision_summary.csv", summary_rows)
    (args.output_dir / "manifest.json").write_text(
        json.dumps(
            {
                "horizons": horizons,
                "iterations": iter_counts,
                "samples": args.samples,
                "output_dir": str(args.output_dir),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    print_summary_table(summary_rows, args.summary_horizon, args.summary_iters)
    print(f"\nSaved results to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
