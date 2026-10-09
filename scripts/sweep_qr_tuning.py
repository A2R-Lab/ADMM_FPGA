#!/usr/bin/env python3
"""Sweep MPC Q/R weight scalings and rank by trajectory tracking error."""

from __future__ import annotations

import argparse
import ast
import csv
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import numpy as np


def parse_list_floats(raw: str) -> list[float]:
    return [float(x.strip()) for x in raw.split(",") if x.strip()]


def get_list_assignment(text: str, var_name: str) -> list[float]:
    m = re.search(rf"^\s*{re.escape(var_name)}(?:\s*:\s*[^=]+)?\s*=\s*(.+?)\s*$", text, re.MULTILINE)
    if m is None:
        raise RuntimeError(f"Missing assignment for {var_name}")
    values = ast.literal_eval(m.group(1))
    if not isinstance(values, list):
        raise RuntimeError(f"{var_name} must be a list")
    return [float(v) for v in values]


def replace_assignment(text: str, var_name: str, rhs_expr: str) -> str:
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = re.match(rf"^(\s*){re.escape(var_name)}(?:\s*:\s*[^=]+)?\s*=\s*(.*)$", line)
        if not m:
            continue
        indent = m.group(1)
        comment = ""
        if "#" in line:
            comment = "  #" + line.split("#", 1)[1].rstrip()
        lines[i] = f"{indent}{var_name} = {rhs_expr}{comment}"
        return "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    raise RuntimeError(f"Missing assignment for {var_name}")


def format_list(values: list[float]) -> str:
    return "[" + ", ".join(f"{v:.12g}" for v in values) + "]"


def patch_qr(
    text: str,
    base_q: list[float],
    base_r: list[float],
    q_pos_scale: float,
    q_att_scale: float,
    q_vel_scale: float,
    q_rate_scale: float,
    r_scale: float,
) -> str:
    if len(base_q) != 12 or len(base_r) != 4:
        raise RuntimeError("Expected Q_DIAG(12) and R_DIAG(4).")
    q = list(base_q)
    for i in (0, 1, 2):
        q[i] *= q_pos_scale
    for i in (3, 4, 5):
        q[i] *= q_att_scale
    for i in (6, 7, 8):
        q[i] *= q_vel_scale
    for i in (9, 10, 11):
        q[i] *= q_rate_scale
    r = [v * r_scale for v in base_r]
    out = replace_assignment(text, "Q_DIAG", format_list(q))
    out = replace_assignment(out, "R_DIAG", format_list(r))
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
    raise RuntimeError("Could not find trajectory_csv in run output.")


def copy_worker_repo(main_repo_root: Path, worker_repo_root: Path) -> None:
    worker_repo_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(main_repo_root / "scripts", worker_repo_root / "scripts", dirs_exist_ok=True)
    shutil.copytree(main_repo_root / "vitis_projects", worker_repo_root / "vitis_projects", dirs_exist_ok=True)
    (worker_repo_root / "vivado_project" / "vivado_project.srcs" / "sources_1" / "new").mkdir(
        parents=True, exist_ok=True
    )


def run_candidate(
    worker_repo_root: Path,
    output_dir: str,
    sim_duration_s: float,
    sim_freq: float,
    timeout_s: float,
    base_q: list[float],
    base_r: list[float],
    c: tuple[float, float, float, float, float],
) -> dict[str, Any]:
    q_pos, q_att, q_vel, q_rate, r_scale = c
    params_path = worker_repo_root / "scripts" / "parameters.py"
    base_text = params_path.read_text()
    params_path.write_text(
        patch_qr(
            base_text,
            base_q=base_q,
            base_r=base_r,
            q_pos_scale=q_pos,
            q_att_scale=q_att,
            q_vel_scale=q_vel,
            q_rate_scale=q_rate,
            r_scale=r_scale,
        )
    )

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
            "q_pos_scale": q_pos,
            "q_att_scale": q_att,
            "q_vel_scale": q_vel,
            "q_rate_scale": q_rate,
            "r_scale": r_scale,
            "ok": 0,
            "error": "run_hls_closed_loop_once failed",
            "stderr_tail": "\n".join(full_output.splitlines()[-40:]),
        }

    traj_csv_path = parse_trajectory_csv_path(full_output)
    metrics = score_trajectory(
        traj_csv=traj_csv_path,
        ref_csv=worker_repo_root / "vitis_projects" / "ADMM" / "trajectory_refs.csv",
        data_h_path=worker_repo_root / "vitis_projects" / "ADMM" / "data.h",
    )
    row: dict[str, Any] = {
        "q_pos_scale": q_pos,
        "q_att_scale": q_att,
        "q_vel_scale": q_vel,
        "q_rate_scale": q_rate,
        "r_scale": r_scale,
        "ok": 1,
        "traj_csv": str(traj_csv_path),
    }
    row.update(metrics)
    return row


def chunk_candidates(cands: list[tuple[float, float, float, float, float]], n_chunks: int) -> list[list[tuple[float, float, float, float, float]]]:
    chunks: list[list[tuple[float, float, float, float, float]]] = [[] for _ in range(n_chunks)]
    for i, c in enumerate(cands):
        chunks[i % n_chunks].append(c)
    return [c for c in chunks if c]


def worker_task(
    worker_id: int,
    main_repo_root: str,
    scratch_root: str,
    output_dir: str,
    sim_duration_s: float,
    sim_freq: float,
    timeout_s: float,
    base_q: list[float],
    base_r: list[float],
    cands: list[tuple[float, float, float, float, float]],
) -> list[dict[str, Any]]:
    main_repo = Path(main_repo_root)
    scratch = Path(scratch_root)
    worker_repo = scratch / f"worker_{worker_id}" / "repo"
    copy_worker_repo(main_repo, worker_repo)
    results: list[dict[str, Any]] = []
    for idx, c in enumerate(cands, start=1):
        print(f"[worker {worker_id}] [{idx}/{len(cands)}] c={c}", flush=True)
        row = run_candidate(
            worker_repo_root=worker_repo,
            output_dir=f"{output_dir}/worker_{worker_id}",
            sim_duration_s=sim_duration_s,
            sim_freq=sim_freq,
            timeout_s=timeout_s,
            base_q=base_q,
            base_r=base_r,
            c=c,
        )
        results.append(row)
        if int(row.get("ok", 0)) == 1:
            print(
                f"[worker {worker_id}] rmse_xy={float(row['rmse_xy']):.4f} "
                f"rmse_xy_aligned={float(row['rmse_xy_aligned']):.4f}",
                flush=True,
            )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Sweep Q/R weight scales.")
    parser.add_argument("--q-pos-scales", type=str, default="0.8,1.0,1.2")
    parser.add_argument("--q-att-scales", type=str, default="0.8,1.0,1.2")
    parser.add_argument("--q-vel-scales", type=str, default="0.8,1.0,1.2")
    parser.add_argument("--q-rate-scales", type=str, default="0.8,1.0,1.2")
    parser.add_argument("--r-scales", type=str, default="0.6,0.8,1.0")
    parser.add_argument("--sim-duration-s", type=float, default=12.0)
    parser.add_argument("--sim-freq", type=float, default=500.0)
    parser.add_argument("--timeout-s", type=float, default=1200.0)
    parser.add_argument("--output-dir", type=str, default="plots/tuning_qr")
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--restore-original", action="store_true")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    params_path = repo_root / "scripts" / "parameters.py"
    summary_csv_path = repo_root / args.output_dir / "sweep_summary.csv"
    summary_csv_path.parent.mkdir(parents=True, exist_ok=True)

    base_text = params_path.read_text()
    base_q = get_list_assignment(base_text, "Q_DIAG")
    base_r = get_list_assignment(base_text, "R_DIAG")

    q_pos_scales = parse_list_floats(args.q_pos_scales)
    q_att_scales = parse_list_floats(args.q_att_scales)
    q_vel_scales = parse_list_floats(args.q_vel_scales)
    q_rate_scales = parse_list_floats(args.q_rate_scales)
    r_scales = parse_list_floats(args.r_scales)
    candidates = [
        (qp, qa, qv, qr, rs)
        for qp in q_pos_scales
        for qa in q_att_scales
        for qv in q_vel_scales
        for qr in q_rate_scales
        for rs in r_scales
    ]
    if not candidates:
        raise RuntimeError("No candidates.")

    results: list[dict[str, Any]] = []
    try:
        if args.jobs <= 1:
            for i, c in enumerate(candidates, start=1):
                print(f"[{i}/{len(candidates)}] c={c}", flush=True)
                row = run_candidate(
                    worker_repo_root=repo_root,
                    output_dir=args.output_dir,
                    sim_duration_s=args.sim_duration_s,
                    sim_freq=args.sim_freq,
                    timeout_s=args.timeout_s,
                    base_q=base_q,
                    base_r=base_r,
                    c=c,
                )
                results.append(row)
                if int(row.get("ok", 0)) == 1:
                    print(
                        f"  rmse_xy={float(row['rmse_xy']):.4f} "
                        f"rmse_xy_aligned={float(row['rmse_xy_aligned']):.4f}",
                        flush=True,
                    )
        else:
            n_jobs = min(args.jobs, len(candidates))
            splits = chunk_candidates(candidates, n_jobs)
            with tempfile.TemporaryDirectory(prefix="admm_qr_sweep_") as scratch:
                with ProcessPoolExecutor(max_workers=n_jobs) as ex:
                    futs = [
                        ex.submit(
                            worker_task,
                            wid,
                            str(repo_root),
                            scratch,
                            args.output_dir,
                            args.sim_duration_s,
                            args.sim_freq,
                            args.timeout_s,
                            base_q,
                            base_r,
                            chunk,
                        )
                        for wid, chunk in enumerate(splits)
                    ]
                    for fut in as_completed(futs):
                        results.extend(fut.result())
    finally:
        successful = [r for r in results if int(r.get("ok", 0)) == 1]
        if successful and not args.restore_original:
            best = min(successful, key=lambda r: (float(r["rmse_xy_aligned"]), float(r["rmse_xy"])))
            best_text = patch_qr(
                base_text,
                base_q=base_q,
                base_r=base_r,
                q_pos_scale=float(best["q_pos_scale"]),
                q_att_scale=float(best["q_att_scale"]),
                q_vel_scale=float(best["q_vel_scale"]),
                q_rate_scale=float(best["q_rate_scale"]),
                r_scale=float(best["r_scale"]),
            )
            params_path.write_text(best_text)
            print(
                "\nApplied best scales: "
                f"q_pos={best['q_pos_scale']} q_att={best['q_att_scale']} "
                f"q_vel={best['q_vel_scale']} q_rate={best['q_rate_scale']} r={best['r_scale']}",
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
        return 0
    print("No results recorded.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
