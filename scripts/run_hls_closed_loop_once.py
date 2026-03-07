#!/usr/bin/env python3
"""
Run one ADMM HLS closed-loop csim and plot the trajectory once.
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import re
import subprocess
import threading
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from parameters import Q_DIAG, R_DIAG, RHO_PARAM, TRAJ_DT, TRAJ_LENGTH, TRAJ_WARMSTART_PAD


def parse_u_hover_from_data_h(data_h_path: Path) -> float:
    text = data_h_path.read_text()
    m_hover = re.search(r"^\s*#define\s+U_HOVER\s+([^\s]+)\s*$", text, re.MULTILINE)
    if m_hover is not None:
        return float(m_hover.group(1))
    m_min = re.search(r"^\s*#define\s+U_MIN\s+([^\s]+)\s*$", text, re.MULTILINE)
    if m_min is None:
        raise ValueError("Neither U_HOVER nor U_MIN found in data.h")
    # Backward compatibility with older data.h files where U_MIN = -u_hover.
    return -float(m_min.group(1))


def parse_int_define_from_data_h(data_h_path: Path, define_name: str) -> int:
    text = data_h_path.read_text()
    m = re.search(rf"^\s*#define\s+{define_name}\s+([0-9]+)\s*$", text, re.MULTILINE)
    if m is None:
        raise ValueError(f"{define_name} not found in data.h")
    return int(m.group(1))


def parse_float_define_from_data_h(data_h_path: Path, define_name: str) -> float:
    text = data_h_path.read_text()
    m = re.search(rf"^\s*#define\s+{define_name}\s+([^\s]+)\s*$", text, re.MULTILINE)
    if m is None:
        raise ValueError(f"{define_name} not found in data.h")
    return float(m.group(1))


def load_reference_csv(csv_path: Path) -> tuple[list[list[float]], list[list[float]]]:
    x_ref_rows: list[list[float]] = []
    u_ref_rows: list[list[float]] = []
    with csv_path.open("r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            x_ref_rows.append([float(row[f"x{i}"]) for i in range(12)])
            u_ref_rows.append([float(row[f"u{i}"]) for i in range(4)])
    return x_ref_rows, u_ref_rows


def parse_ref_dt_from_csv(csv_path: Path) -> float | None:
    with csv_path.open("r", newline="") as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            rows.append(float(row["t"]))
            if len(rows) >= 2:
                break
    if len(rows) < 2:
        return None
    dt = rows[1] - rows[0]
    if dt <= 0:
        return None
    return dt


def generate_trajectory_plot(
    csv_path: Path,
    png_path: Path,
    title: str,
    state_setpoint_t: list[list[float]],
    control_setpoint_t: list[list[float]],
    control_limits_abs: tuple[float, float] | None = None,
    metrics_text: str | None = None,
) -> float:
    t_vals: list[float] = []
    x = [[] for _ in range(12)]
    u0: list[float] = []
    u1: list[float] = []
    u2: list[float] = []
    u3: list[float] = []
    primal_residual: list[float] = []
    dual_residual: list[float] = []
    has_residuals = False

    with csv_path.open("r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            t_vals.append(float(row["t"]))
            for i in range(12):
                x[i].append(float(row[f"x{i}"]))
            u0.append(float(row["u0"]))
            u1.append(float(row["u1"]))
            u2.append(float(row["u2"]))
            u3.append(float(row["u3"]))
            p_res = row.get("primal_residual")
            d_res = row.get("dual_residual")
            if p_res is not None and d_res is not None and p_res != "" and d_res != "":
                primal_residual.append(float(p_res))
                dual_residual.append(float(d_res))
                has_residuals = True

    if len(state_setpoint_t) != len(t_vals):
        raise ValueError("state_setpoint_t length must match trajectory length")
    if len(control_setpoint_t) != len(t_vals):
        raise ValueError("control_setpoint_t length must match trajectory length")

    fig = plt.figure(figsize=(14, 12))
    gs = fig.add_gridspec(4, 2, hspace=0.3)
    ax_pos = fig.add_subplot(gs[0, 0])
    ax_att = fig.add_subplot(gs[0, 1])
    ax_vel = fig.add_subplot(gs[1, 0])
    ax_angvel = fig.add_subplot(gs[1, 1])
    ax_u = fig.add_subplot(gs[2, 0])
    ax_xy = fig.add_subplot(gs[2, 1])
    ax_res = fig.add_subplot(gs[3, :])

    l0 = ax_pos.plot(t_vals, x[0], label="x")[0]
    l1 = ax_pos.plot(t_vals, x[1], label="y")[0]
    l2 = ax_pos.plot(t_vals, x[2], label="z")[0]
    ax_pos.plot(t_vals, [row[0] for row in state_setpoint_t], "--", color=l0.get_color(), label="x_sp")
    ax_pos.plot(t_vals, [row[1] for row in state_setpoint_t], "--", color=l1.get_color(), label="y_sp")
    ax_pos.plot(t_vals, [row[2] for row in state_setpoint_t], "--", color=l2.get_color(), label="z_sp")
    ax_pos.set_title("Position [x y z]")
    ax_pos.set_ylabel("m")
    ax_pos.grid(True)
    ax_pos.legend()

    l3 = ax_att.plot(t_vals, x[3], label="roll")[0]
    l4 = ax_att.plot(t_vals, x[4], label="pitch")[0]
    l5 = ax_att.plot(t_vals, x[5], label="yaw")[0]
    ax_att.plot(t_vals, [row[3] for row in state_setpoint_t], "--", color=l3.get_color(), label="roll_sp")
    ax_att.plot(t_vals, [row[4] for row in state_setpoint_t], "--", color=l4.get_color(), label="pitch_sp")
    ax_att.plot(t_vals, [row[5] for row in state_setpoint_t], "--", color=l5.get_color(), label="yaw_sp")
    ax_att.set_title("Orientation [roll pitch yaw]")
    ax_att.set_ylabel("rad")
    ax_att.grid(True)
    ax_att.legend()

    l6 = ax_vel.plot(t_vals, x[6], label="vx")[0]
    l7 = ax_vel.plot(t_vals, x[7], label="vy")[0]
    l8 = ax_vel.plot(t_vals, x[8], label="vz")[0]
    ax_vel.plot(t_vals, [row[6] for row in state_setpoint_t], "--", color=l6.get_color(), label="vx_sp")
    ax_vel.plot(t_vals, [row[7] for row in state_setpoint_t], "--", color=l7.get_color(), label="vy_sp")
    ax_vel.plot(t_vals, [row[8] for row in state_setpoint_t], "--", color=l8.get_color(), label="vz_sp")
    ax_vel.set_title("Linear Velocity")
    ax_vel.set_ylabel("m/s")
    ax_vel.grid(True)
    ax_vel.legend()

    l9 = ax_angvel.plot(t_vals, x[9], label="wx")[0]
    l10 = ax_angvel.plot(t_vals, x[10], label="wy")[0]
    l11 = ax_angvel.plot(t_vals, x[11], label="wz")[0]
    ax_angvel.plot(t_vals, [row[9] for row in state_setpoint_t], "--", color=l9.get_color(), label="wx_sp")
    ax_angvel.plot(t_vals, [row[10] for row in state_setpoint_t], "--", color=l10.get_color(), label="wy_sp")
    ax_angvel.plot(t_vals, [row[11] for row in state_setpoint_t], "--", color=l11.get_color(), label="wz_sp")
    ax_angvel.set_title("Angular Velocity")
    ax_angvel.set_ylabel("rad/s")
    ax_angvel.grid(True)
    ax_angvel.legend()

    lu0 = ax_u.plot(t_vals, u0, label="u0")[0]
    lu1 = ax_u.plot(t_vals, u1, label="u1")[0]
    lu2 = ax_u.plot(t_vals, u2, label="u2")[0]
    lu3 = ax_u.plot(t_vals, u3, label="u3")[0]
    ax_u.plot(t_vals, [row[0] for row in control_setpoint_t], "--", color=lu0.get_color(), label="u0_sp")
    ax_u.plot(t_vals, [row[1] for row in control_setpoint_t], "--", color=lu1.get_color(), label="u1_sp")
    ax_u.plot(t_vals, [row[2] for row in control_setpoint_t], "--", color=lu2.get_color(), label="u2_sp")
    ax_u.plot(t_vals, [row[3] for row in control_setpoint_t], "--", color=lu3.get_color(), label="u3_sp")
    if control_limits_abs is not None:
        u_min_abs, u_max_abs = control_limits_abs
        ax_u.axhline(u_min_abs, color="k", linestyle=":", linewidth=1.2, label="u_min")
        ax_u.axhline(u_max_abs, color="k", linestyle="--", linewidth=1.2, label="u_max")
    ax_u.set_xlabel("Time [s]")
    ax_u.set_ylabel("Control")
    ax_u.grid(True)
    ax_u.legend()

    ax_xy.plot(x[0], x[1], label="trajectory_xy")
    ax_xy.plot(
        [row[0] for row in state_setpoint_t],
        [row[1] for row in state_setpoint_t],
        "--",
        label="setpoint_xy",
    )
    ax_xy.set_title("x vs y")
    ax_xy.set_xlabel("x [m]")
    ax_xy.set_ylabel("y [m]")
    ax_xy.grid(True)
    ax_xy.axis("equal")
    ax_xy.legend()

    if has_residuals and len(primal_residual) == len(t_vals) and len(dual_residual) == len(t_vals):
        ax_res.plot(t_vals, primal_residual, label="primal residual")
        ax_res.plot(t_vals, dual_residual, label="dual residual")
        if all(v > 0.0 for v in primal_residual) and all(v > 0.0 for v in dual_residual):
            ax_res.set_yscale("log")
        ax_res.set_title("ADMM Residuals")
        ax_res.set_ylabel("L2 norm")
        ax_res.grid(True)
        ax_res.legend()
    else:
        ax_res.set_title("ADMM Residuals (not available in CSV)")
        ax_res.grid(True)
    ax_res.set_xlabel("Time [s]")

    fig.suptitle(title)
    if metrics_text:
        fig.text(
            0.99,
            0.985,
            metrics_text,
            ha="right",
            va="top",
            fontsize=9,
            family="monospace",
            bbox={"boxstyle": "round", "facecolor": "white", "alpha": 0.85, "edgecolor": "0.5"},
        )
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    png_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(png_path, dpi=140)
    plt.close(fig)
    return x[0][-1] if x[0] else math.nan


def compute_position_mse_xyz(
    csv_path: Path,
    state_setpoint_t: list[list[float]],
    active_ref_mask: list[bool],
) -> tuple[float, float, float]:
    if len(state_setpoint_t) != len(active_ref_mask):
        raise ValueError("state_setpoint_t and active_ref_mask length mismatch")

    sum_sq_x = 0.0
    sum_sq_y = 0.0
    sum_sq_z = 0.0
    n = 0
    with csv_path.open("r", newline="") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if i >= len(active_ref_mask):
                break
            if not active_ref_mask[i]:
                continue
            dx = float(row["x0"]) - state_setpoint_t[i][0]
            dy = float(row["x1"]) - state_setpoint_t[i][1]
            dz = float(row["x2"]) - state_setpoint_t[i][2]
            sum_sq_x += dx * dx
            sum_sq_y += dy * dy
            sum_sq_z += dz * dz
            n += 1

    if n == 0:
        return math.nan, math.nan, math.nan
    return sum_sq_x / n, sum_sq_y / n, sum_sq_z / n


def compute_position_error_integral_xyz(
    csv_path: Path,
    state_setpoint_t: list[list[float]],
    active_ref_mask: list[bool],
) -> float:
    if len(state_setpoint_t) != len(active_ref_mask):
        raise ValueError("state_setpoint_t and active_ref_mask length mismatch")

    t_vals: list[float] = []
    err_norms: list[float] = []
    with csv_path.open("r", newline="") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if i >= len(active_ref_mask):
                break
            if not active_ref_mask[i]:
                continue
            dx = float(row["x0"]) - state_setpoint_t[i][0]
            dy = float(row["x1"]) - state_setpoint_t[i][1]
            dz = float(row["x2"]) - state_setpoint_t[i][2]
            t_vals.append(float(row["t"]))
            err_norms.append(math.sqrt(dx * dx + dy * dy + dz * dz))

    if len(t_vals) < 2:
        return math.nan

    integral = 0.0
    for i in range(1, len(t_vals)):
        dt = t_vals[i] - t_vals[i - 1]
        if dt <= 0.0:
            continue
        integral += 0.5 * (err_norms[i] + err_norms[i - 1]) * dt
    return integral


def run_cmd_streaming(
    cmd: list[str],
    cwd: Path,
    env: dict[str, str] | None,
    stdout_log: Path,
    stderr_log: Path,
    prefix: str,
    timeout_s: float | None = None,
) -> tuple[int, str, str]:
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1,
    )

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    def pump(pipe, sink: list[str], tag: str) -> None:
        assert pipe is not None
        for line in iter(pipe.readline, ""):
            sink.append(line)
            print(f"[{prefix} {tag}] {line}", end="")
        pipe.close()

    t_out = threading.Thread(target=pump, args=(proc.stdout, stdout_lines, "stdout"), daemon=True)
    t_err = threading.Thread(target=pump, args=(proc.stderr, stderr_lines, "stderr"), daemon=True)
    t_out.start()
    t_err.start()

    try:
        proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        t_out.join()
        t_err.join()
        out = "".join(stdout_lines)
        err = "".join(stderr_lines)
        stdout_log.write_text(out)
        stderr_log.write_text(err)
        raise

    t_out.join()
    t_err.join()
    out = "".join(stdout_lines)
    err = "".join(stderr_lines)
    stdout_log.write_text(out)
    stderr_log.write_text(err)
    return proc.returncode, out, err


def parse_args() -> argparse.Namespace:
    default_traj_samples = TRAJ_LENGTH + (2 * TRAJ_WARMSTART_PAD)
    default_sim_duration_s = (default_traj_samples - 1) * TRAJ_DT
    parser = argparse.ArgumentParser(description="Run one ADMM HLS closed-loop csim and plot one trajectory.")
    parser.add_argument("--sim-freq", type=float, default=500.0)
    parser.add_argument("--sim-duration-s", type=float, default=default_sim_duration_s)
    parser.add_argument("--step-x", type=float, default=0.0)
    parser.add_argument("--step-y", type=float, default=0.0)
    parser.add_argument("--step-z", type=float, default=0.0)
    parser.add_argument("--step-yaw", type=float, default=0.0)
    parser.add_argument(
        "--horizon",
        type=int,
        default=None,
        help="Override ADMM_HORIZON_LENGTH for this run (applied to trajectory/header generation).",
    )
    parser.add_argument(
        "--traj-start-step",
        type=int,
        default=0,
        help="Step index where time-varying trajectory starts in ADMM_closed_loop_tb.cpp.",
    )
    parser.add_argument("--timeout-s", type=float, default=1200.0, help="csim timeout in seconds, <=0 disables.")
    parser.add_argument(
        "--output-dir",
        default="plots/hls_csim_closed_loop_once",
        help="Output root for one-shot run artifacts.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.sim_freq <= 0 or args.sim_duration_s <= 0:
        raise ValueError("sim-freq and sim-duration-s must be > 0")

    repo_root = Path(__file__).resolve().parents[1]
    out_root = (repo_root / args.output_dir).resolve()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_root = out_root / f"run_{timestamp}"
    logs_dir = run_root / "logs"
    out_dir = run_root / "outputs"
    hls_work_dir = run_root / "hls_work"
    logs_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Run in-place in the ADMM project directory.
    src_dir = (repo_root / "vitis_projects" / "ADMM").resolve()
    run_env = os.environ.copy()
    if args.horizon is not None:
        run_env["ADMM_HORIZON_LENGTH"] = str(args.horizon)

    traj_cmd = [
        "python3",
        str(repo_root / "scripts" / "trajectory_generator.py"),
    ]
    traj_stdout_log = logs_dir / "traj.stdout.log"
    traj_stderr_log = logs_dir / "traj.stderr.log"
    traj_rc, _, _ = run_cmd_streaming(
        cmd=traj_cmd,
        cwd=repo_root,
        env=run_env,
        stdout_log=traj_stdout_log,
        stderr_log=traj_stderr_log,
        prefix="traj",
    )
    if traj_rc != 0:
        print(f"trajectory_generator failed ({traj_rc})")
        print(f"See logs: {logs_dir}")
        return 1

    header_cmd = [
        "python3",
        str(repo_root / "scripts" / "header_generator.py"),
    ]
    header_stdout_log = logs_dir / "header.stdout.log"
    header_stderr_log = logs_dir / "header.stderr.log"
    header_rc, _, _ = run_cmd_streaming(
        cmd=header_cmd,
        cwd=repo_root,
        env=run_env,
        stdout_log=header_stdout_log,
        stderr_log=header_stderr_log,
        prefix="header",
    )
    if header_rc != 0:
        print(f"header_generator failed ({header_rc})")
        print(f"See logs: {logs_dir}")
        return 1

    expected_data_h = src_dir / "data.h"
    if not expected_data_h.exists():
        print("header_generator succeeded but data.h is missing")
        print(f"Checked: {expected_data_h}")
        print(f"See logs: {logs_dir}")
        return 1

    traj_path = out_dir / "trajectory.csv"
    env = run_env.copy()
    env["ADMM_CSIM_TRAJ_PATH"] = str(traj_path)
    env["ADMM_SIM_FREQ"] = f"{args.sim_freq:.12g}"
    env["ADMM_SIM_DURATION_S"] = f"{args.sim_duration_s:.12g}"
    env["ADMM_STEP_X"] = f"{args.step_x:.12g}"
    env["ADMM_STEP_Y"] = f"{args.step_y:.12g}"
    env["ADMM_STEP_Z"] = f"{args.step_z:.12g}"
    env["ADMM_STEP_YAW"] = f"{args.step_yaw:.12g}"

    csim_cmd = [
        "vitis-run",
        "--mode",
        "hls",
        "--csim",
        "--config",
        "./hls_eval_config.cfg",
        "--work_dir",
        str(hls_work_dir),
    ]
    csim_stdout_log = logs_dir / "csim.stdout.log"
    csim_stderr_log = logs_dir / "csim.stderr.log"
    try:
        csim_rc, csim_stdout, csim_stderr = run_cmd_streaming(
            cmd=csim_cmd,
            cwd=src_dir,
            env=env,
            stdout_log=csim_stdout_log,
            stderr_log=csim_stderr_log,
            prefix="csim",
            timeout_s=(None if args.timeout_s <= 0 else args.timeout_s),
        )
    except subprocess.TimeoutExpired:
        print(f"csim timeout after {args.timeout_s:.1f}s")
        return 1

    if csim_rc != 0:
        print(f"csim failed ({csim_rc})")
        print(f"See logs: {logs_dir}")
        return 1

    text = csim_stdout + "\n" + csim_stderr
    m = re.search(r"EARLY_STOP\s+step=([^\s]+)\s+reason=([^\s]+)", text)
    early_step = m.group(1) if m else "unknown"
    early_reason = m.group(2) if m else "missing_from_logs"

    if not traj_path.exists():
        print("csim succeeded but trajectory.csv is missing")
        print(f"See logs: {logs_dir}")
        return 1

    plot_path = out_dir / "trajectory.png"
    u_hover = parse_u_hover_from_data_h(expected_data_h)
    u_min_delta = parse_float_define_from_data_h(expected_data_h, "U_MIN")
    u_max_delta = parse_float_define_from_data_h(expected_data_h, "U_MAX")
    u_min_abs = u_hover + u_min_delta
    u_max_abs = u_hover + u_max_delta
    traj_tick_div = parse_int_define_from_data_h(expected_data_h, "TRAJ_TICK_DIV")
    horizon_len = parse_int_define_from_data_h(expected_data_h, "HORIZON_LENGTH")
    try:
        warmstart_pad = parse_int_define_from_data_h(expected_data_h, "TRAJ_WARMSTART_PAD")
    except RuntimeError:
        warmstart_pad = max(horizon_len - 1, 0)
    ref_csv_path = repo_root / "vitis_projects" / "ADMM" / "trajectory_refs.csv"
    ref_dt = parse_ref_dt_from_csv(ref_csv_path) if ref_csv_path.exists() else None
    if ref_dt is not None:
        expected_tick_div = int(round(ref_dt * args.sim_freq))
        if expected_tick_div < 1:
            expected_tick_div = 1
        if expected_tick_div != traj_tick_div:
            print(
                "warning: timing mismatch between sim and trajectory references: "
                f"sim_freq={args.sim_freq:g}Hz, ref_dt={ref_dt:g}s => expected TRAJ_TICK_DIV={expected_tick_div}, "
                f"but compiled TRAJ_TICK_DIV={traj_tick_div}."
            )
            print("warning: this will distort reference timing and can make plots look wrong.")
    n_rows = sum(1 for _ in csv.DictReader(traj_path.open("r", newline="")))

    if ref_csv_path.exists():
        x_ref_rows, u_ref_rows = load_reference_csv(ref_csv_path)
        if len(x_ref_rows) == 0:
            state_setpoint_t = [[0.0] * 12 for _ in range(n_rows)]
            control_setpoint_t = [[u_hover] * 4 for _ in range(n_rows)]
            active_ref_mask = [False for _ in range(n_rows)]
        else:
            state_setpoint_t = []
            control_setpoint_t = []
            active_ref_mask = []
            for i in range(n_rows):
                # Row i in trajectory.csv is state after applying control from previous solver call.
                # Align setpoint one sample earlier to avoid apparent phase lead/lag in plots.
                i_eff = max(0, i - 1)
                # TB uses zero-reference until trajectory start gate opens.
                if i_eff < args.traj_start_step:
                    state_setpoint_t.append([0.0] * 12)
                    control_setpoint_t.append([u_hover] * 4)
                    active_ref_mask.append(False)
                else:
                    traj_sample = (i_eff - args.traj_start_step) // traj_tick_div
                    ref_idx = traj_sample - warmstart_pad
                    if ref_idx < 0 or ref_idx >= len(x_ref_rows):
                        # Runtime switches to q=0 after trajectory is consumed.
                        state_setpoint_t.append([0.0] * 12)
                        control_setpoint_t.append([u_hover] * 4)
                        active_ref_mask.append(False)
                    else:
                        state_setpoint_t.append(list(x_ref_rows[ref_idx]))
                        # reference CSV stores delta-u around hover
                        control_setpoint_t.append([u_hover + u_ref_rows[ref_idx][k] for k in range(4)])
                        active_ref_mask.append(True)
    else:
        state_setpoint_t = [[0.0] * 12 for _ in range(n_rows)]
        control_setpoint_t = [[u_hover] * 4 for _ in range(n_rows)]
        active_ref_mask = [False for _ in range(n_rows)]

    mse_x, mse_y, mse_z = compute_position_mse_xyz(
        csv_path=traj_path,
        state_setpoint_t=state_setpoint_t,
        active_ref_mask=active_ref_mask,
    )
    integrated_position_error_xyz = compute_position_error_integral_xyz(
        csv_path=traj_path,
        state_setpoint_t=state_setpoint_t,
        active_ref_mask=active_ref_mask,
    )
    metrics_text = (
        f"horizon={horizon_len}\n"
        f"rho={RHO_PARAM}\n"
        f"traj_dt={TRAJ_DT}\n"
        f"traj_tick_div={traj_tick_div}\n"
        f"u_abs_min={u_min_abs:.6g}\n"
        f"u_abs_max={u_max_abs:.6g}\n"
        f"Q_DIAG={Q_DIAG}\n"
        f"R_DIAG={R_DIAG}\n"
        f"mse_x={mse_x:.10g}\n"
        f"mse_y={mse_y:.10g}\n"
        f"mse_z={mse_z:.10g}\n"
        f"integrated_position_error_xyz={integrated_position_error_xyz:.10g}"
    )
    final_x = generate_trajectory_plot(
        csv_path=traj_path,
        png_path=plot_path,
        title="ADMM closed-loop once",
        state_setpoint_t=state_setpoint_t,
        control_setpoint_t=control_setpoint_t,
        control_limits_abs=(u_min_abs, u_max_abs),
        metrics_text=metrics_text,
    )

    print("Run complete.")
    print(f"early_stop_step={early_step}")
    print(f"early_stop_reason={early_reason}")
    print(f"final_x={final_x:.6g}")
    print(f"mse_x={mse_x:.9g}")
    print(f"mse_y={mse_y:.9g}")
    print(f"mse_z={mse_z:.9g}")
    print(f"integrated_position_error_xyz={integrated_position_error_xyz:.9g}")
    print(f"trajectory_csv= {traj_path}")
    print(f"trajectory_png= {plot_path}")
    print(f"logs_dir={logs_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
