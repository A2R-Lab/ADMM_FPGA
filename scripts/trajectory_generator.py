#!/usr/bin/env python3
"""
Parametric trajectory generator for ADMM references.

Default profile: smooth figure-8 with physically coherent state/control references.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from crazyloihimodel import CrazyLoihiModel
from trajectory_opt_scp import ScpConfig, optimize_trajectory_scp


# Keep constants aligned with ADMM_closed_loop_tb.cpp dynamics.
MASS = 0.048
JX = 2.3951e-5
JY = 2.3951e-5
JZ = 3.2347e-5
G = 9.81
THRUST_TO_TORQUE = 0.002078
EL = 0.0353
SCALE = 65535.0
KT = 2.90e-6 * SCALE
KM = KT * THRUST_TO_TORQUE


def _parse_float_list(text: str, expected_len: int, name: str) -> np.ndarray:
    vals = [float(tok.strip()) for tok in text.split(",") if tok.strip()]
    if len(vals) != expected_len:
        raise ValueError(f"{name} must contain exactly {expected_len} comma-separated values")
    return np.array(vals, dtype=np.float64)


def _yaw_from_velocity(vx: np.ndarray, vy: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    yaw = np.zeros_like(vx)
    prev = 0.0
    for i in range(vx.shape[0]):
        s2 = vx[i] * vx[i] + vy[i] * vy[i]
        if s2 > eps * eps:
            prev = float(np.arctan2(vy[i], vx[i]))
        yaw[i] = prev
    return yaw


def _body_rates_from_euler(
    roll: np.ndarray, pitch: np.ndarray, yaw: np.ndarray, dt: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    roll_dot = np.gradient(roll, dt, edge_order=2)
    pitch_dot = np.gradient(pitch, dt, edge_order=2)
    yaw_dot = np.gradient(yaw, dt, edge_order=2)

    cphi = np.cos(roll)
    sphi = np.sin(roll)
    cth = np.cos(pitch)
    sth = np.sin(pitch)

    # ZYX convention mapping from euler rates -> body rates.
    p = roll_dot - yaw_dot * sth
    q = pitch_dot * cphi + yaw_dot * sphi * cth
    r = -pitch_dot * sphi + yaw_dot * cphi * cth
    return p, q, r


def _rpy_to_rp(roll: np.ndarray, pitch: np.ndarray, yaw: np.ndarray) -> np.ndarray:
    cr = np.cos(0.5 * roll)
    sr = np.sin(0.5 * roll)
    cp = np.cos(0.5 * pitch)
    sp = np.sin(0.5 * pitch)
    cy = np.cos(0.5 * yaw)
    sy = np.sin(0.5 * yaw)

    qw = cr * cp * cy + sr * sp * sy
    qx = sr * cp * cy - cr * sp * sy
    qy = cr * sp * cy + sr * cp * sy
    qz = cr * cp * sy - sr * sp * cy

    eps = 1e-9
    qw_safe = np.where(np.abs(qw) < eps, np.sign(qw) * eps + (qw == 0.0) * eps, qw)
    rp = np.vstack([qx / qw_safe, qy / qw_safe, qz / qw_safe]).T
    return rp


def _motor_mixer_inv() -> np.ndarray:
    m = np.array(
        [
            [KT, KT, KT, KT],
            [-EL * KT, -EL * KT, EL * KT, EL * KT],
            [-EL * KT, EL * KT, EL * KT, -EL * KT],
            [-KM, KM, -KM, KM],
        ],
        dtype=np.float64,
    )
    return np.linalg.inv(m)


def _rollout_states_from_controls(u_abs: np.ndarray, dt: float, x0: np.ndarray) -> np.ndarray:
    model = CrazyLoihiModel(freq=1.0 / dt)
    k_len = u_abs.shape[0]
    x_hist = np.zeros((k_len, 12), dtype=np.float64)
    x = np.array(x0, dtype=np.float64)
    x_hist[0, :] = x
    for k in range(k_len - 1):
        u_k = np.clip(u_abs[k, :], 0.0, 1.0)
        x = np.asarray(model.step(x, u_k), dtype=np.float64)
        x_hist[k + 1, :] = x
    return x_hist


def generate_figure8_trajectory(
    *,
    length: int,
    dt: float,
    amp_x: float = 0.50,
    amp_y: float = 1.15,
    z0: float = 0.60,
    cycles: float = 1.0,
    yaw_mode: str = "fixed",  # fixed | velocity
    state_source: str = "rollout",  # rollout | geometric
) -> tuple[np.ndarray, np.ndarray]:
    if length <= 2:
        raise ValueError("length must be > 2")
    if dt <= 0:
        raise ValueError("dt must be > 0")

    t = np.arange(length, dtype=np.float64) * dt
    t_end = max(dt, (length - 1) * dt)
    tau = np.clip(t / t_end, 0.0, 1.0)

    # Quintic smoothstep: zero speed and acceleration at endpoints.
    s = 10.0 * tau**3 - 15.0 * tau**4 + 6.0 * tau**5
    ds_dt = (30.0 * tau**2 - 60.0 * tau**3 + 30.0 * tau**4) / t_end
    d2s_dt2 = (60.0 * tau - 180.0 * tau**2 + 120.0 * tau**3) / (t_end * t_end)

    theta = 2.0 * np.pi * cycles * s
    theta_dot = 2.0 * np.pi * cycles * ds_dt
    theta_ddot = 2.0 * np.pi * cycles * d2s_dt2

    # Lemniscate of Gerono.
    x = amp_x * np.sin(theta)
    y = amp_y * np.sin(theta) * np.cos(theta)
    z = np.full_like(x, z0)

    x_theta = amp_x * np.cos(theta)
    y_theta = amp_y * np.cos(2.0 * theta)
    x_thetatheta = -amp_x * np.sin(theta)
    y_thetatheta = -2.0 * amp_y * np.sin(2.0 * theta)

    vx = x_theta * theta_dot
    vy = y_theta * theta_dot
    vz = np.zeros_like(vx)
    ax = x_thetatheta * (theta_dot**2) + x_theta * theta_ddot
    ay = y_thetatheta * (theta_dot**2) + y_theta * theta_ddot
    az = np.zeros_like(ax)

    if yaw_mode == "velocity":
        yaw = _yaw_from_velocity(vx, vy)
    else:
        yaw = np.zeros_like(x)

    cpsi = np.cos(yaw)
    spsi = np.sin(yaw)
    # Flatness-style roll/pitch from desired acceleration and yaw.
    roll = np.arctan2(ax * spsi - ay * cpsi, G + az)
    pitch = np.arctan2(ax * cpsi + ay * spsi, G + az)

    wx, wy, wz = _body_rates_from_euler(roll, pitch, yaw, dt)
    wdot = np.vstack(
        [
            np.gradient(wx, dt, edge_order=2),
            np.gradient(wy, dt, edge_order=2),
            np.gradient(wz, dt, edge_order=2),
        ]
    )
    w = np.vstack([wx, wy, wz])
    jdiag = np.array([JX, JY, JZ], dtype=np.float64)
    jw = jdiag[:, None] * w
    cross = np.cross(w.T, jw.T).T
    tau_body = jdiag[:, None] * wdot + cross

    thrust = MASS * np.sqrt(ax * ax + ay * ay + (G + az) * (G + az))
    inv_m = _motor_mixer_inv()
    u_abs = np.zeros((length, 4), dtype=np.float64)
    for i in range(length):
        rhs = np.array([thrust[i], tau_body[0, i], tau_body[1, i], tau_body[2, i]], dtype=np.float64)
        u_abs[i, :] = inv_m @ rhs

    u_hover = MASS * G / (4.0 * KT)
    u_ref = u_abs - u_hover

    rp = _rpy_to_rp(roll, pitch, yaw)

    x_ref = np.zeros((length, 12), dtype=np.float64)
    x_ref[:, 0] = x
    x_ref[:, 1] = y
    x_ref[:, 2] = z
    x_ref[:, 3] = rp[:, 0]
    x_ref[:, 4] = rp[:, 1]
    x_ref[:, 5] = rp[:, 2]
    x_ref[:, 6] = vx
    x_ref[:, 7] = vy
    x_ref[:, 8] = vz
    x_ref[:, 9] = wx
    x_ref[:, 10] = wy
    x_ref[:, 11] = wz
    if state_source == "rollout":
        x_ref = _rollout_states_from_controls(u_abs=u_abs, dt=dt, x0=x_ref[0, :])
    elif state_source != "geometric":
        raise ValueError("state_source must be 'rollout' or 'geometric'")
    return x_ref, u_ref


def write_header_x_ref(path: Path, x_ref: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows, cols = x_ref.shape
    with path.open("w") as f:
        f.write(f"static const float X_ref_data[{rows}][{cols}] = {{\n")
        for i in range(rows):
            vals = ",".join(f"{x_ref[i, j]:.4f}" for j in range(cols))
            f.write("{" + vals + "},\n")
        f.write("};\n")


def build_traj_q_packed(
    x_ref: np.ndarray,
    u_ref: np.ndarray,
    q_diag: np.ndarray,
    r_diag: np.ndarray,
    horizon: int,
) -> np.ndarray:
    if x_ref.shape[1] != q_diag.shape[0]:
        raise ValueError("x_ref width and q_diag length mismatch")
    if u_ref.shape[1] != r_diag.shape[0]:
        raise ValueError("u_ref width and r_diag length mismatch")
    if horizon <= 0:
        raise ValueError("horizon must be > 0")

    q_state_ref = -(x_ref * q_diag[None, :])
    q_input_ref = -(u_ref * r_diag[None, :])

    rows = x_ref.shape[0]
    cols = x_ref.shape[1] + u_ref.shape[1]
    traj_q_packed = np.zeros((rows + horizon, cols), dtype=np.float64)
    traj_q_packed[:rows, : x_ref.shape[1]] = q_state_ref
    traj_q_packed[:rows, x_ref.shape[1] :] = q_input_ref
    traj_q_packed[rows:, :] = traj_q_packed[rows - 1, :]
    return traj_q_packed


def write_traj_q_header(path: Path, traj_q_packed: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows, cols = traj_q_packed.shape
    with path.open("w") as f:
        f.write("#ifndef TRAJ_DATA_H\n")
        f.write("#define TRAJ_DATA_H\n\n")
        f.write('#include "data_types.h"\n\n')
        f.write(f"#define TRAJ_Q_PACKED_ROWS {rows}\n")
        f.write(f"#define TRAJ_Q_PACKED_COLS {cols}\n")
        f.write("const fp_t traj_q_packed[TRAJ_Q_PACKED_ROWS][TRAJ_Q_PACKED_COLS] = {\n")
        for i in range(rows):
            vals = ", ".join(f"(fp_t){traj_q_packed[i, j]:.8f}" for j in range(cols))
            f.write(f"   {{ {vals} }},\n")
        f.write("};\n\n")
        f.write("#endif // TRAJ_DATA_H\n")


def write_csv_refs(path: Path, x_ref: np.ndarray, u_ref: np.ndarray, dt: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "t",
                *[f"x{i}" for i in range(12)],
                *[f"u{i}" for i in range(4)],
            ]
        )
        for i in range(x_ref.shape[0]):
            writer.writerow([i * dt, *x_ref[i, :].tolist(), *u_ref[i, :].tolist()])


def write_preview(path: Path, x_ref: np.ndarray, u_ref: np.ndarray, dt: float) -> None:
    t = np.arange(x_ref.shape[0]) * dt
    fig = plt.figure(figsize=(12, 9), constrained_layout=True)
    gs = fig.add_gridspec(3, 2, hspace=0.3)
    ax_xy = fig.add_subplot(gs[0, 0])
    ax_pos = fig.add_subplot(gs[0, 1])
    ax_vel = fig.add_subplot(gs[1, 0])
    ax_att = fig.add_subplot(gs[1, 1])
    ax_rate = fig.add_subplot(gs[2, 0])
    ax_u = fig.add_subplot(gs[2, 1])

    ax_xy.plot(x_ref[:, 0], x_ref[:, 1], lw=1.5)
    ax_xy.set_title("XY path")
    ax_xy.set_xlabel("x [m]")
    ax_xy.set_ylabel("y [m]")
    ax_xy.grid(True)
    ax_xy.axis("equal")

    ax_pos.plot(t, x_ref[:, 0], label="x")
    ax_pos.plot(t, x_ref[:, 1], label="y")
    ax_pos.plot(t, x_ref[:, 2], label="z")
    ax_pos.set_title("Position")
    ax_pos.grid(True)
    ax_pos.legend()

    ax_vel.plot(t, x_ref[:, 6], label="vx")
    ax_vel.plot(t, x_ref[:, 7], label="vy")
    ax_vel.plot(t, x_ref[:, 8], label="vz")
    ax_vel.set_title("Velocity")
    ax_vel.grid(True)
    ax_vel.legend()

    ax_att.plot(t, x_ref[:, 3], label="rp0")
    ax_att.plot(t, x_ref[:, 4], label="rp1")
    ax_att.plot(t, x_ref[:, 5], label="rp2")
    ax_att.set_title("Attitude (qtorp)")
    ax_att.grid(True)
    ax_att.legend()

    ax_rate.plot(t, x_ref[:, 9], label="wx")
    ax_rate.plot(t, x_ref[:, 10], label="wy")
    ax_rate.plot(t, x_ref[:, 11], label="wz")
    ax_rate.set_title("Body rates")
    ax_rate.grid(True)
    ax_rate.legend()

    ax_u.plot(t, u_ref[:, 0], label="du0")
    ax_u.plot(t, u_ref[:, 1], label="du1")
    ax_u.plot(t, u_ref[:, 2], label="du2")
    ax_u.plot(t, u_ref[:, 3], label="du3")
    ax_u.set_title("Input reference (delta around hover)")
    ax_u.grid(True)
    ax_u.legend()

    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=140)
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate coherent figure-8 trajectory references.")
    p.add_argument("--length", type=int, default=2048)
    p.add_argument("--dt", type=float, default=0.02)
    p.add_argument("--amp-x", type=float, default=0.80)
    p.add_argument("--amp-y", type=float, default=1.15)
    p.add_argument("--z0", type=float, default=0.0)
    p.add_argument("--cycles", type=float, default=1.0)
    p.add_argument("--yaw-mode", choices=["fixed", "velocity"], default="fixed")
    p.add_argument(
        "--state-source",
        choices=["rollout", "geometric"],
        default="rollout",
        help="How to build x_ref: rollout nonlinear model from u, or keep geometric closed form.",
    )
    p.add_argument("--csv-out", type=Path, default=Path("build/trajectory/fig8_refs.csv"))
    p.add_argument("--header-out", type=Path, default=Path("build/trajectory/traj_fig8_12.h"))
    p.add_argument("--preview-png", type=Path, default=Path("build/trajectory/fig8_preview.png"))
    p.add_argument("--admm-header-out", type=Path, default=None)
    p.add_argument("--q-diag", type=str, default=None, help="12 comma-separated values")
    p.add_argument("--r-diag", type=str, default=None, help="4 comma-separated values")
    p.add_argument("--horizon", type=int, default=None)
    p.add_argument("--optimize-scp", action="store_true", help="Run SCP offline optimization on top of geometric fig-8.")
    p.add_argument("--scp-iters", type=int, default=6)
    p.add_argument("--scp-trust-x", type=float, default=0.12)
    p.add_argument("--scp-trust-u", type=float, default=0.06)
    p.add_argument("--scp-w-u", type=float, default=2e-2)
    p.add_argument("--scp-w-du", type=float, default=4e-2)
    p.add_argument("--scp-w-x-trust", type=float, default=2.0)
    p.add_argument("--scp-w-u-trust", type=float, default=1.0)
    p.add_argument("--scp-mix-new-u", type=float, default=0.7)
    p.add_argument(
        "--scp-q-diag",
        type=str,
        default="60,60,178,0.4,0.4,4,4,4,4,0.2,0.2,25",
        help="12 comma-separated tracking weights for SCP.",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    x_ref, u_ref = generate_figure8_trajectory(
        length=args.length,
        dt=args.dt,
        amp_x=args.amp_x,
        amp_y=args.amp_y,
        z0=args.z0,
        cycles=args.cycles,
        yaw_mode=args.yaw_mode,
        state_source=args.state_source,
    )

    if args.optimize_scp:
        scp_q = _parse_float_list(args.scp_q_diag, expected_len=12, name="scp-q-diag")
        u_hover = MASS * G / (4.0 * KT)
        scp_cfg = ScpConfig(
            iters=int(args.scp_iters),
            trust_x=float(args.scp_trust_x),
            trust_u=float(args.scp_trust_u),
            w_u_hover=float(args.scp_w_u),
            w_du_smooth=float(args.scp_w_du),
            w_x_trust=float(args.scp_w_x_trust),
            w_u_trust=float(args.scp_w_u_trust),
            mix_new_u=float(args.scp_mix_new_u),
        )
        try:
            x_ref, u_abs_opt = optimize_trajectory_scp(
                x_ref=x_ref,
                u_init_abs=(u_ref + u_hover),
                dt=float(args.dt),
                q_diag=scp_q,
                u_hover=u_hover,
                cfg=scp_cfg,
            )
            u_ref = u_abs_opt - u_hover
        except RuntimeError as exc:
            print(f"warning: SCP optimization failed, using geometric trajectory fallback: {exc}")

    write_csv_refs(args.csv_out, x_ref, u_ref, args.dt)
    write_header_x_ref(args.header_out, x_ref)
    write_preview(args.preview_png, x_ref, u_ref, args.dt)

    if args.admm_header_out is not None:
        if args.q_diag is None or args.r_diag is None or args.horizon is None:
            raise ValueError("--admm-header-out requires --q-diag, --r-diag, and --horizon")
        q_diag = _parse_float_list(args.q_diag, expected_len=12, name="q-diag")
        r_diag = _parse_float_list(args.r_diag, expected_len=4, name="r-diag")
        traj_q_packed = build_traj_q_packed(x_ref, u_ref, q_diag, r_diag, horizon=int(args.horizon))
        write_traj_q_header(args.admm_header_out, traj_q_packed)

    u_hover = MASS * G / (4.0 * KT)
    u_abs = u_ref + u_hover
    print("Trajectory generated.")
    print(f"csv={args.csv_out.resolve()}")
    print(f"header= {args.header_out.resolve()}")
    print(f"preview= {args.preview_png.resolve()}")
    if args.admm_header_out is not None:
        print(f"admm_header= {args.admm_header_out.resolve()}")
    print(
        "u_abs_range="
        f"[{np.min(u_abs):.4f}, {np.max(u_abs):.4f}] "
        "(expect inside [0, 1] for feasible nominal feed-forward)"
    )
    print(
        "max_abs=[rp0,rp1,wx,wy,wz]="
        f"[{np.max(np.abs(x_ref[:,3])):.4f}, {np.max(np.abs(x_ref[:,4])):.4f}, "
        f"{np.max(np.abs(x_ref[:,9])):.4f}, {np.max(np.abs(x_ref[:,10])):.4f}, "
        f"{np.max(np.abs(x_ref[:,11])):.4f}]"
    )
    if np.max(u_abs) > 1.0 or np.min(u_abs) < 0.0:
        print("warning: motor reference leaves [0,1]; reduce --amp-x/--amp-y/--cycles or increase trajectory length")
    if np.max(np.abs(x_ref[:, 3])) > 0.4 or np.max(np.abs(x_ref[:, 4])) > 0.4:
        print("warning: large tilt; reduce aggressiveness for easier closed-loop tracking")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
