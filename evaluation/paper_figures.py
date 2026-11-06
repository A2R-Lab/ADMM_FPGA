#!/usr/bin/env python3
"""Paper benchmark figures from evaluation/data/benchmarks.csv.

    python evaluation/paper_figures.py

Figure 1 (fig1_dismissal_bars): latency, energy per solve and EDP at H = 5, 20, 40, 80 for
TinyMPC on the MCU, MOBY-DIC2, Wu et al. and both AccelMPC mappings, with ratios to staged,
plus the EDP of the FPGA designs at H = 200 to 1800.
Figure 2 (fig2_horizon_sweep): solve latency versus horizon for the three FPGA designs,
bubble area = energy per solve, the 0.9 ms budget line with the 1 kHz horizon capacities,
and each design's block RAM ceiling.
Figure 3 (fig3_radar_h40): H = 40 radar with staged, full-sparse and Wu et al. on the
uninstrumented solver resource basis.
Writes evaluation/output/paper_figures/*.{png,pdf}; only PNG previews belong in evaluation/figures/.
"""
import argparse
import csv
import math
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE / "output/paper_figures"
MCU_P = 0.2871
BUDGET_MS = 0.9  # 1 kHz period minus the 0.1 ms communication reserve, as in the paper's feasibility table
DESIGNS = [  # key, label, color
    ("staged_fused", "AccelMPC staged", "#0b7a4b"),
    ("full_sparse", "AccelMPC full-sparse", "#2a78d6"),
    ("tinympc_fpga_float", "Wu et al. (FPGA)", "#8e5bbf"),
    ("tinympc_e", "TinyMPC (MCU)", "#e05a2b"),
    ("mobydic_small", "MOBY-DIC2 (FPGA)", "#8c8c8c"),
]
COLOR = {k: c for k, _, c in DESIGNS}
LABEL = {k: l for k, l, _ in DESIGNS}
INSTRUMENTED = {"staged_fused", "full_sparse", "tinympc_fpga_float"}


def f(r, k):
    try:
        return float(r[k])
    except (KeyError, TypeError, ValueError):
        return math.nan


def latency_us(r):
    v = f(r, "measured_latency_us")
    return v if not math.isnan(v) else f(r, "solve_us_cfg_clk")


def energy_uj(r):
    if r["arch"] == "tinympc_e":
        return latency_us(r) * MCU_P
    if r["arch"] == "mobydic_small":
        return f(r, "energy_per_solve_cfg_uj")
    return f(r, "measured_energy_uj")


def edp(r):
    return energy_uj(r) * latency_us(r)


def feasible_horizon(fit):
    """Estimated largest integer horizon satisfying the fitted solve budget."""
    slope, intercept = fit
    if slope <= 0 or not all(math.isfinite(v) for v in fit):
        raise ValueError('A finite positive latency slope is required')
    return max(0, math.floor((1000 * BUDGET_MS - intercept) / slope))


def rows_for(rows, arch, scope=True):
    out = [r for r in rows if r["arch"] == arch and int(r["admm_iters"]) == 10
           and (not scope or arch not in INSTRUMENTED or r["resource_scope"] == "instrumented")]
    return sorted(out, key=lambda r: int(r["horizon"]))


def at(rows, arch, h, scope=True):
    m = [r for r in rows_for(rows, arch, scope) if int(r["horizon"]) == h]
    return m[0] if m else None


def style(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color="#e6e5e0", linewidth=0.8)
    ax.set_axisbelow(True)


def save(fig, name):
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{name}.png", dpi=200, bbox_inches="tight")
    fig.savefig(OUT / f"{name}.pdf", bbox_inches="tight")
    plt.close(fig)


# ------------------------------------------------------------------ Figure 1
def figure1(rows):
    horizons = [5, 20, 40, 80]
    high = [200, 400, 1000, 1800]
    def energy_any(r):
        v = energy_uj(r)
        return v if not math.isnan(v) else f(r, "energy_per_solve_cfg_uj")

    metrics = [("Solve latency (ms)", lambda r: latency_us(r) / 1e3),
               ("Energy per solve (mJ)", lambda r: energy_any(r) / 1e3),
               ("EDP (mJ·ms)", lambda r: energy_any(r) * latency_us(r) / 1e6)]
    order = ["mobydic_small", "tinympc_e", "tinympc_fpga_float", "full_sparse", "staged_fused"]
    fpga = ["tinympc_fpga_float", "full_sparse", "staged_fused"]
    width, gap = 0.8, 3.4

    def any_row(arch, h):
        """Instrumented row if there is one, else the solver estimate (staged beyond H1023)."""
        r = at(rows, arch, h)
        if r is None:
            m = [x for x in rows if x["arch"] == arch and int(x["admm_iters"]) == 10 and int(x["horizon"]) == h]
            r = m[0] if m else None
        return r

    def draw(ax, fn, hs, designs, label_legend):
        style(ax)
        ax.set_yscale("log")
        centers, missing, values = [], [], []
        for gi, h in enumerate(hs):
            x0 = gi * (len(designs) * width + gap)
            xs = {a: x0 + i * width for i, a in enumerate(designs)}
            centers.append(x0 + (len(designs) - 1) * width / 2)
            staged = fn(any_row("staged_fused", h))
            for a in designs:
                r = any_row(a, h)
                if r is None:
                    missing.append((xs[a], a))
                    continue
                v = fn(r)
                values.append(v)
                estimated = a == "mobydic_small" or (r["resource_scope"] != "instrumented" and a in INSTRUMENTED)
                ax.bar(xs[a], v, width=width * 0.92, color=COLOR[a], label=LABEL[a] if (gi == 0 and label_legend) else None)
                if estimated:
                    ax.plot(xs[a], v * 1.35, "*", color="black", ms=9, zorder=6, clip_on=False)
                if a != "staged_fused":
                    ratio = v / staged
                    ax.annotate("", xy=(xs["staged_fused"], staged), xytext=(xs[a], v),
                                arrowprops=dict(arrowstyle="-|>", connectionstyle="angle,angleA=0,angleB=90,rad=0",
                                                ls="--", lw=1.1, color=COLOR[a], shrinkA=0, shrinkB=1, mutation_scale=9))
                    ax.text(xs["staged_fused"] + 0.62, v, f"{ratio:.3g}×" if ratio < 100 else f"{ratio:.0f}×",
                            ha="left", va="center", fontsize=9.5, color=COLOR[a], fontweight="bold",
                            bbox=dict(boxstyle="round,pad=0.15", fc="white", ec=COLOR[a], lw=0.7))
        ax.set_xticks(centers, [f"H={h}" for h in hs])
        ax.tick_params(axis="x", labelsize=12 if hs[-1] < 1000 else 10)
        ax.tick_params(axis="y", labelsize=11)
        for x, a in missing:
            ax.plot(x, 0, "x", color=COLOR[a], ms=8, mew=1.8, clip_on=False, zorder=5, transform=ax.get_xaxis_transform())
        ax.set_xlim(-0.8, centers[-1] + (len(designs) - 1) * width / 2 + 2.3)
        return min(values) / 2.0, max(values) * 4

    fig = plt.figure(figsize=(14.5, 3.9))
    gs = fig.add_gridspec(1, 4, width_ratios=(1, 1, 1, 0.95), wspace=0.24, top=0.88, bottom=0.16)
    axes = [fig.add_subplot(gs[0, i]) for i in range(3)]
    limits = []
    for ax, (title, fn) in zip(axes, metrics):
        limits.append(draw(ax, fn, horizons, order, label_legend=ax is axes[0]))
        ax.set_title(title, fontsize=14)
    axes[0].set_ylim(*limits[0])
    axes[1].set_ylim(*limits[1])
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, frameon=False, fontsize=12, loc="upper center", bbox_to_anchor=(0.5, 0.085), ncol=5, columnspacing=1.6)
    axes[2].set_ylim(*limits[2])
    # fourth panel: the EDP of the three FPGA designs at large horizons, on its own axis
    ax4 = fig.add_subplot(gs[0, 3])
    lo4, hi4 = draw(ax4, metrics[2][1], high, fpga, label_legend=False)
    ax4.set_ylim(lo4, hi4)
    ax4.set_title("EDP (mJ·ms), large horizons", fontsize=14)
    save(fig, "fig1_dismissal_bars")


# ------------------------------------------------------------------ Figure 2
def figure2(rows, fits):
    fig, ax = plt.subplots(figsize=(7.2, 4.1))
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(color="#e6e5e0", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_xscale("log")
    ax.set_yscale("log")
    energy_scale = 0.075  # points^2 per uJ, plus a 12 pt^2 floor so the smallest solves stay visible

    def area(uj):
        return 12 + uj * energy_scale

    def energy_any(r):
        v = energy_uj(r)
        return v if not math.isnan(v) else f(r, "energy_per_solve_cfg_uj")

    def bubbles(arch, pts, estimated=False):
        hs = [int(r["horizon"]) for r in pts]
        ys = [latency_us(r) / 1e3 for r in pts]
        sz = [area(energy_any(r)) for r in pts]
        ax.scatter(hs, ys, s=sz, color=COLOR[arch], alpha=0.75, edgecolors="white", linewidths=0.6, zorder=3)
        if estimated:
            ax.scatter(hs, ys, marker="*", s=28, color="black", zorder=4)
        return hs, ys

    # Thin dense horizon ranges on the log axis; retain each measured endpoint.
    # This only thins displayed bubbles, not the CSV or the latency fits.
    display_horizons = {5, 10, 20, 30, 40, 60, 80, 100, 150, 200, 300, 400, 500, 600, 800}
    for arch in ("full_sparse", "tinympc_fpga_float", "staged_fused"):
        all_pts = rows_for(rows, arch)
        endpoint = int(all_pts[-1]["horizon"])
        pts = [r for r in all_pts if int(r["horizon"]) in display_horizons | {endpoint}]
        hs, ys = bubbles(arch, pts)
        if arch == "staged_fused":
            extra = [r for r in rows if r["arch"] == arch and int(r["admm_iters"]) == 10
                     and r["resource_scope"] == "solver_spi" and int(r["horizon"]) > max(hs)]
            extra = sorted(extra, key=lambda r: int(r["horizon"]))
            # Show one intermediate estimate as well as the demonstrated endpoint.
            extra = [r for r in extra if int(r["horizon"]) == 1350 or r is extra[-1]]
            hs2, ys2 = bubbles(arch, extra, estimated=True)
            ax.annotate(f"largest demonstrated\nH = {hs2[-1]}", (hs2[-1], ys2[-1]), xytext=(4, -88), textcoords="offset points",
                        ha="right", fontsize=11.5, color=COLOR[arch], arrowprops=dict(arrowstyle="-", color=COLOR[arch], lw=0.8))
        else:
            ax.plot(hs[-1], ys[-1], "x", color=COLOR[arch], ms=14, mew=3, zorder=5)
            last = pts[-1]
            if arch == "full_sparse":
                xy, ha = (-205, -10), "left"
            else:
                xy, ha = (-150, 30), "left"
            tiles = f"({f(last, 'route_bram_tile_used'):.0f}/135 tiles)"
            text = f"block RAM full\nH = {hs[-1]} {tiles}"
            ax.annotate(text,
                        (hs[-1], ys[-1]), xytext=xy, textcoords="offset points", ha=ha, fontsize=11.5, color=COLOR[arch],
                        arrowprops=dict(arrowstyle="-", color=COLOR[arch], lw=0.8))
    # 1 kHz budget and capacities
    ax.axhline(BUDGET_MS, color="#444", ls="--", lw=1.2, zorder=1)
    ax.text(4.3, BUDGET_MS * 1.10, "1 kHz budget\n(0.9 ms)", fontsize=11.5, color="#444", ha="left", va="bottom", linespacing=1.0)
    crossings = {}
    for arch, (s, b) in fits.items():
        hm = (1000 * BUDGET_MS - b) / s
        crossings[arch] = hm
        ax.plot([hm], [BUDGET_MS], "o", color=COLOR[arch], ms=9, mfc="white", mew=2.2, zorder=6)
        ax.plot([hm, hm], [0.05, BUDGET_MS], ls=":", lw=1.3, color=COLOR[arch], zorder=1)
    ax.set_xlabel("Prediction horizon H", fontsize=14)
    ax.set_ylabel("Solve latency (ms)", fontsize=14)
    ax.tick_params(labelsize=12.5)
    ticks = [(5, "5", "black"), (10, "10", "black"), (100, "100", "black"), (200, "200", "black"), (500, "500", "black"),
             (1000, "1000", "black"), (1800, "1800", "black")] + [(hm, f"{math.floor(hm)}", COLOR[a]) for a, hm in crossings.items()]
    ticks.sort()
    ax.set_xticks([t[0] for t in ticks], [t[1] for t in ticks])
    for lab, (_, _, c) in zip(ax.get_xticklabels(), ticks):
        lab.set_color(c)
        if c != "black":
            lab.set_fontweight("bold")
    ax.set_xticks([], minor=True)
    ax.set_xlim(4, 2800)  # Leave room for the full H1800 energy bubble.
    ax.set_ylim(0.05, 120)
    names = {"staged_fused": "AccelMPC staged", "full_sparse": "AccelMPC full-sparse", "tinympc_fpga_float": "Wu et al."}
    handles = [Line2D([], [], marker="o", ls="", color=COLOR[a], ms=10, label=names[a]) for a in ("staged_fused", "full_sparse", "tinympc_fpga_float")]
    for uj in (100, 1000, 5000):
        handles.append(Line2D([], [], marker="o", ls="", color="#bbb", ms=math.sqrt(area(uj)), label=f"{uj/1000:g} mJ per solve"))
    ax.legend(handles=handles, frameon=True, framealpha=1.0, edgecolor="none", fontsize=11.5, loc="lower right", ncol=2, labelspacing=0.35, columnspacing=1.2, handletextpad=0.6, borderaxespad=0.15, borderpad=0.3)
    save(fig, "fig2_horizon_sweep")


# ------------------------------------------------------------------ Figure 3
def figure3(rows, fits):
    h = 40
    archs = ["staged_fused", "full_sparse", "tinympc_fpga_float"]
    raw = {}
    for a in archs:
        r = at(rows, a, h)
        s, b = fits[a]
        if r is None or not all(math.isfinite(f(r, key)) and f(r, key) > 0
                                for key in ("solver_luts_used", "solver_bram_tiles_used", "solver_dsps_used")):
            raise ValueError(f"Missing uninstrumented H40 resources for {a}")
        raw[a] = {"Latency": latency_us(r) / 1e3, "Energy/solve": energy_uj(r) / 1e3, "EDP": edp(r) / 1e6,
                  "LUT (Logic)": 100 * f(r, "solver_luts_used") / 63400, "DSP (Arithmetic)": 100 * f(r, "solver_dsps_used") / 240,
                  "BRAM\n(Memory)": 100 * f(r, "solver_bram_tiles_used") / 135,
                  "1 kHz horizon": feasible_horizon((s, b))}
    metrics = list(raw[archs[0]])
    # radial position: cost normalized to the worst design (1 = worst, smaller = better); capacity inverted
    norm = {}
    for m in metrics:
        vals = {a: (1 / raw[a][m] if m == "1 kHz horizon" else raw[a][m]) for a in archs}
        worst = max(vals.values())
        norm[m] = {a: 0.22 + 0.78 * vals[a] / worst for a in archs}
    fmt = {"Latency": "{:.3f} ms", "Energy/solve": "{:.3f} mJ", "EDP": "{:.0f} µJ·ms", "LUT (Logic)": "{:.1f}%", "DSP (Arithmetic)": "{:.1f}%", "BRAM\n(Memory)": "{:.1f}%", "1 kHz horizon": "H = {:.0f}"}
    angles = np.linspace(0, 2 * np.pi, len(metrics), endpoint=False)
    fig = plt.figure(figsize=(6.0, 6.0))
    ax = fig.add_subplot(111, polar=True)
    ax.set_theta_offset(np.pi / 2)
    ax.set_theta_direction(-1)
    ax.set_ylim(0, 1.18)
    ax.set_yticks([0.22, 0.415, 0.61, 0.805, 1.0])
    ax.set_yticklabels([])
    ax.set_xticks(angles)
    ax.set_xticklabels(metrics, fontsize=16)
    ax.tick_params(axis="x", pad=14)
    ax.grid(color="#d8d8d3")
    # Point offsets separate nearby values without shifting their data positions.
    label_offsets = {
        "Latency": [(0, -14, 'center'), (0, -14, 'center'), (0, 14, 'center')],
        "Energy/solve": [(-2, -14, 'center'), (-2, -14, 'center'), (-28, 10, 'center')],
        "EDP": [(-6, 13, 'center'), (-30, -13, 'center'), (-6, -14, 'center')],
        "LUT (Logic)": [(-22, -10, 'center'), (0, -15, 'center'), (16, 8, 'left')],
        "DSP (Arithmetic)": [(-12, -13, 'center'), (16, -6, 'left'), (28, 4, 'center')],
        "BRAM\n(Memory)": [(12, 11, 'left'), (12, -14, 'left'), (-2, 14, 'center')],
        "1 kHz horizon": [(-26, -4, 'center'), (-10, -14, 'center'), (-24, 10, 'center')],
    }
    for a in archs:
        vals = [norm[m][a] for m in metrics] + [norm[metrics[0]][a]]
        ang = list(angles) + [angles[0]]
        ax.plot(ang, vals, "-o", color=COLOR[a], lw=2.2, ms=6, label={"tinympc_fpga_float": "Wu et al."}.get(a, LABEL[a]))
        ax.fill(ang, vals, color=COLOR[a], alpha=0.08)
        for m, th in zip(metrics, angles):
            v = norm[m][a]
            txt = fmt[m].format(raw[a][m] * (1000 if m == "EDP" else 1))
            dx, dy, ha = label_offsets[m][archs.index(a)]
            ax.annotate(txt, xy=(th, v), xytext=(dx, dy), textcoords="offset points",
                        ha=ha, va="center", fontsize=11.5, color=COLOR[a], fontweight="bold",
                        bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.85))
    # Manually positioned axis titles, independent of the polar tick redraw.
    axis_offsets = {
        "Latency": (4.32, -11.52),
        "Energy/solve": (26.64, 5.04),
        "EDP": (0, -4.32),
        "LUT (Logic)": (6, 2),
        "DSP (Arithmetic)": (0, -5),
        "BRAM\n(Memory)": (-20, 8),
        "1 kHz horizon": (-33.12, 5.04),
    }
    fig.canvas.draw()
    for tick in ax.get_xticklabels():
        anchor = ax.transAxes.inverted().transform(
            tick.get_transform().transform(tick.get_position()))
        ax.annotate(tick.get_text(), xy=anchor, xycoords="axes fraction",
                    xytext=axis_offsets[tick.get_text()], textcoords="offset points",
                    ha=tick.get_ha(), va=tick.get_va(), fontsize=16,
                    annotation_clip=False)
        tick.set_visible(False)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.06), ncol=3, frameon=False, fontsize=14, columnspacing=1.2, handlelength=1.6)
    save(fig, "fig3_radar_h40")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=HERE / "data/benchmarks.csv")
    args = parser.parse_args()
    with args.csv.open() as fh:
        rows = list(csv.DictReader(fh))
    fits = {}
    for a in INSTRUMENTED:
        pts = np.array([(int(r["horizon"]), f(r, "solve_us_cfg_clk")) for r in rows_for(rows, a) if int(r["horizon"]) <= 400], float)
        fits[a] = tuple(np.polyfit(pts[:, 0], pts[:, 1], 1))
    figure1(rows)
    figure2(rows, fits)
    figure3(rows, fits)
    print("wrote", sorted(p.name for p in OUT.glob("*.png")))


if __name__ == "__main__":
    main()
