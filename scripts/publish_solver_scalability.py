#!/usr/bin/env python3
"""Publish compact solver scalability results and reproducible figures."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


LOW_HORIZONS = list(range(10, 100, 10))
ARCHES = ["full_sparse", "staged_a"]
CANONICAL_FIELDS = [
    "series",
    "arch",
    "horizon",
    "admm_iters",
    "seed",
    "vivado_impl_variant",
    "status",
    "failed_stage",
    "bitstream_exists",
    "timing_clean",
    "route_wns_ns",
    "optimization_variables",
    "constraints",
    "hls_latency_cycles",
    "clock_mhz",
    "latency_ms",
    "solve_rate_hz",
    "power_w",
    "energy_mj_per_solve",
    "bram_used",
    "bram_util_pct",
    "lut_used",
    "lut_util_pct",
    "ff_used",
    "ff_util_pct",
    "dsp_used",
    "dsp_util_pct",
    "lutram_used",
    "lutram_util_pct",
    "compute_lut_ff_util_pct",
    "table_milestone",
    "source_slug",
    "source_run_dir",
    "source_git_head",
    "source_git_status",
]


def parse_float(value: str, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise SystemExit(f"Invalid numeric value for {label}: {value!r}") from None
    if not math.isfinite(result):
        raise SystemExit(f"Non-finite numeric value for {label}: {value!r}")
    return result


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise SystemExit(f"Missing CSV: {path}")
    with path.open(newline="") as fobj:
        return list(csv.DictReader(fobj))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fobj:
        writer = csv.DictWriter(fobj, fieldnames=CANONICAL_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fobj:
        for chunk in iter(lambda: fobj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_output(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def compact(value: float, digits: int = 9) -> str:
    return f"{value:.{digits}g}"


def canonical_from_raw(row: dict[str, str], run_dir: Path) -> dict[str, str]:
    horizon = int(parse_float(row.get("horizon", ""), "horizon"))
    latency_us = parse_float(row.get("solve_us_cfg_clk", ""), "solve_us_cfg_clk")
    wns = parse_float(row.get("route_wns_ns", ""), "route_wns_ns")
    lut_pct = parse_float(row.get("route_slice_luts_util_pct", ""), "LUT utilization")
    ff_pct = parse_float(row.get("route_slice_registers_util_pct", ""), "FF utilization")
    status = row.get("status", "")
    bitstream = row.get("bitstream_exists", "")
    timing_clean = status == "pass" and bitstream == "1" and wns >= 0
    return {
        "series": "low_horizon_comparison",
        "arch": row.get("arch", ""),
        "horizon": str(horizon),
        "admm_iters": row.get("admm_iters", ""),
        "seed": row.get("seed", ""),
        "vivado_impl_variant": row.get("vivado_impl_variant", ""),
        "status": status,
        "failed_stage": row.get("failed_stage", ""),
        "bitstream_exists": bitstream,
        "timing_clean": "1" if timing_clean else "0",
        "route_wns_ns": compact(wns),
        "optimization_variables": str(int(parse_float(row.get("gen_n_var", ""), "gen_n_var"))),
        "constraints": str(int(parse_float(row.get("gen_n_constr", ""), "gen_n_constr"))),
        "hls_latency_cycles": str(int(parse_float(row.get("hls_latency_cycles", ""), "hls_latency_cycles"))),
        "clock_mhz": compact(parse_float(row.get("route_clk_freq_mhz", "100"), "clock MHz")),
        "latency_ms": compact(latency_us / 1000.0),
        "solve_rate_hz": compact(1_000_000.0 / latency_us),
        "power_w": compact(parse_float(row.get("route_power_total_w", ""), "power")),
        "energy_mj_per_solve": compact(parse_float(row.get("energy_per_solve_cfg_uj", ""), "energy") / 1000.0),
        "bram_used": row.get("route_bram_tile_used", ""),
        "bram_util_pct": row.get("route_bram_tile_util_pct", ""),
        "lut_used": row.get("route_slice_luts_used", ""),
        "lut_util_pct": row.get("route_slice_luts_util_pct", ""),
        "ff_used": row.get("route_slice_registers_used", ""),
        "ff_util_pct": row.get("route_slice_registers_util_pct", ""),
        "dsp_used": row.get("route_dsps_used", ""),
        "dsp_util_pct": row.get("route_dsps_util_pct", ""),
        "lutram_used": row.get("route_lut_as_mem_used", ""),
        "lutram_util_pct": row.get("route_lut_as_mem_util_pct", ""),
        "compute_lut_ff_util_pct": compact(lut_pct + ff_pct),
        "table_milestone": "0",
        "source_slug": row.get("slug", ""),
        "source_run_dir": str(run_dir),
        "source_git_head": row.get("git_head", ""),
        "source_git_status": row.get("git_status_short", ""),
    }


def collect_low_rows(run_dirs: list[Path]) -> list[dict[str, str]]:
    raw_rows: list[tuple[dict[str, str], Path]] = []
    for run_dir in run_dirs:
        for path in sorted((run_dir / "rows").glob("*.csv")):
            raw_rows.extend((row, run_dir) for row in read_csv(path))
    selected: list[dict[str, str]] = []
    for arch in ARCHES:
        for horizon in LOW_HORIZONS:
            matches = [
                (row, run_dir)
                for row, run_dir in raw_rows
                if row.get("arch") == arch
                and int(float(row.get("horizon", "0") or 0)) == horizon
                and row.get("seed") == "0"
            ]
            if len(matches) != 1:
                raise SystemExit(f"Expected one seed-0 row for {arch} H={horizon}, found {len(matches)}")
            row, source_run_dir = matches[0]
            selected.append(canonical_from_raw(row, source_run_dir))
    return sorted(selected, key=lambda row: (int(row["horizon"]), row["arch"]))


def load_manual_scalability(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as fobj:
        reader = csv.DictReader(fobj)
        if reader.fieldnames != CANONICAL_FIELDS:
            raise SystemExit(f"{path} must use the canonical columns in the documented order")
        rows = list(reader)
    if not rows:
        raise SystemExit(f"No scalability rows found in {path}")
    seen: set[tuple[str, str]] = set()
    for line_number, row in enumerate(rows, start=2):
        key = (row["arch"], row["horizon"])
        if key in seen:
            raise SystemExit(f"Duplicate scalability point {key} in {path}:{line_number}")
        seen.add(key)
        if row["series"] != "staged_scalability" or row["arch"] != "staged_a":
            raise SystemExit(f"Invalid scalability series/architecture in {path}:{line_number}")
        if row["timing_clean"] != "1" or parse_float(row["route_wns_ns"], "WNS") < 0:
            raise SystemExit(f"Scalability rows must be timing-clean: {path}:{line_number}")
        for key_name in ("optimization_variables", "constraints", "latency_ms", "solve_rate_hz"):
            if parse_float(row[key_name], key_name) <= 0:
                raise SystemExit(f"{key_name} must be positive in {path}:{line_number}")
    if sum(row["table_milestone"] == "1" for row in rows) < 2:
        raise SystemExit(f"At least two table milestones are required in {path}")
    return sorted(rows, key=lambda row: int(row["horizon"]))


def numeric(rows: list[dict[str, str]], key: str) -> list[float]:
    return [parse_float(row[key], key) for row in rows]


def add_constraint_axis(ax, rows: list[dict[str, str]], milestone_only: bool = False) -> None:
    points = [row for row in rows if not milestone_only or row["table_milestone"] == "1"]
    top = ax.twiny()
    top.set_xlim(ax.get_xlim())
    top.set_xticks(numeric(points, "optimization_variables"))
    top.set_xticklabels([f"{int(float(row['constraints'])):,}" for row in points], fontsize=8)
    top.set_xlabel("Constraints")


def plot_low_tradeoffs(rows: list[dict[str, str]], output: Path) -> None:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/admm_fpga_matplotlib")
    import matplotlib.pyplot as plt

    metrics = [
        ("latency_ms", "Latency [ms]"),
        ("power_w", "Power [W]"),
        ("energy_mj_per_solve", "Energy [mJ/solve]"),
        ("bram_util_pct", "BRAM [% used]"),
        ("compute_lut_ff_util_pct", "Compute [% LUT+FF]"),
        ("lutram_util_pct", "LUTRAM [% used]"),
    ]
    colors = {"full_sparse": "#176B87", "staged_a": "#D95F02"}
    fig, axes = plt.subplots(2, 3, figsize=(15, 8.5), sharex=True)
    for ax, (key, ylabel) in zip(axes.flat, metrics):
        for arch in ARCHES:
            points = sorted((row for row in rows if row["arch"] == arch), key=lambda row: int(row["horizon"]))
            xs = numeric(points, "optimization_variables")
            ys = numeric(points, key)
            ax.plot(xs, ys, color=colors[arch], linewidth=2, label=arch)
            for row, x, y in zip(points, xs, ys):
                clean = row["timing_clean"] == "1"
                ax.scatter(x, y, s=42, facecolor=colors[arch] if clean else "white", edgecolor=colors[arch], zorder=3)
                if key == "latency_ms":
                    ax.annotate(f"H={row['horizon']}", (x, y), xytext=(0, 7), textcoords="offset points", ha="center", fontsize=7)
        ax.set_ylabel(ylabel)
        ax.grid(True, alpha=0.25)
    for ax in axes[1, :]:
        ax.set_xlabel("Optimization variables")
    add_constraint_axis(axes[0, 0], [row for row in rows if row["arch"] == "staged_a"])
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=2, frameon=False)
    fig.suptitle("Solver Architecture Tradeoffs - 10 ADMM iterations at 100 MHz", fontsize=16)
    fig.tight_layout(rect=(0, 0.055, 1, 0.96))
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=180)
    plt.close(fig)


def plot_scalability(rows: list[dict[str, str]], output: Path) -> None:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/admm_fpga_matplotlib")
    import matplotlib.pyplot as plt

    xs = numeric(rows, "optimization_variables")
    ys = numeric(rows, "latency_ms")
    fig, ax = plt.subplots(figsize=(10.5, 6.5))
    ax.plot(xs, ys, color="#176B87", marker="o", linewidth=2.5)
    for row, x, y in zip(rows, xs, ys):
        if row["table_milestone"] == "1":
            ax.annotate(f"H={row['horizon']}", (x, y), xytext=(0, 9), textcoords="offset points", ha="center", fontsize=8)
    ax.axhline(50.0, color="#B33A3A", linestyle="--", linewidth=1.5, label="20 solves/s")
    endpoint = rows[-1]
    endpoint_text = (
        f"{int(float(endpoint['optimization_variables'])):,} variables\n"
        f"{int(float(endpoint['constraints'])):,} constraints\n"
        f"{float(endpoint['latency_ms']):.3f} ms / {float(endpoint['solve_rate_hz']):.2f} solves/s"
    )
    ax.annotate(
        endpoint_text,
        (xs[-1], ys[-1]),
        xytext=(-185, -55),
        textcoords="offset points",
        arrowprops={"arrowstyle": "->", "color": "#333333"},
        bbox={"boxstyle": "round,pad=0.35", "fc": "white", "ec": "#888888"},
        fontsize=9,
    )
    ax.set_xlabel("Optimization variables")
    ax.set_ylabel("Latency [ms]")
    ax.set_title("Staged Solver Scaling - 10 ADMM iterations at 100 MHz")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="upper left")
    add_constraint_axis(ax, rows, milestone_only=True)
    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=180)
    plt.close(fig)


def plot_scalability_table(rows: list[dict[str, str]], output: Path) -> None:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/admm_fpga_matplotlib")
    import matplotlib.pyplot as plt

    milestones = [row for row in rows if row["table_milestone"] == "1"]
    headers = ["H", "Variables", "Constraints", "Latency [ms]", "Rate [Hz]", "WNS [ns]", "BRAM [%]", "Compute [%]"]
    cells = [
        [
            row["horizon"],
            f"{int(float(row['optimization_variables'])):,}",
            f"{int(float(row['constraints'])):,}",
            f"{float(row['latency_ms']):.3f}",
            f"{float(row['solve_rate_hz']):.2f}",
            f"{float(row['route_wns_ns']):+.3f}",
            f"{float(row['bram_util_pct']):.1f}",
            f"{float(row['compute_lut_ff_util_pct']):.1f}",
        ]
        for row in milestones
    ]
    fig, ax = plt.subplots(figsize=(12.5, 1.25 + 0.55 * len(cells)))
    ax.axis("off")
    table = ax.table(cellText=cells, colLabels=headers, loc="center", cellLoc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1.0, 1.55)
    for column in range(len(headers)):
        table[(0, column)].set_facecolor("#E6EEF2")
        table[(0, column)].set_text_props(weight="bold")
    ax.set_title("Staged Solver Scaling - 10 ADMM iterations at 100 MHz", pad=16, fontsize=14)
    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=180, bbox_inches="tight")
    plt.close(fig)


def render_figures(output: Path) -> None:
    low_rows = read_csv(output / "data" / "low_horizon_comparison.csv")
    scale_rows = read_csv(output / "data" / "staged_scalability.csv")
    figures = output / "figures"
    plot_low_tradeoffs(low_rows, figures / "solver_low_horizon_tradeoffs.png")
    plot_scalability(scale_rows, figures / "solver_scalability_latency.png")
    plot_scalability_table(scale_rows, figures / "solver_scalability_table.png")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-dir",
        action="append",
        type=Path,
        help="Raw low-horizon run directory; repeat when architectures were run separately",
    )
    parser.add_argument("--manual-scalability", type=Path, help="Manually curated canonical staged scalability CSV")
    parser.add_argument("--output", required=True, type=Path, help="Tracked campaign result directory")
    parser.add_argument("--regenerate-only", action="store_true", help="Regenerate figures from tracked canonical CSVs")
    args = parser.parse_args()

    output = args.output.resolve()
    if args.regenerate_only:
        render_figures(output)
        print(f"Regenerated figures under {output / 'figures'}")
        return 0
    if args.run_dir is None or args.manual_scalability is None:
        parser.error("--run-dir and --manual-scalability are required unless --regenerate-only is used")

    run_dirs = [path.resolve() for path in args.run_dir]
    manual_path = args.manual_scalability.resolve()
    low_rows = collect_low_rows(run_dirs)
    scale_rows = load_manual_scalability(manual_path)
    low_csv = output / "data" / "low_horizon_comparison.csv"
    scale_csv = output / "data" / "staged_scalability.csv"
    write_csv(low_csv, low_rows)
    write_csv(scale_csv, scale_rows)
    render_figures(output)

    repo = Path(__file__).resolve().parents[1]
    manifest = {
        "campaign": output.name,
        "published_utc": datetime.now(timezone.utc).isoformat(),
        "board": "custom",
        "part": "xc7a100tcsg324-1",
        "admm_iterations": 10,
        "configured_clock_mhz": 100.0,
        "trajectory_enabled": False,
        "low_horizons": LOW_HORIZONS,
        "architectures": ARCHES,
        "low_run_dirs": [str(path) for path in run_dirs],
        "manual_scalability_source": str(manual_path),
        "publisher_git_head": git_output(repo, "rev-parse", "HEAD"),
        "publisher_git_status": git_output(repo, "status", "--short"),
        "source_git_heads": sorted({row["source_git_head"] for row in low_rows + scale_rows}),
        "high_horizon_provenance_note": "Existing high-horizon rows were produced from a recorded dirty worktree based on b82e18d; see README.",
        "files": {},
    }
    for path in sorted((output / "data").glob("*.csv")) + sorted((output / "figures").glob("*.png")):
        manifest["files"][str(path.relative_to(output))] = {"sha256": sha256(path), "bytes": path.stat().st_size}
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"Published canonical results under {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
