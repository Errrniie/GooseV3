# Laser/AimSolver.py
from Laser.GroundAim import get_motor_deltas_for_ground_hit
from Laser.Calibration import (
    X_NEUTRAL_MM,
    Y_NEUTRAL_MM
)

def solve_ground_hit(x_m, z_m):
    """
    Returns (x_mm, y_mm) motor targets to hit ground at given coordinates.
    """
    dx_mm, dy_mm = get_motor_deltas_for_ground_hit(x_m, z_m)

    x_target = X_NEUTRAL_MM + dx_mm
    y_target = Y_NEUTRAL_MM + dy_mm

    return x_target, y_target
