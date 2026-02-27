#!/usr/bin/env python3
"""
Compare BENCH_CSV timing logs from three sources:
- TinyMPC
- FPGA floating point
- FPGA fixed point
"""

from __future__ import annotations

import argparse
import csv
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import matplotlib.pyplot as plt
import numpy as np


CSV_RE = re.compile(r"BENCH_CSV,([^\n\r]+)")

TINYMPC = "tinympc"
FPGA_FLOAT = "fpga_float"
FPGA_FIXED = "fpga_fixed"
SOURCES = [TINYMPC, FPGA_FLOAT, FPGA_FIXED]
SOURCE_LABEL = {
    TINYMPC: "TinyMPC",
    FPGA_FLOAT: "FPGA Floating Point",
    FPGA_FIXED: "FPGA Fixed Point",
}
SOURCE_COLOR = {
    TINYMPC: "#1f77b4",
    FPGA_FLOAT: "#ff7f0e",
    FPGA_FIXED: "#2ca02c",
}


@dataclass
class BenchPoint:
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

    @property
    def miss_rate(self) -> float:
        return (self.misses / self.total) if self.total > 0 else math.nan

    @property
    def norm_us_per_iter_step(self) -> float:
        return self.avg_us / (self.it * self.H)


def parse_log(path: Path) -> List[BenchPoint]:
    text = path.read_text()
    points: List[BenchPoint] = []
    for m in CSV_RE.finditer(text):
        row = next(csv.reader([m.group(1)]))
        if len(row) != 11:
            continue
        points.append(
            BenchPoint(
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
        )
    points.sort(key=lambda p: (p.H, p.it))
    return points


def grouped(points: List[BenchPoint]) -> Dict[int, List[BenchPoint]]:
    out: Dict[int, List[BenchPoint]] = {}
    for p in points:
        out.setdefault(p.H, []).append(p)
    for H in out:
        out[H].sort(key=lambda p: p.it)
    return out


def save(fig: plt.Figure, outdir: Path, name: str) -> None:
    fig.tight_layout()
    fig.savefig(outdir / name, dpi=180)
    plt.close(fig)


def prepare_axes(n: int) -> Tuple[plt.Figure, np.ndarray]:
    ncols = 3
    nrows = int(math.ceil(n / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(5.3 * ncols, 3.8 * nrows), squeeze=False)
    return fig, axes


def plot_avg_vs_iter_per_h(
    data_by_source: Dict[str, Dict[int, List[BenchPoint]]],
    horizons: List[int],
    outdir: Path,
) -> None:
    fig, axes = prepare_axes(len(horizons))
    for idx, H in enumerate(horizons):
        ax = axes[idx // 3, idx % 3]
        for src in SOURCES:
            pts = data_by_source[src].get(H, [])
            if not pts:
                continue
            xs = np.array([p.it for p in pts], dtype=float)
            ys = np.array([p.avg_us for p in pts], dtype=float)
            ax.plot(xs, ys, marker="o", linewidth=2, color=SOURCE_COLOR[src], label=SOURCE_LABEL[src])
        ax.set_title(f"H={H}")
        ax.set_xlabel("Iterations")
        ax.set_ylabel("avg_us")
        ax.grid(True, alpha=0.3)
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            ax.legend(fontsize=8)

    # Hide unused axes if horizon count is not multiple of 3.
    for idx in range(len(horizons), axes.size):
        axes[idx // 3, idx % 3].axis("off")
    save(fig, outdir, "01_compare_avg_vs_iter_per_h.png")


def plot_norm_vs_iter_per_h(
    data_by_source: Dict[str, Dict[int, List[BenchPoint]]],
    horizons: List[int],
    outdir: Path,
) -> None:
    fig, axes = prepare_axes(len(horizons))
    for idx, H in enumerate(horizons):
        ax = axes[idx // 3, idx % 3]
        for src in SOURCES:
            pts = data_by_source[src].get(H, [])
            if not pts:
                continue
            xs = np.array([p.it for p in pts], dtype=float)
            ys = np.array([p.norm_us_per_iter_step for p in pts], dtype=float)
            ax.plot(xs, ys, marker="o", linewidth=2, color=SOURCE_COLOR[src], label=SOURCE_LABEL[src])
        ax.set_title(f"H={H}")
        ax.set_xlabel("Iterations")
        ax.set_ylabel("avg_us / (iter*H)")
        ax.grid(True, alpha=0.3)
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            ax.legend(fontsize=8)

    for idx in range(len(horizons), axes.size):
        axes[idx // 3, idx % 3].axis("off")
    save(fig, outdir, "02_compare_norm_vs_iter_per_h.png")


def to_lookup(points_by_h: Dict[int, List[BenchPoint]]) -> Dict[Tuple[int, int], BenchPoint]:
    table: Dict[Tuple[int, int], BenchPoint] = {}
    for H, pts in points_by_h.items():
        for p in pts:
            table[(H, p.it)] = p
    return table


def plot_speedup_vs_tinympc_per_h(
    data_by_source: Dict[str, Dict[int, List[BenchPoint]]],
    horizons: List[int],
    outdir: Path,
) -> None:
    ref = to_lookup(data_by_source[TINYMPC])
    flt = to_lookup(data_by_source[FPGA_FLOAT])
    fix = to_lookup(data_by_source[FPGA_FIXED])

    fig, axes = prepare_axes(len(horizons))
    for idx, H in enumerate(horizons):
        ax = axes[idx // 3, idx % 3]
        xs_flt: List[int] = []
        ys_flt: List[float] = []
        xs_fix: List[int] = []
        ys_fix: List[float] = []

        for it in sorted({it for (h, it) in ref.keys() if h == H}):
            key = (H, it)
            if key in ref and key in flt and flt[key].avg_us > 0:
                xs_flt.append(it)
                ys_flt.append(ref[key].avg_us / flt[key].avg_us)
            if key in ref and key in fix and fix[key].avg_us > 0:
                xs_fix.append(it)
                ys_fix.append(ref[key].avg_us / fix[key].avg_us)

        if xs_flt:
            ax.plot(xs_flt, ys_flt, marker="o", linewidth=2, color=SOURCE_COLOR[FPGA_FLOAT], label="TinyMPC / FPGA Float")
        if xs_fix:
            ax.plot(xs_fix, ys_fix, marker="o", linewidth=2, color=SOURCE_COLOR[FPGA_FIXED], label="TinyMPC / FPGA Fixed")

        ax.axhline(1.0, color="black", linestyle="--", linewidth=1)
        ax.set_title(f"H={H}")
        ax.set_xlabel("Iterations")
        ax.set_ylabel("Speedup vs TinyMPC")
        ax.grid(True, alpha=0.3)
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            ax.legend(fontsize=8)

    for idx in range(len(horizons), axes.size):
        axes[idx // 3, idx % 3].axis("off")
    save(fig, outdir, "03_speedup_vs_tinympc_per_h.png")


def plot_k_step_iter_vs_h(
    data_by_source: Dict[str, Dict[int, List[BenchPoint]]],
    horizons: List[int],
    outdir: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(9, 6))
    for src in SOURCES:
        xs: List[int] = []
        ys: List[float] = []
        for H in horizons:
            pts = data_by_source[src].get(H, [])
            if not pts:
                continue
            vals = [p.norm_us_per_iter_step for p in pts if p.it > 0 and p.H > 0]
            if not vals:
                continue
            # Robust single value per horizon from BENCH_CSV rows.
            ys.append(float(np.median(vals)))
            xs.append(H)
        if xs:
            ax.plot(xs, ys, marker="o", linewidth=2, color=SOURCE_COLOR[src], label=SOURCE_LABEL[src])

    ax.set_title("k_step_iter vs Horizon (from BENCH_CSV)")
    ax.set_xlabel("H")
    ax.set_ylabel("us/(iter*step)")
    ax.grid(True, alpha=0.3)
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        ax.legend()
    save(fig, outdir, "04_k_step_iter_vs_h.png")


def write_summary(
    points_by_source: Dict[str, List[BenchPoint]],
    data_by_source: Dict[str, Dict[int, List[BenchPoint]]],
    outdir: Path,
) -> None:
    lines: List[str] = []
    lines.append("Comparison Summary")
    lines.append("")
    for src in SOURCES:
        pts = points_by_source[src]
        hs = sorted({p.H for p in pts})
        iters = sorted({p.it for p in pts})
        lines.append(f"{SOURCE_LABEL[src]}: points={len(pts)}, horizons={hs}, iters={iters}")

    lines.append("")
    lines.append("Median normalized time avg_us/(iter*H):")
    for src in SOURCES:
        vals = [p.norm_us_per_iter_step for p in points_by_source[src]]
        med = float(np.median(vals)) if vals else float("nan")
        lines.append(f"  {SOURCE_LABEL[src]}: {med:.6f} us/(iter*step)")

    outdir.joinpath("summary.txt").write_text("\n".join(lines) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="Compare TinyMPC/FPGA benchmark BENCH_CSV logs.")
    ap.add_argument("--tinympc", type=Path, required=True, help="TinyMPC log file path.")
    ap.add_argument("--fpga-float", type=Path, required=True, help="FPGA floating-point log file path.")
    ap.add_argument("--fpga-fixed", type=Path, required=True, help="FPGA fixed-point log file path.")
    ap.add_argument("-o", "--outdir", type=Path, default=Path("compare_plots"), help="Output directory.")
    args = ap.parse_args()

    points_by_source: Dict[str, List[BenchPoint]] = {
        TINYMPC: parse_log(args.tinympc),
        FPGA_FLOAT: parse_log(args.fpga_float),
        FPGA_FIXED: parse_log(args.fpga_fixed),
    }

    for src in SOURCES:
        if not points_by_source[src]:
            print(f"No BENCH_CSV rows found in {src} input.")
            return 1

    data_by_source = {src: grouped(points_by_source[src]) for src in SOURCES}
    horizons = sorted(
        set().union(
            *[set(data_by_source[src].keys()) for src in SOURCES]
        )
    )
    if not horizons:
        print("No horizons found across inputs.")
        return 1

    args.outdir.mkdir(parents=True, exist_ok=True)
    plot_avg_vs_iter_per_h(data_by_source, horizons, args.outdir)
    plot_norm_vs_iter_per_h(data_by_source, horizons, args.outdir)
    plot_speedup_vs_tinympc_per_h(data_by_source, horizons, args.outdir)
    plot_k_step_iter_vs_h(data_by_source, horizons, args.outdir)
    write_summary(points_by_source, data_by_source, args.outdir)

    print(f"Wrote comparison plots to: {args.outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
