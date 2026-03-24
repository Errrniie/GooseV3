"""
Orchestrator.py - Core state machine for the goose deterrence system.
"""

from Domains.Motion.Moonraker_Client import MoonrakerWSClient
from Domains.Motion.Controller import MotionController
from Domains.Motion.Homing import home
from Domains.Behavior.Search import SearchController, SearchConfig
from Domains.Behavior.Tracking import TrackingController, TrackingConfig
import Config.Motion_Config as cfg
import Config.Network_Config as net_cfg
from Domains.Vision.Interface import start_vision, stop_vision, get_latest_detection


# --- System states ---
STATE_INIT = "INIT"
STATE_SEARCH = "SEARCH"
STATE_TRACK = "TRACK"
STATE_SHUTDOWN = "SHUTDOWN"

# --- Detection thresholds ---
TRACK_CONFIDENCE_THRESHOLD = 0.6  # Confidence needed to enter TRACK


def run() -> None:
    state = STATE_INIT
    moonraker = MoonrakerWSClient(net_cfg.MOONRAKER_WS_URL)
    motion_cfg = {
        "limits": {
            "x": [cfg.X_MIN, cfg.X_MAX],
            "y": [cfg.Y_MIN, cfg.Y_MAX],
            "z": [cfg.Z_MIN, cfg.Z_MAX],
        },
        "neutral": {
            "x": cfg.NEUTRAL_X,
            "y": cfg.NEUTRAL_Y,
            "z": cfg.NEUTRAL_Z,
        },
        "speeds": {"travel": cfg.TRAVEL_SPEED, "z": cfg.Z_SPEED},
    }
    motion = MotionController(moonraker, motion_cfg)

    search = SearchController(
        SearchConfig(
            min_z=cfg.Z_MIN,
            max_z=cfg.Z_MAX,
            start_z=cfg.NEUTRAL_Z,
            step_size=1.0,
        )
    )

    tracker = TrackingController(
        TrackingConfig(
            frame_width=1080,
            frame_height=720,
            deadzone_px=30,
            kp=0.003,
            max_step_mm=3.0,
            confidence_threshold=TRACK_CONFIDENCE_THRESHOLD,
        )
    )

    while True:
        if state == STATE_INIT:
            print("[STATE] INIT")
            moonraker.connect()
            home(moonraker)
            start_vision()
            motion.set_neutral_intent()
            motion.move_blocking()
            print("Initialization complete. Transitioning to SEARCH state.")
            state = STATE_SEARCH
            continue

        if state == STATE_SEARCH:
            # Check for human detection - transition to TRACK if found
            detection = get_latest_detection()
            if (
                detection.has_target
                and detection.confidence >= TRACK_CONFIDENCE_THRESHOLD
            ):
                print(
                    f"[SEARCH] Target acquired! Center: {detection.bbox_center}, "
                    f"Confidence: {detection.confidence:.2f}"
                )
                print("[STATE] SEARCH -> TRACK")
                tracker.reset()
                state = STATE_TRACK
                continue

            # No target - continue search pattern
            step = search.update()
            z_delta = step["z_delta"]
            motion.move_z_relative_blocking(z_delta)
            continue

        if state == STATE_TRACK:
            # Get latest detection
            detection = get_latest_detection()

            # Compute tracking intent (math only)
            track_result = tracker.update(detection.bbox_center, detection.confidence)

            # Check if target is lost - transition back to SEARCH
            if tracker.is_target_lost():
                print("[TRACK] Target lost!")
                print("[STATE] TRACK -> SEARCH")
                state = STATE_SEARCH
                continue

            # If tracking says we should move, send the command
            if track_result["should_move"]:
                z_delta = track_result["z_delta"]
                print(
                    f"[TRACK] error={track_result['error_px']:.0f}px -> "
                    f"z_delta={z_delta:+.3f}mm"
                )
                motion.move_z_relative_blocking(z_delta)

            # If locked but no move needed (in deadzone), just loop
            continue

        if state == STATE_SHUTDOWN:
            print("[STATE] SHUTDOWN")
            stop_vision()
            motion.set_neutral_intent(z=0.0)
            motion.move_blocking()
            moonraker.close()
            print("Shutdown complete.")
            break
