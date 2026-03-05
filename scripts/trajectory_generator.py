#!/usr/bin/env python3
"""Deterministic trajectory generator for ADMM references.

Single generation method:
- figure-8 geometric seed
- full nonlinear rollout for x_ref
"""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from crazyloihimodel import CrazyLoihiModel
from parameters import (
    FIG8_PERIOD_S,
    HORIZON_LENGTH,
    Q_DIAG,
    R_DIAG,
    TRAJ_DT,
    TRAJ_LENGTH,
)


# -----------------------------------------------------------------------------
# Trajectory generation parameters (edit here)
# -----------------------------------------------------------------------------
AMP_X = 0.60
AMP_Y = 1.0
Z0 = 0.0

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent

TRAJ_REFS_CSV_OUT = REPO_ROOT / "vitis_projects" / "ADMM" / "trajectory_refs.csv"
TRAJ_DATA_HEADER_OUT = REPO_ROOT / "vitis_projects" / "ADMM" / "traj_data.h"
TRAJ_PREVIEW_PNG_OUT = REPO_ROOT / "build" / "trajectory" / "fig8_preview.png"
TRAJ_XREF_HEADER_OUT = REPO_ROOT / "build" / "trajectory" / "traj_fig8_12.h"


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


def generate_figure8_rollout_trajectory(
    *,
    length: int,
    dt: float,
    amp_x: float,
    amp_y: float,
    z0: float,
    cycles: float,
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

    # Single yaw mode: fixed yaw = 0.
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

    rp = _rpy_to_rp(roll, pitch, yaw)
    x_ref_seed = np.zeros((length, 12), dtype=np.float64)
    x_ref_seed[:, 0] = x
    x_ref_seed[:, 1] = y
    x_ref_seed[:, 2] = z
    x_ref_seed[:, 3] = rp[:, 0]
    x_ref_seed[:, 4] = rp[:, 1]
    x_ref_seed[:, 5] = rp[:, 2]
    x_ref_seed[:, 6] = vx
    x_ref_seed[:, 7] = vy
    x_ref_seed[:, 8] = vz
    x_ref_seed[:, 9] = wx
    x_ref_seed[:, 10] = wy
    x_ref_seed[:, 11] = wz

    u_hover = MASS * G / (4.0 * KT)
    u_ref = u_abs - u_hover
    return x_ref_seed, u_ref


def _cycles_from_period_s(length: int, dt: float, period_s: float) -> float:
    if period_s <= 0:
        raise ValueError("FIG8_PERIOD_S must be > 0")
    total_duration_s = (length - 1) * dt
    return total_duration_s / period_s


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

    cols = x_ref.shape[1] + u_ref.shape[1]
    core = np.zeros((x_ref.shape[0], cols), dtype=np.float64)
    core[:, : x_ref.shape[1]] = q_state_ref
    core[:, x_ref.shape[1] :] = q_input_ref

    # Warmstart-friendly timeline:
    # - prepend (horizon-1) all-zero stages so reference first appears at horizon tail
    # - append (horizon-1) all-zero stages so reference fades out to zero
    pad = max(horizon - 1, 0)
    seq = np.vstack(
        [
            np.zeros((pad, cols), dtype=np.float64),
            core,
            np.zeros((pad, cols), dtype=np.float64),
        ]
    )

    # Extra horizon rows provide safe contiguous look-ahead for q_vec pointer reads.
    traj_q_packed = np.zeros((seq.shape[0] + horizon, cols), dtype=np.float64)
    traj_q_packed[: seq.shape[0], :] = seq
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


def write_header_x_ref(path: Path, x_ref: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows, cols = x_ref.shape
    with path.open("w") as f:
        f.write(f"static const float X_ref_data[{rows}][{cols}] = {{\n")
        for i in range(rows):
            vals = ",".join(f"{x_ref[i, j]:.4f}" for j in range(cols))
            f.write("{" + vals + "},\n")
        f.write("};\n")


def write_csv_refs(path: Path, x_ref: np.ndarray, u_ref: np.ndarray, dt: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["t", *[f"x{i}" for i in range(12)], *[f"u{i}" for i in range(4)]])
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


def main() -> int:
    cycles = _cycles_from_period_s(length=TRAJ_LENGTH, dt=TRAJ_DT, period_s=FIG8_PERIOD_S)
    x_ref, u_ref = generate_figure8_rollout_trajectory(
        length=TRAJ_LENGTH,
        dt=TRAJ_DT,
        amp_x=AMP_X,
        amp_y=AMP_Y,
        z0=Z0,
        cycles=cycles,
    )

    write_csv_refs(TRAJ_REFS_CSV_OUT, x_ref, u_ref, TRAJ_DT)
    traj_q_packed = build_traj_q_packed(
        x_ref=x_ref,
        u_ref=u_ref,
        q_diag=np.asarray(Q_DIAG, dtype=np.float64),
        r_diag=np.asarray(R_DIAG, dtype=np.float64),
        horizon=HORIZON_LENGTH,
    )
    write_traj_q_header(TRAJ_DATA_HEADER_OUT, traj_q_packed)
    write_header_x_ref(TRAJ_XREF_HEADER_OUT, x_ref)
    write_preview(TRAJ_PREVIEW_PNG_OUT, x_ref, u_ref, TRAJ_DT)

    u_hover = MASS * G / (4.0 * KT)
    u_abs = u_ref + u_hover

    print("Trajectory generated.")
    print("state_source=geometric_seed")
    print(f"csv={TRAJ_REFS_CSV_OUT}")
    print(f"traj_data_header={TRAJ_DATA_HEADER_OUT}")
    print(f"xref_header={TRAJ_XREF_HEADER_OUT}")
    print(f"preview={TRAJ_PREVIEW_PNG_OUT}")
    print(f"dt={TRAJ_DT:.6f}s traj_length={TRAJ_LENGTH} fig8_period_s={FIG8_PERIOD_S:.6f}")
    print(
        "u_abs_range="
        f"[{np.min(u_abs):.4f}, {np.max(u_abs):.4f}] "
        "(expect inside [0, 1] for feasible nominal feed-forward)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
