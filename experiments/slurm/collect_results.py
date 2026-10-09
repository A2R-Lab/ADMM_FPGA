#!/usr/bin/env python3
"""Collect Tier 1 raw Slurm results into a compact CSV summary."""

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


def parse_early_stop(text: str) -> tuple[str, str]:
    m = re.search(r"EARLY_STOP\s+step=([^\s]+)\s+reason=([^\s]+)", text)
    if not m:
        return "", ""
    return m.group(1), m.group(2)


def parse_int_cell(cell: str) -> str:
    m = re.search(r"(-?\d+)", cell.replace(",", ""))
    return m.group(1) if m else ""


def parse_float_cell(cell: str) -> str:
    m = re.search(r"[-+]?\d+(?:\.\d+)?(?:e[-+]?\d+)?", cell.replace(",", ""), re.IGNORECASE)
    return m.group(0) if m else ""


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


def parse_define(path: Path, name: str) -> str:
    m = re.search(rf"^\s*#define\s+{re.escape(name)}\s+([^\s]+)", read_text(path), re.MULTILINE)
    return m.group(1) if m else ""


def parse_solver_arch(path: Path) -> str:
    if parse_define(path, "ADMM_SOLVER_ARCH_STAGED_A") == "1":
        return "staged_a"
    if parse_define(path, "ADMM_SOLVER_ARCH_FULL_SPARSE") == "1":
        return "full_sparse"
    return str(parse_define(path, "ADMM_SOLVER_ARCH_NAME")).strip('"')


def load_json(path: Path) -> dict[str, object]:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def collect(results_root: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    raw_root = results_root / "raw"
    for run_dir in sorted(raw_root.glob("*")):
        if not run_dir.is_dir():
            continue
        meta = load_json(run_dir / "metadata_final.json") or load_json(run_dir / "metadata_initial.json")
        logs = run_dir / "logs"
        csim_text = read_text(logs / "closed_loop_csim.stdout.log") + "\n" + read_text(logs / "closed_loop_csim.stderr.log")
        early_step, early_reason = parse_early_stop(csim_text)
        status = read_text(run_dir / "status.txt").strip()
        exit_code = str(meta.get("exit_code", ""))
        failed_step = str(meta.get("failed_step", ""))
        if status == "started" and not failed_step:
            status = "running_or_incomplete"
            exit_code = ""
        row = {
            "run_id": run_dir.name,
            "config_id": str(meta.get("admm_config_id", "")),
            "commit": str(meta.get("resolved_commit", "")),
            "commit_short": str(meta.get("commit_short", "")),
            "horizon": str(meta.get("admm_horizon", "")),
            "solver_arch": parse_solver_arch(run_dir / "generated" / "admm_runtime_config.h")
                or str(meta.get("admm_solver_arch", "")),
            "trajectory": str(meta.get("admm_traj_shape", "")),
            "admm_iterations_override": str(meta.get("admm_iterations_override", "")),
            "admm_iterations_actual": parse_define(run_dir / "generated" / "admm_runtime_config.h", "ADMM_ITERATIONS"),
            "exit_code": exit_code,
            "failed_step": failed_step,
            "status": status,
            "csim_rc": read_rc(logs / "closed_loop_csim.rc"),
            "csim_early_stop_step": early_step,
            "csim_early_stop_reason": early_reason,
            "hls_synth_rc": read_rc(logs / "hls_synth.rc"),
        }
        row.update(parse_csynth(run_dir / "reports" / "hls_synth" / "csynth.rpt"))
        rows.append(row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results_root", type=Path, help="Tier results root containing raw/")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output CSV path. Default: <results_root>/summary/tier1_summary.csv",
    )
    args = parser.parse_args()

    rows = collect(args.results_root)
    out = args.output or (args.results_root / "summary" / "tier1_summary.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "run_id",
        "config_id",
        "commit",
        "commit_short",
        "horizon",
        "solver_arch",
        "trajectory",
        "admm_iterations_override",
        "admm_iterations_actual",
        "exit_code",
        "failed_step",
        "status",
        "csim_rc",
        "csim_early_stop_step",
        "csim_early_stop_reason",
        "hls_synth_rc",
        "solver_input_width",
        "hls_latency_cycles",
        "hls_latency_ns",
        "hls_slack",
        "hls_bram",
        "hls_dsp",
        "hls_ff",
        "hls_lut",
        "hls_uram",
    ]
    with out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
