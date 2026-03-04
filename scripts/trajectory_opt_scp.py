#!/usr/bin/env python3
"""
Sequential convex trajectory optimizer (SCP) for long-horizon offline references.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import osqp
from scipy import sparse

from crazyloihimodel import CrazyLoihiModel


@dataclass
class ScpConfig:
    iters: int = 6
    solver_max_iter: int = 6000
    eps_abs: float = 1e-4
    eps_rel: float = 1e-4
    linearize_eps_x: float = 1e-4
    linearize_eps_u: float = 1e-4
    w_track: float = 1.0
    w_u_hover: float = 2e-2
    w_du_smooth: float = 4e-2
    w_x_trust: float = 2.0
    w_u_trust: float = 1.0
    trust_x: float = 0.12
    trust_u: float = 0.06
    mix_new_u: float = 0.7
    max_roll_pitch: float = 0.45
    max_vxy: float = 3.0
    max_vz: float = 2.0
    max_wxy: float = 4.0
    max_wz: float = 3.0


def _rollout(model: CrazyLoihiModel, x0: np.ndarray, u_seq: np.ndarray) -> np.ndarray:
    steps = u_seq.shape[0] + 1
    x_hist = np.zeros((steps, 12), dtype=np.float64)
    x_hist[0, :] = x0
    x = np.array(x0, dtype=np.float64)
    for k in range(steps - 1):
        x = np.asarray(model.step(x, u_seq[k, :]), dtype=np.float64)
        x_hist[k + 1, :] = x
    return x_hist


def _linearize_along(
    model: CrazyLoihiModel,
    x_bar: np.ndarray,
    u_bar: np.ndarray,
    eps_x: float,
    eps_u: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    steps = u_bar.shape[0]
    nx = x_bar.shape[1]
    nu = u_bar.shape[1]
    a = np.zeros((steps, nx, nx), dtype=np.float64)
    b = np.zeros((steps, nx, nu), dtype=np.float64)
    c = np.zeros((steps, nx), dtype=np.float64)

    for k in range(steps):
        xk = x_bar[k, :]
        uk = u_bar[k, :]
        f0 = np.asarray(model.step(xk, uk), dtype=np.float64)

        for i in range(nx):
            dx = np.zeros(nx, dtype=np.float64)
            dx[i] = eps_x
            fp = np.asarray(model.step(xk + dx, uk), dtype=np.float64)
            fm = np.asarray(model.step(xk - dx, uk), dtype=np.float64)
            a[k, :, i] = (fp - fm) / (2.0 * eps_x)

        for j in range(nu):
            du = np.zeros(nu, dtype=np.float64)
            du[j] = eps_u
            fp = np.asarray(model.step(xk, uk + du), dtype=np.float64)
            fm = np.asarray(model.step(xk, uk - du), dtype=np.float64)
            b[k, :, j] = (fp - fm) / (2.0 * eps_u)

        c[k, :] = f0 - a[k, :, :] @ xk - b[k, :, :] @ uk

    return a, b, c


def _build_and_solve_qp(
    *,
    x_ref: np.ndarray,
    x_bar: np.ndarray,
    u_bar: np.ndarray,
    a: np.ndarray,
    b: np.ndarray,
    c: np.ndarray,
    q_diag: np.ndarray,
    u_hover: float,
    cfg: ScpConfig,
) -> tuple[np.ndarray, np.ndarray]:
    k_len = x_ref.shape[0]
    nx = x_ref.shape[1]
    nu = u_bar.shape[1]
    ku = k_len - 1

    nvar_x = k_len * nx
    nvar_u = ku * nu
    nvar = nvar_x + nvar_u

    def x_idx(k: int) -> int:
        return k * nx

    def u_idx(k: int) -> int:
        return nvar_x + k * nu

    p = sparse.lil_matrix((nvar, nvar), dtype=np.float64)
    q = np.zeros(nvar, dtype=np.float64)

    wx = cfg.w_track * q_diag + cfg.w_x_trust
    for k in range(k_len):
        base = x_idx(k)
        p[base : base + nx, base : base + nx] += sparse.diags(2.0 * wx, format="lil")
        q[base : base + nx] += -2.0 * (cfg.w_track * q_diag * x_ref[k, :] + cfg.w_x_trust * x_bar[k, :])

    for k in range(ku):
        base = u_idx(k)
        wu = cfg.w_u_hover + cfg.w_u_trust
        p[base : base + nu, base : base + nu] += sparse.diags([2.0 * wu] * nu, format="lil")
        q[base : base + nu] += -2.0 * (cfg.w_u_hover * u_hover + cfg.w_u_trust * u_bar[k, :])

    # Smoothness: sum ||u_{k+1} - u_k||^2
    if ku >= 2 and cfg.w_du_smooth > 0.0:
        for k in range(ku - 1):
            i0 = u_idx(k)
            i1 = u_idx(k + 1)
            for j in range(nu):
                p[i0 + j, i0 + j] += 2.0 * cfg.w_du_smooth
                p[i1 + j, i1 + j] += 2.0 * cfg.w_du_smooth
                p[i0 + j, i1 + j] += -2.0 * cfg.w_du_smooth
                p[i1 + j, i0 + j] += -2.0 * cfg.w_du_smooth

    # Equality constraints: x0 fixed + linearized dynamics.
    rows_eq = nx + ku * nx
    a_eq = sparse.lil_matrix((rows_eq, nvar), dtype=np.float64)
    l_eq = np.zeros(rows_eq, dtype=np.float64)
    u_eq = np.zeros(rows_eq, dtype=np.float64)

    a_eq[0:nx, x_idx(0) : x_idx(0) + nx] = sparse.eye(nx, format="lil")
    l_eq[0:nx] = x_ref[0, :]
    u_eq[0:nx] = x_ref[0, :]

    for k in range(ku):
        row = nx + k * nx
        a_eq[row : row + nx, x_idx(k + 1) : x_idx(k + 1) + nx] = sparse.eye(nx, format="lil")
        a_eq[row : row + nx, x_idx(k) : x_idx(k) + nx] = -a[k, :, :]
        a_eq[row : row + nx, u_idx(k) : u_idx(k) + nu] = -b[k, :, :]
        l_eq[row : row + nx] = c[k, :]
        u_eq[row : row + nx] = c[k, :]

    # Inequalities: u bounds + trust regions.
    # u in [0,1]
    rows_u = ku * nu
    a_ub_u = sparse.lil_matrix((rows_u, nvar), dtype=np.float64)
    l_ub_u = np.zeros(rows_u, dtype=np.float64)
    u_ub_u = np.ones(rows_u, dtype=np.float64)
    for k in range(ku):
        for j in range(nu):
            r = k * nu + j
            a_ub_u[r, u_idx(k) + j] = 1.0

    # x trust box around nominal
    rows_x_tr = k_len * nx
    a_tr_x = sparse.lil_matrix((rows_x_tr, nvar), dtype=np.float64)
    l_tr_x = np.zeros(rows_x_tr, dtype=np.float64)
    u_tr_x = np.zeros(rows_x_tr, dtype=np.float64)
    for k in range(k_len):
        for i in range(nx):
            r = k * nx + i
            a_tr_x[r, x_idx(k) + i] = 1.0
            l_tr_x[r] = x_bar[k, i] - cfg.trust_x
            u_tr_x[r] = x_bar[k, i] + cfg.trust_x

    # u trust box around nominal
    rows_u_tr = ku * nu
    a_tr_u = sparse.lil_matrix((rows_u_tr, nvar), dtype=np.float64)
    l_tr_u = np.zeros(rows_u_tr, dtype=np.float64)
    u_tr_u = np.zeros(rows_u_tr, dtype=np.float64)
    for k in range(ku):
        for j in range(nu):
            r = k * nu + j
            a_tr_u[r, u_idx(k) + j] = 1.0
            l_tr_u[r] = u_bar[k, j] - cfg.trust_u
            u_tr_u[r] = u_bar[k, j] + cfg.trust_u

    # Hard state envelopes for stability.
    state_lb = np.full(nx, -np.inf, dtype=np.float64)
    state_ub = np.full(nx, np.inf, dtype=np.float64)
    state_lb[3] = -cfg.max_roll_pitch
    state_ub[3] = cfg.max_roll_pitch
    state_lb[4] = -cfg.max_roll_pitch
    state_ub[4] = cfg.max_roll_pitch
    state_lb[6] = -cfg.max_vxy
    state_ub[6] = cfg.max_vxy
    state_lb[7] = -cfg.max_vxy
    state_ub[7] = cfg.max_vxy
    state_lb[8] = -cfg.max_vz
    state_ub[8] = cfg.max_vz
    state_lb[9] = -cfg.max_wxy
    state_ub[9] = cfg.max_wxy
    state_lb[10] = -cfg.max_wxy
    state_ub[10] = cfg.max_wxy
    state_lb[11] = -cfg.max_wz
    state_ub[11] = cfg.max_wz

    rows_x_hard = k_len * nx
    a_hard_x = sparse.lil_matrix((rows_x_hard, nvar), dtype=np.float64)
    l_hard_x = np.zeros(rows_x_hard, dtype=np.float64)
    u_hard_x = np.zeros(rows_x_hard, dtype=np.float64)
    for k in range(k_len):
        base = x_idx(k)
        for i in range(nx):
            r = k * nx + i
            a_hard_x[r, base + i] = 1.0
            l_hard_x[r] = state_lb[i]
            u_hard_x[r] = state_ub[i]

    a_all = sparse.vstack([a_eq, a_ub_u, a_tr_x, a_tr_u, a_hard_x], format="csc")
    l_all = np.hstack([l_eq, l_ub_u, l_tr_x, l_tr_u, l_hard_x])
    u_all = np.hstack([u_eq, u_ub_u, u_tr_x, u_tr_u, u_hard_x])

    solver = osqp.OSQP()
    solver.setup(
        P=p.tocsc(),
        q=q,
        A=a_all,
        l=l_all,
        u=u_all,
        verbose=False,
        polish=True,
        eps_abs=cfg.eps_abs,
        eps_rel=cfg.eps_rel,
        max_iter=cfg.solver_max_iter,
        adaptive_rho=True,
    )
    res = solver.solve()
    if res.x is None or res.info.status_val not in (1, 2):
        raise RuntimeError(f"OSQP failed: {res.info.status}")

    z = np.asarray(res.x, dtype=np.float64)
    x_sol = z[:nvar_x].reshape(k_len, nx)
    u_sol = z[nvar_x:].reshape(ku, nu)
    return x_sol, u_sol


def optimize_trajectory_scp(
    *,
    x_ref: np.ndarray,
    u_init_abs: np.ndarray,
    dt: float,
    q_diag: np.ndarray,
    u_hover: float,
    cfg: ScpConfig | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    cfg = cfg or ScpConfig()
    model = CrazyLoihiModel(freq=1.0 / dt)

    k_len = x_ref.shape[0]
    if x_ref.shape[1] != 12:
        raise ValueError("x_ref must have shape [K, 12]")
    if u_init_abs.shape[0] == k_len:
        u_bar = np.array(u_init_abs[:-1, :], dtype=np.float64)
    elif u_init_abs.shape[0] == k_len - 1:
        u_bar = np.array(u_init_abs, dtype=np.float64)
    else:
        raise ValueError("u_init_abs must have K or K-1 rows")
    if u_bar.shape[1] != 4:
        raise ValueError("u_init_abs must have 4 columns")
    u_bar = np.clip(u_bar, 0.0, 1.0)

    x0 = np.array(x_ref[0, :], dtype=np.float64)
    x_bar = _rollout(model, x0, u_bar)

    trust_x = float(cfg.trust_x)
    trust_u = float(cfg.trust_u)

    for _ in range(cfg.iters):
        local_cfg = ScpConfig(**cfg.__dict__)
        local_cfg.trust_x = trust_x
        local_cfg.trust_u = trust_u

        a, b, c = _linearize_along(
            model=model,
            x_bar=x_bar,
            u_bar=u_bar,
            eps_x=cfg.linearize_eps_x,
            eps_u=cfg.linearize_eps_u,
        )
        solved = False
        last_err = ""
        for _retry in range(5):
            try:
                _, u_qp = _build_and_solve_qp(
                    x_ref=x_ref,
                    x_bar=x_bar,
                    u_bar=u_bar,
                    a=a,
                    b=b,
                    c=c,
                    q_diag=q_diag,
                    u_hover=u_hover,
                    cfg=local_cfg,
                )
                solved = True
                break
            except RuntimeError as exc:
                last_err = str(exc)
                trust_x = min(5.0, trust_x * 1.8)
                trust_u = min(0.5, trust_u * 1.8)
                local_cfg.trust_x = trust_x
                local_cfg.trust_u = trust_u
        if not solved:
            raise RuntimeError(f"SCP QP remained infeasible after trust expansion: {last_err}")

        u_bar = (1.0 - cfg.mix_new_u) * u_bar + cfg.mix_new_u * np.clip(u_qp, 0.0, 1.0)
        x_bar = _rollout(model, x0, u_bar)

    u_full = np.vstack([u_bar, u_bar[-1, :]])
    return x_bar, u_full
