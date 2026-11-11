#!/usr/bin/env python3
"""Compute recorded late-May flight metrics and figures from bundled CSVs."""
from __future__ import annotations

import argparse
import csv
import math
import os
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
STAR_FLIGHT = DATA / "flight_metrics/constrained_star_flight.csv"
STAR_REFERENCE = DATA / "flight_metrics/star_reference.csv"
DYNAMIC_FLIGHT = DATA / "top_side_frame_table/dynamic_obstacle_flight.csv"
STAR_BOUNDS = (-1.3535533905932737, 0.6464466094067263)
REFERENCE_DT = 0.02
REFERENCE_PERIOD = 25.0
# Align reference playback with the flight recording using a fixed phase offset.
# This affects tracking-error scoring and sample selection, not bound violations.
STAR_PHASE_OFFSET_S = 24.343


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError(f"Empty CSV: {path}")
    return rows


def finite(row: dict[str, str], *keys: str) -> list[float]:
    values = [float(row[key]) for key in keys]
    if not all(math.isfinite(v) for v in values):
        raise ValueError(f"Nonfinite values in {keys}")
    return values


def violation(position: np.ndarray, lower: np.ndarray, upper: np.ndarray) -> np.ndarray:
    if not all(np.isfinite(a).all() for a in (position, lower, upper)):
        raise ValueError("Nonfinite position or bounds")
    if np.any(lower > upper):
        raise ValueError("Inverted position bounds")
    return np.maximum(0.0, np.maximum(lower - position, position - upper))


def summarize(values: np.ndarray, times: np.ndarray) -> dict:
    i = int(np.argmax(values))
    return {
        "samples": len(values),
        "outside_samples": int(np.count_nonzero(values > 0)),
        "outside_percent": float(100 * np.mean(values > 0)),
        "max_violation_cm": float(100 * values[i]),
        "rms_violation_cm": float(100 * np.sqrt(np.mean(values**2))),
        "mean_violation_cm": float(100 * np.mean(values)),
        "std_violation_cm": float(100 * np.std(values)),
        "p95_violation_cm": float(100 * np.percentile(values, 95)),
        "p99_violation_cm": float(100 * np.percentile(values, 99)),
        "within_1cm_percent": float(100 * np.mean(values <= 0.01)),
        "worst_elapsed_s": float(times[i]) if values[i] > 0 else None,
    }


def periodic_tracking(t: np.ndarray, positions: np.ndarray, ref: np.ndarray,
                           lower: np.ndarray, upper: np.ndarray,
                           period_s: float, dt_s: float,
                           phase_offset_s: float) -> dict:
    """Score playback-aligned tracking, restricted to reference points inside bounds."""
    n = len(ref)
    if n < 2 or not math.isclose(n * dt_s, period_s, rel_tol=0, abs_tol=1e-6):
        raise ValueError("Periodic reference length, sample time and period disagree")
    feasible = np.all((ref[:, 1:3] >= lower) & (ref[:, 1:3] <= upper), axis=1)
    if not np.any(feasible):
        raise ValueError("Reference has no feasible XY samples")
    indices = np.floor((t + phase_offset_s) / dt_s + 1e-10).astype(np.int64) % n
    score_mask = feasible[indices]
    if not np.any(score_mask):
        raise ValueError("No aligned feasible reference samples")
    delta = positions[score_mask] - ref[indices[score_mask], 1:4]
    error = np.linalg.norm(delta, axis=1)
    xy_error = np.linalg.norm(delta[:, :2], axis=1)
    count = int(score_mask.sum())
    return dict(
        rmse_cm=float(100.0 * np.sqrt(np.mean(error ** 2))), p95_cm=float(100.0 * np.percentile(error, 95)),
        max_cm=float(100.0 * np.max(error)), phase_offset_s=phase_offset_s,
        xy_rmse_cm=float(100.0 * np.sqrt(np.mean(xy_error ** 2))),
        xy_p95_cm=float(100.0 * np.percentile(xy_error, 95)),
        xy_max_cm=float(100.0 * np.max(xy_error)),
        period_s=period_s,
        samples=count, total_samples=len(t), coverage_percent=100.0 * count / len(t),
        feasible_reference_points=int(feasible.sum()),
        reference_points=n,
        feasible_reference_percent=100.0 * float(feasible.mean()),
    )


def interval(rows: list[dict[str, str]], experiment: str) -> tuple[float, float]:
    if experiment == "dynamic":
        return float(rows[0]["elapsed_s"]), float(rows[-1]["elapsed_s"])
    if experiment == "star":
        starts = [float(r["elapsed_s"]) for r in rows
                  if r["event"] == "command" and r["command"] == "start_traj"]
        if len(starts) != 1:
            raise ValueError("start_to_reset requires exactly one start_traj event")
        stops = [float(r["elapsed_s"]) for r in rows
                 if r["event"] == "command" and r["command"] == "reset_traj"
                 and float(r["elapsed_s"]) >= starts[0]]
        if len(stops) != 1:
            raise ValueError("start_to_reset requires exactly one following reset_traj event")
        return starts[0], stops[0]
    raise ValueError(f"Unknown experiment: {experiment}")


def analyze(path: Path, experiment: str, reference: Path | None = None,
            star_bounds: tuple[float, float] = STAR_BOUNDS) -> dict:
    """Select samples once; use these arrays for both figures and metrics."""
    rows = read_csv(path)
    ts = np.array([finite(r, "elapsed_s")[0] for r in rows])
    if np.any(np.diff(ts) < 0):
        raise ValueError(f"Reversed log timestamps: {path.name}")
    result = {
        "experiment": experiment, "file": str(path),
        "id": "constrained_star" if experiment == "star" else "dynamic_obstacle",
        "label": "Constrained STAR" if experiment == "star" else "Dynamic obstacles",
        "metrics": {}, "tracking": None, "status": "ok",
        "source_rows": len(rows),
        "source_sample_rows": sum(r["event"] == "sample" for r in rows),
        "command_rows": sum(r["event"] == "command" for r in rows),
    }
    start, end = interval(rows, experiment)
    counts = dict(outside_interval=0, invalid_mocap=0, inactive_constraints=0,
                  missing_or_nonfinite=0, before_first_transmission=0,
                  static_defaults_not_identified=0)
    samples, send_times, positions, bounds, boxes, origins, stamps = [], [], [], [], [], [], []
    latest = None
    transmissions = []
    for row in rows:
        t = float(row["elapsed_s"])
        if row["event"] == "command" and row["command"] == "set_constraints":
            lo, hi = finite(row, "dynamic_x_min_mm", "dynamic_x_max_mm")
            if lo > hi or lo != int(lo) or hi != int(hi) or lo < -32768 or hi > 32767:
                raise ValueError("Invalid transmitted integer bounds")
            latest = (lo / 1000, hi / 1000, t)
            transmissions.append(latest)
        if row["event"] != "sample":
            continue
        if not start <= t <= end:
            counts["outside_interval"] += 1
            continue
        if row.get("mocap_valid") != "1":
            counts["invalid_mocap"] += 1
            continue
        if experiment == "dynamic" and row.get("constraint_active") != "1":
            counts["inactive_constraints"] += 1
            continue
        if experiment == "dynamic" and latest is None:
            counts["before_first_transmission"] += 1
            continue
        if experiment == "dynamic" and latest[:2] == (0., 0.):
            # A zero packed word selects compiled static defaults, not x == 0.
            # No source-matched static box is available for these dynamic runs.
            counts["static_defaults_not_identified"] += 1
            continue
        try:
            p = finite(row, "mocap_x", "mocap_y", "mocap_z")
            stamp = finite(row, "mocap_stamp_s")[0]
            origin = finite(row, "target_x", "target_y", "target_z") if experiment == "star" else [0., 0., 0.]
        except (KeyError, ValueError):
            counts["missing_or_nonfinite"] += 1
            continue
        if experiment == "star":
            bound = [[star_bounds[0]] * 2, [star_bounds[1]] * 2]
            sent = float("nan")
        else:
            bound = [[latest[0]], [latest[1]]]
            sent = latest[2]
        try:
            box = finite(row, "box_min_x", "box_max_x")
            if box[0] > box[1]:
                raise ValueError("Inverted floating bounds")
        except (KeyError, ValueError):
            box = [float("nan"), float("nan")]
        samples.append(t)
        positions.append(np.array(p) - origin)
        origins.append(origin)
        bounds.append(bound)
        boxes.append(box)
        send_times.append(sent)
        stamps.append(stamp)
    if len(samples) < 2:
        result.update(status="unavailable", reason="Fewer than two usable position samples.",
                      excluded=counts)
        return result
    t = np.array(samples)
    if np.any(np.diff(t) <= 0):
        raise ValueError("Sample elapsed timestamps must increase strictly")
    if np.any(np.diff(stamps) < 0):
        raise ValueError("Mocap timestamps run backwards")
    if experiment == "star" and not np.all(np.array(origins) == origins[0]):
        raise ValueError("Star setpoint origin changes within the selected interval")
    p, b = np.array(positions), np.array(bounds)
    axes = "xy" if experiment == "star" else "x"
    v = violation(p[:, :len(axes)], b[:, 0, :], b[:, 1, :])
    metrics = {axis: summarize(v[:, i], t) for i, axis in enumerate(axes)}
    if len(axes) == 2:
        metrics["xy_any"] = summarize(v.max(axis=1), t)
    result.update(
        metrics=metrics, t=t, positions=p, lower=b[:, 0, :], upper=b[:, 1, :],
        violations=v, floating_bounds=np.array(boxes),
        transmissions=np.array(transmissions), excluded=counts,
        requested_interval=[start, end], evaluated_interval=[float(t[0]), float(t[-1])],
        origin=origins[0], unique_mocap_frames=len(set(stamps)),
        repeated_mocap_samples=len(stamps) - len(set(stamps)),
        median_log_interval_s=float(np.median(np.diff(t))),
        max_log_gap_s=float(np.max(np.diff(t))),
        max_mocap_gap_s=float(np.max(np.diff(stamps))),
    )
    if experiment == "dynamic":
        age = t - np.array(send_times)
        result["median_transmission_age_s"] = float(np.median(age))
        result["max_transmission_age_s"] = float(np.max(age))
        result["missing_floating_bound_samples"] = int(np.sum(~np.isfinite(np.array(boxes)).all(axis=1)))
    if experiment == "star" and reference is not None:
        ref = np.array([finite(r, "t_s", "x_m", "y_m", "z_m") for r in read_csv(reference)])
        if np.any(np.diff(ref[:, 0]) <= 0):
            raise ValueError("Reference timestamps must increase")
        result["reference"] = ref
        result["tracking"] = periodic_tracking(
            t - start, p, ref, b[0, 0, :], b[0, 1, :],
            REFERENCE_PERIOD, REFERENCE_DT, STAR_PHASE_OFFSET_S,
        )
    return result


def metric_rows(results: list[dict]) -> list[dict]:
    out = []
    for r in results:
        base = dict(
            experiment=r["experiment"], recording=r["id"], file=r["file"],
            status=r["status"],
            tracking_status="available" if r["tracking"] else "not evaluated",
        )
        if r["status"] != "ok":
            out.append(dict(base, status=r["reason"]))
            continue
        base.update(start_s=r["evaluated_interval"][0], end_s=r["evaluated_interval"][1],
                    repeated_mocap_samples=r["repeated_mocap_samples"],
                    excluded_samples=sum(r["excluded"].values()))
        if r["tracking"]:
            base.update({f"tracking_{k}": v for k, v in r["tracking"].items()})
        for axis, values in r["metrics"].items():
            out.append(dict(base, axis=axis, **values))
    return out


def render_report(results: list[dict]) -> str:
    lines = ["Flight metrics (cm)", "",
             "STAR: start to reset, target-relative coordinates; feasible-reference tracking.",
             "Fixed phase: 24.343 s over a 25 s loop (20 ms reference hold).",
             "Tracking RMSE uses fixed playback-phase alignment.",
             "Dynamic: full log; constraint violation only, using last transmitted x bounds.",
             "RMS violation includes zero violations; all metrics are sample-weighted.", ""]
    for r in results:
        lines += [r["label"], f"  Input: {Path(r['file']).name}"]
        if r["status"] != "ok":
            lines += [f"  Not calculated: {r['reason']}", ""]
            continue
        lines += [f"  Interval: {r['evaluated_interval'][0]:.6f}–{r['evaluated_interval'][1]:.6f} s",
                  f"  Exclusions: {r['excluded']}",
                  f"  Repeated mocap samples: {r['repeated_mocap_samples']}",
                  "  Axis       Samples   Max violation   RMS violation   Outside (%)"]
        for axis, v in r["metrics"].items():
            lines.append(f"  {axis:<10} {v['samples']:>6}   {v['max_violation_cm']:>13.4f}"
                         f"   {v['rms_violation_cm']:>13.4f}   {v['outside_percent']:>11.3f}")
        lines.append("  Distribution including zeros (cm; population standard deviation):")
        for axis, v in r["metrics"].items():
            lines.append(f"  {axis:<10} Mean {v['mean_violation_cm']:.4f}; std {v['std_violation_cm']:.4f}; "
                         f"p95 {v['p95_violation_cm']:.4f}; p99 {v['p99_violation_cm']:.4f}; "
                         f"inside {100 - v['outside_percent']:.2f}%; "
                         f"violation <=1 cm {v['within_1cm_percent']:.2f}%")
        tr = r["tracking"]
        if tr:
            lines += [f"  Tracking: XY RMSE {tr['xy_rmse_cm']:.4f}; 3D RMSE {tr['rmse_cm']:.4f}; "
                      f"3D p95 {tr['p95_cm']:.4f}; 3D max {tr['max_cm']:.4f}",
                      f"  Phase: {tr['phase_offset_s']:.3f} s / {tr['period_s']:g} s",
                      f"  Feasible flight samples: {tr['samples']} / {tr['total_samples']} "
                      f"({tr['coverage_percent']:.2f}%)",
                      f"  Feasible reference points: {tr['feasible_reference_points']} / {tr['reference_points']}"]
        lines.append("")
    return "\n".join(lines)


def save_figures(results: list[dict], output: Path) -> None:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/accelmpc-flight-matplotlib")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    try:
        from .plot_benchmarks import COLORS
    except ImportError:
        from plot_benchmarks import COLORS

    plt.rcParams.update({
        "font.family": "serif", "font.serif": ["DejaVu Serif"],
        "font.size": 12, "axes.labelsize": 13, "legend.fontsize": 10,
        "pdf.fonttype": 42, "svg.fonttype": "none",
    })
    green, red, blue = COLORS["staged_a"], COLORS["tinympc_e"], COLORS["full_sparse"]
    for r in results:
        if r["status"] != "ok":
            continue
        s, p, t = r, r["positions"], r["t"]
        fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True, layout="constrained")
        if s["experiment"] == "star":
            for i, ax in enumerate(axes):
                ax.plot(t, p[:, i], color=green, lw=1.2, label="Mocap")
                ax.plot(t, r["lower"][:, i], "--", color=blue, lw=1.2, label="Source-derived bounds")
                ax.plot(t, r["upper"][:, i], "--", color=blue, lw=1.2)
                outside = r["violations"][:, i] > 0
                ax.scatter(t[outside], p[outside, i], s=7, color=red, label="Outside bounds", zorder=4)
                ax.set_ylabel(f"{'xy'[i]} relative to origin [m]")
            axes[0].legend(loc="lower center", bbox_to_anchor=(.5, 1.02), ncol=3, frameon=False)
            fig.suptitle(f"{s['label']} — start to reset\nStatic bounds from recorded STAR source", fontsize=14)
        else:
            ax = axes[0]
            ax.plot(t, p[:, 0], color=green, lw=1.2, label="Mocap x")
            sends = r["transmissions"]
            # Include every transmission in the time plot, not just those coincident with samples.
            if len(sends):
                tx = np.r_[sends[:, 2], max(t[-1], sends[-1, 2])]
                default = np.all(sends[:, :2] == 0, axis=1)
                for j in range(2):
                    by = sends[:, j].copy()
                    by[default] = np.nan
                    ax.step(tx, np.r_[by, by[-1]], where="post",
                            color=blue, lw=1.1, label="Last transmitted bounds" if j == 0 else None)
                for k in np.flatnonzero(default):
                    for panel in axes:
                        panel.axvspan(tx[k], tx[k + 1], color="#777777", alpha=.12, lw=0)
            for j in range(2):
                ax.plot(t, r["floating_bounds"][:, j], ":", color="#777777", lw=.9,
                        label="Newly calculated bounds" if j == 0 else None)
            outside = r["violations"][:, 0] > 0
            ax.scatter(t[outside], p[outside, 0], s=8, color=red, zorder=4, label="Outside transmitted bounds")
            ax.set_ylabel("World x [m]")
            ax.legend(loc="lower center", bbox_to_anchor=(.5, 1.02), ncol=2, frameon=False)
            axes[1].plot(t, r["violations"][:, 0] * 100, color=red, lw=1.2)
            axes[1].set_ylabel("x-bound violation [cm]")
            axes[1].set_ylim(bottom=0)
            subtitle = "Full log; flight-only interval not established"
            if r["excluded"]["static_defaults_not_identified"]:
                subtitle += "\nGrey: static defaults requested; bounds unavailable"
            fig.suptitle(f"{s['label']}\n{subtitle}", fontsize=14)
        axes[-1].set_xlabel("Elapsed log time [s]")
        axes[-1].set_xlim(*r["requested_interval"])
        for ax in axes:
            ax.grid(alpha=.25)
            ax.spines[["top", "right"]].set_visible(False)
        for suffix in ("png", "pdf"):
            fig.savefig(output / f"{s['id']}_bounds.{suffix}", dpi=180)
        plt.close(fig)
        if s["experiment"] != "star":
            continue
        fig, ax = plt.subplots(figsize=(7.5, 7.5), layout="constrained")
        if "reference" in r:
            ref = r["reference"]
            ax.plot(ref[:, 1], ref[:, 2], "--", color="#555555", lw=1,
                    label="Recorded STAR reference (b82e18d)")
        lo, hi = r["lower"][0], r["upper"][0]
        ax.add_patch(Rectangle(lo, *(hi - lo), facecolor=blue, alpha=.10))
        ax.add_patch(Rectangle(lo, *(hi - lo), fill=False, edgecolor=blue, lw=1.4,
                               label="Source-derived box"))
        ax.plot(p[:, 0], p[:, 1], color=green, lw=1.1, label="Mocap")
        outside = np.any(r["violations"] > 0, axis=1)
        ax.scatter(p[outside, 0], p[outside, 1], s=6, color=red, label="Outside box", zorder=4)
        ax.scatter(p[0, 0], p[0, 1], marker="o", s=50, facecolors="white", edgecolors="black", zorder=5, label="Start")
        ax.set(xlabel="x relative to logged origin [m]", ylabel="y relative to logged origin [m]",
               title=f"{s['label']}\nRecorded STAR reference and flight path", aspect="equal")
        ax.grid(alpha=.25)
        ax.legend(loc="upper center", bbox_to_anchor=(.5, -.13), ncol=2)
        for suffix in ("png", "pdf"):
            fig.savefig(output / f"{s['id']}_trajectory.{suffix}", dpi=180)
        plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", choices=["all", "star", "dynamic"], default="all")
    parser.add_argument("--no-plots", action="store_true", help="Write metrics without generating figures")
    parser.add_argument("--output-dir", type=Path, default=HERE / "output")
    args = parser.parse_args()
    results = []
    if args.experiment in ("all", "dynamic"):
        results.append(analyze(DYNAMIC_FLIGHT, "dynamic"))
    if args.experiment in ("all", "star"):
        results.append(analyze(STAR_FLIGHT, "star", STAR_REFERENCE))
    report = render_report(results)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    # Scope-specific filenames prevent a subset run overwriting the complete table.
    stem = "flight_metrics" if args.experiment == "all" else f"flight_metrics_{args.experiment}"
    (args.output_dir / f"{stem}.txt").write_text(report)
    rows = metric_rows(results)
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with (args.output_dir / f"{stem}.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    if not args.no_plots:
        save_figures(results, args.output_dir)
    print(report, end="")
    print(f"Outputs: {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
