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
- PI control: z_delta = kp * error + ki * integral(error), integral clamped + anti-windup on step clamp
- Clamp to reasonable step size
"""

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Tuple, Union


@dataclass
class TrackingConfig:
    """Tracking controller configuration (defaults mirror Config.Motion_Config)."""
    frame_width: int = 1920
    frame_height: int = 1080
    deadzone_px: int = 30
    kp: float = 0.003
    ki: float = 0.0
    integral_max_px: float = 500.0
    max_step_mm: float = 3.0
    min_step_mm: float = 0.05
    confidence_threshold: float = 0.6
    target_lost_frames: int = 5


class TrackingController:
    """
    Computes tracking intent from vision detection.
    
    Usage mirrors SearchController:
        tracker = TrackingController(config)
        result = tracker.update(bbox_center, confidence)
        # Jetson sends ``error_px`` / mode to ESP over USB CDC; ``z_delta`` is optional legacy output.
    
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
        self._target_lost_threshold = config.target_lost_frames
        self._integral_px: float = 0.0

    def reset(self) -> None:
        """Reset tracking state."""
        self._frames_without_target = 0
        self._integral_px = 0.0

    def apply_runtime_config(self, config: Union[TrackingConfig, Mapping[str, Any]]) -> None:
        """Update parameters from Motion_Config / API without recreating the controller."""
        if isinstance(config, TrackingConfig):
            self._config = config
        else:
            c = self._config
            self._config = TrackingConfig(
                frame_width=int(config.get("frame_width", c.frame_width)),
                frame_height=int(config.get("frame_height", c.frame_height)),
                deadzone_px=int(config.get("deadzone_px", c.deadzone_px)),
                kp=float(config.get("kp", c.kp)),
                ki=float(config.get("ki", c.ki)),
                integral_max_px=float(
                    config.get("integral_max_px", c.integral_max_px)
                ),
                max_step_mm=float(config.get("max_step_mm", c.max_step_mm)),
                min_step_mm=float(config.get("min_step_mm", c.min_step_mm)),
                confidence_threshold=float(
                    config.get("confidence_threshold", c.confidence_threshold)
                ),
                target_lost_frames=int(
                    config.get("target_lost_frames", c.target_lost_frames)
                ),
            )
        self._center_x = self._config.frame_width // 2
        self._center_y = self._config.frame_height // 2
        self._target_lost_threshold = self._config.target_lost_frames

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
                "integral_px": float,     # Accumulated integral state (pixels·frames)
                "target_locked": bool,    # True if target is being tracked
            }
        """
        # No detection or low confidence
        if bbox_center is None or confidence < self._config.confidence_threshold:
            self._frames_without_target += 1
            self._integral_px *= 0.85
            return {
                "should_move": False,
                "z_delta": 0.0,
                "error_px": 0.0,
                "integral_px": self._integral_px,
                "target_locked": False,
            }
        
        # Valid detection - reset lost counter
        self._frames_without_target = 0
        
        cx, cy = bbox_center
        
        # Compute horizontal error (positive = target is right of center)
        error_px = cx - self._center_x
        
        # Apply deadzone
        if abs(error_px) < self._config.deadzone_px:
            self._integral_px *= 0.98
            return {
                "should_move": False,
                "z_delta": 0.0,
                "error_px": error_px,
                "integral_px": self._integral_px,
                "target_locked": True,
            }

        imax = max(0.0, self._config.integral_max_px)
        if self._config.ki != 0.0 and imax > 0.0:
            self._integral_px += error_px
            self._integral_px = max(-imax, min(imax, self._integral_px))

        # PI: error (px) → z_delta (mm)
        # Sign convention: positive error (target right) → positive Z (rotate right)
        z_raw = self._config.kp * error_px + self._config.ki * self._integral_px
        z_delta = max(
            -self._config.max_step_mm,
            min(self._config.max_step_mm, z_raw),
        )

        # Anti-windup: if output hit the clamp, undo this frame's integral increment
        if self._config.ki != 0.0 and abs(z_raw) > self._config.max_step_mm + 1e-9:
            self._integral_px -= error_px
            self._integral_px = max(-imax, min(imax, self._integral_px))

        # Filter out tiny movements
        if abs(z_delta) < self._config.min_step_mm:
            return {
                "should_move": False,
                "z_delta": 0.0,
                "error_px": error_px,
                "integral_px": self._integral_px,
                "target_locked": True,
            }

        return {
            "should_move": True,
            "z_delta": z_delta,
            "error_px": error_px,
            "integral_px": self._integral_px,
            "target_locked": True,
        }

    def is_target_lost(self) -> bool:
        """
        Returns True if target has been lost for multiple consecutive frames.
        Used for state transition back to SEARCH.
        """
        return self._frames_without_target >= self._target_lost_threshold
