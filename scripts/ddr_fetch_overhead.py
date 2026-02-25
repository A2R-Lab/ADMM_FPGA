#!/usr/bin/env python3
"""Estimate DDR fetch overhead for ADMM matrix offload."""

from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass


DEFINE_RE = re.compile(r"^\s*#define\s+(\w+)\s+([^\s/]+)")


def parse_defines(path: str) -> dict[str, str]:
    defines: dict[str, str] = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            m = DEFINE_RE.match(line)
            if m:
                defines[m.group(1)] = m.group(2)
    return defines


def resolve_path(path: str, script_dir: str) -> str:
    if os.path.isabs(path):
        return path
    return os.path.abspath(os.path.join(script_dir, path))


@dataclass
class Scenario:
    name: str
    bandwidth_mb_s: float
    overlap: float


def pretty_bytes(num_bytes: float) -> str:
    return f"{num_bytes / (1024.0 * 1024.0):.2f} MiB"


def estimate_overhead_ms(bytes_solve: float, bandwidth_mb_s: float, overlap: float) -> float:
    raw_seconds = bytes_solve / (bandwidth_mb_s * 1e6)
    visible_seconds = raw_seconds * (1.0 - overlap)
    return visible_seconds * 1000.0


def main() -> None:
    parser = argparse.ArgumentParser(description="Estimate DDR read traffic and latency overhead.")
    parser.add_argument(
        "--solver-constants",
        default="../vitis_projects/ADMM/solver_constants.h",
        help="Path to solver_constants.h",
    )
    parser.add_argument(
        "--matrix-layout",
        default="../vitis_projects/ADMM/matrix_layout.h",
        help="Path to matrix_layout.h",
    )
    parser.add_argument(
        "--baseline-ms",
        type=float,
        default=9.057,
        help="On-chip baseline solve latency in milliseconds.",
    )
    parser.add_argument(
        "--data-header",
        default="../vitis_projects/ADMM/data.h",
        help="Path to legacy data.h (used as fallback if solver/layout headers are missing).",
    )
    parser.add_argument(
        "--index-bits",
        type=int,
        choices=[16, 32],
        default=None,
        help="Override sparse index storage width for what-if analysis.",
    )
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    constants_path = resolve_path(args.solver_constants, script_dir)
    layout_path = resolve_path(args.matrix_layout, script_dir)
    data_path = resolve_path(args.data_header, script_dir)

    used_fallback = False
    if os.path.exists(constants_path) and os.path.exists(layout_path):
        c_defs = parse_defines(constants_path)
        l_defs = parse_defines(layout_path)

        n_var = int(c_defs["N_VAR"])
        admm_iters = int(c_defs["ADMM_ITERS"])
        l_cols = int(l_defs["MATRIX_L_BANDED_COLS"])
        lt_cols = int(l_defs["MATRIX_LT_BANDED_COLS"])
        a_cols = int(l_defs["MATRIX_A_SPARSE_DATA_COLS"])
        at_cols = int(l_defs["MATRIX_AT_SPARSE_DATA_COLS"])
        index_bits = int(l_defs["MATRIX_BLOB_INDEX_BITS"]) if args.index_bits is None else args.index_bits
    else:
        used_fallback = True
        d_defs = parse_defines(data_path)

        n_var = int(d_defs["N_VAR"])
        admm_iters = int(d_defs["ADMM_ITERS"])
        l_cols = int(d_defs["L_BANDED_COLS"])
        lt_cols = int(d_defs["LT_BANDED_COLS"])
        a_cols = int(d_defs["A_SPARSE_DATA_COLS"])
        at_cols = int(d_defs["AT_SPARSE_DATA_COLS"])

        # data.h cannot infer packed DDR index storage width directly.
        index_bits = 32 if args.index_bits is None else args.index_bits

    matrix_data_bytes_per_iter = n_var * (l_cols + lt_cols + a_cols + at_cols) * 4
    index_bytes_per_iter = n_var * (a_cols + at_cols) * (index_bits // 8)
    total_bytes_per_iter = matrix_data_bytes_per_iter + index_bytes_per_iter
    total_bytes_per_solve = total_bytes_per_iter * admm_iters

    scenarios = [
        Scenario("Conservative boost", 600.0, 0.40),
        Scenario("Mid boost", 800.0, 0.50),
        Scenario("Aggressive boost", 900.0, 0.60),
    ]

    print("DDR Fetch Overhead Estimate")
    print("===========================")
    if used_fallback:
        print(f"fallback data.h  : {data_path}")
    else:
        print(f"solver constants : {constants_path}")
        print(f"matrix layout    : {layout_path}")
    print(f"N_VAR            : {n_var}")
    print(f"ADMM_ITERS       : {admm_iters}")
    print(f"Index bits       : {index_bits}")
    print()

    print("Per-iteration traffic:")
    print(f"  Matrix data bytes : {matrix_data_bytes_per_iter:,} ({pretty_bytes(matrix_data_bytes_per_iter)})")
    print(f"  Index data bytes  : {index_bytes_per_iter:,} ({pretty_bytes(index_bytes_per_iter)})")
    print(f"  Total bytes/iter  : {total_bytes_per_iter:,} ({pretty_bytes(total_bytes_per_iter)})")
    print()

    print("Per-solve traffic:")
    print(f"  Total bytes/solve : {total_bytes_per_solve:,} ({pretty_bytes(total_bytes_per_solve)})")
    print()

    print("Latency estimate:")
    print("  T_overhead = (Bytes_solve / B_eff) * (1 - overlap)")
    print()
    print("  Scenario              Overhead(ms)  Total(ms)")
    print("  ---------------------------------------------")
    for sc in scenarios:
        overhead_ms = estimate_overhead_ms(total_bytes_per_solve, sc.bandwidth_mb_s, sc.overlap)
        total_ms = args.baseline_ms + overhead_ms
        print(f"  {sc.name:<20} {overhead_ms:10.3f}  {total_ms:8.3f}")


if __name__ == "__main__":
    main()
