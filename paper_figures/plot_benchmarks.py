#!/usr/bin/env python3
"""Generate the headline latency, energy, and scalability benchmark plot.

Run from this directory with the project plotting environment:

    source ~/venv/bin/activate
    python plot_benchmarks.py
"""

from __future__ import annotations

import argparse
import csv
import math
import os
from pathlib import Path


LABELS = {
    "full_sparse": "Full-sparse FPGA",
    "staged_a": "Staged FPGA",
    "tinympc_e": "TinyMPC",
}

# Dartmouth's official primary/tertiary palette.
COLORS = {
    "full_sparse": "#267ABA",  # River Blue
    "staged_a": "#00693E",  # Dartmouth Green
    "tinympc_e": "#D94415",  # Tuck Orange
}

ARCH_ORDER = ["staged_a", "full_sparse", "tinympc_e"]

# Points intentionally omitted from the published figure. Keep exclusions here
# rather than editing the source CSV so the presentation choice is reproducible.
# Example: {("staged_a", 704), ("staged_a", 768)}
EXCLUDED_POINTS: set[tuple[str, int]] = {("staged_a", 768),("staged_a", 900), ("staged_a", 1000), ("staged_a", 1100), ("staged_a", 1200), ("staged_a", 1300)}

DEFAULT_TINYMPC_POWER_W = 0.087 * 3.3
ENERGY_AREA_SCALE = 55.0
RADAR_ARCHES = ["staged_a", "full_sparse"]
RADAR_METRIC_UNITS = {
    "Latency": "ms",
    "Energy/solve": "mJ",
    "EDP": "uJ*ms",
    "BRAM": "%",
    "Compute": "%",
    "Scalability": "max H cost",
}


def f(row: dict[str, str], key: str, default: float = math.nan) -> float:
    raw = row.get(key, "")
    if raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as fobj:
        return list(csv.DictReader(fobj))


def best_rows(rows: list[dict[str, str]], compare_iters: int) -> list[dict[str, str]]:
    """Select one timing-clean implementation per architecture and horizon.

    Latency is the primary selection criterion. If implementation variants have
    identical latency, prefer lower reported power and then the stable input
    order. TinyMPC rows are restricted to the requested ADMM iteration count.
    """

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
        if (arch, horizon) in EXCLUDED_POINTS:
            continue
        if arch == "tinympc_e" and int(f(row, "admm_iters", -1)) != compare_iters:
            continue

        key = (arch, horizon)
        candidate = (
            f(row, "solve_us_cfg_clk", math.inf),
            f(row, "route_power_total_w", math.inf),
        )
        current = best.get(key)
        current_score = (
            f(current, "solve_us_cfg_clk", math.inf),
            f(current, "route_power_total_w", math.inf),
        ) if current is not None else (math.inf, math.inf)
        if candidate < current_score:
            best[key] = row

    return sorted(
        best.values(),
        key=lambda row: (ARCH_ORDER.index(row["arch"]) if row["arch"] in ARCH_ORDER else len(ARCH_ORDER),
                         int(f(row, "horizon"))),
    )


def power_w(row: dict[str, str], tinympc_power_w: float) -> float:
    if row["arch"] == "tinympc_e":
        return tinympc_power_w
    return f(row, "route_power_total_w")


def energy_mj(row: dict[str, str], tinympc_power_w: float) -> float:
    """Return energy per solve in mJ.

    FPGA rows carry post-route energy in microjoules. TinyMPC has no energy
    column, so derive it from its measured solve latency and the documented
    MCU active-power estimate. The same derivation is also a safe fallback for
    FPGA rows if an otherwise usable aggregate omits its energy column.
    """

    reported_uj = f(row, "energy_per_solve_cfg_uj")
    if math.isfinite(reported_uj) and reported_uj > 0:
        return reported_uj / 1000.0
    watts = power_w(row, tinympc_power_w)
    solve_us = f(row, "solve_us_cfg_clk")
    return watts * solve_us / 1000.0


def edp_uj_us(row: dict[str, str], tinympc_power_w: float) -> float:
    """Return energy-delay product in uJ*us."""

    return energy_mj(row, tinympc_power_w) * 1000.0 * f(row, "solve_us_cfg_clk")


def normalized_costs(values: dict[str, float]) -> dict[str, float]:
    finite = [value for value in values.values() if math.isfinite(value) and value >= 0]
    if not finite:
        return {key: math.nan for key in values}
    highest = max(finite)
    if highest <= 0:
        return {key: 0.0 if math.isfinite(value) else math.nan for key, value in values.items()}
    return {
        key: value / highest if math.isfinite(value) and value >= 0 else math.nan
        for key, value in values.items()
    }


def format_radar_value(metric: str, value: float, max_horizon: int) -> str:
    if metric == "Scalability":
        return f"H={max_horizon}"
    if not math.isfinite(value):
        return "n/a"
    if metric == "Latency":
        return f"{value:.3f} ms"
    if metric == "Energy/solve":
        return f"{value:.3f} mJ"
    if metric == "EDP":
        return f"{value:.0f} uJ*ms"
    if metric == "Power":
        return f"{value:.3f} W"
    if metric in {"BRAM", "Compute"}:
        return f"{value:.1f}%"
    return f"{value:.3g}"


def _plot_points(ax, rows: list[dict[str, str]], tinympc_power_w: float) -> None:
    """Draw larger bubbles first so smaller overlapping points remain visible."""

    points = sorted(rows, key=lambda row: energy_mj(row, tinympc_power_w), reverse=True)
    for row in points:
        millijoules = energy_mj(row, tinympc_power_w)
        if not math.isfinite(millijoules) or millijoules <= 0:
            continue
        ax.scatter(
            f(row, "horizon"),
            f(row, "solve_us_cfg_clk") / 1000.0,
            s=ENERGY_AREA_SCALE * millijoules,
            color=COLORS.get(row["arch"], "#424141"),
            alpha=0.78,
            edgecolor="white",
            linewidth=1.25,
            zorder=3,
        )


def plot_headline(
    rows: list[dict[str, str]],
    svg_output: Path,
    png_output: Path,
    pdf_output: Path,
    compare_iters: int,
    tinympc_power_w: float,
) -> None:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/latency_benchmark_matplotlib")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FixedLocator, FuncFormatter, NullFormatter

    plt.rcParams.update({
        "font.family": "serif",
        "font.serif": ["Times New Roman", "Times", "DejaVu Serif"],
        "mathtext.fontset": "stix",
        "svg.fonttype": "none",
        "pdf.fonttype": 42,
    })

    if not rows:
        raise ValueError("No timing-clean benchmark rows matched the requested iteration count")

    left_rows = [row for row in rows if f(row, "horizon") <= 100]
    right_rows = [row for row in rows if f(row, "horizon") >= 300]

    fig, (left_ax, right_ax) = plt.subplots(
        1,
        2,
        figsize=(12.2, 4.8),
        sharey=True,
        gridspec_kw={"width_ratios": (1.05, 1.35), "wspace": 0.045},
    )
    fig.patch.set_facecolor("white")

    for ax in (left_ax, right_ax):
        ax.set_yscale("log")
        ax.set_ylim(0.28, 65)
        ax.grid(True, axis="y", which="major", color="#D9D9D9", linewidth=0.9)
        ax.grid(True, axis="y", which="minor", color="#EEEEEE", linewidth=0.55)
        ax.grid(True, axis="x", which="major", color="#EEEEEE", linewidth=0.7)
        ax.tick_params(axis="both", labelsize=10, colors="#333333")
        ax.spines["top"].set_visible(False)
        ax.spines["bottom"].set_color("#333333")
        ax.spines["bottom"].set_linewidth(1.1)

    left_ax.set_xlim(5, 102)
    right_ax.set_xlim(285, 1400)
    left_ax.set_xticks(list(range(10, 101, 10)))
    right_ax.set_xticks([320, 500, 700, 900, 1100, 1350])

    y_ticks = [0.5, 1, 2, 5, 10, 20, 50]
    left_ax.yaxis.set_major_locator(FixedLocator(y_ticks))
    left_ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _pos: f"{value:g}"))
    left_ax.yaxis.set_minor_formatter(NullFormatter())

    left_ax.spines["right"].set_visible(False)
    right_ax.spines["left"].set_visible(False)
    right_ax.spines["right"].set_visible(False)
    right_ax.tick_params(axis="y", which="both", left=False, labelleft=False)

    _plot_points(left_ax, left_rows, tinympc_power_w)
    _plot_points(right_ax, right_rows, tinympc_power_w)

    # Diagonal marks make the discontinuous horizon range explicit.
    break_size = 0.012
    break_style = dict(color="#333333", clip_on=False, linewidth=1.25)
    left_ax.plot((1 - break_size, 1 + break_size), (-break_size, +break_size),
                 transform=left_ax.transAxes, **break_style)
    left_ax.plot((1 - break_size, 1 + break_size), (1 - break_size, 1 + break_size),
                 transform=left_ax.transAxes, **break_style)
    right_ax.plot((-break_size, +break_size), (-break_size, +break_size),
                  transform=right_ax.transAxes, **break_style)
    right_ax.plot((-break_size, +break_size), (1 - break_size, 1 + break_size),
                  transform=right_ax.transAxes, **break_style)

    left_ax.annotate(
        "TinyMPC\n13.6–15.6× slower",
        xy=(80, 42.012),
        xytext=(50, 9),
        color=COLORS["tinympc_e"],
        fontsize=11,
        fontweight="semibold",
        ha="left",
        va="top",
        arrowprops={"arrowstyle": "-", "color": COLORS["tinympc_e"], "lw": 1.2},
        zorder=5,
    )
    left_ax.annotate(
        "Full-sparse FPGA\nFit limit H=90",
        xy=(90, 3.29467),
        xytext=(65, 0.8),
        color=COLORS["full_sparse"],
        fontsize=11,
        fontweight="semibold",
        ha="left",
        va="bottom",
        arrowprops={"arrowstyle": "-", "color": COLORS["full_sparse"], "lw": 1.2},
        zorder=5,
    )
    left_ax.text(
        25,
        0.33,
        "Staged FPGA uses 5.8–6.4× less energy\nthan TinyMPC over H=10–80",
        color=COLORS["staged_a"],
        fontsize=11,
        fontweight="semibold",
        ha="left",
        va="bottom",
        zorder=5,
    )
    right_ax.annotate(
        "Staged FPGA\nworks up to H=1350",
        xy=(1350, 44.85917),
        xytext=(900, 10),
        color=COLORS["staged_a"],
        fontsize=11,
        fontweight="bold",
        ha="left",
        va="top",
        arrowprops={"arrowstyle": "-", "color": COLORS["staged_a"], "lw": 1.3},
        zorder=5,
    )

    legend_energies = [0.25, 2.5, 25.0]
    legend_handles = [
        left_ax.scatter([], [], s=ENERGY_AREA_SCALE * millijoules, color="#707070", alpha=0.35,
                        edgecolor="white", linewidth=2.1)
        for millijoules in legend_energies
    ]
    right_ax.legend(
        legend_handles,
        [f"{millijoules:g} mJ" for millijoules in legend_energies],
        title="Bubble area = energy/solve",
        loc="lower right",
        bbox_to_anchor=(0.985, 0.075),
        frameon=False,
        fontsize=9.5,
        title_fontsize=9.5,
        labelspacing=1.6,
        borderaxespad=0.4,
    )

    left_ax.set_ylabel("Solve latency [ms] (log scale)", fontsize=11.5)
    fig.supxlabel("Prediction horizon H", fontsize=11.5, y=0.075)
    # fig.suptitle(
    #     "Latency, Energy, and Horizon Scalability",
    #     fontsize=16,
    #     fontweight="bold",
    #     y=0.975,
    # )
    # fig.text(
    #     0.5,
    #     0.92,
    #     f"Fixed iteration budget: k={compare_iters}",
    #     ha="center",
    #     va="center",
    #     fontsize=10.5,
    #     color="#555555",
    # )
    # fig.text(
    #     0.5,
    #     0.018,
    #     f"Energy per solve = power × measured latency. FPGA power: post-route estimate; "
    #     f"TinyMPC power: STM32F405 datasheet estimate ({tinympc_power_w:.3f} W).",
    #     ha="center",
    #     va="bottom",
    #     fontsize=8.7,
    #     color="#555555",
    # )
    fig.subplots_adjust(left=0.09, right=0.985, top=0.875, bottom=0.16)

    for output in (svg_output, png_output, pdf_output):
        output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(svg_output, format="svg", bbox_inches="tight")
    fig.savefig(png_output, format="png", dpi=240, bbox_inches="tight")
    fig.savefig(pdf_output, format="pdf", bbox_inches="tight")
    plt.close(fig)


def plot_edp_bars(
    rows: list[dict[str, str]],
    svg_output: Path,
    png_output: Path,
    pdf_output: Path,
    compare_iters: int,
    tinympc_power_w: float,
) -> None:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/latency_benchmark_matplotlib")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import LogFormatterMathtext

    plt.rcParams.update({
        "font.family": "serif",
        "font.serif": ["Times New Roman", "Times", "DejaVu Serif"],
        "mathtext.fontset": "stix",
        "svg.fonttype": "none",
        "pdf.fonttype": 42,
    })

    rows_by_key = {
        (row["arch"], int(f(row, "horizon"))): row
        for row in rows
        if row.get("arch") in ARCH_ORDER and math.isfinite(f(row, "horizon"))
    }
    horizons = [
        horizon
        for horizon in range(10, 81, 10)
        if all((arch, horizon) in rows_by_key for arch in ARCH_ORDER)
    ]
    bar_order = ["tinympc_e", "staged_a", "full_sparse"]
    if not horizons:
        raise ValueError("No horizons have complete EDP rows for all plotted architectures")

    fig, ax = plt.subplots(figsize=(9.2, 4.8))
    fig.patch.set_facecolor("white")

    bar_width = 0.24
    offsets = {
        "tinympc_e": -bar_width,
        "staged_a": 0.0,
        "full_sparse": bar_width,
    }
    x_positions = list(range(len(horizons)))
    edp_by_arch = {
        arch: [edp_uj_us(rows_by_key[(arch, horizon)], tinympc_power_w) for horizon in horizons]
        for arch in ARCH_ORDER
    }

    for arch in bar_order:
        ax.bar(
            [x + offsets[arch] for x in x_positions],
            edp_by_arch[arch],
            width=bar_width,
            color=COLORS[arch],
            alpha=0.78,
            label=LABELS[arch],
            edgecolor="white",
            linewidth=0.8,
            zorder=3,
        )

    ax.set_yscale("log")
    all_edp = [value for values in edp_by_arch.values() for value in values]
    ax.set_ylim(min(all_edp) * 0.55, max(all_edp) * 2.0)
    ax.yaxis.set_major_formatter(LogFormatterMathtext())
    ax.grid(True, axis="y", which="major", color="#D9D9D9", linewidth=0.9)
    ax.grid(True, axis="y", which="minor", color="#EEEEEE", linewidth=0.5)
    ax.grid(True, axis="x", which="major", color="#EEEEEE", linewidth=0.7)
    ax.set_axisbelow(True)
    ax.tick_params(axis="both", labelsize=13, colors="#333333")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#333333")
    ax.spines["bottom"].set_color("#333333")
    ax.spines["bottom"].set_linewidth(1.1)

    ax.set_xticks(x_positions, [str(horizon) for horizon in horizons])
    ax.set_xlabel("Prediction horizon H", fontsize=15)
    ax.set_ylabel(f"EDP at k={compare_iters} [uJ*us] (log scale)", fontsize=15)

    arrow_specs = [
        ("staged_a", COLORS["staged_a"], -0.035, 0.30),
        ("full_sparse", COLORS["full_sparse"], 0.015, 0.48),
    ]
    for idx, _horizon in enumerate(horizons):
        tiny_edp = edp_by_arch["tinympc_e"][idx]
        for arch, arrow_color, x_nudge, label_fraction in arrow_specs:
            target_edp = edp_by_arch[arch][idx]
            target_x = idx + offsets[arch] + x_nudge
            tiny_x = idx + offsets["tinympc_e"] + bar_width / 2.0
            improvement = tiny_edp / target_edp
            label_y = target_edp * (tiny_edp / target_edp) ** label_fraction
            lala = 0.95
            ax.plot(
                [tiny_x, target_x],
                [tiny_edp * lala, tiny_edp * lala],
                color=arrow_color,
                linewidth=1.25,
                linestyle="--",
                zorder=5,
            )
            ax.annotate(
                "",
                xy=(target_x, target_edp * 1.08),
                xytext=(target_x, tiny_edp * lala),
                arrowprops={
                    "arrowstyle": "-|>",
                    "color": arrow_color,
                    "lw": 1.25,
                    "linestyle": "--",
                    "mutation_scale": 11,
                },
                zorder=5,
            )
            ax.text(
                target_x + 0.025,
                label_y,
                f"{improvement:.0f}x",
                color=arrow_color,
                fontsize=8.3,
                fontweight="semibold",
                ha="left",
                va="center",
                zorder=6,
            )

    legend = ax.legend(
        loc="upper left",
        frameon=True,
        fancybox=False,
        edgecolor="#D0D0D0",
        fontsize=10,
    )
    legend.get_frame().set_linewidth(0.8)
    legend.get_frame().set_facecolor("white")

    fig.subplots_adjust(left=0.10, right=0.985, top=0.96, bottom=0.17)

    for output in (svg_output, png_output, pdf_output):
        output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(svg_output, format="svg", bbox_inches="tight")
    fig.savefig(png_output, format="png", dpi=240, bbox_inches="tight")
    fig.savefig(pdf_output, format="pdf", bbox_inches="tight")
    plt.close(fig)


def plot_solver_radar(
    rows: list[dict[str, str]],
    svg_output: Path,
    png_output: Path,
    pdf_output: Path,
    horizon: int,
    tinympc_power_w: float,
) -> None:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/latency_benchmark_matplotlib")
    import matplotlib.pyplot as plt
    import numpy as np

    plt.rcParams.update({
        "font.family": "serif",
        "font.serif": ["Times New Roman", "Times", "DejaVu Serif"],
        "mathtext.fontset": "stix",
        "svg.fonttype": "none",
        "pdf.fonttype": 42,
    })

    rows_by_key = {
        (row["arch"], int(f(row, "horizon"))): row
        for row in rows
        if row.get("arch") in RADAR_ARCHES and math.isfinite(f(row, "horizon"))
    }
    selected = {
        arch: rows_by_key[(arch, horizon)]
        for arch in RADAR_ARCHES
        if (arch, horizon) in rows_by_key
    }
    if len(selected) != len(RADAR_ARCHES):
        missing = sorted(set(RADAR_ARCHES) - set(selected))
        raise ValueError(f"No timing-clean H={horizon} radar rows for: {', '.join(missing)}")

    max_horizons = {
        arch: max(int(f(row, "horizon")) for row in rows if row.get("arch") == arch)
        for arch in RADAR_ARCHES
    }
    best_horizon = max(max_horizons.values())

    raw_by_arch = {}
    for arch, row in selected.items():
        latency_ms = f(row, "solve_us_cfg_clk") / 1000.0
        energy = energy_mj(row, tinympc_power_w)
        raw_by_arch[arch] = {
            "Latency": latency_ms,
            "Energy/solve": energy,
            "EDP": energy * 1000.0 * latency_ms,
            "BRAM": f(row, "route_bram_tile_util_pct"),
            "Compute": f(row, "route_slice_luts_util_pct") + f(row, "route_slice_registers_util_pct"),
            "Scalability": best_horizon / max_horizons[arch],
        }

    metrics = list(RADAR_METRIC_UNITS)
    norm_by_metric = {
        metric: normalized_costs({arch: raw_by_arch[arch][metric] for arch in RADAR_ARCHES})
        for metric in metrics
    }

    angles = np.linspace(0, 2 * np.pi, len(metrics), endpoint=False).tolist()
    angles += angles[:1]

    fig = plt.figure(figsize=(5.8, 5.8))
    fig.patch.set_facecolor("white")
    ax = fig.add_subplot(111, polar=True)
    ax.set_theta_offset(np.pi / 2)
    ax.set_theta_direction(-1)

    for arch_idx, arch in enumerate(RADAR_ARCHES):
        values = [norm_by_metric[metric][arch] for metric in metrics]
        values += values[:1]
        ax.plot(
            angles,
            values,
            color=COLORS[arch],
            alpha=0.78,
            linewidth=2.1,
            marker="o",
            markersize=4.8,
            label=LABELS[arch],
            zorder=3,
        )
        ax.fill(angles, values, color=COLORS[arch], alpha=0.13, zorder=2)
        for metric_idx, metric in enumerate(metrics):
            radius = values[metric_idx]
            if not math.isfinite(radius):
                continue
            label_overrides = {
                ("Latency", "staged_a"): (0.060, 0.85),
                ("Latency", "full_sparse"): (0.00, 1.05),
                ("Energy/solve", "staged_a"): (-0.030, 0.82),
                ("Energy/solve", "full_sparse"): (-0.1, 0.55),
                ("EDP", "staged_a"): (0.1, 0.965),
                ("EDP", "full_sparse"): (-0.07, 0.53),
                ("BRAM", "staged_a"): (-0.0, 0.53),
                ("BRAM", "full_sparse"): (0.00, 1.06),
                ("Compute", "staged_a"): (-0.020, 0.82),
                ("Compute", "full_sparse"): (0.17, 0.47),
                ("Scalability", "staged_a"): (0.030, 0.18),
                ("Scalability", "full_sparse"): (0.030, 0.84),
            }
            default_radius = min(0.98, max(0.10, radius + 0.075 + 0.035 * arch_idx))
            theta_offset, label_radius = label_overrides.get(
                (metric, arch),
                ((arch_idx - 0.5) * 0.035, default_radius),
            )
            ax.text(
                angles[metric_idx] + theta_offset,
                label_radius,
                format_radar_value(metric, raw_by_arch[arch][metric], max_horizons[arch]),
                color=COLORS[arch],
                fontsize=7.2,
                fontweight="semibold",
                ha="center",
                va="center",
                clip_on=False,
                bbox={"boxstyle": "round,pad=0.14", "fc": "white", "ec": "none", "alpha": 0.72},
                zorder=4,
            )

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels([])
    label_distances = {
        "Latency": 1.25,
        "Energy/solve": 1.48,
        "EDP": 1.3,
        "BRAM": 1.28,
        "Compute": 1.4,
        "Scalability": 1.4,
    }
    for angle, metric in zip(angles[:-1], metrics):
        ax.text(
            angle,
            label_distances[metric],
            metric,
            fontsize=12.5,
            ha="center",
            va="center",
            color="#333333",
            clip_on=False,
        )
    ax.set_ylim(0, 1.16)
    ax.set_yticks([0.25, 0.5, 0.75, 1.0])
    ax.set_yticklabels([])
    ax.tick_params(axis="x", pad=0, colors="#333333")
    ax.spines["polar"].set_color("#333333")
    ax.spines["polar"].set_linewidth(1.1)
    ax.grid(True, color="#D9D9D9", linewidth=0.9)
    ax.legend(
        loc="lower center",
        bbox_to_anchor=(0.5, -0.20),
        ncol=2,
        frameon=False,
        fontsize=11,
    )
    fig.subplots_adjust(left=0.10, right=0.90, top=0.96, bottom=0.20)

    for output in (svg_output, png_output, pdf_output):
        output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(svg_output, format="svg", bbox_inches="tight")
    fig.savefig(png_output, format="png", dpi=240, bbox_inches="tight")
    fig.savefig(pdf_output, format="pdf", bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("benchmark_summary.csv"))
    parser.add_argument("--compare-iters", type=int, default=10)
    parser.add_argument(
        "--tinympc-power-w",
        type=float,
        default=DEFAULT_TINYMPC_POWER_W,
        help="TinyMPC active power estimate used for bubble area (default: 87 mA at 3.3 V)",
    )
    parser.add_argument("--svg-output", type=Path, default=Path("benchmark_latency_energy.svg"))
    parser.add_argument("--png-output", type=Path, default=Path("benchmark_latency_energy.png"))
    parser.add_argument("--pdf-output", type=Path, default=Path("benchmark_latency_energy.pdf"))
    parser.add_argument("--edp-svg-output", type=Path, default=Path("benchmark_edp_bars.svg"))
    parser.add_argument("--edp-png-output", type=Path, default=Path("benchmark_edp_bars.png"))
    parser.add_argument("--edp-pdf-output", type=Path, default=Path("benchmark_edp_bars.pdf"))
    parser.add_argument("--radar-horizon", type=int, default=40)
    parser.add_argument("--radar-svg-output", type=Path, default=Path("benchmark_solver_radar.svg"))
    parser.add_argument("--radar-png-output", type=Path, default=Path("benchmark_solver_radar.png"))
    parser.add_argument("--radar-pdf-output", type=Path, default=Path("benchmark_solver_radar.pdf"))
    args = parser.parse_args()

    if not math.isfinite(args.tinympc_power_w) or args.tinympc_power_w <= 0:
        parser.error("--tinympc-power-w must be a positive finite value")

    rows = load_rows(args.input)
    selected = best_rows(rows, args.compare_iters)
    plot_headline(
        selected,
        args.svg_output,
        args.png_output,
        args.pdf_output,
        args.compare_iters,
        args.tinympc_power_w,
    )
    plot_edp_bars(
        selected,
        args.edp_svg_output,
        args.edp_png_output,
        args.edp_pdf_output,
        args.compare_iters,
        args.tinympc_power_w,
    )
    plot_solver_radar(
        selected,
        args.radar_svg_output,
        args.radar_png_output,
        args.radar_pdf_output,
        args.radar_horizon,
        args.tinympc_power_w,
    )
    print(
        f"Wrote {args.svg_output}, {args.png_output}, {args.pdf_output}, "
        f"{args.edp_svg_output}, {args.edp_png_output}, {args.edp_pdf_output}, "
        f"{args.radar_svg_output}, {args.radar_png_output}, and {args.radar_pdf_output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
