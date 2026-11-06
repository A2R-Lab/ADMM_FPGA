#!/usr/bin/env python3
"""
Run the report-based FPGA resource/power sweep in parallel using per-worker repos in /tmp.

This wrapper keeps the trusted single-point flow in sweep_resource_utilization.py unchanged.
Each worker gets its own repo copy, runs one-point sweeps serially inside that copy, and the
wrapper merges successful CSV rows and archived reports back into the main repo.
"""

from __future__ import annotations

import argparse
import csv
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock


DEFAULT_HORIZONS = [10, 20, 30, 40, 50, 60, 70, 80]
DEFAULT_ADMM_ITERS = [1, 2, 5, 10, 15, 20, 25, 30]
COPY_IGNORE = shutil.ignore_patterns(
    ".git",
    ".Xil",
    ".cache",
    "__pycache__",
    "*.pyc",
    "venv",
    ".venv",
    "build",
    "plots",
)


def parse_int_list(text: str, what: str) -> list[int]:
    vals = [int(tok.strip()) for tok in text.split(",") if tok.strip()]
    if not vals:
        raise ValueError(f"No values parsed from {what}")
    if any(v <= 0 for v in vals):
        raise ValueError(f"All values in {what} must be > 0")
    return vals


def load_completed_points(csv_path: Path) -> set[tuple[int, int, str]]:
    completed: set[tuple[int, int, str]] = set()
    if (not csv_path.exists()) or csv_path.stat().st_size == 0:
        return completed

    with csv_path.open("r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                h = int(row["horizon"])
                k = int(row["admm_iters"])
                b = str(row.get("board", "")).strip()
            except (KeyError, ValueError, TypeError):
                continue
            completed.add((h, k, b))
    return completed


def copy_repo(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, ignore=COPY_IGNORE)


def split_round_robin(points: list[tuple[int, int]], workers: int) -> list[list[tuple[int, int]]]:
    buckets: list[list[tuple[int, int]]] = [[] for _ in range(workers)]
    for idx, point in enumerate(points):
        buckets[idx % workers].append(point)
    return buckets


def read_single_row(csv_path: Path) -> tuple[list[str], dict[str, str]]:
    with csv_path.open("r", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        if len(rows) != 1:
            raise ValueError(f"Expected exactly one row in {csv_path}, found {len(rows)}")
        return list(reader.fieldnames or []), rows[0]


def worker_run(
    worker_idx: int,
    points: list[tuple[int, int]],
    *,
    repo_root: Path,
    board: str,
    with_trajectory: bool,
    tmp_root: Path,
    output_csv: Path,
    csv_lock: Lock,
    csv_fieldnames: list[str],
    final_archive_dir: Path,
    continue_on_error: bool,
) -> int:
    if not points:
        return 0

    worker_root = tmp_root / f"worker_{worker_idx}"
    worker_repo = worker_root / "repo"
    print(f"Preparing worker repo: {worker_repo}")
    copy_repo(repo_root, worker_repo)

    ok_count = 0

    for horizon, admm_iters in points:
        print(f"\n=== Worker worker_{worker_idx}: H={horizon}, k={admm_iters} ===")
        point_csv_rel = Path("build") / "parallel_point_outputs" / f"h{horizon}_k{admm_iters}.csv"
        point_archive_rel = Path("build") / "parallel_point_archives"
        point_csv = worker_repo / point_csv_rel
        point_archive = worker_repo / point_archive_rel
        point_csv.parent.mkdir(parents=True, exist_ok=True)
        point_archive.mkdir(parents=True, exist_ok=True)
        if point_csv.exists():
            point_csv.unlink()

        cmd = [
            "python3",
            "scripts/sweep_resource_utilization.py",
            "--board",
            board,
            "--horizons",
            str(horizon),
            "--admm-iters",
            str(admm_iters),
            "--output-csv",
            str(point_csv_rel),
            "--archive-dir",
            str(point_archive_rel),
        ]
        if with_trajectory:
            cmd.append("--with-trajectory")
        if continue_on_error:
            cmd.append("--continue-on-error")

        try:
            print(f"+ {' '.join(cmd)}")
            subprocess.run(cmd, cwd=worker_repo, check=True)

            point_fieldnames, row = read_single_row(point_csv)
            if point_fieldnames != csv_fieldnames:
                raise ValueError("Per-point CSV schema does not match merged output schema")

            src_archive = point_archive / f"h{horizon}_k{admm_iters}"
            dst_archive = final_archive_dir / f"h{horizon}_k{admm_iters}"
            if src_archive.exists():
                if dst_archive.exists():
                    shutil.rmtree(dst_archive)
                shutil.copytree(src_archive, dst_archive)

            with csv_lock:
                with output_csv.open("a", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=csv_fieldnames)
                    writer.writerow(row)

            ok_count += 1

            print(
                f"Saved: H={horizon} k={admm_iters} "
                f"lat={row.get('hls_latency_cycles', '?')} cyc "
                f"routeP={row.get('route_power_total_w', '?')} W"
            )
        except Exception as exc:
            print(f"ERROR at H={horizon}, k={admm_iters}: {exc}")
            if not continue_on_error:
                raise

    return ok_count


def main() -> None:
    parser = argparse.ArgumentParser(description="Parallel wrapper around sweep_resource_utilization.py.")
    parser.add_argument("--board", default="custom", help="Make BOARD target.")
    parser.add_argument(
        "--horizons",
        default=",".join(str(h) for h in DEFAULT_HORIZONS),
        help="Comma-separated horizon list (e.g. 10,20,30).",
    )
    parser.add_argument(
        "--admm-iters",
        type=int,
        default=None,
        help="Optional single ADMM-iteration count.",
    )
    parser.add_argument(
        "--admm-iters-list",
        default=None,
        help="Comma-separated ADMM iteration list for grid sweep.",
    )
    parser.add_argument("--workers", type=int, default=4, help="Number of parallel worker repos.")
    parser.add_argument(
        "--tmp-root",
        default="/tmp/admm_fpga_resource_sweep",
        help="Temporary root used for per-worker repos.",
    )
    parser.add_argument(
        "--output-csv",
        default="plots/fpga_resource_sweep_parallel.csv",
        help="Merged output CSV path (repo-relative).",
    )
    parser.add_argument(
        "--archive-dir",
        default="build/reports_horizon_sweep_parallel",
        help="Folder to store merged per-point report snapshots.",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue with other points if one point fails.",
    )
    parser.add_argument(
        "--with-trajectory",
        action="store_true",
        help="Opt in to the trajectory-enabled build flow. Parallel benchmark sweeps disable trajectory by default.",
    )
    args = parser.parse_args()

    if args.workers <= 0:
        raise ValueError("--workers must be > 0")

    horizons = parse_int_list(args.horizons, "--horizons")
    if args.admm_iters_list is not None:
        admm_iters_values = parse_int_list(args.admm_iters_list, "--admm-iters-list")
    elif args.admm_iters is not None:
        if args.admm_iters <= 0:
            raise ValueError("--admm-iters must be > 0")
        admm_iters_values = [args.admm_iters]
    else:
        admm_iters_values = list(DEFAULT_ADMM_ITERS)

    repo_root = Path(__file__).resolve().parents[1]
    output_csv = repo_root / args.output_csv
    final_archive_dir = repo_root / args.archive_dir
    tmp_root = Path(args.tmp_root)

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    final_archive_dir.mkdir(parents=True, exist_ok=True)
    tmp_root.mkdir(parents=True, exist_ok=True)

    all_points = [(h, k) for h in horizons for k in admm_iters_values]
    completed = load_completed_points(output_csv)
    pending = [(h, k) for (h, k) in all_points if (h, k, args.board) not in completed]

    print(f"Total points requested: {len(all_points)}")
    print(f"Already completed: {len(all_points) - len(pending)}")
    print(f"To run now: {len(pending)}")

    if not pending:
        print(f"Saved CSV: {output_csv}")
        print(f"Archived per-point artifacts under: {final_archive_dir}")
        return

    if output_csv.exists() and output_csv.stat().st_size > 0:
        with output_csv.open("r", newline="") as f:
            reader = csv.DictReader(f)
            csv_fieldnames = list(reader.fieldnames or [])
            if not csv_fieldnames:
                raise RuntimeError(f"Could not read CSV header from {output_csv}")
    else:
        with (repo_root / "scripts" / "sweep_resource_utilization.py").open("r"):
            pass
        csv_fieldnames = [
            "horizon",
            "admm_iters",
            "board",
            "slice_luts_used",
            "slice_luts_avail",
            "slice_luts_util_pct",
            "lut_as_mem_used",
            "lut_as_mem_avail",
            "lut_as_mem_util_pct",
            "bram_tile_used",
            "bram_tile_avail",
            "bram_tile_util_pct",
            "dsps_used",
            "dsps_avail",
            "dsps_util_pct",
            "hls_target_clk_ns",
            "hls_est_clk_ns",
            "hls_uncertainty_ns",
            "hls_est_fmax_mhz",
            "synth_wns_ns",
            "synth_tns_ns",
            "synth_clk_period_ns",
            "synth_clk_freq_mhz",
            "synth_fmax_est_mhz",
            "synth_power_total_w",
            "synth_power_dynamic_w",
            "synth_power_static_w",
            "route_wns_ns",
            "route_tns_ns",
            "route_clk_period_ns",
            "route_clk_freq_mhz",
            "route_fmax_est_mhz",
            "route_power_total_w",
            "route_power_dynamic_w",
            "route_power_static_w",
            "hls_latency_cycles",
            "est_solve_us_cfg_clk",
            "est_solve_us_route_fmax",
            "throughput_cfg_sps",
            "throughput_route_fmax_sps",
            "throughput_per_lut_cfg",
            "throughput_per_dsp_cfg",
            "throughput_per_bram_cfg",
            "throughput_per_lutram_cfg",
            "energy_per_solve_cfg_uj",
            "energy_per_solve_route_fmax_uj",
            "energy_per_iter_cfg_nj",
        ]
        with output_csv.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=csv_fieldnames)
            writer.writeheader()

    buckets = [bucket for bucket in split_round_robin(pending, min(args.workers, len(pending))) if bucket]
    csv_lock = Lock()
    ok_count = 0

    with ThreadPoolExecutor(max_workers=len(buckets)) as ex:
        futures = [
            ex.submit(
                worker_run,
                idx,
                bucket,
                repo_root=repo_root,
                board=args.board,
                with_trajectory=args.with_trajectory,
                tmp_root=tmp_root,
                output_csv=output_csv,
                csv_lock=csv_lock,
                csv_fieldnames=csv_fieldnames,
                final_archive_dir=final_archive_dir,
                continue_on_error=args.continue_on_error,
            )
            for idx, bucket in enumerate(buckets)
        ]
        for fut in futures:
            ok_count += fut.result()

    print(f"\nSaved CSV: {output_csv}")
    print(f"Archived per-point artifacts under: {final_archive_dir}")
    print(f"Completed points: ok={ok_count}, error={len(pending) - ok_count}")


if __name__ == "__main__":
    main()
