#!/usr/bin/env python3
"""Compare FPGA and TinyMPC trajectory logs with automatic time/space offset alignment."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

COMMON_STATE_COLS = ["x", "y", "z", "roll", "pitch", "yaw"]
COMMON_CONTROL_COLS = ["u1_16", "u2_16", "u3_16", "u4_16"]
ALIGN_SPACE_COLS = ["x", "y", "z"]


def _as_float(value: str) -> float:
    return float(value.strip())


def _safe_dt_from_time(t: np.ndarray) -> float | None:
    if t.size < 2:
        return None
    dt = np.diff(t)
    dt = dt[dt > 0.0]
    if dt.size == 0:
        return None
    return float(np.median(dt))


def _qtorp_to_rpy(rp0: np.ndarray, rp1: np.ndarray, rp2: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rp_norm2 = rp0 * rp0 + rp1 * rp1 + rp2 * rp2
    qw = 1.0 / np.sqrt(1.0 + rp_norm2)
    qx = rp0 * qw
    qy = rp1 * qw
    qz = rp2 * qw

    roll = np.arctan2(2.0 * (qw * qx + qy * qz), 1.0 - 2.0 * (qx * qx + qy * qy))
    pitch_arg = np.clip(2.0 * (qw * qy - qz * qx), -1.0, 1.0)
    pitch = np.arcsin(pitch_arg)
    yaw = np.arctan2(2.0 * (qw * qz + qx * qy), 1.0 - 2.0 * (qy * qy + qz * qz))
    return roll, pitch, yaw


def load_hw_log(path: Path) -> dict[str, Any]:
    rows: list[dict[str, str]] = []
    with path.open("r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    if not rows:
        return {"name": path.stem, "path": path, "n": 0, "t": np.array([], dtype=np.float64), "data": {}}

    t_ms = np.array([_as_float(r["time_ms"]) for r in rows], dtype=np.float64)
    t = (t_ms - t_ms[0]) / 1000.0

    data: dict[str, np.ndarray] = {
        "x": np.array([_as_float(r["state_x"]) for r in rows], dtype=np.float64),
        "y": np.array([_as_float(r["state_y"]) for r in rows], dtype=np.float64),
        "z": np.array([_as_float(r["state_z"]) for r in rows], dtype=np.float64),
        # HW log attitude is in degrees; convert to radians to match reference.
        "roll": np.deg2rad(np.array([_as_float(r["roll"]) for r in rows], dtype=np.float64)),
        "pitch": np.deg2rad(np.array([_as_float(r["pitch"]) for r in rows], dtype=np.float64)),
        "yaw": np.deg2rad(np.array([_as_float(r["yaw"]) for r in rows], dtype=np.float64)),
        "u1_16": np.array([_as_float(r["u1_16"]) for r in rows], dtype=np.float64),
        "u2_16": np.array([_as_float(r["u2_16"]) for r in rows], dtype=np.float64),
        "u3_16": np.array([_as_float(r["u3_16"]) for r in rows], dtype=np.float64),
        "u4_16": np.array([_as_float(r["u4_16"]) for r in rows], dtype=np.float64),
    }
    return {"name": path.stem, "path": path, "n": len(rows), "t": t, "data": data}


def load_generated_reference(path: Path) -> dict[str, Any]:
    rows: list[dict[str, str]] = []
    with path.open("r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    if not rows:
        return {"name": path.stem, "path": path, "n": 0, "t": np.array([], dtype=np.float64), "data": {}}

    t = np.array([_as_float(r["t"]) for r in rows], dtype=np.float64)
    x = np.array([_as_float(r["x0"]) for r in rows], dtype=np.float64)
    y = np.array([_as_float(r["x1"]) for r in rows], dtype=np.float64)
    z = np.array([_as_float(r["x2"]) for r in rows], dtype=np.float64)
    rp0 = np.array([_as_float(r["x3"]) for r in rows], dtype=np.float64)
    rp1 = np.array([_as_float(r["x4"]) for r in rows], dtype=np.float64)
    rp2 = np.array([_as_float(r["x5"]) for r in rows], dtype=np.float64)
    roll, pitch, yaw = _qtorp_to_rpy(rp0, rp1, rp2)

    data: dict[str, np.ndarray] = {
        "x": x,
        "y": y,
        "z": z,
        "roll": roll,
        "pitch": pitch,
        "yaw": yaw,
        "u0": np.array([_as_float(r["u0"]) for r in rows], dtype=np.float64),
        "u1": np.array([_as_float(r["u1"]) for r in rows], dtype=np.float64),
        "u2": np.array([_as_float(r["u2"]) for r in rows], dtype=np.float64),
        "u3": np.array([_as_float(r["u3"]) for r in rows], dtype=np.float64),
    }
    return {"name": path.stem, "path": path, "n": len(rows), "t": t, "data": data}


def _aligned_grid(ta: np.ndarray, tb_shifted: np.ndarray, dt: float, min_points: int) -> np.ndarray | None:
    t0 = max(float(ta[0]), float(tb_shifted[0]))
    t1 = min(float(ta[-1]), float(tb_shifted[-1]))
    if not (t1 > t0):
        return None
    n = int(math.floor((t1 - t0) / dt)) + 1
    if n < min_points:
        return None
    return np.linspace(t0, t0 + dt * (n - 1), n)


def _interp_vec(ds: dict[str, Any], cols: list[str], t_grid: np.ndarray, t_shift: float = 0.0) -> np.ndarray:
    t_src = ds["t"] + t_shift
    arr = np.zeros((t_grid.size, len(cols)), dtype=np.float64)
    for j, col in enumerate(cols):
        arr[:, j] = np.interp(t_grid, t_src, ds["data"][col])
    return arr


def _fit_lag_and_translation(
    a: dict[str, Any],
    b: dict[str, Any],
    *,
    max_lag_s: float,
    min_points: int,
    apply_space_alignment: bool,
) -> tuple[float, np.ndarray]:
    da = _safe_dt_from_time(a["t"])
    db = _safe_dt_from_time(b["t"])
    if da is None or db is None:
        return 0.0, np.zeros(3, dtype=np.float64)

    dt = min(da, db)
    if dt <= 0:
        return 0.0, np.zeros(3, dtype=np.float64)

    n_steps = int(round(max_lag_s / dt))
    lags = np.arange(-n_steps, n_steps + 1, dtype=np.int64) * dt

    best_lag = 0.0
    best_offset = np.zeros(3, dtype=np.float64)
    best_score = float("inf")

    for lag in lags:
        tb_shifted = b["t"] + lag
        t_grid = _aligned_grid(a["t"], tb_shifted, dt, min_points)
        if t_grid is None:
            continue

        a_xyz = _interp_vec(a, ALIGN_SPACE_COLS, t_grid, 0.0)
        b_xyz = _interp_vec(b, ALIGN_SPACE_COLS, t_grid, lag)

        if apply_space_alignment:
            offset = np.mean(a_xyz - b_xyz, axis=0)
        else:
            offset = np.zeros(3, dtype=np.float64)

        err = a_xyz - (b_xyz + offset[None, :])
        score = float(np.sqrt(np.mean(err * err)))
        if score < best_score:
            best_score = score
            best_lag = float(lag)
            best_offset = offset

    return best_lag, best_offset


def compare_pair(
    a: dict[str, Any],
    b: dict[str, Any],
    cols: list[str],
    *,
    max_lag_s: float,
    min_points: int,
    apply_space_alignment: bool,
) -> dict[str, Any]:
    if a["n"] < min_points or b["n"] < min_points:
        return {"ok": False, "reason": "insufficient samples"}

    da = _safe_dt_from_time(a["t"])
    db = _safe_dt_from_time(b["t"])
    if da is None or db is None:
        return {"ok": False, "reason": "non-increasing or degenerate time axis"}

    dt = min(da, db)
    lag_s, xyz_offset = _fit_lag_and_translation(
        a,
        b,
        max_lag_s=max_lag_s,
        min_points=min_points,
        apply_space_alignment=apply_space_alignment,
    )

    t_grid = _aligned_grid(a["t"], b["t"] + lag_s, dt, min_points)
    if t_grid is None:
        return {"ok": False, "reason": "no overlapping time window after lag fit"}

    metrics: dict[str, dict[str, float]] = {}
    a_interp: dict[str, np.ndarray] = {}
    b_interp: dict[str, np.ndarray] = {}

    for col in cols:
        if col not in a["data"] or col not in b["data"]:
            continue
        av = np.interp(t_grid, a["t"], a["data"][col])
        bv = np.interp(t_grid, b["t"] + lag_s, b["data"][col])
        if col == "x":
            bv = bv + xyz_offset[0]
        elif col == "y":
            bv = bv + xyz_offset[1]
        elif col == "z":
            bv = bv + xyz_offset[2]

        err = av - bv
        metrics[col] = {
            "rmse": float(np.sqrt(np.mean(err * err))),
            "mae": float(np.mean(np.abs(err))),
            "max_abs": float(np.max(np.abs(err))),
            "bias": float(np.mean(err)),
        }
        a_interp[col] = av
        b_interp[col] = bv

    if not metrics:
        return {"ok": False, "reason": "no common columns to compare"}

    return {
        "ok": True,
        "t": t_grid,
        "metrics": metrics,
        "a_interp": a_interp,
        "b_interp": b_interp,
        "cols": list(metrics.keys()),
        "window": (float(t_grid[0]), float(t_grid[-1])),
        "n": int(t_grid.size),
        "lag_s": lag_s,
        "xyz_offset": xyz_offset,
    }


def _apply_alignment_to_dataset(ds: dict[str, Any], lag_s: float, xyz_offset: np.ndarray) -> dict[str, Any]:
    out_data: dict[str, np.ndarray] = {}
    for k, v in ds["data"].items():
        out_data[k] = np.array(v, copy=True)
    if "x" in out_data:
        out_data["x"] = out_data["x"] + xyz_offset[0]
    if "y" in out_data:
        out_data["y"] = out_data["y"] + xyz_offset[1]
    if "z" in out_data:
        out_data["z"] = out_data["z"] + xyz_offset[2]
    return {
        "name": ds["name"],
        "path": ds["path"],
        "n": ds["n"],
        "t": ds["t"] + lag_s,
        "data": out_data,
    }


def compare_on_overlap_fixed(
    a: dict[str, Any],
    b: dict[str, Any],
    cols: list[str],
    *,
    min_points: int = 3,
) -> dict[str, Any]:
    if a["n"] < min_points or b["n"] < min_points:
        return {"ok": False, "reason": "insufficient samples"}

    da = _safe_dt_from_time(a["t"])
    db = _safe_dt_from_time(b["t"])
    if da is None or db is None:
        return {"ok": False, "reason": "non-increasing or degenerate time axis"}
    dt = min(da, db)

    t_grid = _aligned_grid(a["t"], b["t"], dt, min_points)
    if t_grid is None:
        return {"ok": False, "reason": "no overlapping time window"}

    metrics: dict[str, dict[str, float]] = {}
    a_interp: dict[str, np.ndarray] = {}
    b_interp: dict[str, np.ndarray] = {}
    for col in cols:
        if col not in a["data"] or col not in b["data"]:
            continue
        av = np.interp(t_grid, a["t"], a["data"][col])
        bv = np.interp(t_grid, b["t"], b["data"][col])
        err = av - bv
        metrics[col] = {
            "rmse": float(np.sqrt(np.mean(err * err))),
            "mae": float(np.mean(np.abs(err))),
            "max_abs": float(np.max(np.abs(err))),
            "bias": float(np.mean(err)),
        }
        a_interp[col] = av
        b_interp[col] = bv

    if not metrics:
        return {"ok": False, "reason": "no common columns to compare"}

    return {
        "ok": True,
        "t": t_grid,
        "metrics": metrics,
        "a_interp": a_interp,
        "b_interp": b_interp,
        "cols": list(metrics.keys()),
        "window": (float(t_grid[0]), float(t_grid[-1])),
        "n": int(t_grid.size),
        "lag_s": 0.0,
        "xyz_offset": np.zeros(3, dtype=np.float64),
    }


def print_dataset_summary(ds: dict[str, Any]) -> None:
    dt = _safe_dt_from_time(ds["t"])
    duration = float(ds["t"][-1] - ds["t"][0]) if ds["n"] > 1 else 0.0
    dt_str = f"{dt:.6f}s" if dt is not None else "n/a"
    print(f"- {ds['name']}: n={ds['n']} duration={duration:.3f}s dt_med={dt_str} path={ds['path']}")


def print_metrics(name: str, result: dict[str, Any]) -> None:
    print(f"\n{name}")
    if not result["ok"]:
        print(f"  skipped: {result['reason']}")
        return

    w0, w1 = result["window"]
    dx, dy, dz = result["xyz_offset"]
    print(f"  aligned_window=[{w0:.3f}, {w1:.3f}]s points={result['n']}")
    print(f"  fitted_time_lag_s={result['lag_s']:.6f} (positive means B delayed)")
    print(f"  fitted_xyz_offset_m=[{dx:.6f}, {dy:.6f}, {dz:.6f}] applied to B")
    print("  column        rmse        mae         max_abs     bias")
    for col in result["cols"]:
        m = result["metrics"][col]
        print(
            f"  {col:<12} {m['rmse']:>10.6f} {m['mae']:>10.6f} "
            f"{m['max_abs']:>12.6f} {m['bias']:>10.6f}"
        )


def _plot_xy_overlay(path: Path, datasets: list[dict[str, Any]]) -> None:
    fig, ax = plt.subplots(figsize=(7.5, 6.5), constrained_layout=True)
    styles = [
        {"lw": 2.0, "ls": "-"},
        {"lw": 1.8, "ls": "--"},
        {"lw": 1.8, "ls": "-."},
    ]
    for i, ds in enumerate(datasets):
        if ds["n"] < 1:
            continue
        style = styles[i % len(styles)]
        label = f"{ds['name']} (n={ds['n']})"
        line = ax.plot(ds["data"]["x"], ds["data"]["y"], label=label, **style)[0]
        ax.plot(ds["data"]["x"][0], ds["data"]["y"][0], marker="o", ms=5, color=line.get_color())
        ax.plot(ds["data"]["x"][-1], ds["data"]["y"][-1], marker="x", ms=6, color=line.get_color())
    ax.set_title("XY trajectory overlay")
    ax.set_xlabel("x [m]")
    ax.set_ylabel("y [m]")
    ax.grid(True)
    ax.axis("equal")
    ax.legend()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _plot_xy_reference_fpga_tinympc(
    path: Path,
    reference: dict[str, Any],
    fpga: dict[str, Any],
    tinympc: dict[str, Any],
) -> None:
    fig, ax = plt.subplots(figsize=(8.0, 6.5), constrained_layout=True)
    plot_specs = [
        ("Reference", reference, {"lw": 2.2, "ls": "-"}),
        ("FPGA", fpga, {"lw": 1.8, "ls": "--"}),
        ("TinyMPC", tinympc, {"lw": 1.8, "ls": "-."}),
    ]

    for label, ds, style in plot_specs:
        if ds["n"] < 1:
            continue
        line = ax.plot(ds["data"]["x"], ds["data"]["y"], label=label, **style)[0]
        ax.plot(ds["data"]["x"][0], ds["data"]["y"][0], marker="o", ms=5, color=line.get_color())
        ax.plot(ds["data"]["x"][-1], ds["data"]["y"][-1], marker="x", ms=6, color=line.get_color())

    ax.set_title("XY plane: Reference vs FPGA vs TinyMPC")
    ax.set_xlabel("x [m]")
    ax.set_ylabel("y [m]")
    ax.grid(True)
    ax.axis("equal")
    ax.legend()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _plot_xy_overlay_aligned(
    path: Path,
    reference: dict[str, Any],
    others: list[dict[str, Any]],
    ref_to_other_pairs: list[dict[str, Any]],
) -> None:
    fig, ax = plt.subplots(figsize=(7.5, 6.5), constrained_layout=True)
    ax.plot(reference["data"]["x"], reference["data"]["y"], lw=2.0, label=f"{reference['name']} (ref)")

    for ds, pair in zip(others, ref_to_other_pairs):
        if ds["n"] < 1:
            continue
        if not pair.get("ok", False):
            ax.plot(ds["data"]["x"], ds["data"]["y"], lw=1.6, ls="--", label=f"{ds['name']} (raw)")
            continue

        dx, dy, _ = pair["xyz_offset"]
        # compare_pair(a, b) returns offset applied to b to match a.
        # Here we pass a=reference, b=ds, so +offset aligns ds to reference.
        x_aligned = ds["data"]["x"] + dx
        y_aligned = ds["data"]["y"] + dy
        label = f"{ds['name']} (aligned dx={dx:.3f}, dy={dy:.3f})"
        line = ax.plot(x_aligned, y_aligned, lw=1.8, ls="--", label=label)[0]
        ax.plot(x_aligned[0], y_aligned[0], marker="o", ms=5, color=line.get_color())
        ax.plot(x_aligned[-1], y_aligned[-1], marker="x", ms=6, color=line.get_color())

    ax.set_title("XY trajectory overlay (aligned to reference translation)")
    ax.set_xlabel("x [m]")
    ax.set_ylabel("y [m]")
    ax.grid(True)
    ax.axis("equal")
    ax.legend()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _plot_pair_timeseries(path: Path, pair_name: str, pair: dict[str, Any], cols: list[str]) -> None:
    if not pair["ok"]:
        return

    t = pair["t"]
    n_rows = len(cols)
    fig, axs = plt.subplots(n_rows, 1, figsize=(10, 2.1 * n_rows), sharex=True, constrained_layout=True)
    if n_rows == 1:
        axs = [axs]

    for ax, col in zip(axs, cols):
        if col not in pair["a_interp"]:
            continue
        av = pair["a_interp"][col]
        bv = pair["b_interp"][col]
        ax.plot(t, av, label="A", lw=1.2)
        ax.plot(t, bv, label="B_aligned", lw=1.2)
        ax.plot(t, av - bv, label="A-B", lw=0.9, alpha=0.85)
        ax.set_ylabel(col)
        ax.grid(True)

    axs[0].set_title(pair_name)
    axs[-1].set_xlabel("time [s]")
    axs[0].legend(loc="best")
    fig.savefig(path, dpi=150)
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="Compare FPGA and TinyMPC trajectories and generated reference.")
    parser.add_argument("--fpga", type=Path, default=repo_root / "fpga_trajectory.csv")
    parser.add_argument("--tinympc", type=Path, default=repo_root / "tinympc_trajectory.csv")
    parser.add_argument("--reference", type=Path, default=repo_root / "vitis_projects" / "ADMM" / "trajectory_refs.csv")
    parser.add_argument("--plots-dir", type=Path, default=repo_root / "plots" / "trajectory_comparison")
    parser.add_argument("--no-plots", action="store_true")
    parser.add_argument(
        "--max-lag-s",
        type=float,
        default=2.0,
        help="Maximum absolute time lag searched during alignment.",
    )
    parser.add_argument(
        "--no-space-align",
        action="store_true",
        help="Disable xyz translation fitting.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    for p in [args.fpga, args.tinympc, args.reference]:
        if not p.exists():
            raise FileNotFoundError(f"missing input file: {p}")

    fpga = load_hw_log(args.fpga)
    tinympc = load_hw_log(args.tinympc)
    reference = load_generated_reference(args.reference)

    print("Loaded datasets")
    print_dataset_summary(fpga)
    print_dataset_summary(tinympc)
    print_dataset_summary(reference)

    align_space = not args.no_space_align

    # Fit each logger independently to the same reference frame.
    ref_vs_fpga_fit = compare_pair(
        reference,
        fpga,
        ALIGN_SPACE_COLS,
        max_lag_s=args.max_lag_s,
        min_points=3,
        apply_space_alignment=align_space,
    )
    ref_vs_tiny_fit = compare_pair(
        reference,
        tinympc,
        ALIGN_SPACE_COLS,
        max_lag_s=args.max_lag_s,
        min_points=3,
        apply_space_alignment=align_space,
    )

    fpga_aligned = fpga
    tiny_aligned = tinympc
    if ref_vs_fpga_fit["ok"]:
        fpga_aligned = _apply_alignment_to_dataset(
            fpga, ref_vs_fpga_fit["lag_s"], ref_vs_fpga_fit["xyz_offset"]
        )
    if ref_vs_tiny_fit["ok"]:
        tiny_aligned = _apply_alignment_to_dataset(
            tinympc, ref_vs_tiny_fit["lag_s"], ref_vs_tiny_fit["xyz_offset"]
        )

    # Compare all signals in the common reference-aligned frame.
    fpga_vs_ref = compare_on_overlap_fixed(reference, fpga_aligned, COMMON_STATE_COLS, min_points=3)
    tiny_vs_ref = compare_on_overlap_fixed(reference, tiny_aligned, COMMON_STATE_COLS, min_points=3)
    fpga_vs_tiny_state = compare_on_overlap_fixed(fpga_aligned, tiny_aligned, COMMON_STATE_COLS, min_points=3)
    fpga_vs_tiny_ctrl = compare_on_overlap_fixed(
        fpga_aligned, tiny_aligned, COMMON_CONTROL_COLS, min_points=3
    )

    # Report fitted transforms (reference <- logger).
    print("\nReference alignment fits (applied to logger datasets)")
    if ref_vs_fpga_fit["ok"]:
        dx, dy, dz = ref_vs_fpga_fit["xyz_offset"]
        print(
            f"  fpga: lag_s={ref_vs_fpga_fit['lag_s']:.6f}, "
            f"xyz_offset_m=[{dx:.6f}, {dy:.6f}, {dz:.6f}]"
        )
    else:
        print(f"  fpga: skipped ({ref_vs_fpga_fit['reason']})")
    if ref_vs_tiny_fit["ok"]:
        dx, dy, dz = ref_vs_tiny_fit["xyz_offset"]
        print(
            f"  tinympc: lag_s={ref_vs_tiny_fit['lag_s']:.6f}, "
            f"xyz_offset_m=[{dx:.6f}, {dy:.6f}, {dz:.6f}]"
        )
    else:
        print(f"  tinympc: skipped ({ref_vs_tiny_fit['reason']})")

    print_metrics("FPGA vs TinyMPC (state)", fpga_vs_tiny_state)
    print_metrics("FPGA vs TinyMPC (control raw u*_16)", fpga_vs_tiny_ctrl)
    print_metrics("FPGA vs Generated Reference (state)", fpga_vs_ref)
    print_metrics("TinyMPC vs Generated Reference (state)", tiny_vs_ref)

    if not args.no_plots:
        args.plots_dir.mkdir(parents=True, exist_ok=True)
        _plot_xy_reference_fpga_tinympc(
            args.plots_dir / "xy_plane_reference_fpga_tinympc.png",
            reference,
            fpga,
            tinympc,
        )
        _plot_xy_overlay(args.plots_dir / "xy_overlay.png", [reference, tinympc, fpga])
        _plot_xy_overlay_aligned(
            args.plots_dir / "xy_overlay_aligned.png",
            reference,
            [tinympc, fpga],
            [ref_vs_tiny_fit, ref_vs_fpga_fit],
        )
        _plot_pair_timeseries(
            args.plots_dir / "fpga_vs_tinympc_state_aligned.png",
            "FPGA vs TinyMPC (state, aligned)",
            fpga_vs_tiny_state,
            COMMON_STATE_COLS,
        )
        _plot_pair_timeseries(
            args.plots_dir / "fpga_vs_tinympc_control_aligned.png",
            "FPGA vs TinyMPC (control raw, aligned by lag)",
            fpga_vs_tiny_ctrl,
            COMMON_CONTROL_COLS,
        )
        _plot_pair_timeseries(
            args.plots_dir / "fpga_vs_reference_state_aligned.png",
            "FPGA vs Generated Reference (state, aligned)",
            fpga_vs_ref,
            COMMON_STATE_COLS,
        )
        _plot_pair_timeseries(
            args.plots_dir / "tinympc_vs_reference_state_aligned.png",
            "TinyMPC vs Generated Reference (state, aligned)",
            tiny_vs_ref,
            COMMON_STATE_COLS,
        )
        print(f"\nplots_dir={args.plots_dir}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
