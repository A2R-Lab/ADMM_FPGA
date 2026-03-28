#!/usr/bin/env python3
"""
Full Cartesian grid sweep for HLS csim candidates.

Manual-review oriented:
- no multistage pruning
- no auto-ranking/selection
- one trajectory CSV + one PNG per candidate

Grid parameterization:
- q[0] == q[1] (x/y position)
- q[3] == q[4] (roll/pitch)
- q[6] == q[7] (vx/vy)
- q[9] == q[10] (wx/wy)
- z-related terms are excluded from sweep and kept fixed:
  q[2] (z), q[8] (vz)
"""

from __future__ import annotations

import csv
import itertools
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from sweep_hls_csim_qr_freq import (  # type: ignore
    BASE_Q_DIAG,
    CandidateEval,
    candidate_hash,
    evaluate_candidates_parallel,
    float_or_nan,
    load_cache,
    write_cache,
)
# Reproducible sweep configuration.
# Edit these values directly and commit the file to lock an exact run definition.
CFG = {
    # Total candidates:
    # len(freq_values)*len(rho_values)*len(r_values)*len(qxy_values)*len(qrot_values)*
    # len(qvelxy_values)*len(qomegaxy_values)*len(qyaw_values)*len(qomegaz_values)
    # = 2*1*2*3*2*2*2*1*1 = 96
    "freq_values": [50.0, 100.0],
    # "rho_values": [64, 128],
    # "r_values": [2.5, 5.0, 7.5, 10.0, 15.0],  # R = r * eye(4)
    # "qxy_values": [60.0, 200.0, 600.0, 1000.0],     # q[0] = q[1]
    # "qrot_values": [0.2, 0.4, 4.0, 40.0],              # q[3] = q[4]
    # "qvelxy_values": [0.4, 4.0, 40.0, 400.0],            # q[6] = q[7]
    # "qomegaxy_values": [0.2, 2.0, 20.0],          # q[9] = q[10]
    # "qyaw_values": [0.4, 4.0, 40.0],                   # q[5]
    # "qomegaz_values": [2.5, 25.0, 250.0],               # q[11]

    "rho_values": [32, 64, 128, 256],
    "r_values": [1.0, 2.5, 6.5],  # R = r * eye(4)
    "qxy_values": [30.0, 60.0, 100.0, 200.0, 600.0],     # q[0] = q[1]
    "qrot_values": [0.2, 0.4, 0.8, 2.0, 4.0],              # q[3] = q[4]
    "qvelxy_values": [0.4, 2.0, 4.0, 8.0],            # q[6] = q[7]
    "qomegaxy_values": [0.2, 0.4, 0.8, 1.2, 1.6, 2.0, 4.0, 8.0],          # q[9] = q[10]
    "qyaw_values": [4.0],                   # q[5]
    "qomegaz_values": [25.0],               # q[11]
    "jobs": 24,
    "horizon": 20,
    "admm_iters": 3,
    "sim_freq": 100.0,
    "sim_duration_s": 6.0,
    "step_x": 2.0,
    "step_y": 0.0,
    "step_z": 0.0,
    "step_yaw": 0.0,
    "rise_lo": 0.1,
    "rise_hi": 0.9,
    "settle_pct": 0.02,
    "candidate_timeout_s": 400.0,
    "heartbeat_s": 10.0,
    "output_dir": "plots/hls_csim_full_grid",
    "retry_errors": False,
    "continue_on_error": True,
}


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def init_csv(path: Path, fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()


def append_csv_row(path: Path, row: dict[str, Any], fieldnames: list[str]) -> None:
    with path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writerow(row)
        f.flush()


def main() -> None:
    jobs = int(CFG["jobs"])
    horizon = int(CFG["horizon"])
    admm_iters = int(CFG["admm_iters"])
    sim_freq = float(CFG["sim_freq"])
    sim_duration_s = float(CFG["sim_duration_s"])
    step_x = float(CFG["step_x"])
    step_y = float(CFG["step_y"])
    step_z = float(CFG["step_z"])
    step_yaw = float(CFG["step_yaw"])
    rise_lo = float(CFG["rise_lo"])
    rise_hi = float(CFG["rise_hi"])
    settle_pct = float(CFG["settle_pct"])
    candidate_timeout_s = float(CFG["candidate_timeout_s"])
    heartbeat_s = float(CFG["heartbeat_s"])
    output_dir = str(CFG["output_dir"])
    retry_errors = bool(CFG["retry_errors"])
    continue_on_error = bool(CFG["continue_on_error"])

    freq_values = [float(v) for v in CFG["freq_values"]]
    rho_values = [int(v) for v in CFG["rho_values"]]
    r_values = [float(v) for v in CFG["r_values"]]
    qxy_values = [float(v) for v in CFG["qxy_values"]]
    qrot_values = [float(v) for v in CFG["qrot_values"]]
    qvelxy_values = [float(v) for v in CFG["qvelxy_values"]]
    qomegaxy_values = [float(v) for v in CFG["qomegaxy_values"]]
    qyaw_values = [float(v) for v in CFG["qyaw_values"]]
    qomegaz_values = [float(v) for v in CFG["qomegaz_values"]]

    if jobs <= 0:
        raise ValueError("CFG['jobs'] must be > 0")
    if horizon <= 0 or admm_iters <= 0:
        raise ValueError("CFG['horizon'] and CFG['admm_iters'] must be > 0")
    if sim_freq <= 0 or sim_duration_s <= 0:
        raise ValueError("CFG['sim_freq'] and CFG['sim_duration_s'] must be > 0")
    if not (0.0 < rise_lo < rise_hi < 1.0):
        raise ValueError("CFG rise bounds must satisfy 0 < rise_lo < rise_hi < 1")
    if settle_pct <= 0:
        raise ValueError("CFG['settle_pct'] must be > 0")
    if heartbeat_s <= 0:
        raise ValueError("CFG['heartbeat_s'] must be > 0")

    if any(v <= 0 for v in freq_values):
        raise ValueError("CFG['freq_values'] must contain only positive values")
    if any(v <= 0 for v in r_values):
        raise ValueError("CFG['r_values'] must contain only positive values")
    grouped_lists = [
        ("qxy-values", qxy_values),
        ("qrot-values", qrot_values),
        ("qvelxy-values", qvelxy_values),
        ("qomegaxy-values", qomegaxy_values),
        ("qyaw-values", qyaw_values),
        ("qomegaz-values", qomegaz_values),
    ]
    for name, vals in grouped_lists:
        if any(v <= 0 for v in vals):
            raise ValueError(f"CFG[{name!r}] must contain only positive values")
    for rho in rho_values:
        if rho <= 0 or (rho & (rho - 1)):
            raise ValueError(f"rho={rho} must be a power of 2 > 0")

    repo_root = Path(__file__).resolve().parents[1]
    out_root = (repo_root / output_dir).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    plots_dir = out_root / "plots"
    traj_dir = out_root / "trajectories"
    plots_dir.mkdir(parents=True, exist_ok=True)
    traj_dir.mkdir(parents=True, exist_ok=True)

    run_root = (repo_root / "build" / "tune_runs" / datetime.now().strftime("%Y%m%d_%H%M%S")).resolve()
    run_root.mkdir(parents=True, exist_ok=True)

    cache_csv = out_root / "candidate_cache.csv"
    cache = load_cache(cache_csv)

    total_candidates = (
        len(freq_values)
        * len(rho_values)
        * len(r_values)
        * len(qxy_values)
        * len(qrot_values)
        * len(qvelxy_values)
        * len(qomegaxy_values)
        * len(qyaw_values)
        * len(qomegaz_values)
    )
    print(f"Full-grid candidates (requested): {total_candidates}")
    if total_candidates > 10000:
        print("WARNING: very large grid; runtime can be extremely long.")

    candidates: list[CandidateEval] = []
    grid_rows: list[dict[str, Any]] = []
    idx = 0
    for freq_hz in freq_values:
        for rho in rho_values:
            for r_val in r_values:
                for qxy, qrot, qvelxy, qomegaxy, qyaw, qomegaz in itertools.product(
                    qxy_values,
                    qrot_values,
                    qvelxy_values,
                    qomegaxy_values,
                    qyaw_values,
                    qomegaz_values,
                ):
                    idx += 1
                    q_diag = list(BASE_Q_DIAG)
                    # Coupled grid dimensions
                    q_diag[0] = qxy
                    q_diag[1] = qxy
                    q_diag[3] = qrot
                    q_diag[4] = qrot
                    q_diag[6] = qvelxy
                    q_diag[7] = qvelxy
                    q_diag[9] = qomegaxy
                    q_diag[10] = qomegaxy
                    q_diag[5] = qyaw
                    q_diag[11] = qomegaz
                    # z-related terms excluded from sweep:
                    # q_diag[2] (z) and q_diag[8] (vz) remain baseline.
                    q_diag_t = tuple(q_diag)
                    h = candidate_hash(
                        freq_hz=freq_hz,
                        rho=rho,
                        horizon=horizon,
                        admm_iters=admm_iters,
                        q_diag=q_diag_t,
                        r_scale=r_val,
                        sim_freq=sim_freq,
                        sim_duration_s=sim_duration_s,
                        step_x=step_x,
                        step_y=step_y,
                        step_z=step_z,
                        step_yaw=step_yaw,
                        rise_lo=rise_lo,
                        rise_hi=rise_hi,
                        settle_pct=settle_pct,
                    )
                    candidates.append(
                        CandidateEval(
                            candidate_hash=h,
                            freq_hz=freq_hz,
                            rho=rho,
                            horizon=horizon,
                            admm_iters=admm_iters,
                            q_diag=q_diag_t,
                            r_scale=r_val,
                            sim_freq=sim_freq,
                            sim_duration_s=sim_duration_s,
                            step_x=step_x,
                            step_y=step_y,
                            step_z=step_z,
                            step_yaw=step_yaw,
                            rise_lo=rise_lo,
                            rise_hi=rise_hi,
                            settle_pct=settle_pct,
                            candidate_timeout_s=candidate_timeout_s,
                            heartbeat_s=heartbeat_s,
                            enable_heartbeat=(jobs == 1),
                        )
                    )
                    grid_rows.append(
                        {
                            "grid_idx": idx,
                            "candidate_hash": h,
                            "freq_hz": freq_hz,
                            "rho": rho,
                            "r_scale": r_val,
                            "q_xy": qxy,
                            "q_rot": qrot,
                            "q_vel_xy": qvelxy,
                            "q_omega_xy": qomegaxy,
                            "q_yaw": qyaw,
                            "q_omega_z": qomegaz,
                            "q_diag_json": json.dumps(list(q_diag_t)),
                        }
                    )

    fieldnames = [
        "grid_idx",
        "candidate_hash",
        "status",
        "error",
        "freq_hz",
        "rho",
        "r_scale",
        "q_xy",
        "q_rot",
        "q_vel_xy",
        "q_omega_xy",
        "q_yaw",
        "q_omega_z",
        "q_diag_json",
        "rise_time_s",
        "settling_time_s",
        "overshoot_pct",
        "iae",
        "control_effort_l1",
        "final_x0",
        "plot_png_path",
        "traj_csv_path",
        "job_dir",
    ]
    results_csv = out_root / "grid_results.csv"
    init_csv(results_csv, fieldnames)

    rows_by_hash: dict[str, list[dict[str, Any]]] = {}
    for row in grid_rows:
        rows_by_hash.setdefault(str(row["candidate_hash"]), []).append(row)

    emitted_keys: set[tuple[int, str]] = set()
    completed_since_cache_flush = 0
    cache_flush_every = 10

    def materialize_row(row: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
        h = str(row["candidate_hash"])
        traj_src = Path(c.get("traj_csv_path", "")) if c.get("traj_csv_path", "") else None
        plot_src = Path(c.get("plot_png_path", "")) if c.get("plot_png_path", "") else None

        traj_out = ""
        plot_out = ""
        if traj_src is not None and traj_src.exists():
            traj_dst = traj_dir / f"{int(row['grid_idx']):06d}_{h[:12]}.csv"
            if not traj_dst.exists():
                shutil.copy2(traj_src, traj_dst)
            traj_out = str(traj_dst.relative_to(repo_root))
        if plot_src is not None and plot_src.exists():
            plot_dst = plots_dir / f"{int(row['grid_idx']):06d}_{h[:12]}.png"
            if not plot_dst.exists():
                shutil.copy2(plot_src, plot_dst)
            plot_out = str(plot_dst.relative_to(repo_root))

        merged = dict(row)
        merged.update(
            {
                "status": c.get("status", "error"),
                "error": c.get("error", "missing cache row"),
                "rise_time_s": float_or_nan(c.get("rise_time_s")),
                "settling_time_s": float_or_nan(c.get("settling_time_s")),
                "overshoot_pct": float_or_nan(c.get("overshoot_pct")),
                "iae": float_or_nan(c.get("iae")),
                "control_effort_l1": float_or_nan(c.get("control_effort_l1")),
                "final_x0": float_or_nan(c.get("final_x0")),
                "plot_png_path": plot_out,
                "traj_csv_path": traj_out,
                "job_dir": c.get("job_dir", ""),
            }
        )
        return merged

    def on_result(_source: CandidateEval, c: dict[str, Any]) -> None:
        nonlocal completed_since_cache_flush
        h = str(c.get("candidate_hash", ""))
        for row in rows_by_hash.get(h, []):
            key = (int(row["grid_idx"]), h)
            if key in emitted_keys:
                continue
            merged = materialize_row(row, c)
            append_csv_row(results_csv, merged, fieldnames)
            emitted_keys.add(key)
        completed_since_cache_flush += 1
        if completed_since_cache_flush >= cache_flush_every:
            write_cache(cache_csv, cache)
            completed_since_cache_flush = 0

    cache = evaluate_candidates_parallel(
        candidates=candidates,
        cache=cache,
        repo_root=repo_root,
        run_root=run_root,
        jobs=jobs,
        retry_errors=retry_errors,
        continue_on_error=continue_on_error,
        on_result=on_result,
    )
    write_cache(cache_csv, cache)

    merged_rows: list[dict[str, Any]] = []
    for row in grid_rows:
        h = row["candidate_hash"]
        c = cache.get(h, {})
        merged = materialize_row(row, c)
        merged_rows.append(merged)
        key = (int(row["grid_idx"]), h)
        if key not in emitted_keys:
            append_csv_row(results_csv, merged, fieldnames)
            emitted_keys.add(key)

    ok_count = sum(1 for r in merged_rows if r["status"] == "ok")
    print("\nDone.")
    print(f"- Requested candidates: {len(grid_rows)}")
    print(f"- Successful candidates: {ok_count}")
    print(f"- Plots folder: {plots_dir}")
    print(f"- Trajectory folder: {traj_dir}")
    print(f"- Index CSV: {out_root / 'grid_results.csv'}")
    print(f"- Run root: {run_root}")


if __name__ == "__main__":
    main()
