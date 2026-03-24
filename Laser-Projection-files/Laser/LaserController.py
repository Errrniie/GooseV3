# Laser/LaserController.py
from Motion.Move import safe_move_and_wait
from Laser.AimSolver import solve_ground_hit

def aim_at_coordinates(ws_client, x_m: float, z_m: float, speed: int = 600):
    """
    Aim the laser to hit the ground at the specified (x_m, z_m) coordinates.
    """
    x_target, y_target = solve_ground_hit(x_m, z_m)
    
    # The motion system uses X and Y for the laser galvanometers
    safe_move_and_wait(ws_client, z=None, x=x_target, y=y_target, speed=speed)
