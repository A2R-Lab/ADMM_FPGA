#!/usr/bin/env python3
"""
Plot TinyMPC benchmark CSV-style logs.

Expected log lines:
  TINYMPC-E: BENCH_CSV,H,iter,min_us,avg_us,max_us,misses,total,solved,max_iter,noncvx,other
  TINYMPC-E: BENCH_FIT_CSV,H,T0_us,k_iter_us_per_iter,k_step_iter_us_per_iter_step
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
FIT_RE = re.compile(r"BENCH_FIT_CSV,([^\n\r]+)")


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


@dataclass
class BenchFit:
    H: int
    t0_us: float
    k_iter_us_per_iter: float
    k_step_iter_us: float


def parse_log(path: Path) -> Tuple[List[BenchPoint], Dict[int, BenchFit]]:
    text = path.read_text()
    points: List[BenchPoint] = []
    fits: Dict[int, BenchFit] = {}

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

    for m in FIT_RE.finditer(text):
        row = next(csv.reader([m.group(1)]))
        if len(row) != 4:
            continue
        fit = BenchFit(
            H=int(row[0]),
            t0_us=float(row[1]),
            k_iter_us_per_iter=float(row[2]),
            k_step_iter_us=float(row[3]),
        )
        fits[fit.H] = fit

    points.sort(key=lambda p: (p.H, p.it))
    return points, fits


def grouped(points: List[BenchPoint]) -> Dict[int, List[BenchPoint]]:
    out: Dict[int, List[BenchPoint]] = {}
    for p in points:
        out.setdefault(p.H, []).append(p)
    for k in out:
        out[k].sort(key=lambda x: x.it)
    return out


def save(fig: plt.Figure, outdir: Path, name: str) -> None:
    out = outdir / name
    fig.tight_layout()
    fig.savefig(out, dpi=180)
    plt.close(fig)


def plot_avg_vs_iter(g: Dict[int, List[BenchPoint]], outdir: Path, budget_us: float) -> None:
    fig, ax = plt.subplots(figsize=(9, 6))
    cmap = plt.cm.get_cmap("tab10")
    for i, (H, pts) in enumerate(sorted(g.items())):
        it = np.array([p.it for p in pts], dtype=float)
        avg = np.array([p.avg_us for p in pts], dtype=float)
        mn = np.array([p.min_us for p in pts], dtype=float)
        mx = np.array([p.max_us for p in pts], dtype=float)
        color = cmap(i % 10)
        ax.plot(it, avg, marker="o", linewidth=2, color=color, label=f"H={H}")
        ax.fill_between(it, mn, mx, color=color, alpha=0.18)
    ax.axhline(budget_us, color="red", linestyle="--", linewidth=1.5, label=f"Budget {budget_us:.0f} us")
    ax.set_title("Solve Time vs ADMM Iterations")
    ax.set_xlabel("Iterations")
    ax.set_ylabel("Time [us]")
    ax.grid(True, alpha=0.3)
    ax.legend()
    save(fig, outdir, "01_avg_vs_iter.png")


def plot_normalized_time(g: Dict[int, List[BenchPoint]], outdir: Path) -> None:
    fig, ax = plt.subplots(figsize=(9, 6))
    for H, pts in sorted(g.items()):
        it = np.array([p.it for p in pts], dtype=float)
        norm = np.array([p.avg_us / (p.it * p.H) for p in pts], dtype=float)
        ax.plot(it, norm, marker="o", linewidth=2, label=f"H={H}")
    ax.set_title("Normalized Time per (Iteration * Horizon Step)")
    ax.set_xlabel("Iterations")
    ax.set_ylabel("avg_us / (iter * H) [us]")
    ax.grid(True, alpha=0.3)
    ax.legend()
    save(fig, outdir, "02_normalized_time.png")


def plot_miss_rate_heatmap(g: Dict[int, List[BenchPoint]], outdir: Path) -> None:
    hs = sorted(g.keys())
    iters = sorted({p.it for pts in g.values() for p in pts})
    mat = np.full((len(hs), len(iters)), np.nan)
    for i, H in enumerate(hs):
        by_it = {p.it: p for p in g[H]}
        for j, it in enumerate(iters):
            if it in by_it:
                mat[i, j] = by_it[it].miss_rate
    fig, ax = plt.subplots(figsize=(10, 5))
    im = ax.imshow(mat, aspect="auto", cmap="magma", vmin=0.0, vmax=1.0)
    ax.set_title("Miss Rate Heatmap")
    ax.set_xlabel("Iterations")
    ax.set_ylabel("Horizon")
    ax.set_xticks(range(len(iters)))
    ax.set_xticklabels(iters)
    ax.set_yticks(range(len(hs)))
    ax.set_yticklabels(hs)
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("Miss rate")
    save(fig, outdir, "03_miss_rate_heatmap.png")


def plot_fit_params(fits: Dict[int, BenchFit], outdir: Path) -> None:
    hs = sorted(fits.keys())
    if not hs:
        return
    t0 = [fits[h].t0_us for h in hs]
    k = [fits[h].k_iter_us_per_iter for h in hs]
    ks = [fits[h].k_step_iter_us for h in hs]

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.8))
    axes[0].plot(hs, t0, marker="o")
    axes[0].set_title("T0 vs Horizon")
    axes[0].set_xlabel("H")
    axes[0].set_ylabel("T0 [us]")
    axes[0].grid(True, alpha=0.3)

    axes[1].plot(hs, k, marker="o")
    axes[1].set_title("k_iter vs Horizon")
    axes[1].set_xlabel("H")
    axes[1].set_ylabel("k_iter [us/iter]")
    axes[1].grid(True, alpha=0.3)

    axes[2].plot(hs, ks, marker="o")
    axes[2].set_title("k_step_iter vs Horizon")
    axes[2].set_xlabel("H")
    axes[2].set_ylabel("k_step_iter [us/(iter*step)]")
    axes[2].grid(True, alpha=0.3)

    save(fig, outdir, "04_fit_params_vs_h.png")


def plot_fit_quality(g: Dict[int, List[BenchPoint]], fits: Dict[int, BenchFit], outdir: Path) -> None:
    fig, ax = plt.subplots(figsize=(9, 6))
    for H, pts in sorted(g.items()):
        if H not in fits:
            continue
        f = fits[H]
        x = np.array([p.it for p in pts], dtype=float)
        y = np.array([p.avg_us for p in pts], dtype=float)
        yhat = f.t0_us + f.k_iter_us_per_iter * x
        ax.scatter(y, yhat, label=f"H={H}", s=30)
    all_vals = [p.avg_us for pts in g.values() for p in pts]
    if all_vals:
        lo = min(all_vals)
        hi = max(all_vals)
        ax.plot([lo, hi], [lo, hi], "k--", linewidth=1)
    ax.set_title("Fit Quality: Predicted vs Measured Average Time")
    ax.set_xlabel("Measured avg [us]")
    ax.set_ylabel("Predicted avg [us]")
    ax.grid(True, alpha=0.3)
    ax.legend()
    save(fig, outdir, "05_fit_quality_pred_vs_meas.png")


def plot_speedup_tradeoff(g: Dict[int, List[BenchPoint]], outdir: Path) -> None:
    fig, ax = plt.subplots(figsize=(9, 6))
    for H, pts in sorted(g.items()):
        xs = np.array([p.it for p in pts], dtype=float)
        ys = np.array([1.0 / p.avg_us for p in pts], dtype=float) * 1e6
        ax.plot(xs, ys, marker="o", linewidth=2, label=f"H={H}")
    ax.set_title("Throughput vs Iterations")
    ax.set_xlabel("Iterations")
    ax.set_ylabel("Solve throughput [solves/s]")
    ax.grid(True, alpha=0.3)
    ax.legend()
    save(fig, outdir, "06_throughput_vs_iter.png")


def plot_dashboard(g: Dict[int, List[BenchPoint]], fits: Dict[int, BenchFit], outdir: Path, budget_us: float) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    ax = axes[0, 0]
    for H, pts in sorted(g.items()):
        it = [p.it for p in pts]
        avg = [p.avg_us for p in pts]
        ax.plot(it, avg, marker="o", label=f"H={H}")
    ax.axhline(budget_us, color="red", linestyle="--", linewidth=1)
    ax.set_title("avg_us vs iter")
    ax.set_xlabel("iter")
    ax.set_ylabel("avg_us")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)

    ax = axes[0, 1]
    hs = sorted(fits.keys())
    if hs:
        ax.plot(hs, [fits[h].k_step_iter_us for h in hs], marker="o")
    ax.set_title("k_step_iter vs H")
    ax.set_xlabel("H")
    ax.set_ylabel("us/(iter*step)")
    ax.grid(True, alpha=0.3)

    ax = axes[1, 0]
    hs = sorted(g.keys())
    iters = sorted({p.it for pts in g.values() for p in pts})
    mat = np.full((len(hs), len(iters)), np.nan)
    for i, H in enumerate(hs):
        by_it = {p.it: p for p in g[H]}
        for j, it in enumerate(iters):
            if it in by_it:
                mat[i, j] = by_it[it].miss_rate
    im = ax.imshow(mat, aspect="auto", cmap="viridis", vmin=0, vmax=1)
    ax.set_title("miss_rate")
    ax.set_xticks(range(len(iters)))
    ax.set_xticklabels(iters)
    ax.set_yticks(range(len(hs)))
    ax.set_yticklabels(hs)
    ax.set_xlabel("iter")
    ax.set_ylabel("H")
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)

    ax = axes[1, 1]
    for H, pts in sorted(g.items()):
        x = np.array([p.it for p in pts], dtype=float)
        y = np.array([p.avg_us / (p.it * p.H) for p in pts], dtype=float)
        ax.plot(x, y, marker="o", label=f"H={H}")
    ax.set_title("avg_us/(iter*H)")
    ax.set_xlabel("iter")
    ax.set_ylabel("us")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)

    save(fig, outdir, "00_dashboard.png")


def write_summary(points: List[BenchPoint], fits: Dict[int, BenchFit], outdir: Path, budget_us: float) -> None:
    by_h = grouped(points)
    lines: List[str] = []
    lines.append("TinyMPC Benchmark Plot Summary")
    lines.append("")
    lines.append(f"budget_us={budget_us:.1f}")
    lines.append("")
    for H in sorted(by_h.keys()):
        pts = by_h[H]
        feas = [str(p.it) for p in pts if p.avg_us <= budget_us]
        ftxt = ",".join(feas) if feas else "none"
        lines.append(f"H={H}: feasible_iters_by_avg=[{ftxt}]")
        if H in fits:
            f = fits[H]
            lines.append(
                f"  fit: T0={f.t0_us:.3f} us, k_iter={f.k_iter_us_per_iter:.3f} us/iter, "
                f"k_step_iter={f.k_step_iter_us:.6f} us/(iter*step)"
            )
    (outdir / "summary.txt").write_text("\n".join(lines) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate many plots from TinyMPC BENCH_CSV logs.")
    ap.add_argument("logfile", type=Path, help="Path to firmware log text file")
    ap.add_argument("-o", "--outdir", type=Path, default=Path("bench_plots"), help="Output directory")
    ap.add_argument("--budget-us", type=float, default=2000.0, help="Timing budget for feasibility lines")
    args = ap.parse_args()

    points, fits = parse_log(args.logfile)
    if not points:
        print("No BENCH_CSV rows found.", flush=True)
        return 1

    args.outdir.mkdir(parents=True, exist_ok=True)
    g = grouped(points)

    plot_dashboard(g, fits, args.outdir, args.budget_us)
    plot_avg_vs_iter(g, args.outdir, args.budget_us)
    plot_normalized_time(g, args.outdir)
    plot_miss_rate_heatmap(g, args.outdir)
    plot_fit_params(fits, args.outdir)
    plot_fit_quality(g, fits, args.outdir)
    plot_speedup_tradeoff(g, args.outdir)
    write_summary(points, fits, args.outdir, args.budget_us)

    print(f"Wrote plots to: {args.outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

