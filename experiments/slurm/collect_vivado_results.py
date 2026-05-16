#!/usr/bin/env python3
"""Collect finalist Vivado raw results into a compact CSV summary."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path


def read_text(path: Path) -> str:
    try:
        return path.read_text(errors="replace")
    except FileNotFoundError:
        return ""


def read_rc(path: Path) -> str:
    text = read_text(path).strip()
    return text if text else ""


def load_json(path: Path) -> dict[str, object]:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def parse_int_cell(cell: str) -> str:
    m = re.search(r"(-?\d+)", cell.replace(",", ""))
    return m.group(1) if m else ""


def parse_float_cell(cell: str) -> str:
    m = re.search(r"[-+]?\d+(?:\.\d+)?(?:e[-+]?\d+)?", cell.replace(",", ""), re.IGNORECASE)
    return m.group(0) if m else ""


def parse_define(path: Path, name: str) -> str:
    m = re.search(rf"^\s*#define\s+{re.escape(name)}\s+([^\s]+)", read_text(path), re.MULTILINE)
    return m.group(1) if m else ""


def parse_solver_arch(path: Path) -> str:
    if parse_define(path, "ADMM_SOLVER_ARCH_STAGED_A") == "1":
        return "staged_a"
    if parse_define(path, "ADMM_SOLVER_ARCH_FULL_SPARSE") == "1":
        return "full_sparse"
    return str(parse_define(path, "ADMM_SOLVER_ARCH_NAME")).strip('"')


def parse_csynth(report: Path) -> dict[str, str]:
    text = read_text(report)
    out: dict[str, str] = {
        "hls_latency_cycles": "",
        "hls_latency_ns": "",
        "hls_slack": "",
        "hls_bram": "",
        "hls_dsp": "",
        "hls_ff": "",
        "hls_lut": "",
        "hls_uram": "",
        "solver_input_width": "",
    }
    for line in text.splitlines():
        if line.startswith("|+ ADMM_solver"):
            fields = [part.strip() for part in line.split("|")[1:-1]]
            if len(fields) >= 15:
                out["hls_latency_cycles"] = parse_int_cell(fields[7])
                out["hls_latency_ns"] = parse_float_cell(fields[8])
                out["hls_slack"] = parse_float_cell(fields[9])
                out["hls_bram"] = parse_int_cell(fields[10])
                out["hls_dsp"] = parse_int_cell(fields[11])
                out["hls_ff"] = parse_int_cell(fields[12])
                out["hls_lut"] = parse_int_cell(fields[13])
                out["hls_uram"] = parse_int_cell(fields[14])
            break
    m = re.search(r"\|\s*current_in_bits\s*\|\s*ap_none\s*\|\s*in\s*\|\s*(\d+)\s*\|", text)
    if m:
        out["solver_input_width"] = m.group(1)
    else:
        m = re.search(r"current_in_bits\s*\|\s*in\s*\|\s*ap_uint<(\d+)>", text)
        if m:
            out["solver_input_width"] = m.group(1)
    return out


def parse_vivado_util(report: Path, prefix: str) -> dict[str, str]:
    out = {
        f"{prefix}_lut": "",
        f"{prefix}_lutram": "",
        f"{prefix}_ff": "",
        f"{prefix}_bram_tile": "",
        f"{prefix}_dsp": "",
    }
    patterns = {
        f"{prefix}_lut": r"^\|\s*Slice LUTs\*?\s*\|\s*([^|]+)\|",
        f"{prefix}_lutram": r"^\|\s*LUT as Memory\s*\|\s*([^|]+)\|",
        f"{prefix}_ff": r"^\|\s*Slice Registers\s*\|\s*([^|]+)\|",
        f"{prefix}_bram_tile": r"^\|\s*Block RAM Tile\s*\|\s*([^|]+)\|",
        f"{prefix}_dsp": r"^\|\s*DSPs\s*\|\s*([^|]+)\|",
    }
    for line in read_text(report).splitlines():
        for key, pattern in patterns.items():
            if out[key]:
                continue
            m = re.search(pattern, line)
            if m:
                out[key] = parse_float_cell(m.group(1))
    return out


def parse_vivado_timing(report: Path, prefix: str) -> dict[str, str]:
    out = {
        f"{prefix}_wns": "",
        f"{prefix}_tns": "",
        f"{prefix}_failing_endpoints": "",
        f"{prefix}_whs": "",
        f"{prefix}_ths": "",
    }
    lines = read_text(report).splitlines()
    for i, line in enumerate(lines):
        if "WNS(ns)" not in line or "TNS(ns)" not in line:
            continue
        for candidate in lines[i + 1 : i + 8]:
            if "|" in candidate:
                fields = [part.strip() for part in candidate.split("|")[1:-1]]
                nums = [parse_float_cell(field) for field in fields]
                nums = [num for num in nums if num != ""]
            else:
                nums = re.findall(r"[-+]?\d+(?:\.\d+)?(?:e[-+]?\d+)?", candidate, re.IGNORECASE)
            if len(nums) >= 5:
                out[f"{prefix}_wns"] = nums[0]
                out[f"{prefix}_tns"] = nums[1]
                out[f"{prefix}_failing_endpoints"] = nums[2]
                out[f"{prefix}_whs"] = nums[4]
                if len(nums) >= 6:
                    out[f"{prefix}_ths"] = nums[5]
                return out
    return out


def parse_vivado_power(report: Path, prefix: str) -> dict[str, str]:
    out = {
        f"{prefix}_total_power_w": "",
        f"{prefix}_dynamic_power_w": "",
        f"{prefix}_static_power_w": "",
    }
    text = read_text(report)
    patterns = {
        f"{prefix}_total_power_w": r"Total On-Chip Power \(W\)\s*\|\s*([^|]+)\|",
        f"{prefix}_dynamic_power_w": r"Dynamic \(W\)\s*\|\s*([^|]+)\|",
        f"{prefix}_static_power_w": r"Device Static \(W\)\s*\|\s*([^|]+)\|",
    }
    for key, pattern in patterns.items():
        m = re.search(pattern, text)
        if m:
            out[key] = parse_float_cell(m.group(1))
    return out


def collect(results_root: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    raw_root = results_root / "raw"
    for run_dir in sorted(raw_root.glob("*")):
        if not run_dir.is_dir():
            continue
        meta = load_json(run_dir / "metadata_final.json") or load_json(run_dir / "metadata_after_generation.json") or load_json(run_dir / "metadata_initial.json")
        logs = run_dir / "logs"
        status = read_text(run_dir / "status.txt").strip()
        exit_code = str(meta.get("exit_code", ""))
        failed_step = str(meta.get("failed_step", ""))
        if status == "started" and not failed_step:
            status = "running_or_incomplete"
            exit_code = ""

        row = {
            "run_id": run_dir.name,
            "config_id": str(meta.get("admm_config_id", "")),
            "comparison_view": str(meta.get("admm_comparison_view", "")),
            "commit": str(meta.get("resolved_commit", "")),
            "commit_short": str(meta.get("commit_short", "")),
            "board": str(meta.get("admm_board", "")),
            "horizon": str(meta.get("admm_horizon", "")),
            "solver_arch": parse_solver_arch(run_dir / "generated" / "admm_runtime_config.h")
                or str(meta.get("admm_solver_arch", "")),
            "trajectory": str(meta.get("admm_traj_shape", "")),
            "admm_iterations_override": str(meta.get("admm_iterations_override", "")),
            "admm_iterations_actual": parse_define(run_dir / "generated" / "admm_runtime_config.h", "ADMM_ITERATIONS"),
            "traj_refs_sha256": str(meta.get("trajectory_refs_csv_sha256", "")),
            "traj_data_sha256": str(meta.get("traj_data_h_sha256", "")),
            "traj_q_packed_rows": str(meta.get("traj_q_packed_rows", "")),
            "traj_q_packed_cols": str(meta.get("traj_q_packed_cols", "")),
            "exit_code": exit_code,
            "failed_step": failed_step,
            "status": status,
            "vivado_rc": read_rc(logs / "vivado.rc"),
            "bitstream_rc": read_rc(logs / "bitstream.rc"),
        }
        row.update(parse_csynth(run_dir / "reports" / "hls_synth" / "csynth.rpt"))
        vivado_reports = run_dir / "reports" / "vivado"
        row.update(parse_vivado_util(vivado_reports / "post_synth_utilization.rpt", "post_synth"))
        row.update(parse_vivado_timing(vivado_reports / "post_synth_timing.rpt", "post_synth"))
        row.update(parse_vivado_power(vivado_reports / "post_synth_power.rpt", "post_synth"))
        row.update(parse_vivado_util(vivado_reports / "post_place_utilization.rpt", "post_place"))
        row.update(parse_vivado_timing(vivado_reports / "post_place_timing.rpt", "post_place"))
        row.update(parse_vivado_util(vivado_reports / "post_route_utilization.rpt", "post_route"))
        row.update(parse_vivado_timing(vivado_reports / "post_route_timing.rpt", "post_route"))
        row.update(parse_vivado_power(vivado_reports / "post_route_power.rpt", "post_route"))
        rows.append(row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results_root", type=Path, help="Vivado results root containing raw/")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output CSV path. Default: <results_root>/summary/vivado_summary.csv",
    )
    args = parser.parse_args()

    rows = collect(args.results_root)
    out = args.output or (args.results_root / "summary" / "vivado_summary.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "run_id",
        "config_id",
        "comparison_view",
        "commit",
        "commit_short",
        "board",
        "horizon",
        "solver_arch",
        "trajectory",
        "admm_iterations_override",
        "admm_iterations_actual",
        "traj_refs_sha256",
        "traj_data_sha256",
        "traj_q_packed_rows",
        "traj_q_packed_cols",
        "exit_code",
        "failed_step",
        "status",
        "vivado_rc",
        "bitstream_rc",
        "solver_input_width",
        "hls_latency_cycles",
        "hls_latency_ns",
        "hls_slack",
        "hls_bram",
        "hls_dsp",
        "hls_ff",
        "hls_lut",
        "hls_uram",
        "post_synth_lut",
        "post_synth_lutram",
        "post_synth_ff",
        "post_synth_bram_tile",
        "post_synth_dsp",
        "post_synth_wns",
        "post_synth_tns",
        "post_synth_failing_endpoints",
        "post_synth_whs",
        "post_synth_ths",
        "post_synth_total_power_w",
        "post_synth_dynamic_power_w",
        "post_synth_static_power_w",
        "post_place_lut",
        "post_place_lutram",
        "post_place_ff",
        "post_place_bram_tile",
        "post_place_dsp",
        "post_place_wns",
        "post_place_tns",
        "post_place_failing_endpoints",
        "post_place_whs",
        "post_place_ths",
        "post_route_lut",
        "post_route_lutram",
        "post_route_ff",
        "post_route_bram_tile",
        "post_route_dsp",
        "post_route_wns",
        "post_route_tns",
        "post_route_failing_endpoints",
        "post_route_whs",
        "post_route_ths",
        "post_route_total_power_w",
        "post_route_dynamic_power_w",
        "post_route_static_power_w",
    ]
    with out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
