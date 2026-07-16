#!/usr/bin/env python3
"""Run max-horizon FPGA benchmark points in parallel isolated worker repos."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


IMPL_VARIANTS = [
    {
        "name": "baseline",
        "opt": "Explore",
        "place": "Explore",
        "phys": "AggressiveExplore",
        "route": "Explore",
    },
    {
        "name": "route_aggressive",
        "opt": "Explore",
        "place": "Explore",
        "phys": "AggressiveExplore",
        "route": "AggressiveExplore",
    },
    {
        "name": "route_more_global",
        "opt": "Explore",
        "place": "Explore",
        "phys": "AggressiveExplore",
        "route": "MoreGlobalIterations",
    },
    {
        "name": "route_no_timing_relax",
        "opt": "Explore",
        "place": "Explore",
        "phys": "AggressiveExplore",
        "route": "NoTimingRelaxation",
    },
    {
        "name": "route_higher_delay_cost",
        "opt": "Explore",
        "place": "Explore",
        "phys": "AggressiveExplore",
        "route": "HigherDelayCost",
    },
    {
        "name": "place_aggressive",
        "opt": "Explore",
        "place": "AggressiveExplore",
        "phys": "AggressiveExplore",
        "route": "Explore",
    },
    {
        "name": "phys_hold_tns",
        "opt": "Explore",
        "place": "Explore",
        "phys": "ExploreWithHoldFix",
        "route": "Explore",
        "route_tns_cleanup": "1",
    },
    {
        "name": "opt_remap",
        "opt": "ExploreWithRemap",
        "place": "Explore",
        "phys": "AggressiveExplore",
        "route": "Explore",
    },
    {
        "name": "route_ultrathreads",
        "opt": "Explore",
        "place": "Explore",
        "phys": "AggressiveExplore",
        "route": "Explore",
        "route_ultrathreads": "1",
    },
    {
        "name": "place_reduce_congestion",
        "opt": "Explore",
        "place": "Explore",
        "place_subdirective": "GPlace.ReduceCongestion.high DPlace.ReducePinDensity.high",
        "phys": "AggressiveExplore",
        "route": "Explore",
    },
]


def parse_int_list(text: str, what: str) -> list[int]:
    vals = [int(tok.strip()) for tok in text.split(",") if tok.strip()]
    if not vals:
        raise ValueError(f"No values parsed from {what}")
    return vals


def slug_for(arch: str, horizon: int, iters: int, seed: int | None) -> str:
    suffix = "" if seed is None else f"_s{seed}"
    return f"{arch.replace('_', '')}_h{horizon}_k{iters}{suffix}"


def existing_row_complete(rows_dir: Path, slug: str) -> bool:
    path = rows_dir / f"{slug}.csv"
    if not path.exists():
        return False
    try:
        with path.open(newline="") as f:
            rows = list(csv.DictReader(f))
    except csv.Error:
        return False
    return len(rows) == 1 and bool(rows[0].get("status"))


def read_single_row(rows_dir: Path, slug: str) -> dict[str, str] | None:
    path = rows_dir / f"{slug}.csv"
    if not path.exists():
        return None
    try:
        with path.open(newline="") as f:
            rows = list(csv.DictReader(f))
    except csv.Error:
        return None
    return rows[0] if len(rows) == 1 else None


def is_timing_clean(row: dict[str, str] | None) -> bool:
    if not row:
        return False
    try:
        wns = float(row.get("route_wns_ns", "nan"))
    except ValueError:
        return False
    return row.get("status") == "pass" and row.get("bitstream_exists") == "1" and wns >= 0.0


def horizon_has_timing_clean_seed(rows_dir: Path, arch: str, horizon: int, iters: int, seeds: list[int | None]) -> bool:
    return any(is_timing_clean(read_single_row(rows_dir, slug_for(arch, horizon, iters, seed))) for seed in seeds)


def copy_repo(repo_root: Path, worker_repo: Path) -> None:
    if worker_repo.parent.exists():
        shutil.rmtree(worker_repo.parent)
    worker_repo.parent.mkdir(parents=True, exist_ok=True)
    ignore = shutil.ignore_patterns(
        ".git",
        ".Xil",
        "__pycache__",
        "*.pyc",
        "build",
        "vivado*.log",
        "vivado*.jou",
    )
    shutil.copytree(repo_root, worker_repo, ignore=ignore)


def process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def acquire_work_root_lock(work_root: Path, out_dir: Path) -> Path | None:
    lock_path = work_root / ".run_lock.json"
    work_root.mkdir(parents=True, exist_ok=True)
    metadata = {
        "pid": os.getpid(),
        "started_epoch": int(time.time()),
        "out_dir": str(out_dir),
        "cmd": sys.argv,
    }
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            try:
                existing = json.loads(lock_path.read_text())
            except Exception:
                existing = {}
            pid = existing.get("pid")
            if isinstance(pid, int) and process_exists(pid):
                raise SystemExit(
                    f"Work root is already in use by PID {pid}: {work_root}\n"
                    f"Existing run output: {existing.get('out_dir', '?')}\n"
                    "Use a different --work-root, or omit --work-root to get a unique /tmp directory."
                )
            print(f"Removing stale work-root lock: {lock_path}", flush=True)
            lock_path.unlink(missing_ok=True)
            continue
        with os.fdopen(fd, "w") as fobj:
            json.dump(metadata, fobj, indent=2, sort_keys=True)
            fobj.write("\n")
        return lock_path


def release_work_root_lock(lock_path: Path | None) -> None:
    if lock_path is not None:
        lock_path.unlink(missing_ok=True)


def git_output(repo: Path, args: list[str]) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def variant_for_seed(seed: int | None) -> dict[str, str]:
    idx = 0 if seed is None else seed % len(IMPL_VARIANTS)
    return IMPL_VARIANTS[idx]


def run_point(worker_id: int, worker_repo: Path, point: dict[str, object], args_dict: dict[str, object]) -> dict[str, object]:
    repo = Path(worker_repo)
    out_dir = Path(str(args_dict["out_dir"]))
    horizon = int(point["horizon"])
    seed = point.get("seed")
    seed_int = None if seed is None else int(seed)
    slug = slug_for(str(args_dict["arch"]), horizon, int(args_dict["iters"]), seed_int)
    point_start = time.time()

    env = os.environ.copy()
    env["VIVADO_MAX_THREADS"] = str(args_dict["threads_per_worker"])
    env["BENCHMARK_WORKER_ID"] = str(worker_id)
    env["BENCHMARK_GIT_HEAD"] = str(args_dict["git_head"])
    env["BENCHMARK_GIT_STATUS_SHORT"] = str(args_dict["git_status_short"])
    variant = variant_for_seed(seed_int)
    env["VIVADO_IMPL_VARIANT"] = variant["name"]
    env["VIVADO_OPT_DIRECTIVE"] = variant["opt"]
    env["VIVADO_PLACE_DIRECTIVE"] = variant["place"]
    env["VIVADO_PLACE_SUBDIRECTIVE"] = variant.get("place_subdirective", "")
    env["VIVADO_PHYS_OPT_DIRECTIVE"] = variant["phys"]
    env["VIVADO_ROUTE_DIRECTIVE"] = variant["route"]
    env["VIVADO_ROUTE_TNS_CLEANUP"] = variant.get("route_tns_cleanup", "0")
    env["VIVADO_ROUTE_ULTRATHREADS"] = variant.get("route_ultrathreads", "0")
    if seed_int is not None:
        env["VIVADO_PLACE_SEED"] = str(seed_int)
        env["VIVADO_ROUTE_SEED"] = str(seed_int)

    point_cmd = [
        "python",
        "scripts/run_max_horizon_point.py",
        "--arch",
        str(args_dict["arch"]),
        "--horizon",
        str(horizon),
        "--iters",
        str(args_dict["iters"]),
        "--board",
        str(args_dict["board"]),
        "--out-dir",
        str(out_dir),
        "--heartbeat-s",
        str(args_dict["heartbeat_s"]),
        *(["--slug-suffix", f"s{seed_int}"] if seed_int is not None else []),
        *(["--enable-trajectory"] if args_dict["enable_trajectory"] else []),
        *(["--skip-clean"] if args_dict["skip_clean"] else []),
        *(["--seed", str(seed_int)] if seed_int is not None else []),
    ]
    cmd = [
        "bash",
        "-lc",
        "source ~/venv/bin/activate && " + " ".join(shlex.quote(part) for part in point_cmd),
    ]
    log_dir = out_dir / "parallel_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"worker{worker_id}_{slug}.log"
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        log.write("+ " + " ".join(cmd) + "\n")
        log.flush()
        proc = subprocess.run(cmd, cwd=repo, env=env, stdout=log, stderr=subprocess.STDOUT)

    return {
        "worker_id": worker_id,
        "slug": slug,
        "horizon": horizon,
        "seed": "" if seed_int is None else seed_int,
        "impl_variant": variant["name"],
        "returncode": proc.returncode,
        "elapsed_s": int(time.time() - point_start),
        "log": str(log_path),
    }


def run_worker(worker_id: int, worker_repo: str, horizons: list[int], args_dict: dict[str, object]) -> list[dict[str, object]]:
    repo = Path(worker_repo)
    results: list[dict[str, object]] = []
    rows_dir = Path(str(args_dict["out_dir"])) / "rows"
    seeds = list(args_dict["seeds"])
    for horizon in horizons:
        if not bool(args_dict["force"]) and horizon_has_timing_clean_seed(
            rows_dir, str(args_dict["arch"]), horizon, int(args_dict["iters"]), seeds
        ):
            results.append(
                {
                    "worker_id": worker_id,
                    "slug": f"{str(args_dict['arch']).replace('_', '')}_h{horizon}_k{int(args_dict['iters'])}_already_clean",
                    "horizon": horizon,
                    "seed": "",
                    "impl_variant": "",
                    "returncode": 0,
                    "elapsed_s": 0,
                    "log": "",
                    "result": "skipped_existing_timing_clean",
                }
            )
            continue
        for seed in seeds:
            slug = slug_for(str(args_dict["arch"]), horizon, int(args_dict["iters"]), seed)
            if not bool(args_dict["force"]) and existing_row_complete(rows_dir, slug):
                row = read_single_row(rows_dir, slug)
                results.append(
                    {
                        "worker_id": worker_id,
                        "slug": slug,
                        "horizon": horizon,
                        "seed": "" if seed is None else seed,
                        "impl_variant": variant_for_seed(seed)["name"],
                        "returncode": 0,
                        "elapsed_s": 0,
                        "log": "",
                        "result": "skipped_existing_row",
                    }
                )
                if not bool(args_dict["run_all_seeds"]) and is_timing_clean(row):
                    break
                continue
            result = run_point(worker_id, repo, {"horizon": horizon, "seed": seed}, args_dict)
            row = read_single_row(rows_dir, slug)
            result["result"] = "timing_clean" if is_timing_clean(row) else "not_timing_clean"
            results.append(result)
            if not bool(args_dict["run_all_seeds"]) and is_timing_clean(row):
                print(f"H={horizon} timing-clean with seed {seed}; skipping remaining seeds.", flush=True)
                break
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Run max-horizon benchmark points in parallel worker repos.")
    parser.add_argument("--arch", required=True, choices=["staged_a", "full_sparse"])
    parser.add_argument("--horizons", required=True, help="Comma-separated horizon list, e.g. 640,704,768.")
    parser.add_argument("--seeds", default="0", help="Comma-separated Vivado seed list. Use empty string for no seed.")
    parser.add_argument("--iters", type=int, default=10)
    parser.add_argument("--board", default="custom", choices=["custom", "arty"])
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--threads-per-worker", type=int, default=1)
    parser.add_argument(
        "--work-root",
        type=Path,
        default=None,
        help="Optional worker root. If omitted, a unique /tmp directory is created for this run.",
    )
    parser.add_argument("--keep-workdirs", action="store_true", help="Keep auto-created worker repos after the run.")
    parser.add_argument("--heartbeat-s", type=int, default=60)
    parser.add_argument("--enable-trajectory", action="store_true")
    parser.add_argument("--skip-clean", action="store_true")
    parser.add_argument("--force", action="store_true", help="Rerun points even when their row CSV already exists.")
    parser.add_argument("--run-all-seeds", action="store_true", help="Do not stop a horizon after the first timing-clean seed.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned work and exit before copying or building.")
    parser.add_argument("--clean-workdirs", action="store_true", help="Delete worker repos after all points finish.")
    parser.add_argument("--no-aggregate", action="store_true", help="Do not run aggregate_max_horizon_results.py after points finish.")
    args = parser.parse_args()

    if args.iters <= 0:
        raise ValueError("--iters must be positive")
    if args.threads_per_worker <= 0:
        raise ValueError("--threads-per-worker must be positive")

    repo_root = Path(__file__).resolve().parents[1]
    out_dir = args.out_dir.resolve()
    rows_dir = out_dir / "rows"
    horizons = parse_int_list(args.horizons, "--horizons")
    raw_seeds = [tok.strip() for tok in args.seeds.split(",") if tok.strip()]
    seeds: list[int | None] = [int(tok) for tok in raw_seeds] if raw_seeds else [None]

    planned: list[tuple[int, int | None]] = []
    skipped: list[str] = []
    skipped_clean_horizons: list[int] = []
    for horizon in horizons:
        if horizon <= 0:
            raise ValueError(f"Horizon must be positive, got {horizon}")
        if not args.force and not args.run_all_seeds and horizon_has_timing_clean_seed(rows_dir, args.arch, horizon, args.iters, seeds):
            skipped_clean_horizons.append(horizon)
            continue
        for seed in seeds:
            slug = slug_for(args.arch, horizon, args.iters, seed)
            if not args.force and existing_row_complete(rows_dir, slug):
                skipped.append(slug)
                continue
            planned.append((horizon, seed))

    runnable_horizons = [
        horizon for horizon in horizons if horizon not in set(skipped_clean_horizons)
    ]
    runnable_horizons = [
        horizon for horizon in runnable_horizons
        if args.force or args.run_all_seeds or any(not existing_row_complete(rows_dir, slug_for(args.arch, horizon, args.iters, seed)) for seed in seeds)
    ]
    worker_count = args.workers if args.workers > 0 else min(4, len(runnable_horizons) or 1)
    worker_count = min(worker_count, len(runnable_horizons) or 1)

    print(f"Repo: {repo_root}")
    print(f"Output: {out_dir}")
    print(f"Planned seed attempts: {len(planned)}")
    print(f"Early stop per horizon: {not args.run_all_seeds}")
    print(f"Skipped existing: {len(skipped)}")
    print(f"Skipped timing-clean horizons: {len(skipped_clean_horizons)}")
    print(f"Workers: {worker_count}")
    print(f"Vivado threads per worker: {args.threads_per_worker}")
    print("Implementation variants:")
    for seed in seeds:
        print(f"  seed {'' if seed is None else seed}: {variant_for_seed(seed)['name']}")
    for horizon, seed in planned:
        print(f"  {slug_for(args.arch, horizon, args.iters, seed)}")
    if skipped:
        print("Skipped rows:")
        for slug in skipped:
            print(f"  {slug}")
    if skipped_clean_horizons:
        print("Skipped timing-clean horizons:")
        for horizon in skipped_clean_horizons:
            print(f"  H={horizon}")
    if args.dry_run:
        return 0
    if not runnable_horizons:
        print("No points to run.")
        return 0

    auto_work_root = args.work_root is None
    work_root = (
        Path(tempfile.mkdtemp(prefix=f"admm_fpga_{args.arch.replace('_', '')}_", dir="/tmp"))
        if auto_work_root
        else args.work_root.resolve()
    )
    print(f"Work root: {work_root}")

    out_dir.mkdir(parents=True, exist_ok=True)
    args_dict = {
        "arch": args.arch,
        "iters": args.iters,
        "board": args.board,
        "out_dir": str(out_dir),
        "threads_per_worker": args.threads_per_worker,
        "heartbeat_s": args.heartbeat_s,
        "enable_trajectory": args.enable_trajectory,
        "skip_clean": args.skip_clean,
        "force": args.force,
        "run_all_seeds": args.run_all_seeds,
        "seeds": seeds,
        "git_head": git_output(repo_root, ["rev-parse", "HEAD"]),
        "git_status_short": git_output(repo_root, ["status", "--short"]),
    }

    lock_path = None if auto_work_root else acquire_work_root_lock(work_root, out_dir)
    try:
        worker_repos: list[Path] = []
        for worker_id in range(worker_count):
            worker_repo = work_root / f"worker_{worker_id}" / "repo"
            print(f"Preparing worker repo {worker_id}: {worker_repo}", flush=True)
            copy_repo(repo_root, worker_repo)
            worker_repos.append(worker_repo)

        results: list[dict[str, object]] = []
        chunks: list[list[int]] = [[] for _ in range(worker_count)]
        for idx, horizon in enumerate(runnable_horizons):
            chunks[idx % worker_count].append(horizon)

        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as ex:
            futures = []
            for worker_id, chunk in enumerate(chunks):
                if chunk:
                    futures.append(ex.submit(run_worker, worker_id, str(worker_repos[worker_id]), chunk, args_dict))
            for fut in concurrent.futures.as_completed(futures):
                for result in fut.result():
                    results.append(result)
                    print(
                        f"Finished {result['slug']} rc={result['returncode']} "
                        f"elapsed={result['elapsed_s']}s log={result['log']}",
                        flush=True,
                    )

        manifest = out_dir / "parallel_manifest.csv"
        with manifest.open("w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["worker_id", "slug", "horizon", "seed", "impl_variant", "returncode", "elapsed_s", "log", "result"],
            )
            writer.writeheader()
            writer.writerows(sorted(results, key=lambda r: str(r["slug"])))
        print(f"Wrote {manifest}")

        if args.clean_workdirs or (auto_work_root and not args.keep_workdirs):
            shutil.rmtree(work_root, ignore_errors=True)
            print(f"Removed work root: {work_root}")

        if not args.no_aggregate:
            cmd = [
                "bash",
                "-lc",
                "source ~/venv/bin/activate && python scripts/aggregate_max_horizon_results.py --run-dir "
                + shlex.quote(str(out_dir)),
            ]
            subprocess.run(cmd, cwd=repo_root, check=False)

        failed = [r for r in results if int(r["returncode"]) != 0]
        if failed:
            print(f"Completed with {len(failed)} runner process failures. Archived failed benchmark rows may still exist.")
        return 0
    finally:
        release_work_root_lock(lock_path)


if __name__ == "__main__":
    raise SystemExit(main())
