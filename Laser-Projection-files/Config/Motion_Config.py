# =============================================================================
# Motion System Configuration
# =============================================================================
# All physical units in mm, mm/s, degrees, degrees/s
# This is the single source of truth for motion parameters.

# -----------------------------------------------------------------------------
# Axis Limits (mm)
# -----------------------------------------------------------------------------
X_MIN = 0.0
X_MAX = 11.5
Y_MIN = 0.0
Y_MAX = 7.60
Z_MIN = 0.0
Z_MAX = 7.00

# -----------------------------------------------------------------------------
# Neutral / Home Position (mm)
# -----------------------------------------------------------------------------
NEUTRAL_X = 5.75
NEUTRAL_Y = 3.80
NEUTRAL_Z = 3.00  # Starting Z position for search/tracking

# -----------------------------------------------------------------------------
# Z Axis Geometry
# -----------------------------------------------------------------------------
# Rotation distance: 8mm per full motor revolution (360°)
ROTATION_DISTANCE_MM = 8.0
DEGREES_PER_REVOLUTION = 360.0
MM_PER_DEGREE = ROTATION_DISTANCE_MM / DEGREES_PER_REVOLUTION  # 0.0222 mm/deg

# -----------------------------------------------------------------------------
# Speed Settings
# -----------------------------------------------------------------------------
TRAVEL_SPEED = 3000  # mm/min for X/Y moves
Z_SPEED = 5        # mm/min for Z moves (blocking/init)

# Search angular velocity
SEARCH_ANGULAR_VELOCITY = 60.0   # degrees/second (~1.33 mm/s)
MAX_ANGULAR_VELOCITY = 90.0      # hard cap deg/s

# -----------------------------------------------------------------------------
# Motion Controller Timing
# -----------------------------------------------------------------------------
SEND_RATE_HZ = 10.0          # Command send rate (Hz) - lower = smoother
FEEDRATE_MULTIPLIER = 2.0   # Overspeed factor for smooth streaming

# -----------------------------------------------------------------------------
# Search Pattern Configuration
# -----------------------------------------------------------------------------
# Search sweeps between Z_MIN and Z_MAX
# Internally converted to angles for the sweep math
SEARCH_START_Z = NEUTRAL_Z  # Start at neutral position (mm)


# =============================================================================
# Derived / Computed Values (do not edit)
# =============================================================================
def z_mm_to_angle(z_mm: float) -> float:
    """Convert Z position in mm to angle in degrees."""
    return z_mm / MM_PER_DEGREE

def angle_to_z_mm(angle_deg: float) -> float:
    """Convert angle in degrees to Z position in mm."""
    return angle_deg * MM_PER_DEGREE

# Pre-computed angle limits for search
SEARCH_MIN_ANGLE = z_mm_to_angle(Z_MIN)  # 0°
SEARCH_MAX_ANGLE = z_mm_to_angle(Z_MAX)  # 900°
SEARCH_START_ANGLE = z_mm_to_angle(SEARCH_START_Z)  # 450°
