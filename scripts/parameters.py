"""Shared ADMM trajectory/packing parameters.

Environment overrides are supported to simplify scripted sweeps:
- ADMM_HORIZON_LENGTH
- ADMM_ITERATIONS
- ADMM_USE_FLOAT
- ADMM_ENABLE_TRAJECTORY
- ADMM_SOLVER_ARCH
- ADMM_MPC_LINEAR_DRAG_XY
- ADMM_MPC_LINEAR_DRAG_Z
- ADMM_RHO_EQ_PARAM
- ADMM_RHO_INEQ_PARAM
- ADMM_RHO_PARAM (legacy alias for ADMM_RHO_EQ_PARAM)
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
- ADMM_TRAJ_STAR_INNER_HOLD
- ADMM_TRAJ_ROSE_PETALS
- ADMM_TRAJ_ROSE_MOD
- ADMM_TRAJ_CHICANE_MIX
- ADMM_TRAJ_HUBSTAR_VERTICES
- ADMM_U_ABS_MIN
- ADMM_U_ABS_MAX
- ADMM_XY_MIN
- ADMM_XY_MAX
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


def _env_choice(name: str, default: str, choices: set[str]) -> str:
    raw = os.environ.get(name, default)
    value = raw.strip().lower()
    if value not in choices:
        allowed = ", ".join(sorted(choices))
        raise ValueError(f"Invalid value for {name}: {raw}. Expected one of: {allowed}")
    return value


def _env_float_list(name: str, default: list[float], expected_len: int) -> list[float]:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return list(default)
    vals = [float(tok.strip()) for tok in raw.split(",") if tok.strip()]
    if len(vals) != expected_len:
        raise ValueError(f"{name} expected {expected_len} values, got {len(vals)}")
    return vals


HORIZON_LENGTH = _env_int("ADMM_HORIZON_LENGTH", 40)
Q_DIAG = _env_float_list(
    "ADMM_Q_DIAG",
    [70.0,  # x
     70.0,  # y
     178.0, # z
     0.4,   # roll
     0.4,   # pitch
     40.0,  # yaw
     3.5,   # vx
     3.5,   # vy
     4.0,   # vz
     0.2,   # wx
     0.2,   # wy
     25.0], # wz
    expected_len=12,
)

_BASE_R_DIAG = _env_float_list("ADMM_R_DIAG", [1.0, 1.0, 1.0, 1.0], expected_len=4)
R_SCALE = _env_float("ADMM_R_SCALE", 1.0)
R_DIAG = [R_SCALE * v for v in _BASE_R_DIAG]

# Solver implementation switches
ADMM_USE_FLOAT = _env_bool("ADMM_USE_FLOAT", False)  # False: ap_fixed, True: float
ADMM_ITERATIONS = _env_int("ADMM_ITERATIONS", 10)
ADMM_ENABLE_TRAJECTORY = _env_bool("ADMM_ENABLE_TRAJECTORY", True)
ADMM_SOLVER_ARCH = _env_choice("ADMM_SOLVER_ARCH", "staged_a", {"staged_a", "full_sparse"})
ADMM_SOLVER_INPUT_WIDTH = 418

# Linear drag terms used to bias the MPC linear model (header_generator.py).
MPC_LINEAR_DRAG_XY = _env_float("ADMM_MPC_LINEAR_DRAG_XY", 0.12)
MPC_LINEAR_DRAG_Z = _env_float("ADMM_MPC_LINEAR_DRAG_Z", 0.12)

# ADMM penalty parameters (must be powers of two for shift-based hardware path).
# `ADMM_RHO_PARAM` is kept as a backward-compatible alias for equality rho.
RHO_EQ_PARAM = _env_int("ADMM_RHO_EQ_PARAM", _env_int("ADMM_RHO_PARAM", 128))
RHO_INEQ_PARAM = _env_int("ADMM_RHO_INEQ_PARAM", 32)
RHO_PARAM = RHO_EQ_PARAM
DELAY_STEPS = _env_int("ADMM_DELAY_STEPS", 0)
TRAJ_DT = _env_float("ADMM_TRAJ_DT", 0.02)
FIG8_PERIOD_S = _env_float_alias("ADMM_TRAJ_FIG8_PERIOD_S", "ADMM_FIG8_PERIOD_S", 25.0)
REPETITIONS = _env_int("ADMM_REPETITIONS", 1)
TRAJ_WARMSTART_PAD = _env_int("ADMM_TRAJ_WARMSTART_PAD", 60)
TRAJ_TICK_DIV = 10

# Include endpoint sample: duration = (TRAJ_LENGTH - 1) * TRAJ_DT
TRAJ_LENGTH = int(round(REPETITIONS * FIG8_PERIOD_S / TRAJ_DT)) + 1

# Trajectory shape/geometry controls.
TRAJ_SHAPE = os.environ.get("ADMM_TRAJ_SHAPE", "star_hold").strip().lower()
AMP_X = _env_float("ADMM_TRAJ_AMP_X", 2.0)
AMP_Y = _env_float("ADMM_TRAJ_AMP_Y", 2.0)
Z0 = _env_float("ADMM_TRAJ_Z0", 0.0)
SQUARE_SHARPNESS = _env_float("ADMM_TRAJ_SQUARE_SHARPNESS", 2.8)
STAR_POINTS = _env_int("ADMM_TRAJ_STAR_POINTS", 12)
STAR_INNER_RATIO = _env_float("ADMM_TRAJ_STAR_INNER_RATIO", 1.0 / 4.0)
STAR_INNER_HOLD = _env_float("ADMM_TRAJ_STAR_INNER_HOLD", 0.25)
ROSE_PETALS = _env_int("ADMM_TRAJ_ROSE_PETALS", 3)
ROSE_MOD = _env_float("ADMM_TRAJ_ROSE_MOD", 0.2)
CHICANE_MIX = _env_float("ADMM_TRAJ_CHICANE_MIX", 0.2)
HUBSTAR_VERTICES = _env_int("ADMM_TRAJ_HUBSTAR_VERTICES", 8)

# Constraint bounds used by header_generator.py.
# Input limits are absolute motor command limits before hover-offset conversion.
U_ABS_MIN = _env_float("ADMM_U_ABS_MIN", 0.0)
U_ABS_MAX = _env_float("ADMM_U_ABS_MAX", 1.0)
XY_MIN = _env_float("ADMM_XY_MIN", -1.0)
XY_MAX = _env_float("ADMM_XY_MAX", 1.0)

# Linearization/model frequency used by header generation.
MODEL_FREQ = _env_float("ADMM_MODEL_FREQ", 50.0)
