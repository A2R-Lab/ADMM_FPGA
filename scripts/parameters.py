"""Shared ADMM trajectory/packing parameters.

Environment overrides are supported to simplify scripted sweeps:
- ADMM_HORIZON_LENGTH
- ADMM_ITERATIONS
- ADMM_USE_FLOAT
- ADMM_MPC_LINEAR_DRAG_XY
- ADMM_MPC_LINEAR_DRAG_Z
- ADMM_RHO_PARAM
- ADMM_DELAY_STEPS
- ADMM_TRAJ_DT
- ADMM_TRAJ_FIG8_PERIOD_S (preferred)
- ADMM_FIG8_PERIOD_S
- ADMM_REPETITIONS
- ADMM_TRAJ_WARMSTART_PAD
- ADMM_TRAJ_SHAPE
- ADMM_TRAJ_AMP_X
- ADMM_TRAJ_AMP_Y
- ADMM_TRAJ_Z0
- ADMM_TRAJ_SQUARE_SHARPNESS
- ADMM_TRAJ_STAR_POINTS
- ADMM_TRAJ_STAR_INNER_RATIO
- ADMM_TRAJ_ROSE_PETALS
- ADMM_TRAJ_ROSE_MOD
- ADMM_TRAJ_CHICANE_MIX
- ADMM_TRAJ_HUBSTAR_VERTICES
"""

from __future__ import annotations

import os


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return default if raw is None else int(raw)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return default if raw is None else float(raw)


def _env_float_alias(primary: str, alias: str, default: float) -> float:
    raw = os.environ.get(primary)
    if raw is None:
        raw = os.environ.get(alias)
    return default if raw is None else float(raw)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    v = raw.strip().lower()
    if v in {"1", "true", "yes", "on"}:
        return True
    if v in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean for {name}: {raw}")


HORIZON_LENGTH = _env_int("ADMM_HORIZON_LENGTH", 40)
Q_DIAG =  [250.0, 250.0, 178.0, 0.4, 0.4, 40.0, 1.0, 1.0, 4.0, 0.02, 0.02, 25.0]
#           x     y      z   roll pitch yaw    vx  vy   vz  wx    wy   wz
R_DIAG = [5.0, 5.0, 5.0, 5.0]

# Solver implementation switches
ADMM_USE_FLOAT = _env_bool("ADMM_USE_FLOAT", False)  # False: ap_fixed, True: float
ADMM_ITERATIONS = _env_int("ADMM_ITERATIONS", 10)

# Linear drag terms used to bias the MPC linear model (header_generator.py).
MPC_LINEAR_DRAG_XY = _env_float("ADMM_MPC_LINEAR_DRAG_XY", 0.12)
MPC_LINEAR_DRAG_Z = _env_float("ADMM_MPC_LINEAR_DRAG_Z", 0.12)

# Trajectory timing/generation.
RHO_PARAM = _env_int("ADMM_RHO_PARAM", 128)
DELAY_STEPS = _env_int("ADMM_DELAY_STEPS", 0)
TRAJ_DT = _env_float("ADMM_TRAJ_DT", 0.02)
FIG8_PERIOD_S = _env_float_alias("ADMM_TRAJ_FIG8_PERIOD_S", "ADMM_FIG8_PERIOD_S", 3.0)
REPETITIONS = _env_int("ADMM_REPETITIONS", 6)
TRAJ_WARMSTART_PAD = _env_int("ADMM_TRAJ_WARMSTART_PAD", 60)
TRAJ_TICK_DIV = 10

# Include endpoint sample: duration = (TRAJ_LENGTH - 1) * TRAJ_DT
TRAJ_LENGTH = int(round(REPETITIONS * FIG8_PERIOD_S / TRAJ_DT)) + 1

# Trajectory shape/geometry controls.
TRAJ_SHAPE = os.environ.get("ADMM_TRAJ_SHAPE", "diag_bounce").strip().lower()
AMP_X = _env_float("ADMM_TRAJ_AMP_X", .6)
AMP_Y = _env_float("ADMM_TRAJ_AMP_Y", .6)
Z0 = _env_float("ADMM_TRAJ_Z0", 0.0)
SQUARE_SHARPNESS = _env_float("ADMM_TRAJ_SQUARE_SHARPNESS", 2.8)
STAR_POINTS = _env_int("ADMM_TRAJ_STAR_POINTS", 5)
STAR_INNER_RATIO = _env_float("ADMM_TRAJ_STAR_INNER_RATIO", 0.45)
ROSE_PETALS = _env_int("ADMM_TRAJ_ROSE_PETALS", 3)
ROSE_MOD = _env_float("ADMM_TRAJ_ROSE_MOD", 0.2)
CHICANE_MIX = _env_float("ADMM_TRAJ_CHICANE_MIX", 0.2)
HUBSTAR_VERTICES = _env_int("ADMM_TRAJ_HUBSTAR_VERTICES", 8)
