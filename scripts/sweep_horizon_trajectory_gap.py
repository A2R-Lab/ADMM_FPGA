#!/usr/bin/env python3
"""Sweep trajectory shapes and compare horizon 15 vs 40 performance in parallel."""

from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from parameters import Q_DIAG, R_DIAG


def parse_int_define(data_h_path: Path, name: str) -> int:
    text = data_h_path.read_text()
    m = re.search(rf"^\s*#define\s+{name}\s+([0-9]+)\s*$", text, re.MULTILINE)
    if m is None:
        raise RuntimeError(f"Missing define in {data_h_path}: {name}")
    return int(m.group(1))


def parse_value(output: str, key: str) -> str:
    for line in output.splitlines():
        if line.strip().startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError(f"Could not find {key} in output")


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

    x_arr = np.asarray(x_rows, dtype=np.float64)
    r_arr = np.asarray(r_rows, dtype=np.float64)
    if x_arr.size == 0:
        return {"rmse_xy": float("nan"), "max_err_xy": float("nan"), "n_scored": 0.0}

    err_xy = x_arr[:, :2] - r_arr[:, :2]
    err_norm = np.sqrt(np.sum(err_xy * err_xy, axis=1))
    rmse_xy = float(np.sqrt(np.mean(err_norm * err_norm)))
    max_err_xy = float(np.max(err_norm))
    return {"rmse_xy": rmse_xy, "max_err_xy": max_err_xy, "n_scored": float(err_norm.shape[0])}


def copy_worker_repo(main_repo_root: Path, worker_repo_root: Path) -> None:
    worker_repo_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(main_repo_root / "scripts", worker_repo_root / "scripts", dirs_exist_ok=True)
    shutil.copytree(main_repo_root / "vitis_projects", worker_repo_root / "vitis_projects", dirs_exist_ok=True)
    (worker_repo_root / "vivado_project" / "vivado_project.srcs" / "sources_1" / "new").mkdir(
        parents=True, exist_ok=True
    )


def run_once(
    *,
    repo_root: Path,
    output_dir: str,
    sim_duration_s: float,
    sim_freq: float,
    timeout_s: float,
    env_overrides: dict[str, str],
) -> dict[str, Any]:
    env = os.environ.copy()
    env.update(env_overrides)
    cmd = [
        sys.executable,
        str(repo_root / "scripts" / "run_hls_closed_loop_once.py"),
        "--sim-duration-s",
        f"{sim_duration_s:.12g}",
        "--sim-freq",
        f"{sim_freq:.12g}",
        "--timeout-s",
        f"{timeout_s:.12g}",
        "--output-dir",
        output_dir,
    ]
    proc = subprocess.run(cmd, cwd=repo_root, env=env, capture_output=True, text=True)
    full_output = (proc.stdout or "") + "\n" + (proc.stderr or "")
    if proc.returncode != 0:
        return {
            "ok": 0,
            "error": f"run failed rc={proc.returncode}",
            "stderr_tail": "\n".join(full_output.splitlines()[-40:]),
        }

    traj_csv = Path(parse_value(full_output, "trajectory_csv"))
    traj_png = Path(parse_value(full_output, "trajectory_png"))
    early_stop_reason = parse_value(full_output, "early_stop_reason")
    early_stop_step = parse_value(full_output, "early_stop_step")
    metrics = score_trajectory(
        traj_csv=traj_csv,
        ref_csv=repo_root / "vitis_projects" / "ADMM" / "trajectory_refs.csv",
        data_h_path=repo_root / "vitis_projects" / "ADMM" / "data.h",
    )
    return {
        "ok": 1,
        "trajectory_csv": str(traj_csv),
        "trajectory_png": str(traj_png),
        "early_stop_reason": early_stop_reason,
        "early_stop_step": early_stop_step,
        **metrics,
    }


def run_case_pair(
    *,
    worker_repo_root: Path,
    case_name: str,
    case_env: dict[str, str],
    output_root: Path,
    sim_duration_s: float,
    sim_freq: float,
    timeout_s: float,
) -> dict[str, str]:
    row: dict[str, str] = {"case": case_name}

    by_h: dict[int, dict[str, Any]] = {}
    for horizon in (15, 40):
        run_env = dict(case_env)
        run_env["ADMM_HORIZON_LENGTH"] = str(horizon)
        out_dir = str((output_root / case_name / f"h{horizon}").resolve())
        result = run_once(
            repo_root=worker_repo_root,
            output_dir=out_dir,
            sim_duration_s=sim_duration_s,
            sim_freq=sim_freq,
            timeout_s=timeout_s,
            env_overrides=run_env,
        )
        by_h[horizon] = result

    for horizon in (15, 40):
        result = by_h[horizon]
        row[f"h{horizon}_ok"] = str(int(result.get("ok", 0)))
        row[f"h{horizon}_rmse_xy"] = str(result.get("rmse_xy", "nan"))
        row[f"h{horizon}_max_err_xy"] = str(result.get("max_err_xy", "nan"))
        row[f"h{horizon}_traj_png"] = str(result.get("trajectory_png", ""))
        row[f"h{horizon}_early_stop_reason"] = str(result.get("early_stop_reason", ""))
        row[f"h{horizon}_early_stop_step"] = str(result.get("early_stop_step", ""))

    h15_ok = row.get("h15_ok") == "1"
    h40_ok = row.get("h40_ok") == "1"
    if h15_ok and h40_ok:
        h15 = float(row["h15_rmse_xy"])
        h40 = float(row["h40_rmse_xy"])
        row["rmse_gap_15_minus_40"] = f"{(h15 - h40):.8f}"
        row["rmse_ratio_15_over_40"] = f"{(h15 / h40) if h40 > 0 else float('inf'):.8f}"
    else:
        row["rmse_gap_15_minus_40"] = "nan"
        row["rmse_ratio_15_over_40"] = "nan"
        if not h15_ok:
            row["error"] = f"h15_failed: {by_h[15].get('error', 'unknown')}"
            row["h15_stderr_tail"] = str(by_h[15].get("stderr_tail", ""))
        if not h40_ok:
            row["error"] = f"h40_failed: {by_h[40].get('error', 'unknown')}"
            row["h40_stderr_tail"] = str(by_h[40].get("stderr_tail", ""))
    return row


def chunk_cases(cases: list[tuple[str, dict[str, str]]], n_chunks: int) -> list[list[tuple[str, dict[str, str]]]]:
    chunks: list[list[tuple[str, dict[str, str]]]] = [[] for _ in range(n_chunks)]
    for i, case in enumerate(cases):
        chunks[i % n_chunks].append(case)
    return [chunk for chunk in chunks if chunk]


def _safe_case_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)


def _fmt_diag(vals: list[float]) -> str:
    return "[" + ", ".join(f"{float(v):g}" for v in vals) + "]"


def write_pair_png(
    *,
    case_name: str,
    h15_png: Path,
    h40_png: Path,
    out_png: Path,
    subtitle: str,
) -> bool:
    if not h15_png.exists() or not h40_png.exists():
        return False
    try:
        img15 = plt.imread(h15_png)
        img40 = plt.imread(h40_png)
    except Exception:
        return False

    fig, axes = plt.subplots(1, 2, figsize=(16, 7), constrained_layout=True)
    axes[0].imshow(img15)
    axes[0].set_title("Horizon 15")
    axes[0].axis("off")
    axes[1].imshow(img40)
    axes[1].set_title("Horizon 40")
    axes[1].axis("off")
    fig.suptitle(f"{case_name} | {subtitle}")
    fig.text(
        0.5,
        0.01,
        f"Q_DIAG={_fmt_diag(Q_DIAG)}   R_DIAG={_fmt_diag(R_DIAG)}",
        ha="center",
        va="bottom",
        fontsize=8,
    )
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=130)
    plt.close(fig)
    return True


def worker_task(
    worker_id: int,
    main_repo_root: str,
    scratch_root: str,
    output_root: str,
    sim_duration_s: float,
    sim_freq: float,
    timeout_s: float,
    cases: list[tuple[str, dict[str, str]]],
) -> list[dict[str, str]]:
    main_repo = Path(main_repo_root)
    scratch = Path(scratch_root)
    out_root = Path(output_root)
    worker_repo = scratch / f"worker_{worker_id}" / "repo"
    copy_worker_repo(main_repo, worker_repo)

    rows: list[dict[str, str]] = []
    for i, (case_name, case_env) in enumerate(cases, start=1):
        print(f"[worker {worker_id}] [{i}/{len(cases)}] case={case_name}", flush=True)
        row = run_case_pair(
            worker_repo_root=worker_repo,
            case_name=case_name,
            case_env=case_env,
            output_root=out_root,
            sim_duration_s=sim_duration_s,
            sim_freq=sim_freq,
            timeout_s=timeout_s,
        )
        rows.append(row)
        if row.get("h15_ok") == "1" and row.get("h40_ok") == "1":
            print(
                f"[worker {worker_id}] gap={row['rmse_gap_15_minus_40']} "
                f"ratio={row['rmse_ratio_15_over_40']}",
                flush=True,
            )
        else:
            print(
                f"[worker {worker_id}] failed: {row.get('error', 'unknown')}",
                flush=True,
            )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Find feasible trajectories that separate horizon-15 vs horizon-40 performance.")
    parser.add_argument("--sim-duration-s", type=float, default=12.0)
    parser.add_argument("--sim-freq", type=float, default=500.0)
    parser.add_argument("--timeout-s", type=float, default=1200.0)
    parser.add_argument("--output-dir", type=str, default="plots/horizon_trajectory_gap")
    parser.add_argument("--jobs", type=int, default=1)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    output_root = (repo_root / args.output_dir).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    cases: list[tuple[str, dict[str, str]]] = [
        (
            "square_hold_a060",
            {
                "ADMM_TRAJ_SHAPE": "square_hold",
                "ADMM_TRAJ_AMP_X": "0.60",
                "ADMM_TRAJ_AMP_Y": "0.60",
                "ADMM_FIG8_PERIOD_S": "5.8",
                "ADMM_REPETITIONS": "6",
            },
        ),
        (
            "square_hold_a075",
            {
                "ADMM_TRAJ_SHAPE": "square_hold",
                "ADMM_TRAJ_AMP_X": "0.75",
                "ADMM_TRAJ_AMP_Y": "0.75",
                "ADMM_FIG8_PERIOD_S": "5.8",
                "ADMM_REPETITIONS": "6",
            },
        ),
        (
            "square_hold_a090",
            {
                "ADMM_TRAJ_SHAPE": "square_hold",
                "ADMM_TRAJ_AMP_X": "0.90",
                "ADMM_TRAJ_AMP_Y": "0.90",
                "ADMM_FIG8_PERIOD_S": "6.2",
                "ADMM_REPETITIONS": "6",
            },
        ),
        # (
        #     "fig8_hold_a070",
        #     {
        #         "ADMM_TRAJ_SHAPE": "fig8_hold",
        #         "ADMM_TRAJ_AMP_X": "0.70",
        #         "ADMM_TRAJ_AMP_Y": "1.00",
        #         "ADMM_FIG8_PERIOD_S": "5.5",
        #         "ADMM_REPETITIONS": "6",
        #     },
        # ),
        # (
        #     "circle_a075",
        #     {
        #         "ADMM_TRAJ_SHAPE": "circle",
        #         "ADMM_TRAJ_AMP_X": "0.75",
        #         "ADMM_TRAJ_AMP_Y": "0.75",
        #         "ADMM_FIG8_PERIOD_S": "5.8",
        #         "ADMM_REPETITIONS": "6",
        #     },
        # ),
        # (
        #     "hubstar_v6_a060",
        #     {
        #         "ADMM_TRAJ_SHAPE": "hubstar",
        #         "ADMM_TRAJ_HUBSTAR_VERTICES": "6",
        #         "ADMM_TRAJ_AMP_X": "0.60",
        #         "ADMM_TRAJ_AMP_Y": "0.60",
        #         "ADMM_FIG8_PERIOD_S": "7.0",
        #         "ADMM_REPETITIONS": "6",
        #     },
        # ),
        # (
        #     "hubstar_v8_a060",
        #     {
        #         "ADMM_TRAJ_SHAPE": "hubstar",
        #         "ADMM_TRAJ_HUBSTAR_VERTICES": "8",
        #         "ADMM_TRAJ_AMP_X": "0.60",
        #         "ADMM_TRAJ_AMP_Y": "0.60",
        #         "ADMM_FIG8_PERIOD_S": "7.2",
        #         "ADMM_REPETITIONS": "6",
        #     },
        # ),
        # (
        #     "hubstar_v10_a060",
        #     {
        #         "ADMM_TRAJ_SHAPE": "hubstar",
        #         "ADMM_TRAJ_HUBSTAR_VERTICES": "10",
        #         "ADMM_TRAJ_AMP_X": "0.60",
        #         "ADMM_TRAJ_AMP_Y": "0.60",
        #         "ADMM_FIG8_PERIOD_S": "7.5",
        #         "ADMM_REPETITIONS": "6",
        #     },
        # ),
        # (
        #     "hubstar_v12_a060",
        #     {
        #         "ADMM_TRAJ_SHAPE": "hubstar",
        #         "ADMM_TRAJ_HUBSTAR_VERTICES": "12",
        #         "ADMM_TRAJ_AMP_X": "0.60",
        #         "ADMM_TRAJ_AMP_Y": "0.60",
        #         "ADMM_FIG8_PERIOD_S": "7.8",
        #         "ADMM_REPETITIONS": "6",
        #     },
        # ),
        # (
        #     "hubstar_v8_a070",
        #     {
        #         "ADMM_TRAJ_SHAPE": "hubstar",
        #         "ADMM_TRAJ_HUBSTAR_VERTICES": "8",
        #         "ADMM_TRAJ_AMP_X": "0.70",
        #         "ADMM_TRAJ_AMP_Y": "0.70",
        #         "ADMM_FIG8_PERIOD_S": "8.6",
        #         "ADMM_REPETITIONS": "6",
        #     },
        # ),
        # (
        #     "hubstar_v10_a070",
        #     {
        #         "ADMM_TRAJ_SHAPE": "hubstar",
        #         "ADMM_TRAJ_HUBSTAR_VERTICES": "10",
        #         "ADMM_TRAJ_AMP_X": "0.70",
        #         "ADMM_TRAJ_AMP_Y": "0.70",
        #         "ADMM_FIG8_PERIOD_S": "9.0",
        #         "ADMM_REPETITIONS": "6",
        #     },
        # ),
        # (
        #     "hubstar_v12_a070",
        #     {
        #         "ADMM_TRAJ_SHAPE": "hubstar",
        #         "ADMM_TRAJ_HUBSTAR_VERTICES": "12",
        #         "ADMM_TRAJ_AMP_X": "0.70",
        #         "ADMM_TRAJ_AMP_Y": "0.70",
        #         "ADMM_FIG8_PERIOD_S": "9.4",
        #         "ADMM_REPETITIONS": "6",
        #     },
        # ),
        # (
        #     "hubstar_v14_a065",
        #     {
        #         "ADMM_TRAJ_SHAPE": "hubstar",
        #         "ADMM_TRAJ_HUBSTAR_VERTICES": "14",
        #         "ADMM_TRAJ_AMP_X": "0.65",
        #         "ADMM_TRAJ_AMP_Y": "0.65",
        #         "ADMM_FIG8_PERIOD_S": "10.0",
        #         "ADMM_REPETITIONS": "6",
        #     },
        # ),
        # (
        #     "hubstar_v16_a060",
        #     {
        #         "ADMM_TRAJ_SHAPE": "hubstar",
        #         "ADMM_TRAJ_HUBSTAR_VERTICES": "16",
        #         "ADMM_TRAJ_AMP_X": "0.60",
        #         "ADMM_TRAJ_AMP_Y": "0.60",
        #         "ADMM_FIG8_PERIOD_S": "10.6",
        #         "ADMM_REPETITIONS": "6",
        #     },
        # ),
    ]

    rows: list[dict[str, str]] = []
    if args.jobs <= 1:
        worker_repo = repo_root
        for i, (case_name, case_env) in enumerate(cases, start=1):
            print(f"[{i}/{len(cases)}] case={case_name}", flush=True)
            row = run_case_pair(
                worker_repo_root=worker_repo,
                case_name=case_name,
                case_env=case_env,
                output_root=output_root,
                sim_duration_s=args.sim_duration_s,
                sim_freq=args.sim_freq,
                timeout_s=args.timeout_s,
            )
            rows.append(row)
    else:
        n_jobs = min(args.jobs, len(cases))
        splits = chunk_cases(cases, n_jobs)
        with tempfile.TemporaryDirectory(prefix="admm_horizon_gap_") as scratch:
            with ProcessPoolExecutor(max_workers=n_jobs) as ex:
                futs = [
                    ex.submit(
                        worker_task,
                        worker_id,
                        str(repo_root),
                        scratch,
                        str(output_root),
                        args.sim_duration_s,
                        args.sim_freq,
                        args.timeout_s,
                        chunk,
                    )
                    for worker_id, chunk in enumerate(splits)
                ]
                for fut in as_completed(futs):
                    rows.extend(fut.result())

    out_csv = output_root / "summary.csv"
    keys: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in keys:
                keys.append(key)
    with out_csv.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)

    valid = [
        row
        for row in rows
        if row.get("h15_ok") == "1" and row.get("h40_ok") == "1"
    ]
    valid.sort(key=lambda r: float(r["rmse_gap_15_minus_40"]), reverse=True)

    gallery_dir = output_root / "pair_gallery"
    gallery_dir.mkdir(parents=True, exist_ok=True)
    gallery_rows: list[dict[str, str]] = []
    for rank, row in enumerate(valid, start=1):
        case_name = row["case"]
        h15_png = Path(row["h15_traj_png"])
        h40_png = Path(row["h40_traj_png"])
        rank_tag = f"{rank:03d}"
        case_tag = _safe_case_name(case_name)
        subtitle = (
            f"gap={row['rmse_gap_15_minus_40']} "
            f"ratio={row['rmse_ratio_15_over_40']}"
        )
        pair_png = gallery_dir / f"{rank_tag}_{case_tag}_pair.png"
        ok_pair = write_pair_png(
            case_name=case_name,
            h15_png=h15_png,
            h40_png=h40_png,
            out_png=pair_png,
            subtitle=subtitle,
        )
        if not ok_pair:
            continue
        # Keep single-horizon images in the same folder for quick manual browsing.
        h15_copy = gallery_dir / f"{rank_tag}_{case_tag}_h15.png"
        h40_copy = gallery_dir / f"{rank_tag}_{case_tag}_h40.png"
        try:
            shutil.copy2(h15_png, h15_copy)
            shutil.copy2(h40_png, h40_copy)
        except Exception:
            pass
        gallery_rows.append(
            {
                "rank": str(rank),
                "case": case_name,
                "pair_png": str(pair_png),
                "h15_png_copy": str(h15_copy),
                "h40_png_copy": str(h40_copy),
                "rmse_gap_15_minus_40": row["rmse_gap_15_minus_40"],
                "rmse_ratio_15_over_40": row["rmse_ratio_15_over_40"],
            }
        )

    gallery_csv = gallery_dir / "gallery_index.csv"
    if gallery_rows:
        keys = list(gallery_rows[0].keys())
        with gallery_csv.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(gallery_rows)

    print(f"summary={out_csv}")
    print(f"pair_gallery_dir={gallery_dir}")
    if gallery_rows:
        print(f"pair_gallery_index={gallery_csv}")
    if valid:
        best = valid[0]
        print(
            "best_case="
            f"{best['case']} gap={best['rmse_gap_15_minus_40']} "
            f"ratio={best['rmse_ratio_15_over_40']}"
        )
        print(f"best_h15_plot={best['h15_traj_png']}")
        print(f"best_h40_plot={best['h40_traj_png']}")
    else:
        print("best_case=none (no feasible successful pair)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
