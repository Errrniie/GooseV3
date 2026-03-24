"""
Laser/Calibration.py - Rotary Mirror Axis Calibration Constants

=============================================================================
CRITICAL: UNDERSTANDING ROTATION_DISTANCE FOR ROTARY AXES
=============================================================================

Klipper's rotation_distance is designed for linear axes where:
    linear_distance = steps * (rotation_distance / steps_per_rev)

For ROTARY MIRROR axes, there is no linear travel. The "mm" units are VIRTUAL.
We repurpose rotation_distance as a SCALE FACTOR that converts commanded "mm"
to physical mirror rotation:

    physical_degrees = commanded_mm * (360 / rotation_distance)

Or equivalently:
    rotation_distance = 360 / (degrees_per_mm)

CALIBRATION PROCEDURE:
1. Command a known Δmm (e.g., G1 Y+10 F1000)
2. Measure the actual mirror rotation Δθ in degrees
3. Compute: rotation_distance = commanded_mm * (360 / Δθ)

Example:
    - Command: G1 Y+10
    - Measured rotation: 5.0 degrees
    - rotation_distance = 10 * (360 / 5.0) = 720

If your geometry is correct but shots consistently undershoot/overshoot,
rotation_distance is WRONG. Re-calibrate it.

=============================================================================
"""

import math

# =============================================================================
# AXIS DIRECTION SIGNS
# =============================================================================
# Set to +1 or -1 to match your motor wiring and coordinate conventions.
# Y_SIGN: +1 if positive motor command moves beam DOWN toward ground
# X_SIGN: +1 if positive motor command moves beam RIGHT

Y_SIGN = -1
X_SIGN = +1

# =============================================================================
# NEUTRAL MOTOR POSITIONS (Klipper "mm" units)
# =============================================================================
# These are the motor positions where the laser points straight ahead (level).
# Measure by homing, then manually aiming laser horizontally at a distant wall.

X_NEUTRAL_MM = 108.5
Y_NEUTRAL_MM = 71.0

# =============================================================================
# AXIS TRAVEL LIMITS (Klipper "mm" units)
# =============================================================================

Y_MIN = 0
Y_MAX = 136.8

X_MIN = 0
X_MAX = 207.0

# =============================================================================
# ROTATION_DISTANCE - THE CRITICAL SCALE FACTOR
# =============================================================================
# These values MUST be empirically calibrated. Do NOT guess.
#
# rotation_distance defines how many "mm" Klipper must command for one full
# 360° rotation of the mirror axis.
#
# Formula: rotation_distance = commanded_mm * (360 / measured_degrees)
#
# If these are wrong, ALL shots will be scaled incorrectly (consistent
# undershoot or overshoot that grows with distance).
#
# VALIDATE: After calibration, command +10mm and verify the mirror rotates
# by exactly: 10 * (360 / rotation_distance) degrees

Y_ROTATION_DISTANCE = 720.0  # CALIBRATE THIS - see procedure above
X_ROTATION_DISTANCE = 720.0  # CALIBRATE THIS - see procedure above

# =============================================================================
# PHYSICAL SETUP
# =============================================================================

LASER_HEIGHT_M = 1.119  # Height of laser above ground in meters

# =============================================================================
# UNIT CONVERSION FUNCTIONS
# =============================================================================

def mm_per_rad(rotation_distance: float) -> float:
    """
    Convert rotation_distance to mm per radian.
    
    This is the ONLY function that should be used for angle→motor conversion.
    
    Args:
        rotation_distance: Klipper rotation_distance for the axis
    
    Returns:
        Klipper "mm" per radian of mirror rotation
    """
    return rotation_distance / (2 * math.pi)

def mm_per_deg(rotation_distance: float) -> float:
    """
    Convert rotation_distance to mm per degree.
    
    Args:
        rotation_distance: Klipper rotation_distance for the axis
    
    Returns:
        Klipper "mm" per degree of mirror rotation
    """
    return rotation_distance / 360.0

def deg_per_mm(rotation_distance: float) -> float:
    """
    Convert rotation_distance to degrees per mm.
    
    Args:
        rotation_distance: Klipper rotation_distance for the axis
    
    Returns:
        Degrees of mirror rotation per Klipper "mm"
    """
    return 360.0 / rotation_distance

# =============================================================================
# CALIBRATION HELPER
# =============================================================================

def compute_rotation_distance(commanded_mm: float, measured_degrees: float) -> float:
    """
    Compute the correct rotation_distance from a calibration measurement.
    
    Procedure:
    1. Command a known Δmm movement (e.g., G1 Y+10)
    2. Measure the actual mirror rotation in degrees
    3. Call this function with those values
    4. Update the rotation_distance constant in this file
    
    Args:
        commanded_mm: The "mm" value sent to Klipper (e.g., 10.0)
        measured_degrees: The actual mirror rotation measured (e.g., 5.0)
    
    Returns:
        The correct rotation_distance value
    
    Example:
        >>> compute_rotation_distance(10.0, 5.0)
        720.0
    """
    if measured_degrees <= 0:
        raise ValueError("measured_degrees must be positive")
    if commanded_mm <= 0:
        raise ValueError("commanded_mm must be positive")
    
    rotation_distance = commanded_mm * (360.0 / measured_degrees)
    
    print(f"\n{'='*60}")
    print("ROTATION_DISTANCE CALIBRATION RESULT")
    print(f"{'='*60}")
    print(f"  Commanded:       {commanded_mm:.3f} mm")
    print(f"  Measured:        {measured_degrees:.3f} degrees")
    print(f"  rotation_distance = {rotation_distance:.2f}")
    print(f"{'='*60}")
    print(f"  → mm per degree: {mm_per_deg(rotation_distance):.4f}")
    print(f"  → mm per radian: {mm_per_rad(rotation_distance):.4f}")
    print(f"  → degrees per mm: {deg_per_mm(rotation_distance):.4f}")
    print(f"{'='*60}\n")
    
    return rotation_distance

# =============================================================================
# VALIDATION
# =============================================================================

def validate_rotation_distance(rotation_distance: float, axis_name: str) -> bool:
    """
    Check if rotation_distance is within plausible range.
    
    Typical values for small galvo mirrors: 100-2000
    Values outside this range likely indicate misconfiguration.
    
    Args:
        rotation_distance: The value to check
        axis_name: Name of axis for error messages (e.g., "Y")
    
    Returns:
        True if valid, False if suspicious
    """
    MIN_PLAUSIBLE = 50.0
    MAX_PLAUSIBLE = 5000.0
    
    if rotation_distance < MIN_PLAUSIBLE:
        print(f"⚠ WARNING: {axis_name}_ROTATION_DISTANCE={rotation_distance} is very low!")
        print(f"  This means {deg_per_mm(rotation_distance):.2f}°/mm - mirror may overcorrect.")
        return False
    
    if rotation_distance > MAX_PLAUSIBLE:
        print(f"⚠ WARNING: {axis_name}_ROTATION_DISTANCE={rotation_distance} is very high!")
        print(f"  This means {deg_per_mm(rotation_distance):.4f}°/mm - mirror may barely move.")
        return False
    
    return True

def print_calibration_summary() -> None:
    """
    Print current calibration values for verification.
    Call this on startup to confirm configuration.
    """
    print(f"\n{'='*70}")
    print("LASER CALIBRATION SUMMARY")
    print(f"{'='*70}")
    print(f"  Laser height:     {LASER_HEIGHT_M:.4f} m ({LASER_HEIGHT_M / 0.0254:.1f} inches)")
    print(f"  Neutral position: X={X_NEUTRAL_MM:.2f} mm, Y={Y_NEUTRAL_MM:.2f} mm")
    print(f"{'='*70}")
    print("  Y-AXIS (Pitch):")
    print(f"    rotation_distance: {Y_ROTATION_DISTANCE:.2f}")
    print(f"    mm per radian:     {mm_per_rad(Y_ROTATION_DISTANCE):.4f}")
    print(f"    mm per degree:     {mm_per_deg(Y_ROTATION_DISTANCE):.4f}")
    print(f"    degrees per mm:    {deg_per_mm(Y_ROTATION_DISTANCE):.4f}")
    validate_rotation_distance(Y_ROTATION_DISTANCE, "Y")
    print(f"{'='*70}")
    print("  X-AXIS (Yaw):")
    print(f"    rotation_distance: {X_ROTATION_DISTANCE:.2f}")
    print(f"    mm per radian:     {mm_per_rad(X_ROTATION_DISTANCE):.4f}")
    print(f"    mm per degree:     {mm_per_deg(X_ROTATION_DISTANCE):.4f}")
    print(f"    degrees per mm:    {deg_per_mm(X_ROTATION_DISTANCE):.4f}")
    validate_rotation_distance(X_ROTATION_DISTANCE, "X")
    print(f"{'='*70}\n")

# =============================================================================
# INTERACTIVE CALIBRATION TOOL
# =============================================================================

def run_calibration_wizard() -> None:
    """
    Interactive calibration wizard for rotation_distance.
    
    Run this as: python -c "from Laser.Calibration import run_calibration_wizard; run_calibration_wizard()"
    """
    print("\n" + "="*70)
    print("ROTATION_DISTANCE CALIBRATION WIZARD")
    print("="*70)
    print("""
This wizard helps you determine the correct rotation_distance for your
rotary mirror axes.

PROCEDURE:
1. Home the machine
2. Note the current Y position
3. Send: G1 Y+10 F1000 (or any known Δmm)
4. Measure the actual mirror rotation in degrees
5. Enter the values below
""")
    
    try:
        commanded = float(input("Enter commanded Δmm (e.g., 10): "))
        measured = float(input("Enter measured rotation in degrees: "))
        
        result = compute_rotation_distance(commanded, measured)
        
        print("\nTo apply this calibration:")
        print(f"1. Edit Laser/Calibration.py")
        print(f"2. Set Y_ROTATION_DISTANCE = {result:.2f}")
        print(f"3. Repeat for X axis if needed")
        
    except ValueError as e:
        print(f"Error: {e}")
    except KeyboardInterrupt:
        print("\nCalibration cancelled.")

