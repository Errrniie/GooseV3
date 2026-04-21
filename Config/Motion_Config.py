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
TRAVEL_SPEED = 3000  # mm/min for X/Y moves (G0 / MOVE XY feed)

# Search angular velocity
SEARCH_ANGULAR_VELOCITY = 60.0   # degrees/second (~1.33 mm/s)
MAX_ANGULAR_VELOCITY = 90.0      # hard cap deg/s

# MOVE_Z macro: V= argument (units per your Klipper macro)
MOVE_Z_VELOCITY = 2.0

# -----------------------------------------------------------------------------
# Search Pattern Configuration
# -----------------------------------------------------------------------------
# Search sweeps between Z_MIN and Z_MAX
# Internally converted to angles for the sweep math
SEARCH_START_Z = NEUTRAL_Z  # Start at neutral position (mm)
SEARCH_STEP_MM = 1.0  # Z step size per search tick (mm)

# -----------------------------------------------------------------------------
# Camera / stream (Argus CSI via nvarguscamerasrc — V4L2 RG10 path not used for capture)
# -----------------------------------------------------------------------------
CAMERA_ARGUS_SENSOR_ID = 0
CAMERA_WIDTH = 1920
CAMERA_HEIGHT = 1080
CAMERA_FPS = 60

# -----------------------------------------------------------------------------
# Vision timing (see Config.Vision_Config for YOLO thresholds)
# -----------------------------------------------------------------------------
VISION_STALENESS_S = 0.5  # get_latest_detection treats older results as no target

# -----------------------------------------------------------------------------
# Tracking controller (horizontal centering via Z)
# -----------------------------------------------------------------------------
TRACKING_KP = 0.003
TRACKING_KI = 0.0  # integral gain (mm per (pixel·frame) if kp scales px→mm); 0 = P-only
TRACKING_INTEGRAL_MAX_PX = 500.0  # clamp on summed pixel error (windup limit)
TRACKING_DEADZONE_PX = 30
TRACKING_MIN_STEP_MM = 0.05
TRACKING_MAX_STEP_MM = 3.0
TRACKING_TARGET_LOST_FRAMES = 5  # consecutive bad frames before TRACK -> SEARCH


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
