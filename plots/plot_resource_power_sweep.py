#!/usr/bin/env python3
"""
Plot the current FPGA resource/power validation CSV.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import matplotlib.pyplot as plt
import numpy as np


@dataclass
class BenchPoint:
    horizon: int
    admm_iters: int
    solve_us: float
    throughput_sps: float
    lut_util_pct: float
    dsp_util_pct: float
    bram_util_pct: float
    power_w: float
    energy_uj: float


def parse_csv(path: Path) -> List[BenchPoint]:
    points: List[BenchPoint] = []
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            points.append(
                BenchPoint(
                    horizon=int(row["horizon"]),
                    admm_iters=int(row["admm_iters"]),
                    solve_us=float(row["est_solve_us_route_fmax"]),
                    throughput_sps=float(row["throughput_route_fmax_sps"]),
                    lut_util_pct=float(row["slice_luts_util_pct"]),
                    dsp_util_pct=float(row["dsps_util_pct"]),
                    bram_util_pct=float(row["bram_tile_util_pct"]),
                    power_w=float(row["route_power_total_w"]),
                    energy_uj=float(row["energy_per_solve_route_fmax_uj"]),
                )
            )
    points.sort(key=lambda p: (p.horizon, p.admm_iters))
    return points


def grouped(points: List[BenchPoint]) -> Dict[int, List[BenchPoint]]:
    out: Dict[int, List[BenchPoint]] = {}
    for point in points:
        out.setdefault(point.horizon, []).append(point)
    for horizon in out:
        out[horizon].sort(key=lambda point: point.admm_iters)
    return out


def save(fig: plt.Figure, outdir: Path, name: str) -> None:
    fig.tight_layout()
    fig.savefig(outdir / name, dpi=180)
    plt.close(fig)


def plot_solve_time(g: Dict[int, List[BenchPoint]], outdir: Path, budget_us: float) -> None:
    fig, ax = plt.subplots(figsize=(9, 6))
    for horizon, pts in sorted(g.items()):
        xs = np.array([p.admm_iters for p in pts], dtype=float)
        ys = np.array([p.solve_us for p in pts], dtype=float)
        ax.plot(xs, ys, marker="o", linewidth=2, label=f"H={horizon}")
    ax.axhline(budget_us, color="red", linestyle="--", linewidth=1.5, label=f"Budget {budget_us:.0f} us")
    ax.set_title("Estimated Solve Time vs ADMM Iterations")
    ax.set_xlabel("ADMM Iterations")
    ax.set_ylabel("Estimated Solve Time [us]")
    ax.grid(True, alpha=0.3)
    ax.legend()
    save(fig, outdir, "01_solve_time_vs_iter.png")


def plot_throughput(g: Dict[int, List[BenchPoint]], outdir: Path) -> None:
    fig, ax = plt.subplots(figsize=(9, 6))
    for horizon, pts in sorted(g.items()):
        xs = np.array([p.admm_iters for p in pts], dtype=float)
        ys = np.array([p.throughput_sps for p in pts], dtype=float)
        ax.plot(xs, ys, marker="o", linewidth=2, label=f"H={horizon}")
    ax.set_title("Throughput vs ADMM Iterations")
    ax.set_xlabel("ADMM Iterations")
    ax.set_ylabel("Throughput [solves/s]")
    ax.grid(True, alpha=0.3)
    ax.legend()
    save(fig, outdir, "02_throughput_vs_iter.png")


def plot_resources_vs_horizon(g: Dict[int, List[BenchPoint]], outdir: Path) -> None:
    horizons = sorted(g.keys())
    lut = [max(p.lut_util_pct for p in g[h]) for h in horizons]
    dsp = [max(p.dsp_util_pct for p in g[h]) for h in horizons]
    bram = [max(p.bram_util_pct for p in g[h]) for h in horizons]

    fig, ax = plt.subplots(figsize=(9, 6))
    ax.plot(horizons, lut, marker="o", linewidth=2, label="LUT")
    ax.plot(horizons, dsp, marker="o", linewidth=2, label="DSP")
    ax.plot(horizons, bram, marker="o", linewidth=2, label="BRAM")
    ax.set_title("Peak Resource Utilization vs Horizon")
    ax.set_xlabel("Horizon")
    ax.set_ylabel("Utilization [%]")
    ax.grid(True, alpha=0.3)
    ax.legend()
    save(fig, outdir, "04_resources_vs_horizon.png")


def plot_power_energy(g: Dict[int, List[BenchPoint]], outdir: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))

    for horizon, pts in sorted(g.items()):
        xs = np.array([p.admm_iters for p in pts], dtype=float)
        power = np.array([p.power_w for p in pts], dtype=float)
        energy = np.array([p.energy_uj for p in pts], dtype=float)
        axes[0].plot(xs, power, marker="o", linewidth=2, label=f"H={horizon}")
        axes[1].plot(xs, energy, marker="o", linewidth=2, label=f"H={horizon}")

    axes[0].set_title("Route Power vs ADMM Iterations")
    axes[0].set_xlabel("ADMM Iterations")
    axes[0].set_ylabel("Power [W]")
    axes[0].grid(True, alpha=0.3)

    axes[1].set_title("Energy per Solve vs ADMM Iterations")
    axes[1].set_xlabel("ADMM Iterations")
    axes[1].set_ylabel("Energy [uJ]")
    axes[1].grid(True, alpha=0.3)
    axes[1].legend()

    save(fig, outdir, "05_power_energy_vs_iter.png")


def plot_dashboard(g: Dict[int, List[BenchPoint]], outdir: Path, budget_us: float) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))

    ax = axes[0]
    for horizon, pts in sorted(g.items()):
        ax.plot([p.admm_iters for p in pts], [p.solve_us for p in pts], marker="o", label=f"H={horizon}")
    ax.axhline(budget_us, color="red", linestyle="--", linewidth=1)
    ax.set_title("Solve Time")
    ax.set_xlabel("ADMM Iterations")
    ax.set_ylabel("Time [us]")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)

    ax = axes[1]
    for horizon, pts in sorted(g.items()):
        ax.plot([p.admm_iters for p in pts], [p.throughput_sps for p in pts], marker="o", label=f"H={horizon}")
    ax.set_title("Throughput")
    ax.set_xlabel("ADMM Iterations")
    ax.set_ylabel("Solves/s")
    ax.grid(True, alpha=0.3)

    ax = axes[2]
    horizons = sorted(g.keys())
    ax.plot(horizons, [max(p.lut_util_pct for p in g[h]) for h in horizons], marker="o", label="LUT")
    ax.plot(horizons, [max(p.dsp_util_pct for p in g[h]) for h in horizons], marker="o", label="DSP")
    ax.plot(horizons, [max(p.bram_util_pct for p in g[h]) for h in horizons], marker="o", label="BRAM")
    ax.set_title("Peak Resource Utilization")
    ax.set_xlabel("Horizon")
    ax.set_ylabel("Utilization [%]")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)

    save(fig, outdir, "00_dashboard.png")


def write_summary(points: List[BenchPoint], outdir: Path, budget_us: float) -> None:
    g = grouped(points)
    lines: List[str] = []
    lines.append("FPGA Resource/Power Validation Summary")
    lines.append("")
    lines.append(f"budget_us={budget_us:.1f}")
    lines.append("")
    for horizon in sorted(g.keys()):
        pts = g[horizon]
        feasible = [str(p.admm_iters) for p in pts if p.solve_us <= budget_us]
        best = min(pts, key=lambda p: p.solve_us)
        lines.append(f"H={horizon}: feasible_iters=[{','.join(feasible) if feasible else 'none'}]")
        lines.append(
            f"  best_solve_us={best.solve_us:.3f}, best_iters={best.admm_iters}, "
            f"peak_lut_pct={max(p.lut_util_pct for p in pts):.2f}, "
            f"peak_dsp_pct={max(p.dsp_util_pct for p in pts):.2f}, "
            f"peak_bram_pct={max(p.bram_util_pct for p in pts):.2f}"
        )
    (outdir / "summary.txt").write_text("\n".join(lines) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate plots from the current FPGA validation CSV.")
    ap.add_argument("csvfile", type=Path, help="Path to the CSV file")
    ap.add_argument("-o", "--outdir", type=Path, default=Path("bench_plots"), help="Output directory")
    ap.add_argument("--budget-us", type=float, default=2000.0, help="Timing budget for feasibility lines")
    args = ap.parse_args()

    points = parse_csv(args.csvfile)
    if not points:
        print("No rows found in CSV.", flush=True)
        return 1

    args.outdir.mkdir(parents=True, exist_ok=True)
    g = grouped(points)

    plot_dashboard(g, args.outdir, args.budget_us)
    plot_solve_time(g, args.outdir, args.budget_us)
    plot_throughput(g, args.outdir)
    plot_resources_vs_horizon(g, args.outdir)
    plot_power_energy(g, args.outdir)
    write_summary(points, args.outdir, args.budget_us)

    print(f"Wrote plots to: {args.outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
