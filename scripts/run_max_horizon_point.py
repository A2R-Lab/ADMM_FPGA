#!/usr/bin/env python3
"""Run and archive one direct max-horizon FPGA benchmark point.

This script intentionally does not use Slurm. It runs one point in the current
working tree with the requested ADMM environment, archives reports/metadata, and
emits one CSV row for later aggregation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path


REPORT_NAMES = [
    "post_synth_utilization.rpt",
    "post_synth_timing.rpt",
    "post_synth_power.rpt",
    "post_place_utilization.rpt",
    "post_place_timing.rpt",
    "post_route_utilization.rpt",
    "post_route_timing.rpt",
    "post_route_power.rpt",
    "post_route_drc.rpt",
]

GENERATED_NAMES = [
    "data.h",
    "admm_runtime_config.h",
    "traj_data.h",
    "traj_data_raw.h",
    "trajectory_refs.csv",
]


def read_text(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(path)
    return path.read_text(errors="replace")


def run_capture(
    cmd: list[str],
    cwd: Path,
    env: dict[str, str],
    log_path: Path,
    *,
    heartbeat_s: int,
) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        log.write("+ " + " ".join(cmd) + "\n")
        log.flush()
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT)
        last_heartbeat = time.time()
        while True:
            rc = proc.poll()
            if rc is not None:
                log.write(f"\n[returncode] {rc}\n")
                log.flush()
                return rc
            now = time.time()
            if heartbeat_s > 0 and now - last_heartbeat >= heartbeat_s:
                msg = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] still running: {' '.join(cmd)}"
                print(msg, flush=True)
                log.write(msg + "\n")
                log.flush()
                last_heartbeat = now
            time.sleep(1.0)


def relaunch_detached(argv: list[str], repo: Path, point_dir: Path) -> int:
    point_dir.mkdir(parents=True, exist_ok=True)
    detached_log = point_dir / "detached_runner.log"
    pid_file = point_dir / "runner.pid"
    child_argv: list[str] = []
    skip_next = False
    for arg in argv:
        if skip_next:
            skip_next = False
            continue
        if arg == "--detach":
            continue
        child_argv.append(arg)

    with detached_log.open("ab") as log:
        proc = subprocess.Popen(
            child_argv,
            cwd=repo,
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    pid_file.write_text(f"{proc.pid}\n")
    print(f"Detached benchmark runner PID {proc.pid}", flush=True)
    print(f"Log: {detached_log}", flush=True)
    print(f"PID file: {pid_file}", flush=True)
    return 0


def git_output(repo: Path, args: list[str]) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def as_number(value: str | None) -> float | int:
    if value is None or value == "":
        return 0
    v = float(value)
    return int(v) if v.is_integer() else v


def parse_utilization(report_text: str, prefix: str) -> dict[str, float | int]:
    num = r"[0-9]+(?:\.[0-9]+)?"
    row_pattern = re.compile(
        rf"\|\s*(?P<name>[^|]+?)\s*\|\s*(?P<used>{num})\s*\|"
        rf"\s*(?P<fixed>{num})?\s*\|\s*(?P<proh>{num})?\s*\|"
        rf"\s*(?P<avail>{num})?\s*\|\s*(?P<util>{num})\s*\|"
    )
    wanted = {
        "Slice LUTs": "slice_luts",
        "LUT as Logic": "lut_as_logic",
        "LUT as Memory": "lut_as_mem",
        "Slice Registers": "slice_registers",
        "Register as Flip Flop": "reg_as_ff",
        "Block RAM Tile": "bram_tile",
        "RAMB36/FIFO": "ramb36_fifo",
        "RAMB18": "ramb18",
        "URAM": "uram",
        "DSPs": "dsps",
    }
    out: dict[str, float | int] = {}
    for m in row_pattern.finditer(report_text):
        name = " ".join(m.group("name").split()).rstrip("*")
        key = wanted.get(name)
        if key is None:
            continue
        out[f"{prefix}_{key}_used"] = as_number(m.group("used"))
        out[f"{prefix}_{key}_avail"] = as_number(m.group("avail"))
        out[f"{prefix}_{key}_util_pct"] = float(m.group("util"))
    return out


def parse_vivado_timing(report_text: str, prefix: str) -> dict[str, float | int]:
    summary_match = re.search(
        r"\n\s*([\-0-9.]+)\s+([\-0-9.]+)\s+([0-9]+)\s+([0-9]+)"
        r"\s+([\-0-9.]+)\s+([\-0-9.]+)\s+([0-9]+)\s+([0-9]+)",
        report_text,
    )
    if not summary_match:
        raise ValueError("Could not parse Design Timing Summary row")
    wns = float(summary_match.group(1))
    tns = float(summary_match.group(2))
    failing_endpoints = int(summary_match.group(3))
    total_endpoints = int(summary_match.group(4))

    clk_match = re.search(
        r"\n\s*sys_clk\s+\{[^}]+\}\s+([0-9]+\.?[0-9]*)\s+([0-9]+\.?[0-9]*)\s*\n",
        report_text,
    )
    clk_period_ns = float(clk_match.group(1)) if clk_match else 0.0
    clk_freq_mhz = float(clk_match.group(2)) if clk_match else 0.0
    fmax_est_mhz = (1000.0 / (clk_period_ns - wns)) if clk_period_ns > wns else 0.0
    return {
        f"{prefix}_wns_ns": wns,
        f"{prefix}_tns_ns": tns,
        f"{prefix}_failing_endpoints": failing_endpoints,
        f"{prefix}_total_endpoints": total_endpoints,
        f"{prefix}_clk_period_ns": clk_period_ns,
        f"{prefix}_clk_freq_mhz": clk_freq_mhz,
        f"{prefix}_fmax_est_mhz": fmax_est_mhz,
    }


def parse_hls_timing(report_text: str) -> dict[str, float]:
    m = re.search(
        r"\|\s*ap_clk\s*\|\s*([0-9]+\.?[0-9]*)\s*ns\|\s*([0-9]+\.?[0-9]*)\s*ns\|\s*([0-9]+\.?[0-9]*)\s*ns\|",
        report_text,
    )
    if not m:
        raise ValueError("Could not parse HLS ap_clk timing row")
    estimated_ns = float(m.group(2))
    return {
        "hls_target_clk_ns": float(m.group(1)),
        "hls_est_clk_ns": estimated_ns,
        "hls_uncertainty_ns": float(m.group(3)),
        "hls_est_fmax_mhz": (1000.0 / estimated_ns) if estimated_ns > 0 else 0.0,
    }


def parse_hls_latency_cycles(report_text: str) -> int:
    m = re.search(
        r"\|\s*([0-9]+)\s*\|\s*([0-9]+)\s*\|\s*[0-9]+\.?[0-9]*\s*[num]?s\|\s*"
        r"[0-9]+\.?[0-9]*\s*[num]?s\|\s*([0-9]+)\s*\|\s*([0-9]+)\s*\|",
        report_text,
    )
    if not m:
        raise ValueError("Could not parse HLS latency summary row")
    return int(m.group(2))


def parse_hls_resources(report_text: str) -> dict[str, float | int]:
    out: dict[str, float | int] = {}
    resource_names = {
        "BRAM_18K": "hls_bram_18k",
        "DSP": "hls_dsp",
        "FF": "hls_ff",
        "LUT": "hls_lut",
        "URAM": "hls_uram",
    }
    for label, key in resource_names.items():
        m = re.search(
            rf"\|\s*{re.escape(label)}\s*\|\s*([0-9.]+)\s*\|\s*([0-9.]+)\s*\|\s*([0-9.]+)\s*\|",
            report_text,
        )
        if m:
            out[f"{key}_used"] = as_number(m.group(1))
            out[f"{key}_avail"] = as_number(m.group(2))
            out[f"{key}_util_pct"] = float(m.group(3))
    return out


def parse_power(report_text: str, prefix: str) -> dict[str, float]:
    def grab(label: str) -> float:
        m = re.search(rf"\|\s*{re.escape(label)}\s*\|\s*([0-9]+\.?[0-9]*)\s*\|", report_text)
        if not m:
            raise ValueError(f"Could not parse power field: {label}")
        return float(m.group(1))

    return {
        f"{prefix}_power_total_w": grab("Total On-Chip Power (W)"),
        f"{prefix}_power_dynamic_w": grab("Dynamic (W)"),
        f"{prefix}_power_static_w": grab("Device Static (W)"),
    }


def safe_div(a: float, b: float) -> float:
    return a / b if b else math.nan


def copy_if_exists(src: Path, dst: Path) -> None:
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def remove_generated_files(repo: Path) -> None:
    hls_dir = repo / "vitis_projects" / "ADMM"
    rtl_params = repo / "vivado_project" / "vivado_project.srcs" / "sources_1" / "new" / "admm_autogen_params.vh"
    for name in GENERATED_NAMES + ["test_data.h", "admm_runtime_config.h"]:
        path = hls_dir / name
        if path.exists():
            path.unlink()
    if rtl_params.exists():
        rtl_params.unlink()


def archive_artifacts(repo: Path, point_dir: Path) -> None:
    build_dir = repo / "build"
    reports_dir = build_dir / "reports"
    for name in REPORT_NAMES:
        copy_if_exists(reports_dir / name, point_dir / "reports" / name)

    hls_report_dir = repo / "vitis_projects" / "ADMM" / "ADMM" / "hls" / "syn" / "report"
    for name in ["ADMM_solver_csynth.rpt", "ADMM_solver_csynth.xml"]:
        copy_if_exists(hls_report_dir / name, point_dir / "reports" / name)

    hls_dir = repo / "vitis_projects" / "ADMM"
    for name in GENERATED_NAMES + ["admm_runtime_config.h"]:
        copy_if_exists(hls_dir / name, point_dir / "generated" / name)
    copy_if_exists(
        repo / "vivado_project" / "vivado_project.srcs" / "sources_1" / "new" / "admm_autogen_params.vh",
        point_dir / "generated" / "admm_autogen_params.vh",
    )

    logs_dir = build_dir / "logs"
    if logs_dir.exists():
        dst = point_dir / "vivado_logs"
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(logs_dir, dst)

    for name in ["top_spi.bit", "top_spi.bin", "top_spi.prm", "top_uart.bit", "top_uart.bin", "top_uart.prm"]:
        copy_if_exists(build_dir / name, point_dir / "bitstream" / name)


def parse_reports(repo: Path, deadline_us: float, spi_budget_us: float, iters: int) -> dict[str, object]:
    row: dict[str, object] = {}
    hls_rpt = repo / "vitis_projects" / "ADMM" / "ADMM" / "hls" / "syn" / "report" / "ADMM_solver_csynth.rpt"
    hls_text = read_text(hls_rpt)
    row.update(parse_hls_timing(hls_text))
    row["hls_latency_cycles"] = parse_hls_latency_cycles(hls_text)
    row.update(parse_hls_resources(hls_text))

    reports_dir = repo / "build" / "reports"
    for name, prefix, parser in [
        ("post_synth_utilization.rpt", "synth", parse_utilization),
        ("post_place_utilization.rpt", "place", parse_utilization),
        ("post_route_utilization.rpt", "route", parse_utilization),
        ("post_synth_timing.rpt", "synth", parse_vivado_timing),
        ("post_place_timing.rpt", "place", parse_vivado_timing),
        ("post_route_timing.rpt", "route", parse_vivado_timing),
        ("post_synth_power.rpt", "synth", parse_power),
        ("post_route_power.rpt", "route", parse_power),
    ]:
        path = reports_dir / name
        if path.exists():
            row.update(parser(read_text(path), prefix))

    clk_mhz = float(row.get("route_clk_freq_mhz") or 100.0)
    fmax_mhz = float(row.get("route_fmax_est_mhz") or 0.0)
    latency_cycles = float(row["hls_latency_cycles"])
    solve_us_cfg = safe_div(latency_cycles, clk_mhz)
    solve_us_fmax = safe_div(latency_cycles, fmax_mhz)
    route_power = float(row.get("route_power_total_w") or math.nan)
    row["solve_us_cfg_clk"] = solve_us_cfg
    row["solve_us_route_fmax"] = solve_us_fmax
    row["deadline_us"] = deadline_us
    row["spi_budget_us"] = spi_budget_us
    row["deadline_margin_us"] = deadline_us - spi_budget_us - solve_us_cfg
    row["meets_deadline"] = int(row["deadline_margin_us"] >= 0)
    row["throughput_cfg_sps"] = safe_div(1_000_000.0, solve_us_cfg)
    row["throughput_route_fmax_sps"] = safe_div(1_000_000.0, solve_us_fmax)
    row["energy_per_solve_cfg_uj"] = route_power * solve_us_cfg
    row["energy_per_solve_route_fmax_uj"] = route_power * solve_us_fmax
    row["energy_per_iter_cfg_nj"] = safe_div(row["energy_per_solve_cfg_uj"] * 1000.0, float(iters))
    for res in ["slice_luts", "slice_registers", "lut_as_mem", "bram_tile", "dsps", "uram"]:
        used = row.get(f"route_{res}_used")
        avail = row.get(f"route_{res}_avail")
        if used not in (None, "") and avail not in (None, ""):
            row[f"route_{res}_headroom"] = float(avail) - float(used)
    return row


def write_row_csv(path: Path, row: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=sorted(row))
        writer.writeheader()
        writer.writerow(row)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one direct max-horizon benchmark point.")
    parser.add_argument("--arch", required=True, choices=["staged_a", "full_sparse"])
    parser.add_argument("--horizon", required=True, type=int)
    parser.add_argument("--iters", type=int, default=10)
    parser.add_argument("--seed", type=int, default=None, help="Requested Vivado place/route seed recorded with this point.")
    parser.add_argument("--slug-suffix", default="", help="Suffix appended to the archived point slug.")
    parser.add_argument("--board", default="custom", choices=["custom", "arty"])
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--deadline-us", type=float, default=1000.0)
    parser.add_argument("--spi-budget-us", type=float, default=100.0)
    parser.add_argument("--enable-trajectory", action="store_true")
    parser.add_argument("--skip-clean", action="store_true", help="Do not run make clean-all before this point.")
    parser.add_argument("--detach", action="store_true", help="Start the point in a detached session and return immediately.")
    parser.add_argument("--heartbeat-s", type=int, default=60, help="Foreground heartbeat interval; 0 disables.")
    parser.add_argument(
        "--strict-exit-code",
        action="store_true",
        help="Return the failing build/clean code when the point fails. By default, archived benchmark failures exit 0.",
    )
    args = parser.parse_args()

    if args.horizon <= 0 or args.iters <= 0:
        raise ValueError("--horizon and --iters must be positive")

    repo = Path(__file__).resolve().parents[1]
    safe_suffix = args.slug_suffix.strip()
    if safe_suffix and not safe_suffix.startswith("_"):
        safe_suffix = "_" + safe_suffix
    slug = f"{args.arch.replace('_', '')}_h{args.horizon}_k{args.iters}{safe_suffix}"
    point_dir = (args.out_dir / slug).resolve()
    if args.detach:
        return relaunch_detached(sys.argv, repo, point_dir)

    logs_dir = point_dir / "command_logs"
    rows_dir = args.out_dir / "rows"
    point_dir.mkdir(parents=True, exist_ok=True)
    rows_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.update(
        {
            "ADMM_SOLVER_ARCH": args.arch,
            "ADMM_HORIZON_LENGTH": str(args.horizon),
            "ADMM_ITERATIONS": str(args.iters),
            "ADMM_ENABLE_TRAJECTORY": "1" if args.enable_trajectory else "0",
            "ADMM_GENERATOR_DIAGNOSTICS_PATH": str(point_dir / "generator_diagnostics.json"),
        }
    )
    if args.seed is not None:
        env["VIVADO_PLACE_SEED"] = str(args.seed)
        env["VIVADO_ROUTE_SEED"] = str(args.seed)

    metadata = {
        "slug": slug,
        "arch": args.arch,
        "horizon": args.horizon,
        "admm_iters": args.iters,
        "seed": "" if args.seed is None else args.seed,
        "vivado_place_seed": env.get("VIVADO_PLACE_SEED", ""),
        "vivado_route_seed": env.get("VIVADO_ROUTE_SEED", ""),
        "vivado_max_threads": env.get("VIVADO_MAX_THREADS", ""),
        "vivado_impl_variant": env.get("VIVADO_IMPL_VARIANT", ""),
        "vivado_opt_directive": env.get("VIVADO_OPT_DIRECTIVE", ""),
        "vivado_place_directive": env.get("VIVADO_PLACE_DIRECTIVE", ""),
        "vivado_place_subdirective": env.get("VIVADO_PLACE_SUBDIRECTIVE", ""),
        "vivado_phys_opt_directive": env.get("VIVADO_PHYS_OPT_DIRECTIVE", ""),
        "vivado_route_directive": env.get("VIVADO_ROUTE_DIRECTIVE", ""),
        "vivado_route_tns_cleanup": env.get("VIVADO_ROUTE_TNS_CLEANUP", ""),
        "vivado_route_ultrathreads": env.get("VIVADO_ROUTE_ULTRATHREADS", ""),
        "worker_id": env.get("BENCHMARK_WORKER_ID", ""),
        "board": args.board,
        "enable_trajectory": int(args.enable_trajectory),
        "repo": str(repo),
        "out_dir": str(args.out_dir.resolve()),
        "git_head": env.get("BENCHMARK_GIT_HEAD") or git_output(repo, ["rev-parse", "HEAD"]),
        "git_status_short": env.get("BENCHMARK_GIT_STATUS_SHORT") or git_output(repo, ["status", "--short"]),
        "python": sys.executable,
        "start_epoch": int(time.time()),
    }
    (point_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")

    start = time.time()
    status = "pass"
    failed_stage = ""
    clean_rc = 0
    build_rc = 0
    if not args.skip_clean:
        clean_rc = run_capture(
            ["make", f"BOARD={args.board}", "clean-all"],
            repo,
            env,
            logs_dir / "clean-all.log",
            heartbeat_s=args.heartbeat_s,
        )
        if clean_rc != 0:
            status = "fail"
            failed_stage = f"clean_all_rc_{clean_rc}"

    if status == "pass":
        remove_generated_files(repo)
        build_rc = run_capture(
            ["make", f"BOARD={args.board}", "bit"],
            repo,
            env,
            logs_dir / "make-bit.log",
            heartbeat_s=args.heartbeat_s,
        )
        if build_rc != 0:
            status = "fail"
            failed_stage = f"make_bit_rc_{build_rc}"

    archive_artifacts(repo, point_dir)

    row: dict[str, object] = {
        **metadata,
        "status": status,
        "failed_stage": failed_stage,
        "clean_rc": clean_rc,
        "build_rc": build_rc,
        "build_runtime_s": int(time.time() - start),
        "point_dir": str(point_dir),
    }
    diagnostics_path = point_dir / "generator_diagnostics.json"
    if diagnostics_path.exists():
        diag = json.loads(diagnostics_path.read_text())
        row.update({f"gen_{k}": v for k, v in diag.items() if not isinstance(v, (list, dict))})

    if status == "pass":
        try:
            row.update(parse_reports(repo, args.deadline_us, args.spi_budget_us, args.iters))
        except Exception as exc:
            row["status"] = "parse_fail"
            row["failed_stage"] = f"parse_reports:{type(exc).__name__}:{exc}"

    bit_name = "top_uart.bit" if args.board == "arty" else "top_spi.bit"
    bin_name = "top_uart.bin" if args.board == "arty" else "top_spi.bin"
    for label, name in [("bitstream", bit_name), ("flash_bin", bin_name)]:
        path = point_dir / "bitstream" / name
        row[f"{label}_exists"] = int(path.exists())
        if path.exists():
            row[f"{label}_sha256"] = sha256_file(path)
            row[f"{label}_bytes"] = path.stat().st_size

    write_row_csv(rows_dir / f"{slug}.csv", row)
    write_row_csv(point_dir / "row.csv", row)
    print(f"Wrote point archive: {point_dir}")
    print(f"Wrote row: {rows_dir / f'{slug}.csv'}")
    if status != "pass":
        print(f"Point status: {status} ({row.get('failed_stage', failed_stage)})", flush=True)
    if args.strict_exit_code and status != "pass":
        return build_rc or clean_rc or 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
