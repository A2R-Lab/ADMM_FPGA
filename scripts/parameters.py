"""Shared ADMM trajectory/packing parameters."""

HORIZON_LENGTH = 20
Q_DIAG = [60.0, 60.0, 178.0, 0.4, 0.4, 4.0, 4.0, 4.0, 4.0, 0.2, 0.2, 25.0]
R_DIAG = [20.0, 20.0, 20.0, 20.0]

# Trajectory timing/generation (hardcoded for reproducible commits).

TRAJ_DT = 0.02
FIG8_PERIOD_S = 5.0
REPETITIONS = 3

TRAJ_LENGTH = int(REPETITIONS * FIG8_PERIOD_S / TRAJ_DT)
