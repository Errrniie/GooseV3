"""
Tracking Controller - Computes tracking intent from vision error.

Architecture mirrors Search_v2.py:
- Input: detection state (bbox_center)
- Output: {"z_delta": float} - same format as Search
- No threading, no direct motor commands
- Main.py calls this the same way it calls Search

Tracking math:
- Get (cx, cy) from detection
- Compare cx to frame center
- Compute error in pixels
- Apply deadzone to avoid jitter
- Apply proportional control to get z_delta
- Clamp to reasonable step size
"""

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class TrackingConfig:
    """Tracking controller configuration."""
    frame_width: int = 1920        # Camera frame width in pixels (1080p)
    frame_height: int = 1080        # Camera frame height in pixels (1080p)
    deadzone_px: int = 30           # Pixels from center to ignore (avoids jitter)
    kp: float = 0.003               # Proportional gain (pixels → mm)
    max_step_mm: float = 3.0        # Maximum Z delta per step (clamp)
    min_step_mm: float = 0.05        # Minimum Z delta (below this = no move)
    confidence_threshold: float = 0.7  # Minimum confidence to track


class TrackingController:
    """
    Computes tracking intent from vision detection.
    
    Usage mirrors SearchController:
        tracker = TrackingController(config)
        result = tracker.update(detection)
        if result["should_move"]:
            motion.move_z_relative_blocking(result["z_delta"])
    
    Does NOT:
    - Command motors directly
    - Run in a separate thread
    - Block on anything
    """

    def __init__(self, config: TrackingConfig):
        self._config = config
        self._center_x = config.frame_width // 2
        self._center_y = config.frame_height // 2
        
        # Track consecutive frames without target for hysteresis
        self._frames_without_target = 0
        self._target_lost_threshold = 5  # Frames before declaring target lost

    def reset(self) -> None:
        """Reset tracking state."""
        self._frames_without_target = 0

    def update(self, bbox_center: Optional[Tuple[int, int]], confidence: float) -> dict:
        """
        Compute tracking intent from current detection.
        
        Args:
            bbox_center: (cx, cy) in pixels, or None if no detection
            confidence: Detection confidence (0.0 - 1.0)
        
        Returns:
            {
                "should_move": bool,      # True if motion is needed
                "z_delta": float,         # Relative Z movement in mm
                "error_px": float,        # Raw error in pixels (for debug)
                "target_locked": bool,    # True if target is being tracked
            }
        """
        # No detection or low confidence
        if bbox_center is None or confidence < self._config.confidence_threshold:
            self._frames_without_target += 1
            return {
                "should_move": False,
                "z_delta": 0.0,
                "error_px": 0.0,
                "target_locked": False,
            }
        
        # Valid detection - reset lost counter
        self._frames_without_target = 0
        
        cx, cy = bbox_center
        
        # Compute horizontal error (positive = target is right of center)
        error_px = cx - self._center_x
        
        # Apply deadzone
        if abs(error_px) < self._config.deadzone_px:
            return {
                "should_move": False,
                "z_delta": 0.0,
                "error_px": error_px,
                "target_locked": True,
            }
        
        # Proportional control: error (px) → z_delta (mm)
        # Sign convention: positive error (target right) → positive Z (rotate right)
        # This brings target back toward center
        z_delta = self._config.kp * error_px
        
        # Clamp to max step size
        z_delta = max(-self._config.max_step_mm, min(self._config.max_step_mm, z_delta))
        
        # Filter out tiny movements
        if abs(z_delta) < self._config.min_step_mm:
            return {
                "should_move": False,
                "z_delta": 0.0,
                "error_px": error_px,
                "target_locked": True,
            }
        
        return {
            "should_move": True,
            "z_delta": z_delta,
            "error_px": error_px,
            "target_locked": True,
        }

    def is_target_lost(self) -> bool:
        """
        Returns True if target has been lost for multiple consecutive frames.
        Used for state transition back to SEARCH.
        """
        return self._frames_without_target >= self._target_lost_threshold
