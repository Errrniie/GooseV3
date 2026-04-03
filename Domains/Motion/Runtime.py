"""
Holds optional references to the live MotionController and SearchController (Normal_Mode).

Used so HTTP motion config updates can push new parameters into running pipeline objects.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from Domains.Behavior.Search import SearchController
    from Domains.Behavior.Tracking import TrackingController
    from Domains.Motion.Controller import MotionController

_lock = threading.RLock()
_active_motion: Optional[MotionController] = None
_active_search: Optional[SearchController] = None
_active_tracking: Optional["TrackingController"] = None


def set_active_motion_controller(controller: Optional[MotionController]) -> None:
    """Register the current pipeline MotionController, or None when the pipeline exits."""
    global _active_motion
    with _lock:
        _active_motion = controller


def set_active_search_controller(controller: Optional[SearchController]) -> None:
    """Register the current pipeline SearchController, or None when the pipeline exits."""
    global _active_search
    with _lock:
        _active_search = controller


def set_active_tracking_controller(controller: Optional["TrackingController"]) -> None:
    """Register the current pipeline TrackingController, or None when the pipeline exits."""
    global _active_tracking
    with _lock:
        _active_tracking = controller


def notify_motion_config_changed() -> None:
    """
    After motion settings are updated (manager + JSON), push new values into the
    active MotionController and SearchController if registered.
    """
    from Config.Manager import get_config_manager

    mgr = get_config_manager()
    m = mgr.motion
    motion_dict = mgr.motion_controller_dict()

    with _lock:
        motion_ctrl = _active_motion
        search_ctrl = _active_search
        tracking_ctrl = _active_tracking

    if motion_ctrl is not None:
        motion_ctrl.apply_runtime_config(motion_dict)
    if search_ctrl is not None:
        search_ctrl.apply_runtime_z_bounds(
            m.z_min, m.z_max, m.neutral_z, m.search_step_mm
        )
    if tracking_ctrl is not None:
        tracking_ctrl.apply_runtime_config(mgr.tracking_config_dict())
