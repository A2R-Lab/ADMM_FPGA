#!/usr/bin/env python3
"""
Parallel pre-build of FPGA bitstreams for a rho/Q sweep using isolated worker repos.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import itertools
import os
import shutil
import subprocess
from pathlib import Path


DEFAULT_RHO_VALUES = [1, 4, 8, 16, 32, 64, 128, 256]
DEFAULT_Q_VALUES = [100, 200, 500, 1000, 2000, 5000, 10000, 20000]
DEFAULT_Q_DIAG = [70.0, 70.0, 178.0, 0.4, 0.4, 40.0, 3.5, 3.5, 4.0, 0.2, 0.2, 25.0]


def parse_int_list(text: str, what: str) -> list[int]:
    vals = [int(tok.strip()) for tok in text.split(",") if tok.strip()]
    if not vals:
        raise ValueError(f"No values parsed from {what}")
    return vals


def parse_float_list(text: str, what: str) -> list[float]:
    vals = [float(tok.strip()) for tok in text.split(",") if tok.strip()]
    if not vals:
        raise ValueError(f"No values parsed from {what}")
    return vals


def make_slug(rho: int, q: float) -> str:
    qtxt = f"{q:.6g}".replace("-", "m").replace(".", "p")
    return f"r{rho}_q{qtxt}"


def run_cmd(cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    print(f"[{cwd.name}] + {' '.join(cmd)}")
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def make_generation_env(*, horizon: int, admm_iters: int, rho: int, qxy: float) -> dict[str, str]:
    q_diag = list(DEFAULT_Q_DIAG)
    q_diag[0] = qxy
    q_diag[1] = qxy
    env = os.environ.copy()
    env["ADMM_HORIZON_LENGTH"] = str(horizon)
    env["ADMM_ITERATIONS"] = str(admm_iters)
    env["ADMM_RHO_EQ_PARAM"] = str(rho)
    env["ADMM_RHO_INEQ_PARAM"] = str(rho)
    env["ADMM_Q_DIAG"] = ",".join(f"{v:.12g}" for v in q_diag)
    return env


def run_generators(repo: Path, env: dict[str, str]) -> None:
    run_cmd(["python3", "scripts/trajectory_generator.py"], cwd=repo, env=env)
    run_cmd(["python3", "scripts/header_generator.py"], cwd=repo, env=env)


def worker_run(
    worker_repo: str,
    jobs: list[dict[str, object]],
    board: str,
    horizon: int,
    admm_iters: int,
    bit_out_dir: str,
) -> list[dict[str, object]]:
    repo = Path(worker_repo)
    out_dir = Path(bit_out_dir)
    rows: list[dict[str, object]] = []
    top_module = "top_uart" if board == "arty" else "top_spi"

    for job in jobs:
        rho = int(job["rho"])
        q = float(job["q"])
        slug = str(job["slug"])
        bit_dst = out_dir / f"{slug}.bit"
        status = "ok"
        error = ""
        try:
            env = make_generation_env(horizon=horizon, admm_iters=admm_iters, rho=rho, qxy=q)
            run_generators(repo, env)
            run_cmd(["make", f"BOARD={board}", "bit"], cwd=repo)

            bit_src = repo / "build" / f"{top_module}.bit"
            if not bit_src.exists():
                raise FileNotFoundError(f"Missing generated bitstream: {bit_src}")
            shutil.copy2(bit_src, bit_dst)
        except Exception as exc:
            status = "error"
            error = str(exc)

        rows.append(
            {
                "rho": rho,
                "q": q,
                "slug": slug,
                "bit_path": str(bit_dst),
                "status": status,
                "error": error,
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Build rho/Q sweep bitstreams in parallel workers.")
    parser.add_argument("--board", default="arty", help="FPGA board for make BOARD=... (arty/custom).")
    parser.add_argument("--horizon", type=int, default=20, help="MPC horizon.")
    parser.add_argument("--admm-iters", type=int, default=28, help="ADMM iterations in hardware.")
    parser.add_argument(
        "--rho-values",
        default=",".join(str(v) for v in DEFAULT_RHO_VALUES),
        help="Comma-separated rho values (power-of-2 values).",
    )
    parser.add_argument(
        "--q-values",
        default=",".join(f"{v:.2f}" for v in DEFAULT_Q_VALUES),
        help="Comma-separated Q values (applied to Qx and Qy equally).",
    )
    parser.add_argument("--workers", type=int, default=16, help="Number of parallel builder workers.")
    parser.add_argument(
        "--work-root",
        default="/tmp/admm_fpga_parallel_build",
        help="Root folder for worker repo copies.",
    )
    parser.add_argument(
        "--output-dir",
        default="build/bitstreams_grid",
        help="Repo-relative output folder for built bitstreams and manifest.",
    )
    parser.add_argument(
        "--clean-workdirs",
        action="store_true",
        help="Delete worker repo copies after build completes.",
    )
    parser.add_argument(
        "--force-rebuild",
        action="store_true",
        help="Rebuild even if bitstream already exists in output dir.",
    )
    parser.add_argument(
        "--run-after-build",
        action="store_true",
        help="After build phase completes, launch run_prebuilt_bitstreams.py automatically.",
    )
    parser.add_argument("--run-port", default="/dev/ttyUSB1", help="Runner UART port.")
    parser.add_argument("--run-baud", type=int, default=921600, help="Runner UART baud.")
    parser.add_argument("--run-uart-timeout", type=float, default=30.0, help="Runner UART timeout [s].")
    parser.add_argument("--run-sim-freq", type=float, default=200.0, help="Runner HIL frequency [Hz].")
    parser.add_argument("--run-sim-duration-s", type=float, default=10.0, help="Runner HIL duration [s].")
    parser.add_argument("--run-step-x", type=float, default=2.0, help="Runner step x [m].")
    parser.add_argument("--run-step-y", type=float, default=0.0, help="Runner step y [m].")
    parser.add_argument("--run-step-z", type=float, default=0.0, help="Runner step z [m].")
    parser.add_argument(
        "--run-output-dir",
        default="plots/hw_controller_grid_from_prebuilt",
        help="Runner output directory for trajectory plots/CSVs/metrics.",
    )
    parser.add_argument(
        "--run-continue-on-error",
        action="store_true",
        help="Forward continue-on-error to runner.",
    )
    args = parser.parse_args()

    if args.horizon <= 0:
        raise ValueError("--horizon must be > 0")
    if args.admm_iters <= 0:
        raise ValueError("--admm-iters must be > 0")
    if args.workers <= 0:
        raise ValueError("--workers must be > 0")

    rho_vals = parse_int_list(args.rho_values, "--rho-values")
    for rho in rho_vals:
        if rho <= 0 or (rho & (rho - 1)):
            raise ValueError(f"rho must be positive power-of-2, got {rho}")
    q_vals = parse_float_list(args.q_values, "--q-values")
    if any(v <= 0 for v in q_vals):
        raise ValueError("All q values must be > 0")

    repo_root = Path(__file__).resolve().parents[1]
    output_dir = repo_root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    bit_out_dir = output_dir / "bitstreams"
    bit_out_dir.mkdir(parents=True, exist_ok=True)
    manifest_csv = output_dir / "manifest.csv"

    jobs: list[dict[str, object]] = []
    for rho, q in itertools.product(rho_vals, q_vals):
        slug = make_slug(rho, q)
        bit_path = bit_out_dir / f"{slug}.bit"
        if bit_path.exists() and not args.force_rebuild:
            jobs.append({"rho": rho, "q": q, "slug": slug, "prebuilt": True})
        else:
            jobs.append({"rho": rho, "q": q, "slug": slug, "prebuilt": False})

    to_build = [j for j in jobs if not bool(j["prebuilt"])]
    print(f"Total configs: {len(jobs)}")
    print(f"Already built: {len(jobs) - len(to_build)}")
    print(f"To build now: {len(to_build)}")

    all_rows: list[dict[str, object]] = []
    for j in jobs:
        if bool(j["prebuilt"]):
            all_rows.append(
                {
                    "rho": int(j["rho"]),
                    "q": float(j["q"]),
                    "slug": str(j["slug"]),
                    "bit_path": str(bit_out_dir / f"{j['slug']}.bit"),
                    "status": "ok",
                    "error": "",
                }
            )

    if to_build:
        work_root = Path(args.work_root).resolve()
        work_root.mkdir(parents=True, exist_ok=True)
        worker_count = min(args.workers, len(to_build))
        worker_repos: list[Path] = []

        ignore_names = shutil.ignore_patterns(
            ".git",
            "__pycache__",
            ".Xil",
            "build",
            "vivado*.log",
            "vivado*.jou",
            "*.pyc",
        )

        for w in range(worker_count):
            worker_repo = work_root / f"worker_{w}" / "repo"
            if worker_repo.exists():
                shutil.rmtree(worker_repo.parent)
            worker_repo.parent.mkdir(parents=True, exist_ok=True)
            print(f"Preparing worker repo: {worker_repo}")
            shutil.copytree(repo_root, worker_repo, ignore=ignore_names)
            worker_repos.append(worker_repo)

        chunks: list[list[dict[str, object]]] = [[] for _ in range(worker_count)]
        for idx, job in enumerate(to_build):
            chunks[idx % worker_count].append(job)

        with concurrent.futures.ProcessPoolExecutor(max_workers=worker_count) as ex:
            futures = []
            for idx in range(worker_count):
                futures.append(
                    ex.submit(
                        worker_run,
                        str(worker_repos[idx]),
                        chunks[idx],
                        args.board,
                        args.horizon,
                        args.admm_iters,
                        str(bit_out_dir),
                    )
                )
            for fut in concurrent.futures.as_completed(futures):
                all_rows.extend(fut.result())

        if args.clean_workdirs:
            shutil.rmtree(work_root, ignore_errors=True)

    all_rows_sorted = sorted(all_rows, key=lambda r: (int(r["rho"]), float(r["q"])))
    with manifest_csv.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["rho", "q", "slug", "bit_path", "status", "error"])
        writer.writeheader()
        writer.writerows(all_rows_sorted)

    ok = sum(1 for r in all_rows_sorted if r["status"] == "ok")
    err = len(all_rows_sorted) - ok
    print(f"Manifest: {manifest_csv}")
    print(f"Built/available bitstreams: ok={ok}, error={err}")

    if args.run_after_build:
        run_cmd(
            [
                "python3",
                "scripts/run_prebuilt_bitstreams.py",
                "--manifest",
                str(manifest_csv.relative_to(repo_root)),
                "--port",
                args.run_port,
                "--baud",
                str(args.run_baud),
                "--uart-timeout",
                str(args.run_uart_timeout),
                "--sim-freq",
                str(args.run_sim_freq),
                "--sim-duration-s",
                str(args.run_sim_duration_s),
                "--step-x",
                str(args.run_step_x),
                "--step-y",
                str(args.run_step_y),
                "--step-z",
                str(args.run_step_z),
                "--output-dir",
                args.run_output_dir,
                *(["--continue-on-error"] if args.run_continue_on_error else []),
            ],
            cwd=repo_root,
        )


if __name__ == "__main__":
    main()
