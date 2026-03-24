# Laser/GroundAim.py
"""
GroundAim - The SINGLE source of truth for laser aiming geometry.

This module computes the motor commands needed to hit a point on the ground.

Physics:
- Beam angle θ = atan(height / distance)
- Mirror angle α = θ / 2 (half-angle law: mirror rotates α → beam rotates 2α)
- Motor command = α * mm_per_rad (convert radians to Klipper mm units)

All aiming code MUST use this module. No duplicate geometry elsewhere.
"""

import math
from Laser.Calibration import (
    LASER_HEIGHT_M, 
    Y_ROTATION_DISTANCE, 
    X_ROTATION_DISTANCE, 
    Y_SIGN, 
    X_SIGN, 
    mm_per_rad
)

# =============================================================================
# PLATFORM ROLL COMPENSATION
# =============================================================================
# The platform may not be level. The BNO055 IMU measures roll (tilt around
# the forward axis). This value is updated by the ESP32 reader thread.
#
# Roll compensation is applied ONLY here - nowhere else in the codebase.
#
# PLATFORM_ROLL_RAD: Current platform roll in radians
#   - Positive = right side down
#   - Negative = left side down
#   - Zero = level
# =============================================================================

PLATFORM_ROLL_RAD = 0.0  # Updated by ESP32 IMU reader thread

def get_motor_deltas_for_ground_hit(x_m: float, z_m: float) -> tuple[float, float]:
    """
    Compute motor deltas (in Klipper mm units) to hit ground at (x_m, z_m).
    
    Args:
        x_m: Lateral offset in meters (positive = right, negative = left)
        z_m: Forward distance in meters (must be > 0)
    
    Returns:
        (dx_mm, dy_mm): Motor deltas to ADD to neutral position
    
    Raises:
        ValueError: If z_m <= 0
    """
    if z_m <= 0:
        raise ValueError("z_m must be > 0")

    # =========================================================================
    # Y-AXIS (PITCH / VERTICAL DEFLECTION)
    # =========================================================================
    
    # Ground distance (horizontal distance from laser to target)
    ground_dist_m = math.sqrt(x_m**2 + z_m**2)
    
    # Beam angle: angle below horizontal to hit the ground
    # θ_beam = atan(height / distance)
    theta_beam_rad = math.atan(LASER_HEIGHT_M / ground_dist_m)
    
    # Mirror angle: half the beam angle (mirror half-angle law)
    # When mirror rotates by α, reflected beam rotates by 2α
    alpha_mirror_rad = theta_beam_rad / 2.0
    
    # =========================================================================
    # ROLL COMPENSATION (Y-AXIS ONLY)
    # =========================================================================
    # 
    # PHYSICAL MEANING:
    # Roll (φ) = rotation about the forward (Z) axis = platform left/right tilt
    # 
    # When the platform rolls by angle φ:
    #   - The Y-mirror's "vertical" axis is tilted relative to true vertical
    #   - A beam aimed at angle θ_cmd (assuming level) actually hits at θ_cmd + φ
    #   - The beam lands SHORT of target when platform rolls forward (positive φ)
    #   - The beam lands LONG of target when platform rolls backward (negative φ)
    #
    # CORRECTION:
    # To hit the intended target, we subtract the roll from the commanded angle:
    #   θ_corrected = θ_cmd - φ
    #
    # In motor space (after half-angle conversion):
    #   α_motor_corrected = α_mirror - (φ / 2)
    #
    # The division by 2 accounts for the mirror half-angle law:
    #   - Mirror rotates by α → beam rotates by 2α
    #   - Platform roll φ appears as beam error of φ
    #   - To correct beam by φ, motor must change by φ/2
    #
    # Sign convention:
    #   - Positive roll (right side down) → beam hits short → subtract positive correction
    #   - Negative roll (left side down) → beam hits long → subtract negative correction (add)
    # =========================================================================
    
    alpha_motor_y_rad = alpha_mirror_rad - (PLATFORM_ROLL_RAD / 2.0)
    
    # Convert radians to Klipper mm units
    dy_mm = Y_SIGN * alpha_motor_y_rad * mm_per_rad(Y_ROTATION_DISTANCE)

    # =========================================================================
    # X-AXIS (YAW / HORIZONTAL DEFLECTION)
    # =========================================================================
    
    # Beam angle: angle left/right from center
    theta_beam_x_rad = math.atan2(x_m, z_m)
    
    # Mirror angle: half the beam angle
    alpha_mirror_x_rad = theta_beam_x_rad / 2.0
    
    # Convert radians to Klipper mm units
    dx_mm = X_SIGN * alpha_mirror_x_rad * mm_per_rad(X_ROTATION_DISTANCE)

    # =========================================================================
    # DEBUG OUTPUT (for verification only)
    # =========================================================================
    roll_correction_rad = PLATFORM_ROLL_RAD / 2.0
    print(f"[GroundAim] ───────────────────────────────────────────────────")
    print(f"  Target:        x={x_m:.4f}m, z={z_m:.4f}m")
    print(f"  Ground dist:   {ground_dist_m:.4f}m")
    print(f"  Laser height:  {LASER_HEIGHT_M:.4f}m")
    print(f"  Beam angle:    {math.degrees(theta_beam_rad):.3f}°")
    print(f"  Mirror angle:  {math.degrees(alpha_mirror_rad):.3f}° (= beam/2)")
    print(f"  Platform roll: {math.degrees(PLATFORM_ROLL_RAD):.2f}°")
    print(f"  Roll correction: {math.degrees(roll_correction_rad):+.3f}° (motor space)")
    print(f"  Motor Y (corrected): {math.degrees(alpha_motor_y_rad):.3f}° → {dy_mm:+.3f}mm")
    print(f"  Motor X:       {math.degrees(alpha_mirror_x_rad):.3f}° → {dx_mm:+.3f}mm")
    print(f"─────────────────────────────────────────────────────────────────")

    return dx_mm, dy_mm
