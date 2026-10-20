#!/usr/bin/env python3
"""Compute recorded late-May flight metrics and figures from bundled CSVs."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
MANIFEST = DATA / "flight_metrics" / "experiments.json"


def read_csv(path: Path, expected_sha256: str) -> list[dict[str, str]]:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError(f"Input hash mismatch: {path}")
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
        "worst_elapsed_s": float(times[i]) if values[i] > 0 else None,
    }


def interval(rows: list[dict[str, str]], selection: dict) -> tuple[float, float]:
    if selection["mode"] == "full_log":
        return float(rows[0]["elapsed_s"]), float(rows[-1]["elapsed_s"])
    if selection["mode"] == "start_to_reset":
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
    if selection["mode"] == "explicit":
        if not selection.get("evidence"):
            raise ValueError("An explicit flight interval requires independent evidence")
        start, end = float(selection["start_s"]), float(selection["end_s"])
        if not math.isfinite(start) or not math.isfinite(end) or end <= start:
            raise ValueError("Invalid explicit flight interval")
        return start, end
    raise ValueError(f"Unknown interval mode: {selection['mode']}")


def analyze(spec: dict, data_dir: Path = DATA) -> dict:
    """Select samples once; use these arrays for both figures and metrics."""
    rows = read_csv(data_dir / spec["file"], spec["sha256"])
    ts = np.array([finite(r, "elapsed_s")[0] for r in rows])
    if np.any(np.diff(ts) < 0):
        raise ValueError(f"Reversed log timestamps: {spec['id']}")
    result = {
        "spec": spec, "metrics": {}, "tracking": None, "status": "ok",
        "source_rows": len(rows),
        "source_sample_rows": sum(r["event"] == "sample" for r in rows),
        "command_rows": sum(r["event"] == "command" for r in rows),
    }
    if spec["experiment"] == "star" and not spec.get("static_bounds"):
        result.update(status="unavailable", reason="Static XY bounds are not specified.")
        return result
    if spec["experiment"] == "star" and spec.get("origin") != "logged_target_xyz":
        result.update(status="unavailable", reason="The reference coordinate origin is not established.")
        return result
    start, end = interval(rows, spec["interval"])
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
        if spec["experiment"] == "dynamic" and row.get("constraint_active") != "1":
            counts["inactive_constraints"] += 1
            continue
        if spec["experiment"] == "dynamic" and latest is None:
            counts["before_first_transmission"] += 1
            continue
        if spec["experiment"] == "dynamic" and latest[:2] == (0., 0.):
            # A zero packed word selects compiled static defaults, not x == 0.
            # No source-matched static box is available for these dynamic runs.
            counts["static_defaults_not_identified"] += 1
            continue
        try:
            p = finite(row, "mocap_x", "mocap_y", "mocap_z")
            stamp = finite(row, "mocap_stamp_s")[0]
            origin = finite(row, "target_x", "target_y", "target_z") if spec["experiment"] == "star" else [0., 0., 0.]
        except (KeyError, ValueError):
            counts["missing_or_nonfinite"] += 1
            continue
        if spec["experiment"] == "star":
            b = spec["static_bounds"]
            bound = [[b["x"][0], b["y"][0]], [b["x"][1], b["y"][1]]]
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
    if spec["experiment"] == "star" and not np.all(np.array(origins) == origins[0]):
        raise ValueError("Star setpoint origin changes within the selected interval")
    p, b = np.array(positions), np.array(bounds)
    axes = "xy" if spec["experiment"] == "star" else "x"
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
    if spec["experiment"] == "dynamic":
        age = t - np.array(send_times)
        result["median_transmission_age_s"] = float(np.median(age))
        result["max_transmission_age_s"] = float(np.max(age))
        result["missing_floating_bound_samples"] = int(np.sum(~np.isfinite(np.array(boxes)).all(axis=1)))
    ref = spec.get("reference")
    if ref:
        ref_rows = read_csv(data_dir / ref["file"], ref["sha256"])
        ref_values = np.array([finite(r, "t_s", "x_m", "y_m", "z_m") for r in ref_rows])
        if np.any(np.diff(ref_values[:, 0]) <= 0):
            raise ValueError("Reference timestamps must increase")
        result["reference"] = ref_values
        # Only explicitly synchronized, same-frame references can supply tracking metrics.
        # Current bundled references are geometry reconstructions, with timing unverified.
        if ref.get("timing") == "verified_log_elapsed":
            expected_frame = "relative_to_logged_target" if spec["experiment"] == "star" else "world"
            if ref.get("frame") != expected_frame:
                raise ValueError("Verified reference frame does not match measured positions")
            rt = ref_values[:, 0]
            if t[0] < rt[0] or t[-1] > rt[-1]:
                raise ValueError("Verified reference does not cover every evaluated sample")
            indices = np.searchsorted(rt, t, side="right") - 1
            error = np.linalg.norm(p - ref_values[indices, 1:4], axis=1)
            result["tracking"] = dict(
                rmse_cm=float(100 * np.sqrt(np.mean(error**2))),
                p95_cm=float(100 * np.percentile(error, 95)),
                max_cm=float(100 * error.max()),
            )
    return result


def metric_rows(results: list[dict]) -> list[dict]:
    out = []
    for r in results:
        spec = r["spec"]
        base = dict(
            experiment=spec["experiment"], recording=spec["id"], file=spec["file"],
            sha256=spec["sha256"], attribution=spec["attribution"],
            interval=spec["interval"]["mode"], status=r["status"],
            bounds=spec["bounds_description"],
            tracking_status="available" if r["tracking"] else spec["tracking_unavailable_reason"],
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


def render_report(results: list[dict], provenance: dict) -> str:
    lines = [
        "AccelMPC — late-May recorded flight metrics",
        "",
        "SUMMARY — position-constraint violation, NOT position tracking error",
        "Recording          Axis       Samples   Maximum [cm]   RMS [cm]   Outside [%]",
    ]
    for r in results:
        if r["status"] != "ok":
            lines.append(f"{r['spec']['id']}: NOT CALCULATED — {r['reason']}")
            continue
        axis = "xy_any" if r["spec"]["experiment"] == "star" else "x"
        v = r["metrics"][axis]
        lines.append(f"{r['spec']['id']:<18} {axis:<8} {v['samples']:>7}"
                     f"   {v['max_violation_cm']:>12.4f}   {v['rms_violation_cm']:>8.4f}"
                     f"   {v['outside_percent']:>11.3f}")
    lines += [
        "",
        "Star: start-to-reset runs; static bounds/source association inferred.",
        "Dynamic: full logs, including any termination/handling; unavailable bounds excluded.",
        "",
        "Position-constraint violation [m] = max(lower - position, position - upper, 0).",
        "Numbers below are in cm. RMS includes zero-violation samples.",
        "XY-any uses the maximum axis violation at each sample; outside means either axis.",
        "Counts and percentages are sample-weighted. Repeated mocap frames are retained.",
        "They do not measure continuous-time violation duration or physical obstacle clearance.",
        "No error-based trimming, smoothing, fitted translations or fitted timing is used.",
        "",
        f"Bridge source revision: {provenance['bridge_revision']}",
        f"Candidate star source revision: {provenance['star_revision']}",
        "The star bounds/frame association is inferred, not a verified flashed configuration.",
        "Dynamic bounds are last logged transmissions, not acknowledged controller application.",
        "A transmitted (0, 0) pair requests compiled static defaults. Those samples are",
        "unavailable for dynamic-bound metrics until their static defaults are identified.",
        "",
    ]
    for r in results:
        s = r["spec"]
        lines += [f"{s['label']} [{s['id']}]", f"  Input: data/{s['file']}",
                  f"  SHA-256: {s['sha256']}", f"  Attribution: {s['attribution']}",
                  f"  Scope: {s['interval']['description']}",
                  f"  Bounds: {s['bounds_description']}"]
        if r["status"] != "ok":
            lines += [f"  NOT CALCULATED: {r['reason']}", ""]
            continue
        lines += [
            f"  Requested interval: {r['requested_interval'][0]:.6f}–{r['requested_interval'][1]:.6f} s",
            f"  Evaluated support: {r['evaluated_interval'][0]:.6f}–{r['evaluated_interval'][1]:.6f} s",
            f"  Origin subtracted from mocap XYZ [m]: {r['origin']}",
            f"  Source rows: {r['source_rows']}; sample rows: {r['source_sample_rows']}; command rows: {r['command_rows']}",
            f"  Exclusions: {json.dumps(r['excluded'], sort_keys=True)}",
            f"  Unique mocap frames: {r['unique_mocap_frames']}; repeated samples: {r['repeated_mocap_samples']}",
            f"  Logging interval median/max gap: {r['median_log_interval_s']:.6f}/{r['max_log_gap_s']:.6f} s",
            f"  Maximum mocap timestamp gap: {r['max_mocap_gap_s']:.6f} s",
        ]
        if s["experiment"] == "dynamic":
            lines += [
                f"  Last transmission age median/max: {r['median_transmission_age_s']:.6f}/{r['max_transmission_age_s']:.6f} s",
                f"  Missing floating diagnostic bounds: {r['missing_floating_bound_samples']} samples",
            ]
        lines += ["  Axis       Max [cm]    RMS [cm]    Outside / samples       Outside [%]    Worst time [s]"]
        for axis, v in r["metrics"].items():
            worst = "none" if v["worst_elapsed_s"] is None else f"{v['worst_elapsed_s']:.6f}"
            lines.append(f"  {axis:<9} {v['max_violation_cm']:>9.4f}   {v['rms_violation_cm']:>9.4f}"
                         f"    {v['outside_samples']:>6} / {v['samples']:<8}      {v['outside_percent']:>8.3f}    {worst}")
        if r["tracking"]:
            lines.append(f"  Position tracking [cm]: {json.dumps(r['tracking'], sort_keys=True)}")
        else:
            lines.append(f"  Tracking metrics unavailable: {s['tracking_unavailable_reason']}")
        lines += [f"  Note: {note}" for note in s.get("notes", [])]
        lines.append("")
    return "\n".join(lines) + "\n"


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
        s, p, t = r["spec"], r["positions"], r["t"]
        fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True, layout="constrained")
        if s["experiment"] == "star":
            for i, ax in enumerate(axes):
                ax.plot(t, p[:, i], color=green, lw=1.2, label="Mocap")
                ax.plot(t, r["lower"][:, i], "--", color=blue, lw=1.2, label="Source-derived bounds (inferred)")
                ax.plot(t, r["upper"][:, i], "--", color=blue, lw=1.2)
                outside = r["violations"][:, i] > 0
                ax.scatter(t[outside], p[outside, i], s=7, color=red, label="Outside bounds", zorder=4)
                ax.set_ylabel(f"{'xy'[i]} relative to origin [m]")
            axes[0].legend(loc="lower center", bbox_to_anchor=(.5, 1.02), ncol=3, frameon=False)
            fig.suptitle(f"{s['label']} — start to reset\nStatic bounds inferred from the named star source", fontsize=14)
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
                    label="Reconstructed reference geometry")
        lo, hi = r["lower"][0], r["upper"][0]
        ax.add_patch(Rectangle(lo, *(hi - lo), facecolor=blue, alpha=.10))
        ax.add_patch(Rectangle(lo, *(hi - lo), fill=False, edgecolor=blue, lw=1.4,
                               label="Source-derived box (inferred)"))
        ax.plot(p[:, 0], p[:, 1], color=green, lw=1.1, label="Mocap")
        outside = np.any(r["violations"] > 0, axis=1)
        ax.scatter(p[outside, 0], p[outside, 1], s=6, color=red, label="Outside box", zorder=4)
        ax.scatter(p[0, 0], p[0, 1], marker="o", s=50, facecolors="white", edgecolors="black", zorder=5, label="Start")
        ax.set(xlabel="x relative to logged origin [m]", ylabel="y relative to logged origin [m]",
               title=f"{s['label']}\nStar source/frame association inferred", aspect="equal")
        ax.grid(alpha=.25)
        ax.legend(loc="upper center", bbox_to_anchor=(.5, -.13), ncol=2)
        for suffix in ("png", "pdf"):
            fig.savefig(output / f"{s['id']}_trajectory.{suffix}", dpi=180)
        plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", choices=["all", "star", "dynamic"], default="all")
    parser.add_argument("--output-dir", type=Path, default=HERE / "output")
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text())
    specs = [s for s in manifest["experiments"]
             if args.experiment == "all" or s["experiment"] == args.experiment]
    results = [analyze(s) for s in specs]
    report = render_report(results, manifest["provenance"])
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
    save_figures(results, args.output_dir)
    print(report, end="")
    print(f"Outputs: {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
