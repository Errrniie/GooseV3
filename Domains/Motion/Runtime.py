"""
Holds optional references to SearchController / TrackingController (Normal_Mode).

Used so HTTP motion config updates can push new parameters into running pipeline objects.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from Domains.Behavior.Search import SearchController
    from Domains.Behavior.Tracking import TrackingController

_lock = threading.RLock()
_active_search: Optional["SearchController"] = None
_active_tracking: Optional["TrackingController"] = None


def set_active_search_controller(controller: Optional["SearchController"]) -> None:
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
    active SearchController / TrackingController if registered.
    """
    from Config.Manager import get_config_manager

    mgr = get_config_manager()
    m = mgr.motion

    with _lock:
        search_ctrl = _active_search
        tracking_ctrl = _active_tracking

    if search_ctrl is not None:
        search_ctrl.apply_runtime_z_bounds(
            m.z_min, m.z_max, m.neutral_z, m.search_step_mm
        )
    if tracking_ctrl is not None:
        tracking_ctrl.apply_runtime_config(mgr.tracking_config_dict())


def notify_vision_config_changed() -> None:
    """After vision thresholds change: refresh TrackingController confidence gate from bird_min_conf."""
    from Config.Manager import get_config_manager

    mgr = get_config_manager()
    with _lock:
        tracking_ctrl = _active_tracking
    if tracking_ctrl is not None:
        tracking_ctrl.apply_runtime_config(mgr.tracking_config_dict())
