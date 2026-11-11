#!/usr/bin/env python3
"""Generate the headline latency, energy, and scalability benchmark plot.

Run from the repository root:

    python evaluation/plot_benchmarks.py
"""

from __future__ import annotations

import argparse
import csv
import math
import os
from pathlib import Path
from typing import Any

import numpy as np


LABELS = {
    "full_sparse": "AccelMPC full-sparse",
    "staged_a": "Staged FPGA",
    "tinympc_e": "TinyMPC (MCU)",
    "tinympc_fpga_float": "Wu et al. FPGA",
    "staged_fused": "AccelMPC staged",
    "mobydic_small": "MOBY-DIC2*",
}

# University's official primary/tertiary palette.
COLORS = {
    "full_sparse": "#267ABA",  # River Blue
    "staged_fused": "#00693E",
    "mobydic_small": "#777777",
    "staged_a": "#00693E",  # University Green
    "tinympc_fpga_float": "#8067A8",
    "tinympc_e": "#D94415",  # Tuck Orange
}

ARCH_ORDER = ["staged_fused", "full_sparse", "tinympc_e", "tinympc_fpga_float", "mobydic_small"]

# Use a consistent selection of synthesis-derived timing and resource results.
# Publication CSV already excludes invalid configurations.
EXCLUDED_POINTS: set[tuple[str, int]] = set()

DEFAULT_TINYMPC_POWER_W = 0.087 * 3.3
ENERGY_AREA_SCALE = 55.0
RADAR_ARCHES = ["staged_fused", "full_sparse"]
RADAR_METRIC_UNITS = {
    "Latency": "ms",
    "Energy/solve": "mJ",
    "EDP": "uJ*ms",
    "BRAM": "%",
    "Logic": "%",
    "Scalability": "max H cost",
}

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
OUTPUT_DIR = HERE / "output"

BENCHMARK_SUMMARY_CSV = DATA_DIR / "benchmarks.csv"

FIGURE8_REFERENCE_CSV = DATA_DIR / "figure8_ref_trajectory.csv"
FIGURE8_FPGA_CSV = DATA_DIR / "figure8_fpga_trajectory.csv"
FIGURE8_TINYMPC_CSV = DATA_DIR / "figure8_tinympc_trajectory.csv"

FIGURE8_X_LIMITS = (-0.65, 0.65)
FIGURE8_Y_LIMITS = (-0.65, 0.65)
FIGURE8_FPGA_ROW_RANGE = (500, 1300)
FIGURE8_TINYMPC_ROW_RANGE = (350, 1070)
FIGURE8_FPGA_ALIGNMENT = (0.757180, -0.383558, 0.598284, -0.289005)
FIGURE8_TINYMPC_ALIGNMENT = (0.971674, -0.439716, 0.580961, -0.313049)

FEASIBILITY_HORIZONS = (5, 10, 40, 100, 200, 300, 400, 500, 600, 800)
FEASIBILITY_SOLVERS = (
    ("tinympc_e", "TinyMPC (MCU)"),
    ("tinympc_fpga_float", "Wu et al. FPGA"),
    ("full_sparse", r"\texttt{full\_sparse}"),
    ("staged_fused", r"\texttt{staged}"),
)
FEASIBILITY_MANUAL_ITERATIONS = {
    ("tinympc_e", 5): 4,
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


def parse_horizon_list(raw: str) -> tuple[int, ...]:
    horizons = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        horizon = int(token)
        if horizon <= 0:
            raise ValueError("feasibility horizons must be positive")
        horizons.append(horizon)
    if not horizons:
        raise ValueError("at least one feasibility horizon is required")
    return tuple(horizons)


def row_has_valid_feasibility_timing(row: dict[str, str]) -> bool:
    if row.get("timing_clean") != "1":
        return False
    per_iter_us = f(row, "solve_us_per_iter_cfg_clk")
    if not math.isfinite(per_iter_us) or per_iter_us <= 0:
        return False

    arch = row.get("arch")
    if arch in {"staged_fused", "staged_a", "full_sparse", "tinympc_fpga_float"}:
        return row.get("status") == "pass"
    if arch == "tinympc_e":
        return row.get("status") == "benchmark"
    return False


def feasible_iteration_table(
    rows: list[dict[str, str]],
    horizons: tuple[int, ...],
    control_period_us: float,
    fpga_spi_overhead_us: float,
) -> dict[str, dict[int, int | None]]:
    table: dict[str, dict[int, int | None]] = {
        arch: {horizon: None for horizon in horizons}
        for arch, _label in FEASIBILITY_SOLVERS
    }
    rows_by_key: dict[tuple[str, int], list[dict[str, str]]] = {}

    for row in rows:
        if not row_has_valid_feasibility_timing(row):
            continue
        arch = row.get("arch", "")
        horizon = int(f(row, "horizon", -1))
        if horizon in horizons:
            rows_by_key.setdefault((arch, horizon), []).append(row)

    for arch, _label in FEASIBILITY_SOLVERS:
        budget_us = control_period_us
        if arch in {"staged_fused", "staged_a", "full_sparse", "tinympc_fpga_float"}:
            budget_us -= fpga_spi_overhead_us
        if budget_us <= 0:
            continue

        for horizon in horizons:
            manual_value = FEASIBILITY_MANUAL_ITERATIONS.get((arch, horizon))
            if manual_value is not None:
                table[arch][horizon] = manual_value
                continue
            candidates = rows_by_key.get((arch, horizon), [])
            if not candidates:
                continue
            best_per_iter_us = min(f(row, "solve_us_per_iter_cfg_clk") for row in candidates)
            max_iters = math.floor(budget_us / best_per_iter_us)
            if max_iters >= 0:
                table[arch][horizon] = max_iters

    return table


def format_feasibility_cell(value: int | None, best_value: int | None) -> str:
    if value is None:
        return "--"
    if best_value is not None and value > 0 and value == best_value:
        return rf"\textbf{{{value}}}"
    return str(value)


def write_feasibility_table(
    rows: list[dict[str, str]],
    output: Path,
    horizons: tuple[int, ...],
    control_period_us: float,
    fpga_spi_overhead_us: float,
) -> None:
    table = feasible_iteration_table(rows, horizons, control_period_us, fpga_spi_overhead_us)
    best_by_horizon: dict[int, int | None] = {}
    for horizon in horizons:
        values = [
            by_horizon[horizon]
            for by_horizon in table.values()
            if by_horizon[horizon] is not None
        ]
        best_by_horizon[horizon] = max(values) if values else None

    col_spec = "l" + ("c" * len(horizons))
    cmidrule_end = len(horizons) + 1
    control_rate_khz = 1000.0 / control_period_us
    lines = [
        rf"\begin{{tabular}}{{{col_spec}}}",
        r"\toprule",
        rf"& \multicolumn{{{len(horizons)}}}{{c}}{{Prediction Horizon $H$}} \\",
        rf"\cmidrule(lr){{2-{cmidrule_end}}}",
        "Solver & " + " & ".join(str(horizon) for horizon in horizons) + r" \\",
        r"\midrule",
    ]

    for arch, label in FEASIBILITY_SOLVERS:
        cells = [
            format_feasibility_cell(table[arch][horizon], best_by_horizon[horizon])
            for horizon in horizons
        ]
        lines.append(label + " & " + " & ".join(cells) + r" \\")

    lines.extend([
        r"\bottomrule",
        r"\end{tabular}",
        "",
    ])

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines))


def load_figure8_hw_log(path: Path) -> dict[str, Any]:
    rows = load_rows(path)
    if not rows:
        return {"name": path.stem, "path": path, "n": 0, "t": np.array([], dtype=np.float64), "data": {}}

    t_ms = np.array([f(row, "time_ms") for row in rows], dtype=np.float64)
    data = {
        "x": np.array([f(row, "state_x") for row in rows], dtype=np.float64),
        "y": np.array([f(row, "state_y") for row in rows], dtype=np.float64),
        "z": np.array([f(row, "state_z") for row in rows], dtype=np.float64),
    }
    return {
        "name": path.stem,
        "path": path,
        "n": len(rows),
        "t": (t_ms - t_ms[0]) / 1000.0,
        "data": data,
    }


def load_figure8_reference(path: Path) -> dict[str, Any]:
    rows = load_rows(path)
    if not rows:
        return {"name": path.stem, "path": path, "n": 0, "t": np.array([], dtype=np.float64), "data": {}}

    data = {
        "x": np.array([f(row, "x0") for row in rows], dtype=np.float64),
        "y": np.array([f(row, "x1") for row in rows], dtype=np.float64),
        "z": np.array([f(row, "x2") for row in rows], dtype=np.float64),
    }
    return {
        "name": path.stem,
        "path": path,
        "n": len(rows),
        "t": np.array([f(row, "t") for row in rows], dtype=np.float64),
        "data": data,
    }


def apply_figure8_alignment(ds: dict[str, Any], alignment: tuple[float, float, float, float]) -> dict[str, Any]:
    lag_s, dx, dy, dz = alignment
    data = {key: np.array(value, copy=True) for key, value in ds["data"].items()}
    for key, offset in (("x", dx), ("y", dy), ("z", dz)):
        if key in data:
            data[key] = data[key] + offset
    return {
        "name": ds["name"],
        "path": ds["path"],
        "n": ds["n"],
        "t": ds["t"] + lag_s,
        "data": data,
    }


def slice_figure8_dataset(ds: dict[str, Any], row_range: tuple[int | None, int | None]) -> dict[str, Any]:
    if ds["n"] < 1:
        return ds
    row_start, row_end = row_range
    sliced_t = ds["t"][row_start:row_end]
    if sliced_t.size == 0:
        return ds
    return {
        "name": ds["name"],
        "path": ds["path"],
        "n": int(sliced_t.size),
        "t": sliced_t - sliced_t[0],
        "data": {key: value[row_start:row_end] for key, value in ds["data"].items()},
    }


def best_rows(rows: list[dict[str, str]], compare_iters: int) -> list[dict[str, str]]:
    """Select one timing-clean implementation per architecture and horizon.

    Latency is the primary selection criterion. If implementation variants have
    identical latency, prefer lower reported power and then the stable input
    order. All rows are restricted to the requested ADMM iteration count.
    """

    best: dict[tuple[str, int], dict[str, str]] = {}
    for row in rows:
        if row.get("timing_clean") != "1":
            continue
        arch = row.get("arch", "")
        if arch not in ARCH_ORDER:
            continue
        horizon = int(f(row, "horizon", -1))
        if horizon < 0:
            continue
        if (arch, horizon) in EXCLUDED_POINTS:
            continue
        if int(f(row, "admm_iters", -1)) != compare_iters:
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


def comparison_latency_us(row):
    if row["arch"] in ("tinympc_e", "tinympc_fpga_float"):
        return f(row, "solve_us_cfg_clk")
    return f(row, "measured_latency_us", f(row, "solve_us_cfg_clk"))


def power_w(row: dict[str, str], tinympc_power_w: float) -> float:
    return tinympc_power_w if row["arch"] == "tinympc_e" else f(row, "measured_power_w")


def energy_mj(row: dict[str, str], tinympc_power_w: float) -> float:
    """Publication energy, with the source carried explicitly in each CSV row."""
    if row["arch"] == "tinympc_e":
        return tinympc_power_w * comparison_latency_us(row) / 1000
    if math.isfinite(f(row, "measured_energy_uj")):
        return f(row, "measured_energy_uj") / 1000
    return f(row, "energy_per_solve_cfg_uj") / 1000


def edp_uj_us(row: dict[str, str], tinympc_power_w: float) -> float:
    return energy_mj(row, tinympc_power_w) * 1000 * comparison_latency_us(row)


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
        return "TBD" if max_horizon is None else f"H={max_horizon}"
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
    if metric in {"BRAM", "Logic"}:
        return f"{value:.1f}%"
    return f"{value:.3g}"


def _plot_points(ax, rows: list[dict[str, str]], tinympc_power_w: float) -> None:
    """Draw larger bubbles first so smaller overlapping points remain visible."""

    def bubble_energy(row):
        measured = energy_mj(row, tinympc_power_w)
        return measured if math.isfinite(measured) else f(row, "energy_per_solve_cfg_uj") / 1000

    points = sorted(rows, key=bubble_energy, reverse=True)
    for row in points:
        millijoules = bubble_energy(row)
        if not math.isfinite(millijoules) or millijoules <= 0:
            continue
        estimated = row.get("energy_source") == "post_route_estimate"
        latency = comparison_latency_us(row) / 1000
        ax.scatter(
            f(row, "horizon"),
            latency,
            s=ENERGY_AREA_SCALE * millijoules,
            color=COLORS.get(row["arch"], "#424141"),
            alpha=0.78,
            edgecolor="white",
            linewidth=0.35,
            zorder=3,
        )
        if estimated:
            # A centered marker avoids the font baseline offset of a text asterisk.
            ax.scatter(f(row, "horizon"), latency, marker=r"$\ast$", s=45,
                       color="#333333", linewidths=0, zorder=4)


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
    # Thin only the display; keep every valid row for comparisons and statistics.
    right_rows = []
    for arch in ARCH_ORDER:
        candidates = sorted((r for r in rows if r["arch"] == arch and f(r,"horizon") >= 110),
                            key=lambda r: f(r,"horizon"))
        picked = []
        for row in candidates:
            if not picked or f(row,"horizon") - f(picked[-1],"horizon") >= 180:
                picked.append(row)
        if candidates and picked[-1] is not candidates[-1]:
            if len(picked) > 1 and f(candidates[-1],"horizon") - f(picked[-1],"horizon") < 140:
                picked[-1] = candidates[-1]
            else:
                picked.append(candidates[-1])
        # Align staged with Wu's largest shared horizon rather than thinning
        # their nearby endpoints independently (e.g. H1000 versus H1023).
        if arch == "staged_fused":
            wu_horizons = {f(r, "horizon") for r in rows if r["arch"] == "tinympc_fpga_float"}
            shared = [r for r in candidates if f(r, "horizon") in wu_horizons]
            if shared:
                endpoint = shared[-1]
                nearby = [i for i, r in enumerate(picked)
                          if abs(f(r, "horizon") - f(endpoint, "horizon")) < 140]
                if nearby:
                    closest = min(nearby, key=lambda i: abs(f(picked[i], "horizon") - f(endpoint, "horizon")))
                    picked[closest] = endpoint
                else:
                    picked.append(endpoint)
                picked.sort(key=lambda r: f(r, "horizon"))
        right_rows.extend(r for r in picked
                          if not (r["arch"] == "full_sparse" and f(r, "horizon") in (120, 400)))

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
        ax.set_ylim(0.07, 110)
        ax.grid(True, axis="y", which="major", color="#D9D9D9", linewidth=0.9)
        ax.grid(True, axis="y", which="minor", color="#EEEEEE", linewidth=0.55)
        ax.grid(True, axis="x", which="major", color="#EEEEEE", linewidth=0.7)
        ax.tick_params(axis="both", labelsize=10, colors="#333333")
        ax.spines["top"].set_visible(False)
        ax.spines["bottom"].set_color("#333333")
        ax.spines["bottom"].set_linewidth(1.1)

    left_ax.set_xlim(2, 102)
    right_ax.set_xlim(110, 1880)
    left_ax.set_xticks(list(range(10, 101, 10)))
    right_ax.set_xticks([120, 400, 800, 1200, 1500, 1800])

    y_ticks = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50]
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

    # Direct callouts retain the original plot's explanation of each mapping.
    by_arch = {arch: {int(f(r, "horizon")): r for r in rows if r["arch"] == arch}
               for arch in ARCH_ORDER}
    staged = by_arch["staged_fused"]

    def callout(ax, arch, horizon, label, position):
        row = by_arch[arch][horizon]
        ax.annotate(label, xy=(horizon, f(row, "solve_us_cfg_clk") / 1000),
                    xytext=position, color=COLORS[arch], fontsize=10,
                    fontweight="semibold", ha="left", va="top",
                    arrowprops={"arrowstyle": "-", "color": COLORS[arch], "lw": 1.2},
                    bbox={"fc": "white", "ec": "none", "alpha": 0.85, "pad": 1.5},
                    zorder=5)

    common = sorted(staged.keys() & by_arch["tinympc_e"].keys())
    speedups = [f(by_arch["tinympc_e"][h], "solve_us_cfg_clk") /
                f(staged[h], "solve_us_cfg_clk") for h in common]
    callout(left_ax, "tinympc_e", max(common),
            f"TinyMPC MCU: {min(speedups):.1f}–{max(speedups):.1f}× slower\nthan AccelMPC staged", (36, 95))
    # Magnify the short-horizon FPGA region; preserve energy ratios within inset.
    zoom = left_ax.inset_axes([0.35, 0.065, 0.60, 0.27])
    zoom.set_facecolor("white")
    zoom.set_yscale("log")
    zoom.set_xlim(3, 22)
    zoom.set_ylim(0.07, 4.5)
    zoom.set_xticks([5, 10, 20])
    zoom.set_yticks([0.1, 0.3, 1.0])
    zoom.yaxis.set_major_formatter(FuncFormatter(lambda value, _pos: f"{value:g}"))
    zoom.yaxis.set_minor_formatter(NullFormatter())
    zoom.tick_params(labelsize=8, pad=1)
    zoom.grid(True, which="major", color="#E5E5E5", linewidth=.6)
    zoom_rows = [r for r in rows if r["arch"] in
                 ("staged_fused", "full_sparse", "tinympc_fpga_float") and f(r, "horizon") <= 20]
    for row in sorted(zoom_rows, key=lambda r: energy_mj(r, tinympc_power_w), reverse=True):
        zoom.scatter(f(row, "horizon"), comparison_latency_us(row) / 1000,
                     s=9 * ENERGY_AREA_SCALE * energy_mj(row, tinympc_power_w),
                     color=COLORS[row["arch"]], alpha=.78,
                     edgecolor="white", linewidth=.35, zorder=3)
    zoom.text(.03, .97, "FPGA close-up\nBubble areas ×9", transform=zoom.transAxes,
              ha="left", va="top", fontsize=9, color="#555555")
    right_ax.text(.05, .20,
                 "AccelMPC staged: lowest latency,\nlowest energy per solve,\nlargest supported horizon",
                 transform=right_ax.transAxes, ha="left", va="center",
                 fontsize=10, color=COLORS["staged_fused"], fontweight="semibold",
                 bbox={"fc": "white", "ec": "none", "alpha": .85, "pad": 1.5},
                 zorder=6)
    zoom.set_xlabel("H", fontsize=8, labelpad=-4)
    zoom.set_ylabel("ms", fontsize=8, labelpad=1)
    # Link the actual data region (excluding inset caption headroom) to the zoom.
    from matplotlib.patches import Rectangle, ConnectionPatch
    zoom_region = (3, 0.07, 19, 1.23)
    left_ax.add_patch(Rectangle(zoom_region[:2], zoom_region[2], zoom_region[3],
                                fill=False, edgecolor="#999999", linewidth=.7, zorder=2))
    for source, destination in [((22, 1.3), (0, 1)), ((22, 0.07), (0, 0))]:
        connector = ConnectionPatch(xyA=source, coordsA=left_ax.transData,
                                    xyB=destination, coordsB=zoom.transAxes,
                                    color="#AAAAAA", linewidth=.65, zorder=2)
        left_ax.add_artist(connector)

    right_ax.annotate(
        "AccelMPC full-sparse\nLower compute resources\nWorks up to H=100\nwithout BRAM spillover",
        xy=(100, f(by_arch["full_sparse"][100], "solve_us_cfg_clk") / 1000),
        xycoords=left_ax.transData, xytext=(160, 85), textcoords=right_ax.transData,
        color=COLORS["full_sparse"], fontsize=10, fontweight="semibold",
        ha="left", va="top",
        arrowprops={"arrowstyle": "-", "color": COLORS["full_sparse"], "lw": 1.2},
        bbox={"fc": "white", "ec": "none", "alpha": .85, "pad": 1.5},
        annotation_clip=False, zorder=5,
    )
    staged_h = max(staged)
    callout(right_ax, "staged_fused", staged_h,
            f"AccelMPC staged\nWorks up to H={staged_h}", (1300, 90))
    common_wu = sorted(staged.keys() & by_arch["tinympc_fpga_float"].keys())
    wu_speedups = [f(by_arch["tinympc_fpga_float"][h], "solve_us_cfg_clk") /
                   f(staged[h], "solve_us_cfg_clk") for h in common_wu]
    callout(right_ax, "tinympc_fpga_float", max(common_wu),
            f"Wu et al. FPGA: {min(wu_speedups):.2f}–{max(wu_speedups):.2f}× slower\nthan AccelMPC staged",
            (300, 2.2))
    if by_arch["mobydic_small"]:
        callout(left_ax, "mobydic_small", min(by_arch["mobydic_small"]),
                "MOBY-DIC FPGA", (8, 42))

    from matplotlib.lines import Line2D
    fig.legend(handles=[Line2D([], [], marker="o", linestyle="", color=COLORS[a], label=LABELS[a].rstrip("*") if a == "mobydic_small" else LABELS[a])
                        for a in ARCH_ORDER], loc="upper center", ncol=5, frameon=False, fontsize=10)
    legend_energies = [0.25, 2.5, 25.0]
    legend_handles = [
        left_ax.scatter([], [], s=ENERGY_AREA_SCALE * millijoules, color="#707070", alpha=0.35,
                        edgecolor="white", linewidth=2.1)
        for millijoules in legend_energies
    ]
    right_ax.legend(
        legend_handles,
        [f"{millijoules:g} mJ" for millijoules in legend_energies],
        title="Bubble area = energy/solve\n* FPGA energy estimate",
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
    fig.subplots_adjust(left=0.09, right=0.985, top=0.925, bottom=0.16)

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
        for horizon in [5, *range(10, 81, 10)]
        if any((arch, horizon) in rows_by_key and
               math.isfinite(edp_uj_us(rows_by_key[(arch, horizon)], tinympc_power_w))
               for arch in RADAR_ARCHES)
    ]
    bar_order = ["tinympc_e", "tinympc_fpga_float", "staged_fused"]
    if not horizons:
        raise ValueError("No horizons have measured FPGA EDP and a TinyMPC baseline")

    fig, ax = plt.subplots(figsize=(9.2, 4.8))
    fig.patch.set_facecolor("white")
    non_axis_fontsize = 10
    improvement_label_fontsize = 13

    bar_width = 0.16
    offsets = {arch: (i - (len(bar_order)-1)/2) * bar_width for i, arch in enumerate(bar_order)}
    x_positions = list(range(len(horizons)))
    edp_by_arch = {
        arch: [edp_uj_us(rows_by_key[(arch, horizon)], tinympc_power_w)
               if (arch, horizon) in rows_by_key else math.nan for horizon in horizons]
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
            hatch=None,
            edgecolor="white",
            linewidth=0.8,
            zorder=3,
        )

    # MOBY-DIC is available only at H5; do not reserve empty bars elsewhere.
    if 5 in horizons and ("mobydic_small", 5) in rows_by_key:
        idx = horizons.index(5)
        mobydic = rows_by_key[("mobydic_small", 5)]
        mobydic_x = idx + offsets["tinympc_e"] - bar_width
        mobydic_edp = edp_uj_us(mobydic, tinympc_power_w)
        ax.bar(mobydic_x, mobydic_edp, width=bar_width,
               color=COLORS["mobydic_small"], alpha=.78,
               label=LABELS["mobydic_small"].rstrip("*"), edgecolor="white", linewidth=.8, zorder=3)

    for arch in bar_order:
        for idx,h in enumerate(horizons):
            row=rows_by_key.get((arch,h))
            if row and row.get("energy_source") == "post_route_estimate":
                ax.text(idx+offsets[arch], edp_by_arch[arch][idx]*1.1,"*",ha="center",fontsize=9)
    ax.set_yscale("log")
    all_edp = [value for values in edp_by_arch.values() for value in values if math.isfinite(value)]
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

    for idx, horizon in enumerate(horizons):
        for arch in bar_order:
            if not math.isfinite(edp_by_arch[arch][idx]):
                ax.text(idx + offsets[arch], min(all_edp) * .65, "n/a",
                        ha="center", color=COLORS[arch], fontsize=8, rotation=90)
    # Restore dashed comparison arrows and boxed improvement labels.
    for idx, horizon in enumerate(horizons):
        target = edp_by_arch["staged_fused"][idx]
        target_x = idx + offsets["staged_fused"]
        for baseline, color, label_scale in [("tinympc_e", COLORS["tinympc_e"], 0.5),
                                              ("tinympc_fpga_float", COLORS["tinympc_fpga_float"], 0.5)]:
            base = edp_by_arch[baseline][idx]
            top, bottom = base * .95, target * 1.08
            x = target_x + bar_width * .30 if baseline == "tinympc_e" else target_x
            ax.plot([idx+offsets[baseline]+bar_width/2, x], [top,top],
                    color=color, linewidth=1.25, linestyle="--", zorder=5)
            ax.annotate("",xy=(x,bottom),xytext=(x,top),
                        arrowprops={"arrowstyle":"-|>","color":color,"lw":1.25,
                                    "linestyle":"--","mutation_scale":11},zorder=5)
            ratio = base/target
            label = f"{ratio:.0f}×" if baseline == "tinympc_e" else f"{ratio:.2f}×"
            ax.annotate(label, xy=(x, bottom*(top/bottom)**label_scale),
                        xytext=(-9, 0) if baseline == "tinympc_fpga_float" else (0, 0),
                        textcoords="offset points",color=color,
                        fontsize=11,fontweight="semibold",
                        ha="right" if baseline == "tinympc_fpga_float" else "center",va="center",
                        bbox={"boxstyle":"round,pad=0.14","fc":"white","ec":color,
                              "alpha":.9,"linewidth":.55},zorder=6)
    fig.text(0.5, 0.025, "Arrows: EDP reduction to AccelMPC staged. MCU energy uses nominal active power.",
             ha="center", fontsize=10)

    legend = ax.legend(
        loc="lower center", bbox_to_anchor=(0.5, 1.005),
        frameon=False,
        fancybox=False,
        edgecolor="#D0D0D0",
        fontsize=11, ncol=4,
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
        arch: (None if selected[arch].get("max_horizon_status") == "TBD" else
               max(int(f(row,"horizon")) for row in rows if row["arch"] == arch))
        for arch in RADAR_ARCHES
    }
    best_horizon = max(h for h in max_horizons.values() if h is not None)

    raw_by_arch = {}
    for arch, row in selected.items():
        # Match the EDP comparison: measured latency and core/BRAM energy,
        # plus auxiliary/I/O estimates stored in the consolidated CSV.
        latency_ms = comparison_latency_us(row) / 1000.0
        energy = energy_mj(row, tinympc_power_w)
        if not all(math.isfinite(value) and value > 0 for value in (latency_ms, energy)):
            raise ValueError(f"Missing measured radar latency/energy for {arch}, H={horizon}")
        if not all(math.isfinite(f(row,k)) and f(row,k) > 0
                   for k in ("solver_luts_used", "solver_bram_tiles_used")):
            raise ValueError(f"Missing matched solver/SPI resources for {arch}")
        raw_by_arch[arch] = {
            "Latency": latency_ms,
            "Energy/solve": energy,
            "EDP": energy * 1000.0 * latency_ms,
            "BRAM": f(row,"solver_bram_tiles_used") / 135 * 100,
            "Logic": f(row,"solver_luts_used") / 63400 * 100,
            "Scalability": best_horizon / max_horizons[arch] if max_horizons[arch] else math.nan,
        }

    metrics = list(RADAR_METRIC_UNITS)
    norm_by_metric = {
        metric: normalized_costs({arch: raw_by_arch[arch][metric] for arch in RADAR_ARCHES})
        for metric in metrics
    }

    # Compress the BRAM spoke equally for both mappings; retain actual percentages.
    for arch in RADAR_ARCHES:
        norm_by_metric["BRAM"][arch] *= 0.8

    angles = np.linspace(0, 2 * np.pi, len(metrics), endpoint=False).tolist()
    angles += angles[:1]

    fig = plt.figure(figsize=(5.8, 5.8))
    fig.patch.set_facecolor("white")
    ax = fig.add_subplot(111, polar=True)
    ax.set_theta_offset(np.pi / 2)
    ax.set_theta_direction(-1)
    radar_label_fontsize = 12.5

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
        # Leave the unknown horizon open instead of inventing a radius.
        if all(max_horizons[a] is not None for a in RADAR_ARCHES):
            ax.fill(angles, values, color=COLORS[arch], alpha=0.13, zorder=2)
    # Anchor labels to the actual data points; offsets are in display points.
    # Separate the nearly coincident BRAM labels to either side of the spoke.
    label_offsets = {
        "Latency": [(0, 9), (0, 9)],
        "Energy/solve": [(8, 5), (8, 5)],
        "EDP": [(7, -9), (7, -9)],
        "BRAM": [(9, -7), (-9, 7)],
        "Logic": [(-8, -5), (-8, -5)],
        "Scalability": [(-8, 6), (-8, 6)],
    }
    for i, metric in enumerate(metrics):
        for j, arch in enumerate(RADAR_ARCHES):
            dx, dy = label_offsets[metric][j]
            radius = norm_by_metric[metric][arch]
            ax.annotate(
                format_radar_value(metric, raw_by_arch[arch][metric], max_horizons[arch]),
                xy=(angles[i], radius), xytext=(dx, dy), textcoords="offset points",
                color=COLORS[arch], fontsize=10, fontweight="semibold",
                ha="left" if dx > 0 else "right" if dx < 0 else "center",
                va="bottom" if dy > 0 else "top",
                bbox={"boxstyle": "round,pad=0.12", "fc": "white", "ec": "none", "alpha": .85},
                zorder=6,
            )
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels([])
    label_distances = {
        "Latency": 1.25,
        "Energy/solve": 1.48,
        "EDP": 1.55,
        "BRAM": 1.28,
        "Logic": 1.4,
        "Scalability": 1.4,
    }
    for angle, metric in zip(angles[:-1], metrics):
        ax.text(
            angle,
            label_distances[metric],
            metric,
            fontsize=radar_label_fontsize,
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


def plot_figure8_trajectory(
    reference_csv: Path,
    fpga_csv: Path,
    tinympc_csv: Path,
    svg_output: Path,
    png_output: Path,
    pdf_output: Path,
) -> None:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/latency_benchmark_matplotlib")
    import matplotlib.pyplot as plt

    plt.rcParams.update({
        "font.family": "serif",
        "font.serif": ["Times New Roman", "Times", "DejaVu Serif"],
        "mathtext.fontset": "stix",
        "svg.fonttype": "none",
        "pdf.fonttype": 42,
    })

    reference = load_figure8_reference(reference_csv)
    fpga = slice_figure8_dataset(
        apply_figure8_alignment(load_figure8_hw_log(fpga_csv), FIGURE8_FPGA_ALIGNMENT),
        FIGURE8_FPGA_ROW_RANGE,
    )
    tinympc = slice_figure8_dataset(
        apply_figure8_alignment(load_figure8_hw_log(tinympc_csv), FIGURE8_TINYMPC_ALIGNMENT),
        FIGURE8_TINYMPC_ROW_RANGE,
    )

    fig, ax = plt.subplots(figsize=(5.9, 5.25))
    fig.patch.set_facecolor("white")

    ax.plot(
        reference["data"]["x"],
        reference["data"]["y"],
        color="#424141",
        linewidth=2.0,
        linestyle="--",
        label="Reference",
        zorder=2,
    )
    ax.plot(
        fpga["data"]["x"],
        fpga["data"]["y"],
        color=COLORS["staged_a"],
        linewidth=2.2,
        label="FPGA",
        zorder=3,
    )
    ax.plot(
        tinympc["data"]["x"],
        tinympc["data"]["y"],
        color=COLORS["tinympc_e"],
        linewidth=2.2,
        label="TinyMPC",
        zorder=3,
    )

    ax.set_xlim(*FIGURE8_X_LIMITS)
    ax.set_ylim(*FIGURE8_Y_LIMITS)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("x [m]", fontsize=15)
    ax.set_ylabel("y [m]", fontsize=15)
    ax.grid(True, color="#D9D9D9", linewidth=0.9)
    ax.set_axisbelow(True)
    ax.tick_params(axis="both", labelsize=13, colors="#333333")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#333333")
    ax.spines["bottom"].set_color("#333333")
    ax.spines["bottom"].set_linewidth(1.1)

    ax.legend(
        loc="lower center",
        bbox_to_anchor=(0.5, -0.22),
        ncol=3,
        frameon=False,
        fontsize=12,
    )

    fig.subplots_adjust(left=0.14, right=0.98, top=0.98, bottom=0.23)

    for output in (svg_output, png_output, pdf_output):
        output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(svg_output, format="svg", bbox_inches="tight")
    fig.savefig(png_output, format="png", dpi=240, bbox_inches="tight")
    fig.savefig(pdf_output, format="pdf", bbox_inches="tight")
    plt.close(fig)


def write_publication_numbers(rows, output, tinympc_power_w):
    """Generate manuscript values using common horizons and board-measured fused points."""
    by_key = {(r["arch"], int(f(r,"horizon"))): r for r in rows}
    numbers = {}
    for baseline, prefix in [("tinympc_e","MCU"), ("tinympc_fpga_float","Wu"),
                             ("mobydic_small","Moby"), ("full_sparse","FullSparse")]:
        pairs = [(base, by_key[("staged_fused", h)]) for (arch,h),base in by_key.items()
                 if arch == baseline and ("staged_fused",h) in by_key
                 and by_key[("staged_fused",h)]["energy_source"] == "board_core_plus_estimated_aux_io"
                 and (baseline in ("tinympc_e","mobydic_small") or
                      base["energy_source"] == "board_core_plus_estimated_aux_io")]
        numbers[prefix+"SharedHorizonMin"] = str(min(int(f(base,"horizon")) for base,_ in pairs))
        numbers[prefix+"SharedHorizonMax"] = str(max(int(f(base,"horizon")) for base,_ in pairs))
        for metric, getter in [("Speed",comparison_latency_us),
                               ("Energy",lambda r: energy_mj(r,tinympc_power_w)),
                               ("EDP",lambda r: edp_uj_us(r,tinympc_power_w))]:
            ratios = [getter(base)/getter(fused) for base,fused in pairs]
            for suffix, value in [("Min",min(ratios)),("Max",max(ratios))]:
                precision = 2 if prefix in ("Wu","FullSparse") else (0 if metric == "EDP" else 1)
                numbers[prefix+metric+suffix] = f"{value:.{precision}f}"
    largest = max((r for r in rows if r["arch"] == "staged_fused"),key=lambda r:f(r,"horizon"))
    h = int(f(largest,"horizon"))
    numbers.update(FusedHorizon=str(h), FusedVariables=f"{16*h+12:,}",
                   FusedConstraints=f"{18*h+12:,}", FusedLargestMs=f"{comparison_latency_us(largest)/1000:.2f}")
    for arch,prefix in [("staged_fused","Fused"),("tinympc_fpga_float","Wu")]:
        row = by_key[arch,40]
        numbers[prefix+"FortyUs"] = f"{comparison_latency_us(row):.2f}"
        numbers[prefix+"FortyUj"] = f"{energy_mj(row,tinympc_power_w)*1000:.2f}"
    numbers["FortyEDPRatio"] = f"{edp_uj_us(by_key['tinympc_fpga_float',40],tinympc_power_w)/edp_uj_us(by_key['staged_fused',40],tinympc_power_w):.2f}"
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text("% Generated from benchmarks.csv; do not edit.\n" + "".join(
        "\\newcommand{\\bench"+name+"}{"+value.replace(",","{,}")+"}\n" for name,value in numbers.items()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--numbers-output", type=Path, default=OUTPUT_DIR / "benchmark_numbers.tex")
    parser.add_argument("--skip-trajectory", action="store_true", help="Regenerate benchmark figures only")
    parser.add_argument("--input", type=Path, default=BENCHMARK_SUMMARY_CSV)
    parser.add_argument("--compare-iters", type=int, default=10)
    parser.add_argument(
        "--tinympc-power-w",
        type=float,
        default=DEFAULT_TINYMPC_POWER_W,
        help="TinyMPC active power estimate for energy/EDP (default: 87 mA at 3.3 V)",
    )
    parser.add_argument("--svg-output", type=Path, default=OUTPUT_DIR / "benchmark_latency_energy.svg")
    parser.add_argument("--png-output", type=Path, default=OUTPUT_DIR / "benchmark_latency_energy.png")
    parser.add_argument("--pdf-output", type=Path, default=OUTPUT_DIR / "benchmark_latency_energy.pdf")
    parser.add_argument("--edp-svg-output", type=Path, default=OUTPUT_DIR / "benchmark_edp_bars.svg")
    parser.add_argument("--edp-png-output", type=Path, default=OUTPUT_DIR / "benchmark_edp_bars.png")
    parser.add_argument("--edp-pdf-output", type=Path, default=OUTPUT_DIR / "benchmark_edp_bars.pdf")
    parser.add_argument("--radar-horizon", type=int, default=40)
    parser.add_argument("--radar-svg-output", type=Path, default=OUTPUT_DIR / "benchmark_solver_radar.svg")
    parser.add_argument("--radar-png-output", type=Path, default=OUTPUT_DIR / "benchmark_solver_radar.png")
    parser.add_argument("--radar-pdf-output", type=Path, default=OUTPUT_DIR / "benchmark_solver_radar.pdf")
    parser.add_argument("--trajectory-reference", type=Path, default=FIGURE8_REFERENCE_CSV)
    parser.add_argument("--trajectory-fpga", type=Path, default=FIGURE8_FPGA_CSV)
    parser.add_argument("--trajectory-tinympc", type=Path, default=FIGURE8_TINYMPC_CSV)
    parser.add_argument("--trajectory-svg-output", type=Path, default=OUTPUT_DIR / "figure8_trajectory_overlay.svg")
    parser.add_argument("--trajectory-png-output", type=Path, default=OUTPUT_DIR / "figure8_trajectory_overlay.png")
    parser.add_argument("--trajectory-pdf-output", type=Path, default=OUTPUT_DIR / "figure8_trajectory_overlay.pdf")
    parser.add_argument("--feasibility-table-output", type=Path, default=OUTPUT_DIR / "feasibility_table.tex")
    parser.add_argument(
        "--feasibility-horizons",
        default=",".join(str(horizon) for horizon in FEASIBILITY_HORIZONS),
        help="Comma-separated prediction horizons for the generated feasibility table.",
    )
    parser.add_argument("--control-period-us", type=float, default=1000.0)
    parser.add_argument("--fpga-spi-overhead-us", type=float, default=100.0)
    args = parser.parse_args()

    if not math.isfinite(args.tinympc_power_w) or args.tinympc_power_w <= 0:
        parser.error("--tinympc-power-w must be a positive finite value")
    if not math.isfinite(args.control_period_us) or args.control_period_us <= 0:
        parser.error("--control-period-us must be a positive finite value")
    if not math.isfinite(args.fpga_spi_overhead_us) or args.fpga_spi_overhead_us < 0:
        parser.error("--fpga-spi-overhead-us must be a nonnegative finite value")
    if args.fpga_spi_overhead_us >= args.control_period_us:
        parser.error("--fpga-spi-overhead-us must be smaller than --control-period-us")
    try:
        feasibility_horizons = parse_horizon_list(args.feasibility_horizons)
    except ValueError as exc:
        parser.error(str(exc))

    rows = load_rows(args.input)
    seen = set()
    for row in rows:
        key = (row["arch"], f(row,"horizon"), f(row,"admm_iters"), f(row,"clock_mhz"))
        if key in seen or row.get("timing_clean") != "1":
            raise ValueError(f"Duplicate or invalid publication point: {key}")
        seen.add(key)
        latency = comparison_latency_us(row)
        energy = energy_mj(row,args.tinympc_power_w)*1000
        if not all(math.isfinite(v) and v > 0 for v in (latency,energy)):
            raise ValueError(f"Invalid latency/energy: {key}")
        if not math.isclose(f(row,"edp_uj_us"),latency*energy,rel_tol=1e-8):
            raise ValueError(f"Inconsistent EDP units: {key}")
    selected = best_rows(rows, args.compare_iters)
    write_publication_numbers(selected, args.numbers_output, args.tinympc_power_w)
    plot_selected = selected
    plot_headline(
        plot_selected,
        args.svg_output,
        args.png_output,
        args.pdf_output,
        args.compare_iters,
        args.tinympc_power_w,
    )
    plot_edp_bars(
        plot_selected,
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
    if not args.skip_trajectory:
        plot_figure8_trajectory(
            args.trajectory_reference,
            args.trajectory_fpga,
            args.trajectory_tinympc,
            args.trajectory_svg_output,
            args.trajectory_png_output,
            args.trajectory_pdf_output,
        )
    write_feasibility_table(
        rows,
        args.feasibility_table_output,
        feasibility_horizons,
        args.control_period_us,
        args.fpga_spi_overhead_us,
    )
    print(f"Generated benchmark figures, {args.feasibility_table_output}, and {args.numbers_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
