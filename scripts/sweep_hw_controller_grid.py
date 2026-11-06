#!/usr/bin/env python3
"""
Grid sweep for FPGA controller tuning over rho and selected Q diagonal values.

For each (rho, q) with qx=qy=q:
1) regenerate headers with fixed ADMM iterations
2) build/program FPGA
3) run hardware-in-loop simulation with step input
4) save plot + trajectory CSV + quality metrics
"""

from __future__ import annotations

import argparse
import csv
import itertools
import math
import os
import subprocess
from pathlib import Path

DEFAULT_RHO_VALUES = [1, 4, 8, 16, 32, 64, 128, 256]
DEFAULT_Q_VALUES = [100, 200, 500, 1000, 2000, 5000, 10000, 20000]
DEFAULT_Q_DIAG = [70.0, 70.0, 178.0, 0.4, 0.4, 40.0, 3.5, 3.5, 4.0, 0.2, 0.2, 25.0]


def parse_int_list(text: str, what: str) -> list[int]:
    vals = [int(tok.strip()) for tok in text.split(",") if tok.strip()]
    if not vals:
        raise ValueError(f"No values parsed from {what}")
    return vals


def parse_float_list(text: str, what: str) -> list[float]:
    vals = [float(tok.strip()) for tok in text.split(",") if tok.strip()]
    if not vals:
        raise ValueError(f"No values parsed from {what}")
    return vals


def run_cmd(cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    print(f"+ {' '.join(cmd)}")
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def make_generation_env(*, horizon: int, admm_iters: int, rho: int, qx: float, qy: float) -> dict[str, str]:
    q_diag = list(DEFAULT_Q_DIAG)
    q_diag[0] = qx
    q_diag[1] = qy
    env = os.environ.copy()
    env["ADMM_HORIZON_LENGTH"] = str(horizon)
    env["ADMM_ITERATIONS"] = str(admm_iters)
    env["ADMM_RHO_EQ_PARAM"] = str(rho)
    env["ADMM_RHO_INEQ_PARAM"] = str(rho)
    env["ADMM_Q_DIAG"] = ",".join(f"{v:.12g}" for v in q_diag)
    return env


def run_generators(repo_root: Path, env: dict[str, str]) -> None:
    scripts_dir = repo_root / "scripts"
    run_cmd(["python3", str(scripts_dir / "trajectory_generator.py")], cwd=repo_root, env=env)
    run_cmd(["python3", str(scripts_dir / "header_generator.py")], cwd=repo_root, env=env)


def make_slug(x: float) -> str:
    s = f"{x:.6g}"
    s = s.replace("-", "m").replace(".", "p")
    return s


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
    settle_pct: float,
    rise_lo: float,
    rise_hi: float,
) -> dict[str, float]:
    if not t_vals:
        return {
            "rise_time_s": math.nan,
            "settling_time_s": math.nan,
            "overshoot_pct": math.nan,
            "iae": math.nan,
        }

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
        overshoot = ((peak - target) if amp > 0 else (target - peak))
        overshoot_pct = max(0.0, 100.0 * overshoot / abs(amp))

    iae = 0.0
    for i in range(1, len(t_vals)):
        dt = t_vals[i] - t_vals[i - 1]
        iae += 0.5 * (abs(err[i - 1]) + abs(err[i])) * dt

    return {
        "rise_time_s": rise_time,
        "settling_time_s": settling_time,
        "overshoot_pct": overshoot_pct,
        "iae": iae,
    }


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


def normalize(v: float, lo: float, hi: float) -> float:
    if not math.isfinite(v) or not math.isfinite(lo) or not math.isfinite(hi):
        return math.nan
    if hi <= lo:
        return 0.0
    return (v - lo) / (hi - lo)


def combo_key(rho: int, qx: float, qy: float) -> tuple[int, str, str]:
    return (rho, f"{qx:.12g}", f"{qy:.12g}")


def load_existing_rows(metrics_csv: Path) -> list[dict[str, object]]:
    if not metrics_csv.exists() or metrics_csv.stat().st_size == 0:
        return []

    dedup: dict[tuple[int, str, str], dict[str, object]] = {}
    with metrics_csv.open("r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                rho = int(float(row["rho"]))
                qx = float(row["qx"])
                qy = float(row["qy"])
            except (KeyError, ValueError, TypeError):
                continue
            key = combo_key(rho, qx, qy)
            dedup[key] = {
                "run_idx": int(float(row.get("run_idx", 0) or 0)),
                "rho": rho,
                "qx": qx,
                "qy": qy,
                "plot_path": row.get("plot_path", ""),
                "traj_csv_path": row.get("traj_csv_path", ""),
                "rise_time_s": float(row.get("rise_time_s", "nan") or "nan"),
                "settling_time_s": float(row.get("settling_time_s", "nan") or "nan"),
                "overshoot_pct": float(row.get("overshoot_pct", "nan") or "nan"),
                "iae": float(row.get("iae", "nan") or "nan"),
                "control_effort_l1": float(row.get("control_effort_l1", "nan") or "nan"),
                "score": float(row.get("score", "nan") or "nan"),
                "rank": row.get("rank", ""),
                "status": row.get("status", ""),
                "error": row.get("error", ""),
            }
    return sorted(dedup.values(), key=lambda r: int(r["run_idx"]))


def main() -> None:
    parser = argparse.ArgumentParser(description="Sweep FPGA controller parameters rho/Q with HIL plots (Qx=Qy).")
    parser.add_argument("--board", default="arty", help="Make BOARD target.")
    parser.add_argument("--horizon", type=int, default=20, help="MPC horizon passed to header generator.")
    parser.add_argument("--admm-iters", type=int, default=28, help="ADMM iterations fixed in hardware.")
    parser.add_argument(
        "--rho-values",
        default=",".join(str(v) for v in DEFAULT_RHO_VALUES),
        help="Comma-separated rho values (must each be power of 2).",
    )
    parser.add_argument(
        "--q-values",
        default=",".join(f"{v:.2f}" for v in DEFAULT_Q_VALUES),
        help="Comma-separated candidate values for both Q[0,0] and Q[1,1].",
    )
    parser.add_argument("--port", default="/dev/ttyUSB1", help="UART serial port.")
    parser.add_argument("--baud", type=int, default=921600, help="UART baud rate.")
    parser.add_argument("--uart-timeout", type=float, default=30.0, help="UART timeout in seconds for simulation.")
    parser.add_argument("--sim-freq", type=float, default=200.0, help="HIL simulation frequency [Hz].")
    parser.add_argument("--sim-duration-s", type=float, default=10.0, help="HIL simulation duration [s].")
    parser.add_argument("--step-x", type=float, default=2.0, help="Initial x offset (step) [m].")
    parser.add_argument("--step-y", type=float, default=0.5, help="Initial y offset (step) [m].")
    parser.add_argument("--step-z", type=float, default=0.0, help="Initial z offset (step) [m].")
    parser.add_argument("--skip-build", action="store_true", help="Skip `make bit` step.")
    parser.add_argument("--skip-program", action="store_true", help="Skip `make program` step.")
    parser.add_argument(
        "--retry-errors",
        action="store_true",
        help="Retry points marked as error in existing metrics.csv.",
    )
    parser.add_argument("--continue-on-error", action="store_true", help="Continue grid even if one point fails.")
    parser.add_argument(
        "--output-dir",
        default="plots/hw_controller_grid",
        help="Repo-relative output directory for plots, trajectories, and metrics.",
    )
    args = parser.parse_args()

    if args.horizon <= 0:
        raise ValueError("--horizon must be > 0")
    if args.admm_iters <= 0:
        raise ValueError("--admm-iters must be > 0")
    if args.sim_freq <= 0:
        raise ValueError("--sim-freq must be > 0")
    if args.sim_duration_s <= 0:
        raise ValueError("--sim-duration-s must be > 0")

    rho_vals = parse_int_list(args.rho_values, "--rho-values")
    for rho in rho_vals:
        if rho <= 0:
            raise ValueError("All rho values must be > 0")
        if rho & (rho - 1):
            raise ValueError(f"rho={rho} is not a power of 2")
    q_vals = parse_float_list(args.q_values, "--q-values")
    if any(v <= 0 for v in q_vals):
        raise ValueError("All Q values must be > 0")

    repo_root = Path(__file__).resolve().parents[1]
    scripts_dir = repo_root / "scripts"
    out_dir = repo_root / args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    metrics_csv = out_dir / "metrics.csv"
    fieldnames = [
        "run_idx",
        "rho",
        "qx",
        "qy",
        "plot_path",
        "traj_csv_path",
        "rise_time_s",
        "settling_time_s",
        "overshoot_pct",
        "iae",
        "control_effort_l1",
        "score",
        "rank",
        "status",
        "error",
    ]
    combos = list(itertools.product(rho_vals, q_vals))
    all_rows = load_existing_rows(metrics_csv)
    by_key: dict[tuple[int, str, str], dict[str, object]] = {
        combo_key(int(r["rho"]), float(r["qx"]), float(r["qy"])): r for r in all_rows
    }

    if (not metrics_csv.exists()) or metrics_csv.stat().st_size == 0:
        with metrics_csv.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

    for run_idx, (rho, q) in enumerate(combos, start=1):
        qx = q
        qy = q
        key = combo_key(rho, qx, qy)
        existing = by_key.get(key)
        if existing is not None:
            existing_status = str(existing.get("status", ""))
            if existing_status == "ok":
                print(f"\n=== [{run_idx}/{len(combos)}] rho={rho}, Q={q:.6g} ===")
                print("Skipping (already completed).")
                continue
            if existing_status == "error" and not args.retry_errors:
                print(f"\n=== [{run_idx}/{len(combos)}] rho={rho}, Q={q:.6g} ===")
                print("Skipping previous error (use --retry-errors to rerun).")
                continue

        slug = f"r{rho}_q{make_slug(q)}"
        plot_path = out_dir / f"{run_idx:03d}_{slug}.png"
        traj_path = out_dir / f"{run_idx:03d}_{slug}.csv"
        title = f"rho={rho}, Q={q:.6g} (Qx=Qy)"
        print(f"\n=== [{run_idx}/{len(combos)}] {title} ===")

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
            gen_env = make_generation_env(
                horizon=args.horizon,
                admm_iters=args.admm_iters,
                rho=rho,
                qx=qx,
                qy=qy,
            )
            run_generators(repo_root, gen_env)

            if not args.skip_build:
                run_cmd(["make", f"BOARD={args.board}", "bit"], cwd=repo_root)

            if not args.skip_program:
                run_cmd(["make", f"BOARD={args.board}", "program"], cwd=repo_root)

            run_cmd(
                [
                    "python3",
                    str(scripts_dir / "hw_in_loop_simulation.py"),
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
            metrics.update(
                compute_step_metrics(
                    t_vals=t_vals,
                    y_vals=x_vals,
                    y0=float(args.step_x),
                    target=0.0,
                    settle_pct=0.02,
                    rise_lo=0.1,
                    rise_hi=0.9,
                )
            )
            metrics["control_effort_l1"] = compute_control_effort(traj_path)
            print(f"saved: plot={plot_path.relative_to(repo_root)} traj={traj_path.relative_to(repo_root)}")
            print(
                "metrics: "
                f"rise={metrics['rise_time_s']:.4f}s "
                f"settle={metrics['settling_time_s']:.4f}s "
                f"overshoot={metrics['overshoot_pct']:.2f}% "
                f"IAE={metrics['iae']:.4f} "
                f"Ueff={metrics['control_effort_l1']:.4f}"
            )
        except Exception as exc:
            status = "error"
            err_msg = str(exc)
            print(f"ERROR: {err_msg}")
            if not args.continue_on_error:
                raise
        finally:
            row_data = {
                "run_idx": run_idx,
                "rho": rho,
                "qx": qx,
                "qy": qy,
                "plot_path": str(plot_path.relative_to(repo_root)),
                "traj_csv_path": str(traj_path.relative_to(repo_root)),
                "rise_time_s": metrics["rise_time_s"],
                "settling_time_s": metrics["settling_time_s"],
                "overshoot_pct": metrics["overshoot_pct"],
                "iae": metrics["iae"],
                "control_effort_l1": metrics["control_effort_l1"],
                "score": math.nan,
                "rank": "",
                "status": status,
                "error": err_msg,
            }
            by_key[key] = row_data
            all_rows = sorted(by_key.values(), key=lambda r: int(r["run_idx"]))
            with metrics_csv.open("a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writerow(row_data)

    ok_rows = [r for r in all_rows if r["status"] == "ok"]
    if ok_rows:
        rise_vals = [float(r["rise_time_s"]) for r in ok_rows]
        settle_vals = [float(r["settling_time_s"]) for r in ok_rows]
        over_vals = [float(r["overshoot_pct"]) for r in ok_rows]
        effort_vals = [float(r["control_effort_l1"]) for r in ok_rows]

        rise_lo, rise_hi = min(rise_vals), max(rise_vals)
        settle_lo, settle_hi = min(settle_vals), max(settle_vals)
        over_lo, over_hi = min(over_vals), max(over_vals)
        effort_lo, effort_hi = min(effort_vals), max(effort_vals)

        for row in ok_rows:
            n_rise = normalize(float(row["rise_time_s"]), rise_lo, rise_hi)
            n_settle = normalize(float(row["settling_time_s"]), settle_lo, settle_hi)
            n_over = normalize(float(row["overshoot_pct"]), over_lo, over_hi)
            n_eff = normalize(float(row["control_effort_l1"]), effort_lo, effort_hi)
            row["score"] = 0.45 * n_settle + 0.25 * n_rise + 0.20 * n_over + 0.10 * n_eff

        ranked = sorted(ok_rows, key=lambda r: float(r["score"]))
        for idx, row in enumerate(ranked, start=1):
            row["rank"] = idx

        with metrics_csv.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in all_rows:
                writer.writerow(row)

        top_n = min(10, len(ranked))
        print(f"\nTop {top_n} candidates (lower score is better):")
        for row in ranked[:top_n]:
            print(
                f"rank={row['rank']} rho={row['rho']} qx={row['qx']} qy={row['qy']} "
                f"score={float(row['score']):.4f} "
                f"settle={float(row['settling_time_s']):.4f}s "
                f"rise={float(row['rise_time_s']):.4f}s "
                f"overshoot={float(row['overshoot_pct']):.2f}% "
                f"eff={float(row['control_effort_l1']):.4f}"
            )

    with metrics_csv.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in all_rows:
            writer.writerow(row)

    print(f"\nSweep complete. Metrics: {metrics_csv}")
    print(f"Plots + trajectories: {out_dir}")


if __name__ == "__main__":
    main()
