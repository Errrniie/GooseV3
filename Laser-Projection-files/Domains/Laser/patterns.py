"""
Laser/DeterrencePattern.py - Square Deterrence Pattern Control

This module generates and controls a square deterrence pattern around a target point.
Python computes all geometry, Klipper executes motion.

Pattern is centered on a ground hit point:
  - Input: target distance (inches), square size (feet)
  - Square corners are offset ±(size/2) from center
  - Each corner is converted via AimSolver to absolute motor positions
  - Klipper macros handle the perimeter stepping

Architecture:
  - Python: geometry decisions (this file)
  - Klipper: motion timing only (SQUARE_DEFINE, SQUARE_START, SQUARE_STOP)
"""

from typing import Tuple, List
from Laser.AimSolver import solve_ground_hit

# =============================================================================
# UNIT CONVERSION
# =============================================================================

def inches_to_meters(inches: float) -> float:
    """Convert inches to meters."""
    return inches * 0.0254

def feet_to_meters(feet: float) -> float:
    """Convert feet to meters."""
    return feet * 0.3048

# =============================================================================
# PATTERN GEOMETRY
# =============================================================================

def compute_square_corners(target_dist_in: float, square_size_ft: float) -> List[Tuple[float, float]]:
    """
    Compute the 4 corners of a square pattern centered on the target distance.
    
    Args:
        target_dist_in: Forward distance to target center in inches
        square_size_ft: Size of the square in feet
    
    Returns:
        List of 4 corner coordinates as (x_m, z_m) tuples in meters:
        [bottom-left, bottom-right, top-right, top-left]
        
    Pattern layout (looking down at ground):
        
        TL ─────── TR      (far from laser)
        │         │
        │    +    │        (+ = center at target_dist)
        │         │
        BL ─────── BR      (close to laser)
        
        ← X →              (lateral direction)
        ↑ Z                (forward direction)
    """
    # Convert to meters
    z_center_m = inches_to_meters(target_dist_in)
    half_size_m = feet_to_meters(square_size_ft) / 2.0
    
    # Compute corners: (x_m, z_m)
    # Order: BL → BR → TR → TL (counter-clockwise from bottom-left)
    corners = [
        (-half_size_m, z_center_m - half_size_m),  # Bottom-left
        ( half_size_m, z_center_m - half_size_m),  # Bottom-right
        ( half_size_m, z_center_m + half_size_m),  # Top-right
        (-half_size_m, z_center_m + half_size_m),  # Top-left
    ]
    
    return corners

def compute_motor_positions(corners: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """
    Convert ground coordinates to absolute motor positions.
    
    Uses AimSolver.solve_ground_hit() for each corner.
    
    Args:
        corners: List of (x_m, z_m) ground coordinates
    
    Returns:
        List of (x_mm, y_mm) absolute motor positions
    """
    motor_positions = []
    
    for x_m, z_m in corners:
        x_mm, y_mm = solve_ground_hit(x_m, z_m)
        motor_positions.append((x_mm, y_mm))
    
    return motor_positions

# =============================================================================
# PATTERN CONTROL FUNCTIONS
# =============================================================================

def start_square_pattern(ws, target_dist_in: float, square_size_ft: float, 
                         speed: int = 12000, dwell_ms: int = 100) -> None:
    """
    Start a square deterrence pattern centered at the target distance.
    
    This function:
    1. Computes square corners in ground coordinates
    2. Converts each corner to motor positions via AimSolver
    3. Sends SQUARE_DEFINE with all 4 corner positions
    4. Sends SQUARE_START to begin the pattern
    
    Args:
        ws: MoonrakerWSClient instance
        target_dist_in: Forward distance to pattern center in inches
        square_size_ft: Size of the square pattern in feet
        speed: Motor speed for pattern moves (mm/min)
        dwell_ms: Dwell time at each corner in milliseconds
    
    Example:
        start_square_pattern(ws, target_dist_in=140, square_size_ft=0.5)
    """
    # Step 1: Compute ground coordinates for square corners
    corners = compute_square_corners(target_dist_in, square_size_ft)
    
    # Step 2: Convert to motor positions
    motor_positions = compute_motor_positions(corners)
    
    # Debug output
    print(f"\n[Pattern] ═══════════════════════════════════════════════════════")
    print(f"  Target distance: {target_dist_in:.1f} inches")
    print(f"  Square size:     {square_size_ft:.2f} ft × {square_size_ft:.2f} ft")
    print(f"  Speed:           {speed} mm/min")
    print(f"  Dwell:           {dwell_ms} ms")
    print(f"  Corners (ground coords in meters):")
    for i, (x_m, z_m) in enumerate(corners):
        print(f"    Corner {i+1}: x={x_m:+.4f}m, z={z_m:.4f}m")
    print(f"  Motor positions (absolute mm):")
    for i, (x_mm, y_mm) in enumerate(motor_positions):
        print(f"    Corner {i+1}: X={x_mm:.3f}mm, Y={y_mm:.3f}mm")
    print(f"═══════════════════════════════════════════════════════════════════")
    
    # Step 3: Send SQUARE_DEFINE with all corner positions
    # Format: SQUARE_DEFINE X1=... Y1=... X2=... Y2=... X3=... Y3=... X4=... Y4=... SPEED=... DWELL=...
    gcode = (
        f"GRID_DEFINE "
        f"X1={motor_positions[0][0]:.3f} Y1={motor_positions[0][1]:.3f} "
        f"X2={motor_positions[1][0]:.3f} Y2={motor_positions[1][1]:.3f} "
        f"X3={motor_positions[2][0]:.3f} Y3={motor_positions[2][1]:.3f} "
        f"X4={motor_positions[3][0]:.3f} Y4={motor_positions[3][1]:.3f} "
        f"SPEED={speed} DWELL={dwell_ms}"
    )
    ws.send_gcode(gcode)
    
    # Step 4: Start the pattern
    ws.send_gcode("GRID_START")
    
    print(f"[Pattern] ✓ Square pattern started")

def stop_pattern(ws) -> None:
    """
    Stop the currently running deterrence pattern immediately.
    
    Args:
        ws: MoonrakerWSClient instance
    """
    ws.send_gcode("GRID_STOP")
    print("[Pattern] ✗ Pattern stopped")

# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def aim_and_pattern(ws, target_dist_in: float, square_size_ft: float = 0.5,
                    speed: int = 12000, dwell_ms: int = 100) -> None:
    """
    Convenience function to start a deterrence pattern at a target.
    
    Args:
        ws: MoonrakerWSClient instance
        target_dist_in: Distance to target in inches
        square_size_ft: Pattern size in feet (default 0.5 ft = 6 inches)
        speed: Motor speed (default 12000 mm/min)
        dwell_ms: Dwell at corners (default 100 ms)
    """
    start_square_pattern(ws, target_dist_in, square_size_ft, speed, dwell_ms)
