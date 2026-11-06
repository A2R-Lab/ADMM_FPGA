#!/usr/bin/env python3
"""
Run prebuilt bitstreams sequentially on a single FPGA board and collect trajectories/metrics.
"""

from __future__ import annotations

import argparse
import csv
import math
import subprocess
from pathlib import Path


def run_cmd(cmd: list[str], cwd: Path) -> None:
    print(f"+ {' '.join(cmd)}")
    subprocess.run(cmd, cwd=cwd, check=True)


def load_manifest(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with path.open("r", newline="") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows


def load_signal(csv_path: Path, signal: str, time_key: str = "t") -> tuple[list[float], list[float]]:
    t_vals: list[float] = []
    y_vals: list[float] = []
    with csv_path.open("r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            t_vals.append(float(row[time_key]))
            y_vals.append(float(row[signal]))
    return t_vals, y_vals


def compute_step_metrics(
    t_vals: list[float],
    y_vals: list[float],
    y0: float,
    target: float,
    settle_pct: float = 0.02,
    rise_lo: float = 0.1,
    rise_hi: float = 0.9,
) -> dict[str, float]:
    if not t_vals:
        return {"rise_time_s": math.nan, "settling_time_s": math.nan, "overshoot_pct": math.nan, "iae": math.nan}

    amp = target - y0
    err = [target - y for y in y_vals]
    if abs(amp) < 1e-12:
        rise_time = 0.0
        settling_time = 0.0
        overshoot_pct = 0.0
    else:
        lo = y0 + rise_lo * amp
        hi = y0 + rise_hi * amp
        lo_idx = next((i for i, y in enumerate(y_vals) if (y >= lo if amp > 0 else y <= lo)), None)
        hi_idx = next((i for i, y in enumerate(y_vals) if (y >= hi if amp > 0 else y <= hi)), None)
        rise_time = (t_vals[hi_idx] - t_vals[lo_idx]) if (lo_idx is not None and hi_idx is not None and hi_idx >= lo_idx) else math.nan

        tol = settle_pct * abs(amp)
        settling_time = math.nan
        for i in range(len(y_vals)):
            if all(abs(target - yy) <= tol for yy in y_vals[i:]):
                settling_time = t_vals[i]
                break

        peak = max(y_vals) if amp > 0 else min(y_vals)
        overshoot = (peak - target) if amp > 0 else (target - peak)
        overshoot_pct = max(0.0, 100.0 * overshoot / abs(amp))

    iae = 0.0
    for i in range(1, len(t_vals)):
        dt = t_vals[i] - t_vals[i - 1]
        iae += 0.5 * (abs(err[i - 1]) + abs(err[i])) * dt
    return {"rise_time_s": rise_time, "settling_time_s": settling_time, "overshoot_pct": overshoot_pct, "iae": iae}


def compute_control_effort(csv_path: Path) -> float:
    t_vals, u0 = load_signal(csv_path, "u0")
    _, u1 = load_signal(csv_path, "u1")
    _, u2 = load_signal(csv_path, "u2")
    _, u3 = load_signal(csv_path, "u3")
    effort = 0.0
    for i in range(1, len(t_vals)):
        dt = t_vals[i] - t_vals[i - 1]
        umag_prev = abs(u0[i - 1]) + abs(u1[i - 1]) + abs(u2[i - 1]) + abs(u3[i - 1])
        umag_cur = abs(u0[i]) + abs(u1[i]) + abs(u2[i]) + abs(u3[i])
        effort += 0.5 * (umag_prev + umag_cur) * dt
    return effort


def load_existing_ok(metrics_csv: Path) -> set[tuple[int, str]]:
    if not metrics_csv.exists() or metrics_csv.stat().st_size == 0:
        return set()
    out: set[tuple[int, str]] = set()
    with metrics_csv.open("r", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("status", "") == "ok":
                out.add((int(float(row["rho"])), f"{float(row['q']):.12g}"))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Run HIL sweep from prebuilt bitstreams manifest.")
    parser.add_argument(
        "--manifest",
        default="build/bitstreams_grid/manifest.csv",
        help="Manifest from build_bitstreams_parallel.py.",
    )
    parser.add_argument("--vivado-bin", default="vivado", help="Vivado executable.")
    parser.add_argument("--port", default="/dev/ttyUSB1", help="UART serial port.")
    parser.add_argument("--baud", type=int, default=921600, help="UART baud rate.")
    parser.add_argument("--uart-timeout", type=float, default=30.0, help="UART timeout in seconds.")
    parser.add_argument("--sim-freq", type=float, default=200.0, help="HIL simulation frequency [Hz].")
    parser.add_argument("--sim-duration-s", type=float, default=10.0, help="HIL simulation duration [s].")
    parser.add_argument("--step-x", type=float, default=2.0, help="Initial x offset [m].")
    parser.add_argument("--step-y", type=float, default=0.0, help="Initial y offset [m].")
    parser.add_argument("--step-z", type=float, default=0.0, help="Initial z offset [m].")
    parser.add_argument(
        "--output-dir",
        default="plots/hw_controller_grid_from_prebuilt",
        help="Repo-relative folder for per-run trajectories and plots.",
    )
    parser.add_argument(
        "--retry-errors",
        action="store_true",
        help="Retry rows marked as error in existing metrics.csv.",
    )
    parser.add_argument("--continue-on-error", action="store_true", help="Continue if one run fails.")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    manifest = repo_root / args.manifest
    if not manifest.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest}")

    out_dir = repo_root / args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    metrics_csv = out_dir / "metrics.csv"

    fieldnames = [
        "run_idx",
        "rho",
        "q",
        "slug",
        "bit_path",
        "plot_path",
        "traj_csv_path",
        "rise_time_s",
        "settling_time_s",
        "overshoot_pct",
        "iae",
        "control_effort_l1",
        "status",
        "error",
    ]
    if (not metrics_csv.exists()) or metrics_csv.stat().st_size == 0:
        with metrics_csv.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

    existing_ok = load_existing_ok(metrics_csv)
    manifest_rows = [r for r in load_manifest(manifest) if r.get("status", "") == "ok"]

    for run_idx, row in enumerate(manifest_rows, start=1):
        rho = int(float(row["rho"]))
        q = float(row["q"])
        slug = row["slug"]
        bit_path = Path(row["bit_path"])
        if not bit_path.is_absolute():
            bit_path = (repo_root / bit_path).resolve()
        key = (rho, f"{q:.12g}")
        if key in existing_ok and not args.retry_errors:
            print(f"\n=== [{run_idx}/{len(manifest_rows)}] rho={rho}, q={q:.6g} ===")
            print("Skipping (already completed).")
            continue

        title = f"rho={rho}, Q={q:.6g} (Qx=Qy)"
        plot_path = out_dir / f"{run_idx:03d}_{slug}.png"
        traj_path = out_dir / f"{run_idx:03d}_{slug}.csv"
        print(f"\n=== [{run_idx}/{len(manifest_rows)}] {title} ===")
        status = "ok"
        err_msg = ""
        metrics = {
            "rise_time_s": math.nan,
            "settling_time_s": math.nan,
            "overshoot_pct": math.nan,
            "iae": math.nan,
            "control_effort_l1": math.nan,
        }
        try:
            run_cmd(
                [
                    args.vivado_bin,
                    "-mode",
                    "batch",
                    "-source",
                    str(repo_root / "scripts" / "program_file.tcl"),
                    "-tclargs",
                    str(bit_path),
                    "-notrace",
                ],
                cwd=repo_root,
            )

            run_cmd(
                [
                    "python3",
                    str(repo_root / "scripts" / "hw_in_loop_simulation.py"),
                    "--port",
                    args.port,
                    "--baud",
                    str(args.baud),
                    "--uart-timeout",
                    str(args.uart_timeout),
                    "--freq",
                    str(args.sim_freq),
                    "--duration-s",
                    str(args.sim_duration_s),
                    "--step-x",
                    str(args.step_x),
                    "--step-y",
                    str(args.step_y),
                    "--step-z",
                    str(args.step_z),
                    "--title",
                    title,
                    "--save-plot",
                    str(plot_path),
                    "--save-csv",
                    str(traj_path),
                    "--no-show",
                    "--quiet",
                ],
                cwd=repo_root,
            )

            t_vals, x_vals = load_signal(traj_path, "x0")
            metrics.update(compute_step_metrics(t_vals=t_vals, y_vals=x_vals, y0=float(args.step_x), target=0.0))
            metrics["control_effort_l1"] = compute_control_effort(traj_path)
            print(f"saved: plot={plot_path.relative_to(repo_root)} traj={traj_path.relative_to(repo_root)}")
        except Exception as exc:
            status = "error"
            err_msg = str(exc)
            print(f"ERROR: {err_msg}")
            if not args.continue_on_error:
                raise
        finally:
            with metrics_csv.open("a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writerow(
                    {
                        "run_idx": run_idx,
                        "rho": rho,
                        "q": q,
                        "slug": slug,
                        "bit_path": str(bit_path),
                        "plot_path": str(plot_path.relative_to(repo_root)),
                        "traj_csv_path": str(traj_path.relative_to(repo_root)),
                        "rise_time_s": metrics["rise_time_s"],
                        "settling_time_s": metrics["settling_time_s"],
                        "overshoot_pct": metrics["overshoot_pct"],
                        "iae": metrics["iae"],
                        "control_effort_l1": metrics["control_effort_l1"],
                        "status": status,
                        "error": err_msg,
                    }
                )

    print(f"\nDone. Metrics: {metrics_csv}")
    print(f"Trajectories + plots: {out_dir}")


if __name__ == "__main__":
    main()
