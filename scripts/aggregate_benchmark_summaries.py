#!/usr/bin/env python3
"""Aggregate benchmark summaries into compact latency datasets."""

from __future__ import annotations

import argparse
import csv
import math
import os
from pathlib import Path


ALL_FIELDS = [
    "campaign",
    "source_summary",
    "slug",
    "arch",
    "horizon",
    "admm_iters",
    "status",
    "failed_stage",
    "bitstream_exists",
    "timing_clean",
    "route_wns_ns",
    "hls_latency_cycles",
    "solve_us_cfg_clk",
    "solve_us_per_iter_cfg_clk",
    "hls_latency_cycles_per_iter",
    "route_power_total_w",
    "energy_per_solve_cfg_uj",
    "energy_per_iter_cfg_uj",
    "route_bram_tile_used",
    "route_bram_tile_util_pct",
    "route_dsps_used",
    "route_dsps_util_pct",
    "route_slice_luts_used",
    "route_slice_luts_util_pct",
    "route_slice_registers_used",
    "route_slice_registers_util_pct",
    "route_lut_as_mem_used",
    "route_lut_as_mem_util_pct",
    "tinympc_min_us",
    "tinympc_avg_us",
    "tinympc_max_us",
    "tinympc_misses",
    "tinympc_total",
    "tinympc_solved",
    "tinympc_max_iter",
    "tinympc_noncvx",
    "tinympc_other",
    "gen_n_var",
    "gen_n_constr",
    "gen_kkt_nnz",
    "gen_chol_l_nnz",
    "seed",
    "vivado_impl_variant",
    "vivado_place_seed",
    "vivado_route_seed",
    "git_head",
    "git_status_short",
    "point_dir",
]


BEST_FIELDS = [
    "arch",
    "horizon",
    "admm_iters",
    "solve_us_cfg_clk",
    "solve_us_per_iter_cfg_clk",
    "hls_latency_cycles",
    "hls_latency_cycles_per_iter",
    "route_wns_ns",
    "route_power_total_w",
    "energy_per_solve_cfg_uj",
    "route_bram_tile_util_pct",
    "route_slice_luts_util_pct",
    "route_slice_registers_util_pct",
    "route_lut_as_mem_util_pct",
    "tinympc_min_us",
    "tinympc_avg_us",
    "tinympc_max_us",
    "tinympc_misses",
    "tinympc_total",
    "tinympc_solved",
    "tinympc_max_iter",
    "tinympc_noncvx",
    "tinympc_other",
    "campaign",
    "slug",
    "source_summary",
]


def f(row: dict[str, str], key: str, default: float = math.nan) -> float:
    raw = row.get(key, "")
    if raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def compact(value: float) -> str:
    return "" if not math.isfinite(value) else f"{value:.9g}"


def timing_clean(row: dict[str, str]) -> bool:
    return (
        row.get("status") == "pass"
        and row.get("bitstream_exists") == "1"
        and f(row, "route_wns_ns", -math.inf) >= 0
        and math.isfinite(f(row, "solve_us_cfg_clk"))
    )


def read_summary(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as fobj:
        reader = csv.DictReader(fobj)
        rows = []
        for row in reader:
            campaign = path.parent.name
            iters = f(row, "admm_iters")
            solve_us = f(row, "solve_us_cfg_clk")
            cycles = f(row, "hls_latency_cycles")
            energy = f(row, "energy_per_solve_cfg_uj")
            out = {name: row.get(name, "") for name in ALL_FIELDS}
            out.update(
                {
                    "campaign": campaign,
                    "source_summary": str(path),
                    "timing_clean": "1" if timing_clean(row) else "0",
                    "solve_us_per_iter_cfg_clk": compact(solve_us / iters) if iters > 0 else "",
                    "hls_latency_cycles_per_iter": compact(cycles / iters) if iters > 0 else "",
                    "energy_per_iter_cfg_uj": compact(energy / iters) if iters > 0 else "",
                }
            )
            rows.append(out)
        return rows


def read_tinympc(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    prefix = "TINYMPC-E: BENCH_CSV,"
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        line = line.strip()
        if not line.startswith(prefix):
            continue
        values = [value.strip() for value in line[len(prefix):].split(",")]
        if len(values) != 11:
            raise SystemExit(f"Expected 11 TinyMPC values in {path}:{line_number}")
        (
            horizon,
            iters,
            min_us,
            avg_us,
            max_us,
            misses,
            total,
            solved,
            max_iter,
            noncvx,
            other,
        ) = values
        iters_f = float(iters)
        avg_f = float(avg_us)
        out = {name: "" for name in ALL_FIELDS}
        out.update(
            {
                "campaign": "tinympc",
                "source_summary": str(path),
                "slug": f"tinympc_e_h{horizon}_k{iters}",
                "arch": "tinympc_e",
                "horizon": horizon,
                "admm_iters": iters,
                "status": "benchmark",
                "timing_clean": "1",
                "solve_us_cfg_clk": avg_us,
                "solve_us_per_iter_cfg_clk": compact(avg_f / iters_f) if iters_f > 0 else "",
                "tinympc_min_us": min_us,
                "tinympc_avg_us": avg_us,
                "tinympc_max_us": max_us,
                "tinympc_misses": misses,
                "tinympc_total": total,
                "tinympc_solved": solved,
                "tinympc_max_iter": max_iter,
                "tinympc_noncvx": noncvx,
                "tinympc_other": other,
            }
        )
        rows.append(out)
    if not rows:
        raise SystemExit(f"No TinyMPC benchmark rows found in {path}")
    return rows


def output_name(prefix: str, filename: str) -> str:
    return f"{prefix}_{filename}" if prefix else filename


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fobj:
        writer = csv.DictWriter(fobj, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def best_rows(rows: list[dict[str, str]], compare_iters: int) -> list[dict[str, str]]:
    best: dict[tuple[str, int], dict[str, str]] = {}
    for row in rows:
        if row.get("timing_clean") != "1":
            continue
        arch = row.get("arch", "")
        if not arch:
            continue
        horizon = int(f(row, "horizon", -1))
        if horizon < 0:
            continue
        if arch == "tinympc_e" and int(f(row, "admm_iters", -1)) != compare_iters:
            continue
        key = (arch, horizon)
        current = best.get(key)
        if current is None or f(row, "solve_us_cfg_clk", math.inf) < f(current, "solve_us_cfg_clk", math.inf):
            best[key] = row
    selected = []
    for row in sorted(best.values(), key=lambda r: (r["arch"], int(f(r, "horizon")))):
        selected.append({name: row.get(name, "") for name in BEST_FIELDS})
    return selected


def plot_latency(best: list[dict[str, str]], output: Path) -> None:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/admm_fpga_matplotlib")
    import matplotlib.pyplot as plt

    by_arch: dict[str, list[dict[str, str]]] = {}
    for row in best:
        by_arch.setdefault(row["arch"], []).append(row)

    fig, ax = plt.subplots(figsize=(11.5, 5.8))
    colors = {"full_sparse": "#176B87", "staged_a": "#D95F02", "tinympc_e": "#4C956C"}
    archs = sorted(by_arch)
    horizons = sorted({int(f(row, "horizon")) for row in best})
    x = list(range(len(horizons)))
    width = 0.82 / max(1, len(archs))
    for arch_idx, arch in enumerate(archs):
        by_h = {int(f(row, "horizon")): row for row in by_arch[arch]}
        xs = [idx + (arch_idx - (len(archs) - 1) / 2) * width for idx in x if horizons[idx] in by_h]
        ys = [f(by_h[horizons[idx]], "solve_us_cfg_clk") / 1000.0 for idx in x if horizons[idx] in by_h]
        ax.bar(xs, ys, width=width, color=colors.get(arch), label=arch)
    ax.set_xticks(x)
    ax.set_xticklabels([str(h) for h in horizons], rotation=45, ha="right")
    ax.set_xlabel("Horizon")
    ax.set_ylabel("Solve latency [ms]")
    ax.set_title("Whole-Solve Latency by Horizon")
    ax.grid(True, axis="y", alpha=0.3)
    ax.legend()
    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=180)
    plt.close(fig)


def plot_latency_bar_svg(best: list[dict[str, str]], output: Path) -> None:
    by_arch: dict[str, list[dict[str, str]]] = {}
    for row in best:
        by_arch.setdefault(row["arch"], []).append(row)
    points = [
        (f(row, "horizon"), f(row, "solve_us_cfg_clk") / 1000.0)
        for rows in by_arch.values()
        for row in rows
    ]
    if not points:
        return

    width, height = 1180, 650
    left, right, top, bottom = 90, 40, 48, 105
    plot_w = width - left - right
    plot_h = height - top - bottom
    min_y = 0.0
    max_y = max(y for _, y in points) * 1.08
    colors = {"full_sparse": "#176B87", "staged_a": "#D95F02", "tinympc_e": "#4C956C"}

    def sy(y: float) -> float:
        return top + plot_h - (y - min_y) * plot_h / (max_y - min_y if max_y > min_y else 1.0)

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<style>text{font-family:Arial,sans-serif;font-size:14px;fill:#222}.title{font-size:20px;font-weight:700}.axis{stroke:#222;stroke-width:1.5}.grid{stroke:#ddd;stroke-width:1}.line{fill:none;stroke-width:3}.pt{stroke:white;stroke-width:1.5}</style>',
        f'<text class="title" x="{width/2}" y="26" text-anchor="middle">Whole-Solve Latency by Horizon</text>',
    ]
    horizons = sorted({int(x) for x, _ in points})
    archs = sorted(by_arch)
    group_w = plot_w / max(1, len(horizons))
    bar_w = min(26.0, group_w * 0.78 / max(1, len(archs)))

    def gx(index: int) -> float:
        return left + index * group_w + group_w / 2

    for frac in [0, 0.25, 0.5, 0.75, 1.0]:
        y = min_y + frac * (max_y - min_y)
        yy = sy(y)
        lines.append(f'<line class="grid" x1="{left}" y1="{yy:.1f}" x2="{width-right}" y2="{yy:.1f}"/>')
        lines.append(f'<text x="{left-10}" y="{yy+5:.1f}" text-anchor="end">{y:.1f}</text>')
    lines.append(f'<line class="axis" x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}"/>')
    lines.append(f'<line class="axis" x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}"/>')
    for idx, horizon in enumerate(horizons):
        xx = gx(idx)
        lines.append(f'<text x="{xx:.1f}" y="{height-bottom+24}" text-anchor="middle" transform="rotate(-45 {xx:.1f} {height-bottom+24})">{horizon}</text>')

    legend_x = width - right - 180
    legend_y = top + 10
    for idx, (arch, rows) in enumerate(sorted(by_arch.items())):
        color = colors.get(arch, "#444")
        by_h = {int(f(row, "horizon")): row for row in rows}
        for h_idx, horizon in enumerate(horizons):
            row = by_h.get(horizon)
            if row is None:
                continue
            value = f(row, "solve_us_cfg_clk") / 1000.0
            cx = gx(h_idx) + (idx - (len(archs) - 1) / 2) * bar_w
            y = sy(value)
            bar_h = height - bottom - y
            lines.append(
                f'<rect x="{cx - bar_w/2:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" fill="{color}"/>'
            )
        y = legend_y + idx * 24
        lines.append(f'<rect x="{legend_x}" y="{y-10}" width="28" height="14" fill="{color}"/>')
        lines.append(f'<text x="{legend_x+36}" y="{y+5}">{arch}</text>')
    lines.append(f'<text x="{width/2}" y="{height-20}" text-anchor="middle">Horizon</text>')
    lines.append(f'<text x="20" y="{height/2}" transform="rotate(-90 20 {height/2})" text-anchor="middle">Solve latency [ms]</text>')
    lines.append("</svg>")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n")


def plot_latency_line_svg(best: list[dict[str, str]], output: Path) -> None:
    by_arch: dict[str, list[dict[str, str]]] = {}
    for row in best:
        by_arch.setdefault(row["arch"], []).append(row)
    points = [
        (f(row, "horizon"), f(row, "solve_us_cfg_clk") / 1000.0)
        for rows in by_arch.values()
        for row in rows
    ]
    if not points:
        return

    width, height = 1000, 600
    left, right, top, bottom = 85, 35, 45, 75
    plot_w = width - left - right
    plot_h = height - top - bottom
    min_x = min(x for x, _ in points)
    max_x = max(x for x, _ in points)
    min_y = 0.0
    max_y = max(y for _, y in points) * 1.08
    colors = {"full_sparse": "#176B87", "staged_a": "#D95F02", "tinympc_e": "#4C956C"}

    def sx(x: float) -> float:
        return left + (x - min_x) * plot_w / (max_x - min_x if max_x > min_x else 1.0)

    def sy(y: float) -> float:
        return top + plot_h - (y - min_y) * plot_h / (max_y - min_y if max_y > min_y else 1.0)

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<style>text{font-family:Arial,sans-serif;font-size:14px;fill:#222}.title{font-size:20px;font-weight:700}.axis{stroke:#222;stroke-width:1.5}.grid{stroke:#ddd;stroke-width:1}.line{fill:none;stroke-width:3}.pt{stroke:white;stroke-width:1.5}</style>',
        f'<text class="title" x="{width/2}" y="26" text-anchor="middle">Whole-Solve Latency vs Horizon</text>',
    ]
    for frac in [0, 0.25, 0.5, 0.75, 1.0]:
        y = min_y + frac * (max_y - min_y)
        yy = sy(y)
        lines.append(f'<line class="grid" x1="{left}" y1="{yy:.1f}" x2="{width-right}" y2="{yy:.1f}"/>')
        lines.append(f'<text x="{left-10}" y="{yy+5:.1f}" text-anchor="end">{y:.1f}</text>')
    lines.append(f'<line class="axis" x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}"/>')
    lines.append(f'<line class="axis" x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}"/>')
    for x in sorted({int(p[0]) for p in points}):
        xx = sx(x)
        lines.append(f'<line class="grid" x1="{xx:.1f}" y1="{top}" x2="{xx:.1f}" y2="{height-bottom}"/>')
        lines.append(f'<text x="{xx:.1f}" y="{height-bottom+24}" text-anchor="middle">{x}</text>')

    legend_x = width - right - 180
    legend_y = top + 10
    for idx, (arch, rows) in enumerate(sorted(by_arch.items())):
        rows = sorted(rows, key=lambda r: int(f(r, "horizon")))
        color = colors.get(arch, "#444")
        coords = " ".join(f'{sx(f(row, "horizon")):.1f},{sy(f(row, "solve_us_cfg_clk") / 1000.0):.1f}' for row in rows)
        lines.append(f'<polyline class="line" stroke="{color}" points="{coords}"/>')
        for row in rows:
            lines.append(
                f'<circle class="pt" cx="{sx(f(row, "horizon")):.1f}" cy="{sy(f(row, "solve_us_cfg_clk") / 1000.0):.1f}" r="4.5" fill="{color}"/>'
            )
        y = legend_y + idx * 24
        lines.append(f'<line x1="{legend_x}" y1="{y}" x2="{legend_x+28}" y2="{y}" stroke="{color}" stroke-width="3"/>')
        lines.append(f'<text x="{legend_x+36}" y="{y+5}">{arch}</text>')
    lines.append(f'<text x="{width/2}" y="{height-20}" text-anchor="middle">Horizon</text>')
    lines.append(f'<text x="20" y="{height/2}" transform="rotate(-90 20 {height/2})" text-anchor="middle">Solve latency [ms]</text>')
    lines.append("</svg>")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exp-dir", type=Path, default=Path("../exp"))
    parser.add_argument("--tinympc", type=Path, default=Path("../tinympcBenchmark.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("../exp/benchmark-aggregate"))
    parser.add_argument("--compare-iters", type=int, default=10)
    parser.add_argument(
        "--summary-glob",
        default="2026-*/summary.csv",
        help="Glob under --exp-dir selecting benchmark summary CSVs.",
    )
    parser.add_argument("--output-prefix", default="", help="Optional prefix for generated output filenames.")
    parser.add_argument("--no-plot", action="store_true")
    parser.add_argument("--png", action="store_true", help="Try to write a Matplotlib PNG instead of the default SVG")
    args = parser.parse_args()

    summary_paths = sorted(args.exp_dir.glob(args.summary_glob))
    if not summary_paths:
        raise SystemExit(f"No summary CSVs matching {args.summary_glob!r} under {args.exp_dir}")

    rows: list[dict[str, str]] = []
    for path in summary_paths:
        if path.parent.resolve() == args.output_dir.resolve():
            continue
        rows.extend(read_summary(path))
    if args.tinympc.exists():
        rows.extend(read_tinympc(args.tinympc))

    output_dir = args.output_dir
    all_csv = output_dir / output_name(args.output_prefix, "benchmark_summary.csv")
    best_csv = output_dir / output_name(args.output_prefix, "best_timing_clean_latency.csv")
    best = best_rows(rows, args.compare_iters)
    write_csv(all_csv, rows, ALL_FIELDS)
    write_csv(best_csv, best, BEST_FIELDS)
    if not args.no_plot and args.png:
        try:
            plot_latency(best, output_dir / output_name(args.output_prefix, "latency_vs_horizon.png"))
        except Exception as exc:
            svg_path = output_dir / output_name(args.output_prefix, "latency_vs_horizon.svg")
            plot_latency_bar_svg(best, svg_path)
            plot_latency_line_svg(best, output_dir / output_name(args.output_prefix, "latency_vs_horizon_line.svg"))
            print(f"Matplotlib plot failed ({exc}); wrote SVG fallback to {svg_path}")
    elif not args.no_plot:
        plot_latency_bar_svg(best, output_dir / output_name(args.output_prefix, "latency_vs_horizon.svg"))
        plot_latency_line_svg(best, output_dir / output_name(args.output_prefix, "latency_vs_horizon_line.svg"))
    print(f"Wrote {len(rows)} rows to {all_csv}")
    print(f"Wrote {len(best)} best timing-clean rows to {best_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
