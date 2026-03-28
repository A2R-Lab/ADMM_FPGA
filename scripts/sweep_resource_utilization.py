#!/usr/bin/env python3
"""
Sweep ADMM horizon values and collect FPGA resource utilization from Vivado reports.

Per horizon, this script:
1) Regenerates headers with the requested horizon (+ optionally ADMM iterations)
2) Runs Vivado synthesis + implementation
3) Parses HLS timing + post-synth/post-route reports
4) Saves both a machine-readable CSV and per-horizon report snapshots
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import subprocess
from pathlib import Path

DEFAULT_HORIZONS = [10, 20, 30, 40, 50, 60, 70, 80]
DEFAULT_ADMM_ITERS = [1,2,5,10,15,20,25,30]


def parse_horizons(text: str) -> list[int]:
    vals = [int(tok.strip()) for tok in text.split(",") if tok.strip()]
    if not vals:
        raise ValueError("No horizons parsed from --horizons")
    if any(v <= 0 for v in vals):
        raise ValueError("All horizons must be > 0")
    return vals


def parse_positive_int_list(text: str, what: str) -> list[int]:
    vals = [int(tok.strip()) for tok in text.split(",") if tok.strip()]
    if not vals:
        raise ValueError(f"No values parsed from {what}")
    if any(v <= 0 for v in vals):
        raise ValueError(f"All values in {what} must be > 0")
    return vals


def run_cmd(cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    print(f"+ {' '.join(cmd)}")
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def run_generation(repo_root: Path, *, horizon: int, admm_iters: int) -> None:
    env = os.environ.copy()
    env["ADMM_HORIZON_LENGTH"] = str(horizon)
    env["ADMM_ITERATIONS"] = str(admm_iters)
    scripts_dir = repo_root / "scripts"
    run_cmd(["python3", str(scripts_dir / "trajectory_generator.py")], cwd=repo_root, env=env)
    run_cmd(["python3", str(scripts_dir / "header_generator.py")], cwd=repo_root, env=env)


def read_text(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Missing report file: {path}")
    return path.read_text(errors="replace")


def parse_utilization(report_text: str) -> dict[str, float | int]:
    # Matches table rows like:
    # | Slice LUTs                 | 40392 | ... | 63400 | 63.71 |
    num = r"[0-9]+(?:\.[0-9]+)?"
    row_pattern = re.compile(
        rf"\|\s*(?P<name>[^|]+?)\s*\|\s*(?P<used>{num})\s*\|"
        rf"\s*(?P<fixed>{num})?\s*\|\s*(?P<proh>{num})?\s*\|"
        rf"\s*(?P<avail>{num})?\s*\|\s*(?P<util>{num})\s*\|"
    )

    wanted = {
        "Slice LUTs": ("slice_luts_used", "slice_luts_avail", "slice_luts_util_pct"),
        "LUT as Memory": ("lut_as_mem_used", "lut_as_mem_avail", "lut_as_mem_util_pct"),
        "Block RAM Tile": ("bram_tile_used", "bram_tile_avail", "bram_tile_util_pct"),
        "DSPs": ("dsps_used", "dsps_avail", "dsps_util_pct"),
    }

    def as_number(value: str | None) -> float | int:
        if value is None or value == "":
            return 0
        v = float(value)
        return int(v) if v.is_integer() else v

    out: dict[str, float | int] = {}
    for m in row_pattern.finditer(report_text):
        name = " ".join(m.group("name").split())
        if name not in wanted:
            continue

        used_k, avail_k, util_k = wanted[name]
        out[used_k] = as_number(m.group("used"))
        out[avail_k] = as_number(m.group("avail"))
        out[util_k] = float(m.group("util"))

    missing = [k for trio in wanted.values() for k in trio if k not in out]
    if missing:
        raise ValueError(f"Could not parse utilization fields: {missing}")

    return out


def parse_vivado_timing(report_text: str) -> dict[str, float | int]:
    # Design Timing Summary row values, e.g.:
    #   0.002  0.000  0  159038 ...
    summary_match = re.search(
        r"\n\s*([\-0-9.]+)\s+([\-0-9.]+)\s+([0-9]+)\s+([0-9]+)"
        r"\s+([\-0-9.]+)\s+([\-0-9.]+)\s+([0-9]+)\s+([0-9]+)",
        report_text,
    )
    if not summary_match:
        raise ValueError("Could not parse Design Timing Summary row")

    wns = float(summary_match.group(1))
    tns = float(summary_match.group(2))

    # Clock summary for nominal frequency
    clk_match = re.search(
        r"\n\s*sys_clk\s+\{[^}]+\}\s+([0-9]+\.?[0-9]*)\s+([0-9]+\.?[0-9]*)\s*\n",
        report_text,
    )
    clk_period_ns = float(clk_match.group(1)) if clk_match else 0.0
    clk_freq_mhz = float(clk_match.group(2)) if clk_match else 0.0

    fmax_est_mhz = (1000.0 / (clk_period_ns - wns)) if clk_period_ns > wns else 0.0

    return {
        "wns_ns": wns,
        "tns_ns": tns,
        "clk_period_ns": clk_period_ns,
        "clk_freq_mhz": clk_freq_mhz,
        "fmax_est_mhz": fmax_est_mhz,
    }


def parse_hls_timing(report_text: str) -> dict[str, float]:
    # Timing table in ADMM_solver_csynth.rpt, e.g.:
    # |ap_clk  | 10.00 ns|  7.916 ns|     2.70 ns|
    m = re.search(
        r"\|\s*ap_clk\s*\|\s*([0-9]+\.?[0-9]*)\s*ns\|\s*([0-9]+\.?[0-9]*)\s*ns\|\s*([0-9]+\.?[0-9]*)\s*ns\|",
        report_text,
    )
    if not m:
        raise ValueError("Could not parse HLS ap_clk timing row")

    target_ns = float(m.group(1))
    estimated_ns = float(m.group(2))
    uncertainty_ns = float(m.group(3))
    est_fmax_mhz = (1000.0 / estimated_ns) if estimated_ns > 0 else 0.0

    return {
        "hls_target_clk_ns": target_ns,
        "hls_est_clk_ns": estimated_ns,
        "hls_uncertainty_ns": uncertainty_ns,
        "hls_est_fmax_mhz": est_fmax_mhz,
    }


def parse_hls_latency_cycles(report_text: str) -> int:
    # Latency summary row in ADMM_solver_csynth.rpt, e.g.:
    # |   677101|   677101|  6.771 ms|  6.771 ms|  677102|  677102|       no|
    m = re.search(
        r"\|\s*([0-9]+)\s*\|\s*([0-9]+)\s*\|\s*[0-9]+\.?[0-9]*\s*[num]?s\|\s*"
        r"[0-9]+\.?[0-9]*\s*[num]?s\|\s*([0-9]+)\s*\|\s*([0-9]+)\s*\|",
        report_text,
    )
    if not m:
        raise ValueError("Could not parse HLS latency summary row")

    lat_max_cycles = int(m.group(2))
    return lat_max_cycles


def parse_power(report_text: str) -> dict[str, float]:
    # Rows like:
    # | Total On-Chip Power (W)  | 0.694        |
    def grab(label: str) -> float:
        m = re.search(rf"\|\s*{re.escape(label)}\s*\|\s*([0-9]+\.?[0-9]*)\s*\|", report_text)
        if not m:
            raise ValueError(f"Could not parse power field: {label}")
        return float(m.group(1))

    return {
        "power_total_w": grab("Total On-Chip Power (W)"),
        "power_dynamic_w": grab("Dynamic (W)"),
        "power_static_w": grab("Device Static (W)"),
    }


def archive_reports(reports_dir: Path, archive_root: Path, horizon: int, admm_iters: int) -> None:
    out_dir = archive_root / f"h{horizon}_k{admm_iters}"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in [
        "post_synth_utilization.rpt",
        "post_synth_timing.rpt",
        "post_place_utilization.rpt",
        "post_place_timing.rpt",
        "post_route_utilization.rpt",
        "post_route_timing.rpt",
        "post_route_power.rpt",
        "post_route_drc.rpt",
    ]:
        src = reports_dir / name
        if src.exists():
            shutil.copy2(src, out_dir / name)


def archive_hls_report(hls_report: Path, archive_root: Path, horizon: int, admm_iters: int) -> None:
    out_dir = archive_root / f"h{horizon}_k{admm_iters}"
    out_dir.mkdir(parents=True, exist_ok=True)
    if hls_report.exists():
        shutil.copy2(hls_report, out_dir / hls_report.name)


def safe_div(num: float, den: float) -> float:
    return num / den if den > 0 else 0.0


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Run FPGA resource-utilization sweep across horizons.")
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
        help="Optional ADMM iterations forwarded to header_generator.py.",
    )
    parser.add_argument(
        "--admm-iters-list",
        default=None,
        help="Comma-separated ADMM iteration list for grid sweep (e.g. 5,10,20).",
    )
    parser.add_argument(
        "--output-csv",
        default="plots/fpga_resource_sweep.csv",
        help="Output CSV path (repo-relative).",
    )
    parser.add_argument(
        "--archive-dir",
        default="build/reports_horizon_sweep",
        help="Folder to store per-horizon copies of Vivado reports.",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue with next horizon if one horizon fails.",
    )
    args = parser.parse_args()

    horizons = parse_horizons(args.horizons)
    if args.admm_iters_list is not None:
        admm_iters_values = parse_positive_int_list(args.admm_iters_list, "--admm-iters-list")
    elif args.admm_iters is not None:
        if args.admm_iters <= 0:
            raise ValueError("--admm-iters must be > 0")
        admm_iters_values = [args.admm_iters]
    else:
        admm_iters_values = list(DEFAULT_ADMM_ITERS)

    repo_root = Path(__file__).resolve().parents[1]
    scripts_dir = repo_root / "scripts"
    reports_dir = repo_root / "build" / "reports"
    hls_timing_report = repo_root / "vitis_projects" / "ADMM" / "ADMM" / "hls" / "syn" / "report" / "ADMM_solver_csynth.rpt"
    output_csv = repo_root / args.output_csv
    archive_dir = repo_root / args.archive_dir

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    archive_dir.mkdir(parents=True, exist_ok=True)

    fieldnames = [
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

    # Resume-friendly behavior:
    # - if CSV does not exist (or is empty), create it and write header
    # - otherwise append rows only and skip points already present in CSV
    if (not output_csv.exists()) or output_csv.stat().st_size == 0:
        with output_csv.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
    completed_points = load_completed_points(output_csv)

    for horizon in horizons:
        for admm_iters in admm_iters_values:
            key = (horizon, admm_iters, args.board)
            if key in completed_points:
                print(f"\n=== Horizon {horizon}, ADMM iters {admm_iters} ===")
                print("Skipping (already present in output CSV).")
                continue

            print(f"\n=== Horizon {horizon}, ADMM iters {admm_iters} ===")
            try:
                run_generation(repo_root, horizon=horizon, admm_iters=admm_iters)

                # Rebuild from HLS export onward to ensure horizon-dependent IP/RTL is fresh.
                run_cmd(["make", f"BOARD={args.board}", "vivado"], cwd=repo_root)

                util = parse_utilization(read_text(reports_dir / "post_route_utilization.rpt"))
                hls_report_text = read_text(hls_timing_report)
                hls_timing = parse_hls_timing(hls_report_text)
                hls_latency_cycles = parse_hls_latency_cycles(hls_report_text)
                synth_timing_raw = parse_vivado_timing(read_text(reports_dir / "post_synth_timing.rpt"))
                route_timing_raw = parse_vivado_timing(read_text(reports_dir / "post_route_timing.rpt"))
                power_raw = parse_power(read_text(reports_dir / "post_route_power.rpt"))

                synth_timing = {
                    "synth_wns_ns": synth_timing_raw["wns_ns"],
                    "synth_tns_ns": synth_timing_raw["tns_ns"],
                    "synth_clk_period_ns": synth_timing_raw["clk_period_ns"],
                    "synth_clk_freq_mhz": synth_timing_raw["clk_freq_mhz"],
                    "synth_fmax_est_mhz": synth_timing_raw["fmax_est_mhz"],
                }
                route_timing = {
                    "route_wns_ns": route_timing_raw["wns_ns"],
                    "route_tns_ns": route_timing_raw["tns_ns"],
                    "route_clk_period_ns": route_timing_raw["clk_period_ns"],
                    "route_clk_freq_mhz": route_timing_raw["clk_freq_mhz"],
                    "route_fmax_est_mhz": route_timing_raw["fmax_est_mhz"],
                }
                power = {
                    "route_power_total_w": power_raw["power_total_w"],
                    "route_power_dynamic_w": power_raw["power_dynamic_w"],
                    "route_power_static_w": power_raw["power_static_w"],
                }
                est_solve_us_cfg_clk = safe_div(float(hls_latency_cycles), float(route_timing["route_clk_freq_mhz"]))
                est_solve_us_route_fmax = safe_div(float(hls_latency_cycles), float(route_timing["route_fmax_est_mhz"]))
                throughput_cfg_sps = safe_div(1_000_000.0, est_solve_us_cfg_clk)
                throughput_route_fmax_sps = safe_div(1_000_000.0, est_solve_us_route_fmax)
                energy_per_solve_cfg_uj = float(power["route_power_total_w"]) * est_solve_us_cfg_clk
                energy_per_solve_route_fmax_uj = float(power["route_power_total_w"]) * est_solve_us_route_fmax
                perf = {
                    "hls_latency_cycles": hls_latency_cycles,
                    "est_solve_us_cfg_clk": est_solve_us_cfg_clk,
                    "est_solve_us_route_fmax": est_solve_us_route_fmax,
                    "throughput_cfg_sps": throughput_cfg_sps,
                    "throughput_route_fmax_sps": throughput_route_fmax_sps,
                    "throughput_per_lut_cfg": safe_div(throughput_cfg_sps, float(util["slice_luts_used"])),
                    "throughput_per_dsp_cfg": safe_div(throughput_cfg_sps, float(util["dsps_used"])),
                    "throughput_per_bram_cfg": safe_div(throughput_cfg_sps, float(util["bram_tile_used"])),
                    "throughput_per_lutram_cfg": safe_div(throughput_cfg_sps, float(util["lut_as_mem_used"])),
                    "energy_per_solve_cfg_uj": energy_per_solve_cfg_uj,
                    "energy_per_solve_route_fmax_uj": energy_per_solve_route_fmax_uj,
                    "energy_per_iter_cfg_nj": safe_div(energy_per_solve_cfg_uj * 1000.0, float(admm_iters)),
                }

                row: dict[str, int | float | str] = {
                    "horizon": horizon,
                    "admm_iters": admm_iters,
                    "board": args.board,
                    **util,
                    **hls_timing,
                    **synth_timing,
                    **route_timing,
                    **power,
                    **perf,
                }

                with output_csv.open("a", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writerow(row)
                completed_points.add(key)

                archive_reports(
                    reports_dir=reports_dir,
                    archive_root=archive_dir,
                    horizon=horizon,
                    admm_iters=admm_iters,
                )
                archive_hls_report(
                    hls_report=hls_timing_report,
                    archive_root=archive_dir,
                    horizon=horizon,
                    admm_iters=admm_iters,
                )

                print(
                    "Saved: "
                    f"H={horizon} k={admm_iters} "
                    f"LUT={row['slice_luts_used']} "
                    f"DSP={row['dsps_used']} "
                    f"BRAM={row['bram_tile_used']} "
                    f"LUTRAM={row['lut_as_mem_used']} "
                    f"HLSclk={row['hls_est_clk_ns']}ns "
                    f"lat={row['hls_latency_cycles']} cyc "
                    f"synthWNS={row['synth_wns_ns']}ns "
                    f"routeWNS={row['route_wns_ns']}ns "
                    f"Pdyn={row['route_power_dynamic_w']}W "
                    f"Pstat={row['route_power_static_w']}W "
                    f"thr/LUT={row['throughput_per_lut_cfg']:.3e}"
                )
            except Exception as exc:
                print(f"ERROR at H={horizon}, k={admm_iters}: {exc}")
                if not args.continue_on_error:
                    raise

    print(f"\nSaved sweep CSV: {output_csv}")
    print(f"Saved per-horizon reports under: {archive_dir}")


if __name__ == "__main__":
    main()
