#!/usr/bin/env python3
"""Sweep motor-lag model parameters and rank by trajectory tracking error."""

from __future__ import annotations

import argparse
import csv
import math
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import numpy as np


def _replace_assignment(text: str, var_name: str, rhs_expr: str) -> str:
    lines = text.splitlines()
    updated = False
    for i, line in enumerate(lines):
        # Match:
        #   VAR = ...
        #   VAR: type = ...
        m = re.match(rf"^(\s*){re.escape(var_name)}(?:\s*:\s*[^=]+)?\s*=\s*(.*)$", line)
        if not m:
            continue
        indent = m.group(1)
        comment = ""
        if "#" in line:
            comment = "  #" + line.split("#", 1)[1].rstrip()
        lines[i] = f"{indent}{var_name} = {rhs_expr}{comment}"
        updated = True
        break
    if not updated:
        raise RuntimeError(f"Could not patch parameters.py: missing assignment for {var_name}")
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def patch_parameters(text: str, tau_s: float, q_scalar: float) -> str:
    out = _replace_assignment(text, "MPC_MOTOR_TAU_S", f"{tau_s}")
    q_diag = f"[{q_scalar}, {q_scalar}, {q_scalar}, {q_scalar}]"
    out = _replace_assignment(out, "MOTOR_STATE_Q_DIAG", q_diag)
    return out


def parse_int_define(data_h_path: Path, name: str) -> int:
    text = data_h_path.read_text()
    m = re.search(rf"^\s*#define\s+{name}\s+([0-9]+)\s*$", text, re.MULTILINE)
    if m is None:
        raise RuntimeError(f"Missing define in {data_h_path}: {name}")
    return int(m.group(1))


def score_trajectory(traj_csv: Path, ref_csv: Path, data_h_path: Path) -> dict[str, float]:
    tick_div = parse_int_define(data_h_path, "TRAJ_TICK_DIV")
    horizon = parse_int_define(data_h_path, "HORIZON_LENGTH")
    try:
        warmstart_pad = parse_int_define(data_h_path, "TRAJ_WARMSTART_PAD")
    except RuntimeError:
        warmstart_pad = max(horizon - 1, 0)

    refs: list[list[float]] = []
    with ref_csv.open("r", newline="") as f:
        for row in csv.DictReader(f):
            refs.append([float(row[f"x{i}"]) for i in range(12)])
    if not refs:
        raise RuntimeError(f"Empty reference CSV: {ref_csv}")

    x_rows: list[list[float]] = []
    r_rows: list[list[float]] = []
    with traj_csv.open("r", newline="") as f:
        for i, row in enumerate(csv.DictReader(f)):
            i_eff = max(0, i - 1)
            traj_sample = i_eff // tick_div
            ref_idx = traj_sample - warmstart_pad
            if 0 <= ref_idx < len(refs):
                x_rows.append([float(row[f"x{k}"]) for k in range(12)])
                r_rows.append(refs[ref_idx])

    if not x_rows:
        raise RuntimeError("No valid aligned samples to score.")

    x_arr = np.asarray(x_rows, dtype=np.float64)
    r_arr = np.asarray(r_rows, dtype=np.float64)
    err_xyz = x_arr[:, :3] - r_arr[:, :3]
    err_xy = err_xyz[:, :2]

    rmse_xyz = float(np.sqrt(np.mean(np.sum(err_xyz * err_xyz, axis=1))))
    rmse_xy = float(np.sqrt(np.mean(np.sum(err_xy * err_xy, axis=1))))

    xyz_offset = np.mean(r_arr[:, :3] - x_arr[:, :3], axis=0)
    err_xyz_aligned = (x_arr[:, :3] + xyz_offset[None, :]) - r_arr[:, :3]
    err_xy_aligned = err_xyz_aligned[:, :2]
    rmse_xyz_aligned = float(np.sqrt(np.mean(np.sum(err_xyz_aligned * err_xyz_aligned, axis=1))))
    rmse_xy_aligned = float(np.sqrt(np.mean(np.sum(err_xy_aligned * err_xy_aligned, axis=1))))

    return {
        "samples": float(x_arr.shape[0]),
        "rmse_xy": rmse_xy,
        "rmse_xyz": rmse_xyz,
        "rmse_xy_aligned": rmse_xy_aligned,
        "rmse_xyz_aligned": rmse_xyz_aligned,
        "offset_x": float(xyz_offset[0]),
        "offset_y": float(xyz_offset[1]),
        "offset_z": float(xyz_offset[2]),
    }


def parse_trajectory_csv_path(run_output: str) -> Path:
    for line in run_output.splitlines():
        if line.strip().startswith("trajectory_csv="):
            return Path(line.split("=", 1)[1].strip())
    raise RuntimeError("Could not find trajectory_csv in run_hls_closed_loop_once output.")


def parse_list_floats(raw: str) -> list[float]:
    return [float(x.strip()) for x in raw.split(",") if x.strip()]


def copy_worker_repo(main_repo_root: Path, worker_repo_root: Path) -> None:
    worker_repo_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(main_repo_root / "scripts", worker_repo_root / "scripts", dirs_exist_ok=True)
    shutil.copytree(main_repo_root / "vitis_projects", worker_repo_root / "vitis_projects", dirs_exist_ok=True)
    # header_generator.py always emits this RTL params header; workers need the path to exist.
    (worker_repo_root / "vivado_project" / "vivado_project.srcs" / "sources_1" / "new").mkdir(
        parents=True, exist_ok=True
    )


def run_candidate(
    worker_repo_root: Path,
    output_dir: str,
    sim_duration_s: float,
    sim_freq: float,
    timeout_s: float,
    tau: float,
    q_scalar: float,
) -> dict[str, Any]:
    params_path = worker_repo_root / "scripts" / "parameters.py"
    data_h_path = worker_repo_root / "vitis_projects" / "ADMM" / "data.h"
    ref_csv_path = worker_repo_root / "vitis_projects" / "ADMM" / "trajectory_refs.csv"

    base_text = params_path.read_text()
    params_path.write_text(patch_parameters(base_text, tau, q_scalar))

    cmd = [
        sys.executable,
        str(worker_repo_root / "scripts" / "run_hls_closed_loop_once.py"),
        "--sim-duration-s",
        f"{sim_duration_s:.12g}",
        "--sim-freq",
        f"{sim_freq:.12g}",
        "--timeout-s",
        f"{timeout_s:.12g}",
        "--output-dir",
        output_dir,
    ]
    proc = subprocess.run(cmd, cwd=worker_repo_root, capture_output=True, text=True)
    full_output = (proc.stdout or "") + "\n" + (proc.stderr or "")
    if proc.returncode != 0:
        return {
            "tau_s": tau,
            "q_scalar": q_scalar,
            "ok": 0,
            "error": "run_hls_closed_loop_once failed",
            "stderr_tail": "\n".join(full_output.splitlines()[-40:]),
        }

    traj_csv_path = parse_trajectory_csv_path(full_output)
    metrics = score_trajectory(traj_csv_path, ref_csv_path, data_h_path)
    row: dict[str, Any] = {
        "tau_s": tau,
        "q_scalar": q_scalar,
        "ok": 1,
        "traj_csv": str(traj_csv_path),
    }
    row.update(metrics)
    return row


def _worker_task(
    worker_id: int,
    main_repo_root: str,
    scratch_root: str,
    output_dir: str,
    sim_duration_s: float,
    sim_freq: float,
    timeout_s: float,
    candidates: list[tuple[float, float]],
) -> list[dict[str, Any]]:
    main_repo = Path(main_repo_root)
    scratch = Path(scratch_root)
    worker_repo = scratch / f"worker_{worker_id}" / "repo"
    copy_worker_repo(main_repo, worker_repo)

    results: list[dict[str, Any]] = []
    total = len(candidates)
    for idx, (tau, q_scalar) in enumerate(candidates, start=1):
        print(f"[worker {worker_id}] [{idx}/{total}] tau={tau:.6g} q={q_scalar:.6g}", flush=True)
        row = run_candidate(
            worker_repo_root=worker_repo,
            output_dir=f"{output_dir}/worker_{worker_id}",
            sim_duration_s=sim_duration_s,
            sim_freq=sim_freq,
            timeout_s=timeout_s,
            tau=tau,
            q_scalar=q_scalar,
        )
        results.append(row)
        if int(row.get("ok", 0)) == 1:
            print(
                f"[worker {worker_id}] rmse_xy={float(row['rmse_xy']):.4f} "
                f"rmse_xy_aligned={float(row['rmse_xy_aligned']):.4f}",
                flush=True,
            )
        else:
            print(
                f"[worker {worker_id}] failed tau={tau:.6g} q={q_scalar:.6g}",
                flush=True,
            )
    return results


def chunk_candidates(candidates: list[tuple[float, float]], n_chunks: int) -> list[list[tuple[float, float]]]:
    chunks: list[list[tuple[float, float]]] = [[] for _ in range(n_chunks)]
    for i, cand in enumerate(candidates):
        chunks[i % n_chunks].append(cand)
    return [c for c in chunks if c]


def main() -> int:
    parser = argparse.ArgumentParser(description="Sweep MPC motor-lag parameters.")
    parser.add_argument(
        "--taus",
        type=str,
        default="0.015,0.020,0.025,0.030,0.035",
        help="Comma-separated tau values [s].",
    )
    parser.add_argument(
        "--q-scalars",
        type=str,
        default="0.03,0.05,0.1,0.2",
        help="Comma-separated scalar values for MOTOR_STATE_Q_DIAG = [q,q,q,q].",
    )
    parser.add_argument("--sim-duration-s", type=float, default=12.0)
    parser.add_argument("--sim-freq", type=float, default=500.0)
    parser.add_argument("--timeout-s", type=float, default=1200.0)
    parser.add_argument("--output-dir", type=str, default="plots/tuning_motor_lag")
    parser.add_argument("--jobs", type=int, default=1, help="Number of parallel workers.")
    parser.add_argument(
        "--restore-original",
        action="store_true",
        help="Restore original parameters.py after sweep (do not keep best).",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    params_path = repo_root / "scripts" / "parameters.py"
    summary_csv_path = repo_root / args.output_dir / "sweep_summary.csv"
    summary_csv_path.parent.mkdir(parents=True, exist_ok=True)

    taus = parse_list_floats(args.taus)
    q_scalars = parse_list_floats(args.q_scalars)
    if not taus or not q_scalars:
        raise ValueError("Provide at least one value in --taus and --q-scalars.")
    if args.jobs < 1:
        raise ValueError("--jobs must be >= 1")

    candidates = [(tau, q) for tau in taus for q in q_scalars]
    base_text = params_path.read_text()
    results: list[dict[str, Any]] = []

    try:
        if args.jobs == 1:
            for run_idx, (tau, q_scalar) in enumerate(candidates, start=1):
                print(f"[{run_idx}/{len(candidates)}] tau={tau:.6g} q={q_scalar:.6g}", flush=True)
                row = run_candidate(
                    worker_repo_root=repo_root,
                    output_dir=args.output_dir,
                    sim_duration_s=args.sim_duration_s,
                    sim_freq=args.sim_freq,
                    timeout_s=args.timeout_s,
                    tau=tau,
                    q_scalar=q_scalar,
                )
                results.append(row)
                if int(row.get("ok", 0)) == 1:
                    print(
                        f"  rmse_xy={float(row['rmse_xy']):.4f} "
                        f"rmse_xy_aligned={float(row['rmse_xy_aligned']):.4f} "
                        f"offset=({float(row['offset_x']):.3f},{float(row['offset_y']):.3f},{float(row['offset_z']):.3f})",
                        flush=True,
                    )
                else:
                    print(f"  failed: {row.get('error', 'unknown')}", flush=True)
                    if row.get("stderr_tail"):
                        print(str(row["stderr_tail"]), file=sys.stderr)
        else:
            n_jobs = min(args.jobs, len(candidates))
            split = chunk_candidates(candidates, n_jobs)
            with tempfile.TemporaryDirectory(prefix="admm_sweep_") as scratch_root:
                futures = []
                with ProcessPoolExecutor(max_workers=n_jobs) as ex:
                    for worker_id, chunk in enumerate(split):
                        futures.append(
                            ex.submit(
                                _worker_task,
                                worker_id,
                                str(repo_root),
                                scratch_root,
                                args.output_dir,
                                args.sim_duration_s,
                                args.sim_freq,
                                args.timeout_s,
                                chunk,
                            )
                        )
                    for fut in as_completed(futures):
                        results.extend(fut.result())
    finally:
        successful = [r for r in results if int(r.get("ok", 0)) == 1]
        if successful and not args.restore_original:
            best = min(
                successful,
                key=lambda r: (float(r["rmse_xy_aligned"]), float(r["rmse_xy"])),
            )
            params_path.write_text(patch_parameters(base_text, float(best["tau_s"]), float(best["q_scalar"])))
            print(
                f"\nApplied best: tau={float(best['tau_s']):.6g}, q={float(best['q_scalar']):.6g}, "
                f"rmse_xy_aligned={float(best['rmse_xy_aligned']):.4f}",
                flush=True,
            )
        else:
            params_path.write_text(base_text)
            print("\nRestored original parameters.py", flush=True)

    if results:
        keys: list[str] = []
        for row in results:
            for k in row.keys():
                if k not in keys:
                    keys.append(k)
        with summary_csv_path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(results)
        print(f"Summary: {summary_csv_path}")
    else:
        print("No results recorded.")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
