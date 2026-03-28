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
    AMP_X,
    AMP_Y,
    CHICANE_MIX,
    FIG8_PERIOD_S,
    HORIZON_LENGTH,
    HUBSTAR_VERTICES,
    Q_DIAG,
    R_DIAG,
    ROSE_MOD,
    ROSE_PETALS,
    STAR_INNER_HOLD,
    SQUARE_SHARPNESS,
    STAR_INNER_RATIO,
    STAR_POINTS,
    TRAJ_DT,
    TRAJ_LENGTH,
    TRAJ_SHAPE,
    TRAJ_WARMSTART_PAD,
    Z0,
)

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent

TRAJ_REFS_CSV_OUT = REPO_ROOT / "vitis_projects" / "ADMM" / "trajectory_refs.csv"
TRAJ_DATA_HEADER_OUT = REPO_ROOT / "vitis_projects" / "ADMM" / "traj_data.h"
TRAJ_DATA_RAW_HEADER_OUT = REPO_ROOT / "vitis_projects" / "ADMM" / "traj_data_raw.h"
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

    # Lemniscate of Gerono, then swap x/y axes.
    x_raw = amp_x * np.sin(theta)
    y_raw = amp_y * np.sin(theta) * np.cos(theta)
    x = y_raw
    y = x_raw
    z = np.full_like(x, z0)

    x_theta_raw = amp_x * np.cos(theta)
    y_theta_raw = amp_y * np.cos(2.0 * theta)
    x_thetatheta_raw = -amp_x * np.sin(theta)
    y_thetatheta_raw = -2.0 * amp_y * np.sin(2.0 * theta)

    x_theta = y_theta_raw
    y_theta = x_theta_raw
    x_thetatheta = y_thetatheta_raw
    y_thetatheta = x_thetatheta_raw

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
    u_cmd = np.zeros((length, 4), dtype=np.float64)
    for i in range(length):
        rhs = np.array([thrust[i], tau_body[0, i], tau_body[1, i], tau_body[2, i]], dtype=np.float64)
        u_cmd[i, :] = inv_m @ rhs

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
    u_ref = u_cmd - u_hover
    return x_ref_seed, u_ref


def generate_planar_shape_rollout_trajectory(
    *,
    length: int,
    dt: float,
    amp_x: float,
    amp_y: float,
    z0: float,
    cycles: float,
    shape: str,
    square_sharpness: float,
    star_points: int,
    star_inner_ratio: float,
    star_inner_hold: float,
    rose_petals: int,
    rose_mod: float,
    chicane_mix: float,
    hubstar_vertices: int,
) -> tuple[np.ndarray, np.ndarray]:
    if length <= 2:
        raise ValueError("length must be > 2")
    if dt <= 0:
        raise ValueError("dt must be > 0")
    if cycles <= 0:
        raise ValueError("cycles must be > 0")
    if star_points < 3:
        raise ValueError("star_points must be >= 3")
    if not (0.0 < star_inner_ratio <= 1.0):
        raise ValueError("star_inner_ratio must be in (0, 1]")
    if not (0.0 <= star_inner_hold < 1.0):
        raise ValueError("star_inner_hold must be in [0, 1)")
    if rose_petals < 2:
        raise ValueError("rose_petals must be >= 2")
    if not (0.0 <= rose_mod < 1.0):
        raise ValueError("rose_mod must be in [0, 1)")
    if not (0.0 <= chicane_mix < 0.5):
        raise ValueError("chicane_mix must be in [0, 0.5)")
    if hubstar_vertices < 3:
        raise ValueError("hubstar_vertices must be >= 3")

    t = np.arange(length, dtype=np.float64) * dt
    t_end = max(dt, (length - 1) * dt)
    tau = np.clip(t / t_end, 0.0, 1.0)
    s = 10.0 * tau**3 - 15.0 * tau**4 + 6.0 * tau**5
    theta = 2.0 * np.pi * cycles * s

    if shape == "circle":
        x = amp_x * np.sin(theta)
        y = amp_y * np.cos(theta)
    elif shape == "square":
        k = max(0.5, square_sharpness)
        x = amp_x * np.tanh(k * np.sin(theta)) / np.tanh(k)
        y = amp_y * np.tanh(k * np.cos(theta)) / np.tanh(k)
    elif shape == "star":
        radial = star_inner_ratio + (1.0 - star_inner_ratio) * 0.5 * (
            1.0 + np.cos(float(star_points) * theta)
        )
        x = amp_x * radial * np.cos(theta)
        y = amp_y * radial * np.sin(theta)
    elif shape == "rose":
        radial = 1.0 + rose_mod * np.cos(float(rose_petals) * theta)
        x = amp_x * radial * np.cos(theta)
        y = amp_y * radial * np.sin(theta)
    elif shape == "chicane":
        x = amp_x * (np.sin(theta) + chicane_mix * np.sin(3.0 * theta))
        y = amp_y * np.cos(theta)
    elif shape == "square_hold":
        # Position-only square reference with edge interpolation and no corner dwell:
        # only XYZ position is commanded, all other states remain hover reference (zero),
        # and feed-forward input reference stays zero (hover).
        total_edges = max(4, int(round(cycles * 4.0)))
        # Use endpoint=False so the same corner is not sampled twice on edge transitions.
        # This keeps the path moving through corners without one-sample "stops".
        phase = np.linspace(0.0, 1.0, num=length, endpoint=False, dtype=np.float64)
        edge_phase = phase * float(total_edges)
        edge_idx = np.floor(edge_phase).astype(np.int64)
        edge_alpha = edge_phase - edge_idx
        vertices = np.array(
            [
                [amp_x, amp_y],
                [amp_x, -amp_y],
                [-amp_x, -amp_y],
                [-amp_x, amp_y],
            ],
            dtype=np.float64,
        )
        # Translate so the first vertex coincides with the starting point (origin).
        vertices = vertices - vertices[0]
        i0 = np.mod(edge_idx, 4)
        i1 = np.mod(edge_idx + 1, 4)
        p0 = vertices[i0]
        p1 = vertices[i1]
        p = (1.0 - edge_alpha)[:, None] * p0 + edge_alpha[:, None] * p1
        x = p[:, 0]
        y = p[:, 1]
        x_ref_seed = np.zeros((length, 12), dtype=np.float64)
        x_ref_seed[:, 0] = x
        x_ref_seed[:, 1] = y
        x_ref_seed[:, 2] = z0
        u_ref = np.zeros((length, 4), dtype=np.float64)
        return x_ref_seed, u_ref
    elif shape == "star_hold":
        # Position-only star polygon matching the alternating outer/inner vertex path,
        # phase-rotated so the first inner vertex lies on the x=y diagonal, then
        # translated so that first sample becomes the origin.
        # Uses amp_x/amp_y for the outer radius and star_inner_ratio for the inner radius.
        phase = np.linspace(0.0, 1.0, num=length, endpoint=False, dtype=np.float64)
        vertex_count = max(6, int(round(cycles * 2.0 * star_points)))
        path_phase = phase * float(vertex_count)
        vertex_idx = np.floor(path_phase).astype(np.int64)
        edge_alpha = path_phase - vertex_idx

        # Choose the global star rotation so the first inner vertex satisfies x=y.
        diagonal_angle = np.arctan2(amp_x, amp_y)
        star_phase = diagonal_angle - (np.pi / float(star_points))
        base_angles = (
            np.linspace(0.0, 2.0 * np.pi, num=star_points, endpoint=False, dtype=np.float64)
            + star_phase
        )
        vertices = np.zeros((2 * star_points, 2), dtype=np.float64)
        for i, angle0 in enumerate(base_angles):
            outer_idx = 2 * i
            inner_idx = outer_idx + 1
            vertices[outer_idx, 0] = amp_x * np.cos(angle0)
            vertices[outer_idx, 1] = amp_y * np.sin(angle0)
            inner_angle = angle0 + (np.pi / float(star_points))
            vertices[inner_idx, 0] = amp_x * star_inner_ratio * np.cos(inner_angle)
            vertices[inner_idx, 1] = amp_y * star_inner_ratio * np.sin(inner_angle)

        vertices = np.roll(vertices, shift=-1, axis=0)
        vertices = vertices - vertices[0]

        i0 = np.mod(vertex_idx, 2 * star_points)
        i1 = np.mod(vertex_idx + 1, 2 * star_points)
        is_inner_start = (i0 % 2) == 0
        edge_alpha_eff = edge_alpha.copy()
        if star_inner_hold > 0.0:
            moving_mask = is_inner_start & (edge_alpha >= star_inner_hold)
            edge_alpha_eff[is_inner_start & ~moving_mask] = 0.0
            edge_alpha_eff[moving_mask] = (
                (edge_alpha[moving_mask] - star_inner_hold) / (1.0 - star_inner_hold)
            )
        p0 = vertices[i0]
        p1 = vertices[i1]
        p = (1.0 - edge_alpha_eff)[:, None] * p0 + edge_alpha_eff[:, None] * p1
        x = p[:, 0]
        y = p[:, 1]
        x_ref_seed = np.zeros((length, 12), dtype=np.float64)
        x_ref_seed[:, 0] = x
        x_ref_seed[:, 1] = y
        x_ref_seed[:, 2] = z0
        u_ref = np.zeros((length, 4), dtype=np.float64)
        return x_ref_seed, u_ref
    elif shape == "diamond1m_hold":
        # Position-only rotated square (diamond), fixed 1.0 m side length.
        # Useful with axis-aligned XY box limits to produce clipped-octagon behavior.
        side_m = 1.0
        radius = side_m / np.sqrt(2.0)
        vertices = np.array(
            [
                [0.0, radius],
                [radius, 0.0],
                [0.0, -radius],
                [-radius, 0.0],
            ],
            dtype=np.float64,
        )

        # Use the midpoint of edge [v0 -> v1] as frame origin so trajectory
        # starts at (0,0) while preserving the same geometric path shape.
        origin_xy = 0.5 * (vertices[0] + vertices[1])
        vertices = vertices - origin_xy[None, :]

        # Start directly on-trajectory at the chosen origin (edge midpoint).
        total_edges = max(4, int(round(cycles * 4.0)))
        phase = np.linspace(0.0, 1.0, num=length, endpoint=True, dtype=np.float64)
        edge_phase = 0.5 + phase * float(total_edges)
        edge_idx = np.floor(edge_phase).astype(np.int64)
        edge_alpha = edge_phase - edge_idx
        i0 = np.mod(edge_idx, 4)
        i1 = np.mod(edge_idx + 1, 4)
        p0 = vertices[i0]
        p1 = vertices[i1]
        p = (1.0 - edge_alpha)[:, None] * p0 + edge_alpha[:, None] * p1

        x = p[:, 0]
        y = p[:, 1]
        x_ref_seed = np.zeros((length, 12), dtype=np.float64)
        x_ref_seed[:, 0] = x
        x_ref_seed[:, 1] = y
        x_ref_seed[:, 2] = z0
        u_ref = np.zeros((length, 4), dtype=np.float64)
        return x_ref_seed, u_ref
    elif shape == "fig8_hold":
        # Figure-8 position-only reference:
        # use geometric XY path but keep non-position states at hover reference.
        x_raw = amp_x * np.sin(theta)
        y_raw = amp_y * np.sin(theta) * np.cos(theta)
        x = y_raw
        y = x_raw
        x_ref_seed = np.zeros((length, 12), dtype=np.float64)
        x_ref_seed[:, 0] = x
        x_ref_seed[:, 1] = y
        x_ref_seed[:, 2] = z0
        u_ref = np.zeros((length, 4), dtype=np.float64)
        return x_ref_seed, u_ref
    elif shape == "diag_bounce":
        # Position-only diagonal bounce:
        # (0,0) -> (L,L) -> (0,0), repeated with no endpoint dwell.
        # L is taken from amp_x.
        segments = max(1, int(round(cycles * 2.0)))
        phase = np.linspace(0.0, 1.0, num=length, endpoint=False, dtype=np.float64)
        seg_phase = phase * float(segments)
        seg_idx = np.floor(seg_phase).astype(np.int64)
        seg_alpha = seg_phase - seg_idx

        endpoints = np.array(
            [
                [0.0, 0.0],
                [amp_x, amp_x],
            ],
            dtype=np.float64,
        )
        i0 = np.mod(seg_idx, 2)
        i1 = np.mod(seg_idx + 1, 2)
        p0 = endpoints[i0]
        p1 = endpoints[i1]
        p = (1.0 - seg_alpha)[:, None] * p0 + seg_alpha[:, None] * p1
        x = p[:, 0]
        y = p[:, 1]
        x_ref_seed = np.zeros((length, 12), dtype=np.float64)
        x_ref_seed[:, 0] = x
        x_ref_seed[:, 1] = y
        x_ref_seed[:, 2] = z0
        u_ref = np.zeros((length, 4), dtype=np.float64)
        return x_ref_seed, u_ref
    elif shape == "hubstar_hold":
        # Position-only center-hub star:
        # center -> spoke tip -> center, repeated for each spoke, with hover input.
        total_legs = max(1, hubstar_vertices)
        leg_phase = s * float(total_legs)
        leg_idx = np.floor(leg_phase).astype(np.int64)
        leg_local = leg_phase - leg_idx

        spoke_idx = np.mod(leg_idx, hubstar_vertices)
        angle = 2.0 * np.pi * (spoke_idx.astype(np.float64) / float(hubstar_vertices))

        r = 0.5 * (1.0 - np.cos(2.0 * np.pi * leg_local))
        x = amp_x * r * np.cos(angle)
        y = amp_y * r * np.sin(angle)
        x_ref_seed = np.zeros((length, 12), dtype=np.float64)
        x_ref_seed[:, 0] = x
        x_ref_seed[:, 1] = y
        x_ref_seed[:, 2] = z0
        u_ref = np.zeros((length, 4), dtype=np.float64)
        return x_ref_seed, u_ref
    elif shape == "hubstar":
        total_legs = max(1, hubstar_vertices)
        leg_phase = s * float(total_legs)
        leg_idx = np.floor(leg_phase).astype(np.int64)
        leg_local = leg_phase - leg_idx

        spoke_idx = np.mod(leg_idx, hubstar_vertices)
        angle = 2.0 * np.pi * (spoke_idx.astype(np.float64) / float(hubstar_vertices))

        # Smooth center -> tip -> center profile with zero speed at both ends.
        r = 0.5 * (1.0 - np.cos(2.0 * np.pi * leg_local))
        x = amp_x * r * np.cos(angle)
        y = amp_y * r * np.sin(angle)
    else:
        raise ValueError(f"unsupported shape: {shape}")

    z = np.full_like(x, z0)
    vx = np.gradient(x, dt, edge_order=2)
    vy = np.gradient(y, dt, edge_order=2)
    vz = np.zeros_like(vx)
    ax = np.gradient(vx, dt, edge_order=2)
    ay = np.gradient(vy, dt, edge_order=2)
    az = np.zeros_like(vx)

    yaw = np.zeros_like(x)
    cpsi = np.cos(yaw)
    spsi = np.sin(yaw)
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
    u_cmd = np.zeros((length, 4), dtype=np.float64)
    for i in range(length):
        rhs = np.array([thrust[i], tau_body[0, i], tau_body[1, i], tau_body[2, i]], dtype=np.float64)
        u_cmd[i, :] = inv_m @ rhs

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
    u_ref = u_cmd - u_hover
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
    del u_ref
    del r_diag
    xyz_cols = 3
    if x_ref.shape[1] != q_diag.shape[0]:
        raise ValueError("x_ref width and q_diag length mismatch")
    if horizon <= 0:
        raise ValueError("horizon must be > 0")

    q_state_ref = -(x_ref[:, :xyz_cols] * q_diag[None, :xyz_cols])

    cols = xyz_cols
    core = np.zeros((x_ref.shape[0], cols), dtype=np.float64)
    core[:, :xyz_cols] = q_state_ref

    # Warmstart-friendly timeline with fixed pad so cross-horizon comparisons are aligned.
    pad = max(TRAJ_WARMSTART_PAD, 0)
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


def build_traj_raw_packed(x_ref: np.ndarray, u_ref: np.ndarray, horizon: int) -> np.ndarray:
    del u_ref
    if horizon <= 0:
        raise ValueError("horizon must be > 0")

    xyz_cols = 3
    cols = xyz_cols
    core = np.zeros((x_ref.shape[0], cols), dtype=np.float64)
    core[:, :xyz_cols] = x_ref[:, :xyz_cols]

    # Match q-packed timeline so both headers are drop-in equivalent in indexing.
    pad = max(TRAJ_WARMSTART_PAD, 0)
    seq = np.vstack(
        [
            np.zeros((pad, cols), dtype=np.float64),
            core,
            np.zeros((pad, cols), dtype=np.float64),
        ]
    )

    traj_raw_packed = np.zeros((seq.shape[0] + horizon, cols), dtype=np.float64)
    traj_raw_packed[: seq.shape[0], :] = seq
    return traj_raw_packed


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


def write_traj_raw_header(path: Path, traj_raw_packed: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows, cols = traj_raw_packed.shape
    with path.open("w") as f:
        f.write("#ifndef TRAJ_DATA_RAW_H\n")
        f.write("#define TRAJ_DATA_RAW_H\n\n")
        f.write('#include "data_types.h"\n\n')
        f.write(f"#define TRAJ_RAW_PACKED_ROWS {rows}\n")
        f.write(f"#define TRAJ_RAW_PACKED_COLS {cols}\n")
        f.write("const fp_t traj_raw_packed[TRAJ_RAW_PACKED_ROWS][TRAJ_RAW_PACKED_COLS] = {\n")
        for i in range(rows):
            vals = ", ".join(f"(fp_t){traj_raw_packed[i, j]:.8f}" for j in range(cols))
            f.write(f"   {{ {vals} }},\n")
        f.write("};\n\n")
        f.write("#endif // TRAJ_DATA_RAW_H\n")


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
    if TRAJ_SHAPE == "fig8":
        x_ref, u_ref = generate_figure8_rollout_trajectory(
            length=TRAJ_LENGTH,
            dt=TRAJ_DT,
            amp_x=AMP_X,
            amp_y=AMP_Y,
            z0=Z0,
            cycles=cycles,
        )
    else:
        x_ref, u_ref = generate_planar_shape_rollout_trajectory(
            length=TRAJ_LENGTH,
            dt=TRAJ_DT,
            amp_x=AMP_X,
            amp_y=AMP_Y,
            z0=Z0,
            cycles=cycles,
            shape=TRAJ_SHAPE,
            square_sharpness=SQUARE_SHARPNESS,
            star_points=STAR_POINTS,
            star_inner_ratio=STAR_INNER_RATIO,
            star_inner_hold=STAR_INNER_HOLD,
            rose_petals=ROSE_PETALS,
            rose_mod=ROSE_MOD,
            chicane_mix=CHICANE_MIX,
            hubstar_vertices=HUBSTAR_VERTICES,
        )

    u_hover = MASS * G / (4.0 * KT)
    u_cmd = u_ref + u_hover
    u_min = float(np.min(u_cmd))
    u_max = float(np.max(u_cmd))
    if u_min < 0.0 or u_max > 1.0:
        print(
            "Trajectory infeasible: raw motor command u is out of bounds. "
            f"u_range=[{u_min:.4f}, {u_max:.4f}] required: 0 <= u <= 1."
        )
        return 1

    write_csv_refs(TRAJ_REFS_CSV_OUT, x_ref, u_ref, TRAJ_DT)
    traj_q_packed = build_traj_q_packed(
        x_ref=x_ref,
        u_ref=u_ref,
        q_diag=np.asarray(Q_DIAG, dtype=np.float64),
        r_diag=np.asarray(R_DIAG, dtype=np.float64),
        horizon=HORIZON_LENGTH,
    )
    write_traj_q_header(TRAJ_DATA_HEADER_OUT, traj_q_packed)
    traj_raw_packed = build_traj_raw_packed(x_ref=x_ref, u_ref=u_ref, horizon=HORIZON_LENGTH)
    write_traj_raw_header(TRAJ_DATA_RAW_HEADER_OUT, traj_raw_packed)
    write_header_x_ref(TRAJ_XREF_HEADER_OUT, x_ref)
    write_preview(TRAJ_PREVIEW_PNG_OUT, x_ref, u_ref, TRAJ_DT)

    print("Trajectory generated.")
    print("state_source=geometric_seed")
    print(f"csv={TRAJ_REFS_CSV_OUT}")
    print(f"traj_data_header={TRAJ_DATA_HEADER_OUT}")
    print(f"traj_data_raw_header={TRAJ_DATA_RAW_HEADER_OUT}")
    print(f"xref_header={TRAJ_XREF_HEADER_OUT}")
    print(f"preview= {TRAJ_PREVIEW_PNG_OUT}")
    print(
        f"shape={TRAJ_SHAPE} amp_x={AMP_X:.4f} amp_y={AMP_Y:.4f} "
        f"square_sharpness={SQUARE_SHARPNESS:.3f} star_points={STAR_POINTS} "
        f"star_inner_ratio={STAR_INNER_RATIO:.3f} "
        f"star_inner_hold={STAR_INNER_HOLD:.3f} "
        f"rose_petals={ROSE_PETALS} rose_mod={ROSE_MOD:.3f} "
        f"chicane_mix={CHICANE_MIX:.3f} "
        f"hubstar_vertices={HUBSTAR_VERTICES}"
    )
    print(f"dt={TRAJ_DT:.6f}s traj_length={TRAJ_LENGTH} fig8_period_s={FIG8_PERIOD_S:.6f}")
    print(
        "u_range="
        f"[{u_min:.4f}, {u_max:.4f}] "
        "(required: 0 <= u <= 1 for feasible nominal feed-forward)"
    )
    # Summary metrics for quick feasibility checks.
    pos_xy = np.sqrt(x_ref[:, 0] ** 2 + x_ref[:, 1] ** 2)
    speed_xy = np.sqrt(x_ref[:, 6] ** 2 + x_ref[:, 7] ** 2)
    speed_3d = np.sqrt(x_ref[:, 6] ** 2 + x_ref[:, 7] ** 2 + x_ref[:, 8] ** 2)
    # Convert controller attitude coordinates (rp = q_vec / q_w) to roll/pitch for a
    # physically meaningful combined tilt metric.
    rp0 = x_ref[:, 3]
    rp1 = x_ref[:, 4]
    rp2 = x_ref[:, 5]
    rp_norm2 = rp0**2 + rp1**2 + rp2**2
    qw = 1.0 / np.sqrt(1.0 + rp_norm2)
    qx = rp0 * qw
    qy = rp1 * qw
    qz = rp2 * qw
    roll = np.arctan2(2.0 * (qw * qx + qy * qz), 1.0 - 2.0 * (qx * qx + qy * qy))
    pitch_arg = np.clip(2.0 * (qw * qy - qz * qx), -1.0, 1.0)
    pitch = np.arcsin(pitch_arg)
    tilt_deg = np.degrees(np.sqrt(roll**2 + pitch**2))
    ang_rate_xy = np.sqrt(x_ref[:, 9] ** 2 + x_ref[:, 10] ** 2)
    ang_rate_3d = np.sqrt(x_ref[:, 9] ** 2 + x_ref[:, 10] ** 2 + x_ref[:, 11] ** 2)
    accel_xy = np.sqrt(
        np.gradient(x_ref[:, 6], TRAJ_DT, edge_order=2) ** 2
        + np.gradient(x_ref[:, 7], TRAJ_DT, edge_order=2) ** 2
    )
    accel_3d = np.sqrt(
        np.gradient(x_ref[:, 6], TRAJ_DT, edge_order=2) ** 2
        + np.gradient(x_ref[:, 7], TRAJ_DT, edge_order=2) ** 2
        + np.gradient(x_ref[:, 8], TRAJ_DT, edge_order=2) ** 2
    )
    print(
        "trajectory_stats: "
        f"max_pos_xy={np.max(pos_xy):.4f} m, "
        f"max_speed_xy={np.max(speed_xy):.4f} m/s, "
        f"max_speed_3d={np.max(speed_3d):.4f} m/s, "
        f"max_tilt_rollpitch={np.max(tilt_deg):.2f} deg, "
        f"max_ang_rate_xy={np.max(ang_rate_xy):.4f} rad/s, "
        f"max_ang_rate_3d={np.max(ang_rate_3d):.4f} rad/s, "
        f"max_accel_xy={np.max(accel_xy):.4f} m/s^2, "
        f"max_accel_3d={np.max(accel_3d):.4f} m/s^2"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
