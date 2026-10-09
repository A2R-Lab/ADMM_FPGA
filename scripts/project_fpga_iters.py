#!/usr/bin/env python3
"""
Generate synthetic FPGA BENCH_CSV rows for multiple iteration counts by
linearly scaling timing from a measured baseline iteration count.
"""

from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from pathlib import Path


CSV_RE = re.compile(r"^(?P<prefix>.*?BENCH_CSV,)(?P<body>[^\n\r]+)\s*$")


@dataclass
class BenchRow:
    prefix: str
    H: int
    it: int
    min_us: float
    avg_us: float
    max_us: float
    misses: int
    total: int
    solved: int
    max_iter: int
    noncvx: int
    other: int


def parse_row(line: str) -> BenchRow | None:
    m = CSV_RE.match(line)
    if not m:
        return None

    row = next(csv.reader([m.group("body")]))
    if len(row) != 11:
        return None

    return BenchRow(
        prefix=m.group("prefix"),
        H=int(row[0]),
        it=int(row[1]),
        min_us=float(row[2]),
        avg_us=float(row[3]),
        max_us=float(row[4]),
        misses=int(row[5]),
        total=int(row[6]),
        solved=int(row[7]),
        max_iter=int(row[8]),
        noncvx=int(row[9]),
        other=int(row[10]),
    )


def render_row(r: BenchRow) -> str:
    return (
        f"{r.prefix}{r.H},{r.it},{r.min_us:.3f},{r.avg_us:.3f},{r.max_us:.3f},"
        f"{r.misses},{r.total},{r.solved},{r.max_iter},{r.noncvx},{r.other}"
    )


def parse_iters(text: str) -> list[int]:
    vals = [int(tok.strip()) for tok in text.split(",") if tok.strip()]
    if not vals:
        raise ValueError("No target iterations parsed from --target-iters")
    if any(v <= 0 for v in vals):
        raise ValueError("All target iterations must be > 0")
    return sorted(set(vals))


def main() -> None:
    parser = argparse.ArgumentParser(description="Expand FPGA BENCH_CSV rows to multiple iteration points.")
    parser.add_argument("input_log", type=Path, help="Input log containing BENCH_CSV rows.")
    parser.add_argument("output_log", type=Path, help="Output log with synthetic BENCH_CSV rows.")
    parser.add_argument(
        "--base-iter",
        type=int,
        default=10,
        help="Measured baseline iteration count in input rows.",
    )
    parser.add_argument(
        "--target-iters",
        default="1,2,5,10,15,20,25,30",
        help="Comma-separated target iteration values to synthesize.",
    )
    parser.add_argument(
        "--budget-us",
        type=float,
        default=2000.0,
        help="Timing budget used to recompute misses/solved for synthetic rows.",
    )
    args = parser.parse_args()

    if args.base_iter <= 0:
        raise ValueError("--base-iter must be > 0")

    target_iters = parse_iters(args.target_iters)
    lines = args.input_log.read_text().splitlines()

    base_rows: list[BenchRow] = []
    passthrough: list[str] = []
    for line in lines:
        parsed = parse_row(line)
        if parsed is None:
            passthrough.append(line)
            continue
        if parsed.it == args.base_iter:
            base_rows.append(parsed)

    if not base_rows:
        raise ValueError(
            f"No BENCH_CSV rows found with iter={args.base_iter} in {args.input_log}"
        )

    synth_rows: list[BenchRow] = []
    for r in base_rows:
        for it in target_iters:
            scale = it / args.base_iter
            synth_min = r.min_us * scale
            synth_avg = r.avg_us * scale
            synth_max = r.max_us * scale
            # Assume deterministic timing for FPGA rows: if avg exceeds budget,
            # all samples miss; otherwise none miss.
            total = r.total
            misses = total if synth_avg > args.budget_us else 0
            solved = total - misses
            synth_rows.append(
                BenchRow(
                    prefix=r.prefix,
                    H=r.H,
                    it=it,
                    min_us=synth_min,
                    avg_us=synth_avg,
                    max_us=synth_max,
                    misses=misses,
                    total=total,
                    solved=solved,
                    max_iter=r.max_iter,
                    noncvx=r.noncvx,
                    other=r.other,
                )
            )

    synth_rows.sort(key=lambda x: (x.H, x.it))

    out_lines = passthrough + [render_row(r) for r in synth_rows]
    args.output_log.write_text("\n".join(out_lines) + "\n")
    print(f"Wrote {len(synth_rows)} synthetic BENCH_CSV rows to {args.output_log}")


if __name__ == "__main__":
    main()
