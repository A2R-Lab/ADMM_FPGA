#!/usr/bin/env python3
"""Aggregate and plot direct max-horizon benchmark point rows."""

from __future__ import annotations

import argparse
import csv
import math
import os
from pathlib import Path


def load_rows(rows_dir: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in sorted(rows_dir.glob("*.csv")):
        with path.open(newline="") as f:
            rows.extend(csv.DictReader(f))
    return rows


def write_summary(rows: list[dict[str, str]], output_csv: Path) -> None:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: set[str] = set()
    for row in rows:
        fieldnames.update(row)
    preferred = [
        "slug",
        "arch",
        "horizon",
        "admm_iters",
        "status",
        "failed_stage",
        "bitstream_exists",
        "route_wns_ns",
        "hls_latency_cycles",
        "solve_us_cfg_clk",
        "route_power_total_w",
        "energy_per_solve_cfg_uj",
        "route_bram_tile_used",
        "route_dsps_used",
        "route_slice_luts_used",
        "route_slice_registers_used",
        "route_lut_as_mem_used",
        "gen_chol_bandwidth",
        "gen_kkt_nnz",
        "gen_chol_l_nnz",
        "build_runtime_s",
        "point_dir",
    ]
    ordered = [name for name in preferred if name in fieldnames] + sorted(fieldnames - set(preferred))
    with output_csv.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=ordered)
        writer.writeheader()
        writer.writerows(rows)


def f(row: dict[str, str], key: str, default: float = math.nan) -> float:
    try:
        raw = row.get(key, "")
        return default if raw == "" else float(raw)
    except ValueError:
        return default


def is_pass(row: dict[str, str]) -> bool:
    return row.get("status") == "pass" and row.get("bitstream_exists") == "1" and f(row, "route_wns_ns", -1) >= 0


def row_horizon(row: dict[str, str]) -> int:
    return int(float(row.get("horizon", "0") or 0))


def better_common_row(row: dict[str, str]) -> tuple[float, float, float]:
    return (
        f(row, "route_wns_ns", -math.inf),
        -f(row, "solve_us_cfg_clk", math.inf),
        -f(row, "energy_per_solve_cfg_uj", math.inf),
    )


def load_manual_max_horizons(path: Path) -> dict[str, int] | None:
    if not path.exists():
        return None

    with path.open(newline="") as fobj:
        reader = csv.DictReader(fobj)
        expected = ["arch", "max_timing_clean_horizon"]
        if reader.fieldnames != expected:
            raise SystemExit(f"{path} must have columns: {','.join(expected)}")

        max_horizons: dict[str, int] = {}
        for line_number, row in enumerate(reader, start=2):
            arch = row["arch"].strip()
            try:
                horizon = int(row["max_timing_clean_horizon"])
            except ValueError:
                raise SystemExit(f"Invalid max horizon in {path}:{line_number}") from None
            if not arch or horizon <= 0:
                raise SystemExit(f"Invalid arch or max horizon in {path}:{line_number}")
            if arch in max_horizons:
                raise SystemExit(f"Duplicate architecture {arch!r} in {path}:{line_number}")
            max_horizons[arch] = horizon

    if not max_horizons:
        raise SystemExit(f"No max-horizon rows found in {path}")
    return max_horizons


def write_max_horizon_table(max_horizons: dict[str, int], output_csv: Path) -> None:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="") as fobj:
        writer = csv.DictWriter(fobj, fieldnames=["arch", "max_timing_clean_horizon"])
        writer.writeheader()
        for arch, horizon in sorted(max_horizons.items()):
            writer.writerow({"arch": arch, "max_timing_clean_horizon": horizon})


def common_cost_metrics(row: dict[str, str], max_horizons: dict[str, int] | None = None) -> dict[str, float]:
    latency_ms = f(row, "solve_us_cfg_clk") / 1000.0
    energy_mj = f(row, "energy_per_solve_cfg_uj") / 1000.0
    metrics = {
        "Latency": latency_ms,
        "Energy": energy_mj,
        "EDP": f(row, "energy_per_solve_cfg_uj") * latency_ms,
        "Power": f(row, "route_power_total_w"),
        "BRAM": f(row, "route_bram_tile_util_pct"),
        "Compute": f(row, "route_slice_luts_util_pct") + f(row, "route_slice_registers_util_pct"),
    }
    if max_horizons:
        arch_h = max_horizons.get(row.get("arch", ""), 0)
        best_h = max(max_horizons.values()) if max_horizons else 0
        if arch_h > 0 and best_h > 0:
            metrics["Scalability"] = best_h / arch_h
    return metrics


COMMON_COST_UNITS = {
    "Latency": "ms",
    "Energy": "mJ/solve",
    "EDP": "uJ*ms",
    "Power": "W",
    "BRAM": "% used",
    "Compute": "% LUT+FF",
    "Scalability": "Max H",
}


def write_common_horizon_table(
    rows: list[dict[str, str]],
    output_csv: Path,
    max_horizons: dict[str, int] | None = None,
) -> None:
    passing = [row for row in rows if row.get("arch") and is_pass(row)]
    by_horizon_arch: dict[int, dict[str, dict[str, str]]] = {}
    for row in passing:
        horizon = row_horizon(row)
        arch = row["arch"]
        current = by_horizon_arch.setdefault(horizon, {}).get(arch)
        if current is None or better_common_row(row) > better_common_row(current):
            by_horizon_arch[horizon][arch] = row

    common_horizons = [
        horizon for horizon, by_arch in sorted(by_horizon_arch.items()) if len(by_arch) >= 2
    ]
    fieldnames = [
        "horizon",
        "arch",
        "slug",
        "seed",
        "vivado_impl_variant",
        "route_wns_ns",
        "latency_ms",
        "energy_mj_per_solve",
        "edp_uj_ms",
        "compute_lut_ff_util_pct",
        "solve_us_cfg_clk",
        "energy_per_solve_cfg_uj",
        "route_power_total_w",
        "route_bram_tile_util_pct",
        "route_slice_luts_util_pct",
        "route_slice_registers_util_pct",
        "route_dsps_util_pct",
        "route_lut_as_mem_util_pct",
    ]
    if max_horizons is not None:
        insert_at = fieldnames.index("solve_us_cfg_clk")
        fieldnames[insert_at:insert_at] = ["max_timing_clean_horizon", "scalability_cost"]
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="") as fobj:
        writer = csv.DictWriter(fobj, fieldnames=fieldnames)
        writer.writeheader()
        for horizon in common_horizons:
            for arch, row in sorted(by_horizon_arch[horizon].items()):
                metrics = common_cost_metrics(row, max_horizons)
                out = {name: row.get(name, "") for name in fieldnames}
                out.update(
                    {
                        "latency_ms": f"{metrics['Latency']:.6g}",
                        "energy_mj_per_solve": f"{metrics['Energy']:.6g}",
                        "edp_uj_ms": f"{metrics['EDP']:.6g}",
                        "compute_lut_ff_util_pct": f"{metrics['Compute']:.6g}",
                    }
                )
                if max_horizons is not None:
                    out.update(
                        {
                            "max_timing_clean_horizon": str(max_horizons.get(arch, "")),
                            "scalability_cost": f"{metrics['Scalability']:.6g}" if "Scalability" in metrics else "",
                        }
                    )
                writer.writerow(out)


def print_maxima(rows: list[dict[str, str]]) -> None:
    print("Max routed timing-clean horizons:")
    for arch in sorted({row.get("arch", "") for row in rows if row.get("arch")}):
        passing = [row for row in rows if row.get("arch") == arch and is_pass(row)]
        if not passing:
            print(f"  {arch}: none")
            continue
        best = max(passing, key=lambda row: int(float(row["horizon"])))
        print(
            f"  {arch}: H={best['horizon']} "
            f"lat={best.get('solve_us_cfg_clk', '?')}us "
            f"WNS={best.get('route_wns_ns', '?')}ns "
            f"E={best.get('energy_per_solve_cfg_uj', '?')}uJ"
        )


def normalize_higher_better(values: dict[str, float]) -> dict[str, float]:
    finite = [v for v in values.values() if math.isfinite(v)]
    if not finite:
        return {k: 0.0 for k in values}
    lo = min(finite)
    hi = max(finite)
    if hi == lo:
        return {k: 10.0 for k in values}
    return {k: 10.0 * (v - lo) / (hi - lo) if math.isfinite(v) else 0.0 for k, v in values.items()}


def normalize_lower_better(values: dict[str, float]) -> dict[str, float]:
    finite = [v for v in values.values() if math.isfinite(v)]
    if not finite:
        return {k: 0.0 for k in values}
    lo = min(finite)
    hi = max(finite)
    if hi == lo:
        return {k: 10.0 for k in values}
    return {k: 10.0 * (hi - v) / (hi - lo) if math.isfinite(v) else 0.0 for k, v in values.items()}


def make_plots(rows: list[dict[str, str]], out_dir: Path, max_horizons: dict[str, int] | None = None) -> None:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/admm_fpga_matplotlib")

    import matplotlib.pyplot as plt
    import numpy as np

    out_dir.mkdir(parents=True, exist_ok=True)
    by_arch: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        if row.get("arch"):
            by_arch.setdefault(row["arch"], []).append(row)
    for arch_rows in by_arch.values():
        arch_rows.sort(key=lambda row: int(float(row.get("horizon", "0") or 0)))

    def line_plot(metric: str, ylabel: str, name: str, only_pass: bool = False) -> None:
        fig, ax = plt.subplots(figsize=(9, 5))
        for arch, arch_rows in sorted(by_arch.items()):
            pts = [row for row in arch_rows if (not only_pass or is_pass(row)) and math.isfinite(f(row, metric))]
            if not pts:
                continue
            ax.plot(
                [int(float(row["horizon"])) for row in pts],
                [f(row, metric) for row in pts],
                marker="o",
                linewidth=2,
                label=arch,
            )
        ax.set_xlabel("Horizon")
        ax.set_ylabel(ylabel)
        ax.grid(True, alpha=0.3)
        ax.legend()
        fig.tight_layout()
        fig.savefig(out_dir / name, dpi=180)
        plt.close(fig)

    def radar_plot(
        selected_rows: dict[str, dict[str, str]],
        axes: list[str],
        raw: dict[str, dict[str, float]],
        higher_better: set[str],
        title: str,
        filename: str,
    ) -> None:
        scores = {
            axis: (
                normalize_higher_better(raw[axis])
                if axis in higher_better
                else normalize_lower_better(raw[axis])
            )
            for axis in axes
        }
        angles = np.linspace(0, 2 * np.pi, len(axes), endpoint=False).tolist()
        angles += angles[:1]
        fig = plt.figure(figsize=(8, 8))
        ax = fig.add_subplot(111, polar=True)
        for arch in sorted(selected_rows):
            vals = [scores[axis][arch] for axis in axes]
            vals += vals[:1]
            ax.plot(angles, vals, linewidth=2, label=arch)
            ax.fill(angles, vals, alpha=0.15)
        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(axes)
        ax.set_ylim(0, 10)
        ax.set_title(title)
        ax.grid(True, alpha=0.35)
        ax.legend(loc="upper right", bbox_to_anchor=(1.2, 1.1))
        fig.tight_layout()
        fig.savefig(out_dir / filename, dpi=180)
        plt.close(fig)

    def normalized_costs(values: dict[str, float]) -> dict[str, float]:
        finite = [v for v in values.values() if math.isfinite(v) and v >= 0]
        if not finite:
            return {k: math.nan for k in values}
        hi = max(finite)
        if hi <= 0:
            return {k: 0.0 if math.isfinite(v) else math.nan for k, v in values.items()}
        return {k: v / hi if math.isfinite(v) and v >= 0 else math.nan for k, v in values.items()}

    def fmt_metric(value: float, unit: str, arch: str = "", max_horizons_for_fmt: dict[str, int] | None = None) -> str:
        if not math.isfinite(value):
            return "n/a"
        if unit == "Max H":
            horizon = max_horizons_for_fmt.get(arch, 0) if max_horizons_for_fmt else 0
            return f"H={horizon}" if horizon else "n/a"
        if unit == "% used":
            return f"{value:.1f}%"
        if unit == "% LUT+FF":
            return f"{value:.1f}%"
        if unit == "W":
            return f"{value:.3f} W"
        if unit == "ms":
            return f"{value:.3f} ms"
        if unit == "mJ/solve":
            return f"{value:.3f} mJ"
        if unit == "uJ*ms":
            return f"{value:.0f} uJ*ms"
        return f"{value:.3g} {unit}"

    def common_cost_radar(horizon: int, selected: dict[str, dict[str, str]]) -> None:
        raw_by_arch = {arch: common_cost_metrics(row, max_horizons) for arch, row in selected.items()}
        axes = [axis for axis in COMMON_COST_UNITS if all(axis in metrics for metrics in raw_by_arch.values())]
        norm_by_axis = {
            axis: normalized_costs({arch: metrics[axis] for arch, metrics in raw_by_arch.items()})
            for axis in axes
        }
        angles = np.linspace(0, 2 * np.pi, len(axes), endpoint=False).tolist()
        angles += angles[:1]

        fig = plt.figure(figsize=(13, 9))
        gs = fig.add_gridspec(1, 2, width_ratios=[1.25, 1.0])
        ax = fig.add_subplot(gs[0, 0], polar=True)
        archs = sorted(selected)
        for arch_idx, arch in enumerate(archs):
            vals = [norm_by_axis[axis][arch] for axis in axes]
            vals += vals[:1]
            ax.plot(angles, vals, linewidth=2.5, marker="o", label=arch)
            ax.fill(angles, vals, alpha=0.12)
            for axis_idx, axis in enumerate(axes):
                unit = COMMON_COST_UNITS[axis]
                theta = angles[axis_idx]
                radius = vals[axis_idx]
                label = fmt_metric(raw_by_arch[arch][axis], unit, arch, max_horizons)
                theta_offset = (arch_idx - (len(archs) - 1) / 2) * 0.045
                radius_label = (1.08 + 0.055 * arch_idx) if radius >= 0.9 else radius + 0.07 + 0.045 * arch_idx
                ax.text(
                    theta + theta_offset,
                    min(1.2, radius_label),
                    label,
                    fontsize=7,
                    ha="center",
                    va="center",
                    clip_on=False,
                    bbox={"boxstyle": "round,pad=0.15", "fc": "white", "ec": "none", "alpha": 0.72},
                )

        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(axes, fontsize=11)
        ax.set_ylim(0, 1.24)
        ax.set_yticks([0.25, 0.5, 0.75, 1.0])
        ax.set_yticklabels(["25%", "50%", "75%", "max"], fontsize=9)
        ax.set_title(f"H={horizon} Solver Cost Radar\nLower is better; both designs are timing-clean", pad=28)
        ax.grid(True, alpha=0.35)
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.08), ncol=max(1, len(selected)))

        table_ax = fig.add_subplot(gs[0, 1])
        table_ax.axis("off")
        col_labels = ["Metric", "Unit", *archs]
        table_rows = []
        for axis in axes:
            unit = COMMON_COST_UNITS[axis]
            table_rows.append(
                [axis, unit, *[fmt_metric(raw_by_arch[arch][axis], unit, arch, max_horizons) for arch in archs]]
            )
        table = table_ax.table(cellText=table_rows, colLabels=col_labels, loc="center", cellLoc="center")
        table.auto_set_font_size(False)
        table.set_fontsize(9)
        table.scale(1.0, 1.45)
        table_ax.set_title("Raw values", pad=14)

        fig.tight_layout()
        fig.savefig(out_dir / f"solver_cost_radar_h{horizon}.png", dpi=180)
        plt.close(fig)

    def common_cost_bars(horizon: int, selected: dict[str, dict[str, str]]) -> None:
        raw_by_arch = {arch: common_cost_metrics(row, max_horizons) for arch, row in selected.items()}
        axes = [axis for axis in COMMON_COST_UNITS if all(axis in metrics for metrics in raw_by_arch.values())]
        norm_by_axis = {
            axis: normalized_costs({arch: metrics[axis] for arch, metrics in raw_by_arch.items()})
            for axis in axes
        }
        archs = sorted(selected)
        x = np.arange(len(axes))
        width = 0.8 / max(1, len(archs))
        fig, ax = plt.subplots(figsize=(12, 5.5))
        for idx, arch in enumerate(archs):
            offset = (idx - (len(archs) - 1) / 2) * width
            vals = [norm_by_axis[axis][arch] for axis in axes]
            bars = ax.bar(x + offset, vals, width, label=arch)
            for bar, axis in zip(bars, axes):
                unit = COMMON_COST_UNITS[axis]
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + 0.025,
                    fmt_metric(raw_by_arch[arch][axis], unit, arch, max_horizons),
                    ha="center",
                    va="bottom",
                    rotation=90,
                    fontsize=8,
                )
        ax.set_title(f"H={horizon} Solver Cost Bars")
        ax.set_ylabel("Normalized cost per metric; lower is better")
        ax.set_xticks(x)
        ax.set_xticklabels(axes)
        ax.set_ylim(0, 1.25)
        ax.grid(True, axis="y", alpha=0.3)
        ax.legend()
        fig.tight_layout()
        fig.savefig(out_dir / f"solver_comparison_h{horizon}_bars.png", dpi=180)
        plt.close(fig)

    line_plot("solve_us_cfg_clk", "Solve time at configured clock [us]", "latency_vs_horizon.png")
    line_plot("energy_per_solve_cfg_uj", "Energy per solve [uJ]", "energy_vs_horizon.png")
    line_plot("route_power_total_w", "Post-route report power [W]", "power_vs_horizon.png")
    line_plot("route_wns_ns", "Post-route WNS [ns]", "wns_vs_horizon.png")

    fig, ax = plt.subplots(figsize=(9, 5))
    for arch, arch_rows in sorted(by_arch.items()):
        pts = [row for row in arch_rows if math.isfinite(f(row, "route_bram_tile_used"))]
        if not pts:
            continue
        ax.plot([int(float(row["horizon"])) for row in pts], [f(row, "route_bram_tile_used") for row in pts], marker="o", label=f"{arch} BRAM")
        ax.plot([int(float(row["horizon"])) for row in pts], [f(row, "route_slice_luts_used") for row in pts], marker="s", label=f"{arch} LUT")
        ax.plot([int(float(row["horizon"])) for row in pts], [f(row, "route_lut_as_mem_used") for row in pts], marker="^", label=f"{arch} LUTRAM")
    ax.set_xlabel("Horizon")
    ax.set_ylabel("Used resources")
    ax.grid(True, alpha=0.3)
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_dir / "resources_vs_horizon.png", dpi=180)
    plt.close(fig)

    best_rows = {}
    for arch, arch_rows in by_arch.items():
        passing = [row for row in arch_rows if is_pass(row)]
        if passing:
            best_rows[arch] = max(passing, key=row_horizon)
    if len(best_rows) >= 2:
        axes = ["Max Horizon", "Latency", "Energy", "BRAM Headroom", "LUTRAM Headroom", "Timing Slack"]
        raw = {
            "Max Horizon": {arch: f(row, "horizon") for arch, row in best_rows.items()},
            "Latency": {arch: f(row, "solve_us_cfg_clk") for arch, row in best_rows.items()},
            "Energy": {arch: f(row, "energy_per_solve_cfg_uj") for arch, row in best_rows.items()},
            "BRAM Headroom": {arch: f(row, "route_bram_tile_headroom") for arch, row in best_rows.items()},
            "LUTRAM Headroom": {arch: f(row, "route_lut_as_mem_headroom") for arch, row in best_rows.items()},
            "Timing Slack": {arch: f(row, "route_wns_ns") for arch, row in best_rows.items()},
        }
        radar_plot(
            best_rows,
            axes,
            raw,
            {"Max Horizon", "BRAM Headroom", "LUTRAM Headroom", "Timing Slack"},
            "Solver Max-Capability Radar",
            "solver_radar.png",
        )

    passing_by_horizon_arch: dict[int, dict[str, dict[str, str]]] = {}
    for row in rows:
        if not row.get("arch") or not is_pass(row):
            continue
        horizon = row_horizon(row)
        arch = row["arch"]
        current = passing_by_horizon_arch.setdefault(horizon, {}).get(arch)
        if current is None or better_common_row(row) > better_common_row(current):
            passing_by_horizon_arch[horizon][arch] = row
    for horizon, selected in sorted(passing_by_horizon_arch.items()):
        if len(selected) < 2:
            continue
        common_cost_radar(horizon, selected)
        common_cost_bars(horizon, selected)


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate direct max-horizon benchmark rows.")
    parser.add_argument("--run-dir", required=True, type=Path, help="Directory passed as --out-dir to run_max_horizon_point.py")
    parser.add_argument("--no-plots", action="store_true")
    args = parser.parse_args()

    rows_dir = args.run_dir / "rows"
    rows = load_rows(rows_dir)
    if not rows:
        raise SystemExit(f"No row CSVs found under {rows_dir}")
    max_horizons = load_manual_max_horizons(args.run_dir / "max_horizon_manual.csv")
    write_summary(rows, args.run_dir / "summary.csv")
    print(f"Wrote {args.run_dir / 'summary.csv'}")
    write_common_horizon_table(rows, args.run_dir / "common_horizon_comparison.csv", max_horizons)
    print(f"Wrote {args.run_dir / 'common_horizon_comparison.csv'}")
    if max_horizons is not None:
        write_max_horizon_table(max_horizons, args.run_dir / "max_horizon_by_arch.csv")
        print(f"Wrote {args.run_dir / 'max_horizon_by_arch.csv'}")
    print_maxima(rows)
    if not args.no_plots:
        make_plots(rows, args.run_dir / "plots", max_horizons)
        print(f"Wrote plots under {args.run_dir / 'plots'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
