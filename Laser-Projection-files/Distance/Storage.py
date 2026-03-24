# Distance/Storage.py
"""
Storage module for managing multiple calibrations in a single JSON file.
Supports calibration metadata, points, and test results.
"""

import json
import os
from datetime import datetime

CALIBRATION_FILE = "camera_calibration.json"


def _get_default_storage():
    """Returns the default storage structure."""
    return {
        "version": "2.0",
        "calibrations": {}
    }


def _load_storage():
    """Load the entire storage file."""
    try:
        with open(CALIBRATION_FILE, 'r') as f:
            data = json.load(f)
            # Handle legacy format (list of points)
            if isinstance(data, list):
                return _migrate_legacy_data(data)
            return data
    except FileNotFoundError:
        return _get_default_storage()
    except json.JSONDecodeError as e:
        print(f"Error parsing calibration file: {e}")
        return _get_default_storage()
    except IOError as e:
        print(f"Error loading calibration file: {e}")
        return _get_default_storage()


def _save_storage(data):
    """Save the entire storage file."""
    try:
        with open(CALIBRATION_FILE, 'w') as f:
            json.dump(data, f, indent=4)
        return True
    except IOError as e:
        print(f"Error saving calibration file: {e}")
        return False


def _migrate_legacy_data(legacy_data):
    """Migrate legacy calibration format to new multi-calibration format."""
    storage = _get_default_storage()
    
    if legacy_data and len(legacy_data) > 0:
        # Create a default calibration from legacy data
        storage["calibrations"]["legacy_calibration"] = {
            "name": "legacy_calibration",
            "created_at": datetime.now().isoformat(),
            "metadata": {
                "source_type": "live_camera",
                "source_path": None,
                "resolution": {"width": None, "height": None},
                "fps": None,
                "zoom_label": "unknown"
            },
            "distance_list": [p[1] for p in legacy_data],
            "calibration_points": legacy_data,
            "test_results": []
        }
        print("Migrated legacy calibration data to new format.")
    
    return storage


# --- Public API ---

def list_calibrations():
    """
    List all available calibrations.
    
    Returns:
        List of dictionaries with calibration info:
        [{"name": str, "created_at": str, "zoom_label": str, "num_points": int}, ...]
    """
    storage = _load_storage()
    calibrations = []
    
    for name, cal in storage.get("calibrations", {}).items():
        calibrations.append({
            "name": name,
            "created_at": cal.get("created_at", "unknown"),
            "zoom_label": cal.get("metadata", {}).get("zoom_label", "unknown"),
            "num_points": len(cal.get("calibration_points", [])),
            "source_type": cal.get("metadata", {}).get("source_type", "unknown")
        })
    
    return calibrations


def get_calibration(name):
    """
    Get a specific calibration by name.
    
    Args:
        name: Calibration name
    
    Returns:
        Calibration dictionary or None if not found
    """
    storage = _load_storage()
    return storage.get("calibrations", {}).get(name)


def get_calibration_points(name):
    """
    Get calibration points for a specific calibration.
    This is the format expected by Model.load_model().
    
    Args:
        name: Calibration name
    
    Returns:
        List of (y_pixel, distance) tuples or None
    """
    cal = get_calibration(name)
    if cal:
        return cal.get("calibration_points", [])
    return None


def create_calibration(name, metadata, distance_list, calibration_points):
    """
    Create a new calibration.
    
    Args:
        name: Unique calibration name
        metadata: Dict with source_type, source_path, resolution, fps, zoom_label
        distance_list: List of distance values used for calibration
        calibration_points: List of (y_pixel, distance) tuples
    
    Returns:
        True on success, False on failure
    """
    storage = _load_storage()
    
    if name in storage.get("calibrations", {}):
        print(f"Warning: Calibration '{name}' already exists. Overwriting.")
    
    storage["calibrations"][name] = {
        "name": name,
        "created_at": datetime.now().isoformat(),
        "metadata": metadata,
        "distance_list": distance_list,
        "calibration_points": calibration_points,
        "test_results": []
    }
    
    if _save_storage(storage):
        print(f"Calibration '{name}' saved successfully.")
        return True
    return False


def delete_calibration(name):
    """
    Delete a calibration by name.
    
    Args:
        name: Calibration name
    
    Returns:
        True if deleted, False if not found or error
    """
    storage = _load_storage()
    
    if name not in storage.get("calibrations", {}):
        print(f"Calibration '{name}' not found.")
        return False
    
    del storage["calibrations"][name]
    
    if _save_storage(storage):
        print(f"Calibration '{name}' deleted.")
        return True
    return False


def add_test_result(calibration_name, test_result):
    """
    Add a test result to a calibration.
    
    Args:
        calibration_name: Name of the calibration
        test_result: Dict with known_distance, estimated_distance, error_percent, 
                     feet_y, frame_number, timestamp
    
    Returns:
        True on success, False on failure
    """
    storage = _load_storage()
    
    if calibration_name not in storage.get("calibrations", {}):
        print(f"Calibration '{calibration_name}' not found.")
        return False
    
    test_result["timestamp"] = datetime.now().isoformat()
    storage["calibrations"][calibration_name]["test_results"].append(test_result)
    
    return _save_storage(storage)


def get_test_results(calibration_name):
    """
    Get all test results for a calibration.
    
    Args:
        calibration_name: Name of the calibration
    
    Returns:
        List of test result dictionaries or empty list
    """
    cal = get_calibration(calibration_name)
    if cal:
        return cal.get("test_results", [])
    return []


def clear_test_results(calibration_name):
    """
    Clear all test results for a calibration.
    
    Args:
        calibration_name: Name of the calibration
    
    Returns:
        True on success, False on failure
    """
    storage = _load_storage()
    
    if calibration_name not in storage.get("calibrations", {}):
        print(f"Calibration '{calibration_name}' not found.")
        return False
    
    storage["calibrations"][calibration_name]["test_results"] = []
    return _save_storage(storage)


# --- Legacy API (for backward compatibility) ---

def save_calibration_data(data):
    """
    Legacy function: Saves calibration data.
    Creates a 'default' calibration for backward compatibility.
    """
    return create_calibration(
        name="default",
        metadata={
            "source_type": "live_camera",
            "source_path": None,
            "resolution": {"width": None, "height": None},
            "fps": None,
            "zoom_label": "default"
        },
        distance_list=[p[1] for p in data],
        calibration_points=data
    )


def load_calibration_data():
    """
    Legacy function: Loads calibration data.
    Returns points from 'default' calibration if exists, otherwise first available.
    """
    storage = _load_storage()
    calibrations = storage.get("calibrations", {})
    
    if not calibrations:
        print("No calibrations found. Please run the calibration process.")
        return None
    
    # Try 'default' first, then 'legacy_calibration', then first available
    for name in ["default", "legacy_calibration"]:
        if name in calibrations:
            return calibrations[name].get("calibration_points", [])
    
    # Return first available
    first_name = next(iter(calibrations))
    return calibrations[first_name].get("calibration_points", [])


# --- Detection Coverage API ---

def save_detection_coverage(calibration_name, coverage_data):
    """
    Save detection coverage analysis results to a calibration.
    
    Args:
        calibration_name: Name of the calibration to store results under
        coverage_data: Dict with total_frames, detected_frames, percent_detected, etc.
    
    Returns:
        True on success, False on failure
    """
    storage = _load_storage()
    
    if calibration_name not in storage.get("calibrations", {}):
        print(f"Calibration '{calibration_name}' not found.")
        return False
    
    # Add timestamp and store
    coverage_data["timestamp"] = datetime.now().isoformat()
    storage["calibrations"][calibration_name]["detection_coverage"] = coverage_data
    
    return _save_storage(storage)


def get_detection_coverage(calibration_name):
    """
    Get detection coverage data for a calibration.
    
    Args:
        calibration_name: Name of the calibration
    
    Returns:
        Detection coverage dictionary or None if not found
    """
    cal = get_calibration(calibration_name)
    if cal:
        return cal.get("detection_coverage")
    return None
