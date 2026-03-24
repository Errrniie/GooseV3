import numpy as np

# --- Globals ---
# For get_distance(y): y must be increasing for np.interp
_interp_y = None
_interp_dist_from_y = None

# For get_y(distance): distance must be increasing for np.interp
_interp_dist = None
_interp_y_from_dist = None

def load_model(calibration_data):
    """
    Loads the distance model from calibration data.
    The model uses linear interpolation between the calibrated points, which is more robust
    than a polynomial fit for this type of data.
    """
    global _interp_y, _interp_dist_from_y, _interp_dist, _interp_y_from_dist
    
    if not calibration_data or len(calibration_data) < 2:
        raise ValueError("Calibration data must contain at least two points for interpolation.")

    # --- Prepare for get_y(distance) ---
    # Sort by distance (ascending), which is the required order for np.interp's x-array.
    cal_sorted_by_dist = sorted(calibration_data, key=lambda p: p[1])
    _interp_dist = np.array([p[1] for p in cal_sorted_by_dist])
    _interp_y_from_dist = np.array([p[0] for p in cal_sorted_by_dist])

    # --- Prepare for get_distance(y) ---
    # Sort by y-coordinate (ascending) for the other interpolation direction.
    cal_sorted_by_y = sorted(calibration_data, key=lambda p: p[0])
    _interp_y = np.array([p[0] for p in cal_sorted_by_y])
    _interp_dist_from_y = np.array([p[1] for p in cal_sorted_by_y])
    
    print("Distance model loaded using linear interpolation.")

def get_distance(y):
    """
    Get the estimated distance for a given y-coordinate using linear interpolation.
    np.interp handles extrapolation linearly beyond the calibrated range.
    """
    if _interp_y is None:
        raise RuntimeError("Distance model not loaded. Call load_model() first.")
    
    return np.interp(y, _interp_y, _interp_dist_from_y)

def get_y(distance):
    """
    Get the estimated y-coordinate for a given distance using linear interpolation.
    """
    if _interp_dist is None:
        raise RuntimeError("Distance model not loaded. Call load_model() first.")
    
    return np.interp(distance, _interp_dist, _interp_y_from_dist)
