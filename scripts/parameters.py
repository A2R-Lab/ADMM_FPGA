"""Shared ADMM trajectory/packing parameters."""

HORIZON_LENGTH = 40
Q_DIAG = [50.0, 50.0, 178.0, 0.4, 0.4, 40.0, 40.0, 40.0, 4.0, 1, 1, 25.0]
#          x    y      z     roll pitch yaw  vx    vy   vz  wx    wy   wz
R_DIAG = [5.0, 5.0, 5.0, 5.0]

# Solver implementation switches
ADMM_USE_FLOAT = True   # False: ap_fixed, True: float
ADMM_ITERATIONS = 10

# Trajectory timing/generation (hardcoded for reproducible commits).
RHO_PARAM = 64
DELAY_STEPS = 0
TRAJ_DT = 0.02
FIG8_PERIOD_S = 5.5
REPETITIONS = 6

# Include endpoint sample: duration = (TRAJ_LENGTH - 1) * TRAJ_DT
TRAJ_LENGTH = int(round(REPETITIONS * FIG8_PERIOD_S / TRAJ_DT)) + 1
