"""Default production pipeline: SEARCH / TRACK vision loop; ESP32 motors via USB CDC."""

import time

from Config.Manager import get_config_manager, init_config
import Config.Motion_Config as cfg
import Config.Vision_Config as vcfg
from Domains.Behavior.Search import SearchController, SearchConfig
from Domains.Behavior.Tracking import TrackingController, TrackingConfig
from Domains.Motion.Esp_Usb_Client import EspUsbClient
from Domains.Motion.Runtime import (
    set_active_search_controller,
    set_active_tracking_controller,
)
from Domains.Vision.Interface import get_latest_detection, start_vision, stop_vision

STATE_INIT = "INIT"
STATE_SEARCH = "SEARCH"
STATE_TRACK = "TRACK"
STATE_SHUTDOWN = "SHUTDOWN"


def run() -> None:
    init_config()
    state = STATE_INIT
    mgr = get_config_manager()
    nw = mgr.network

    esp = EspUsbClient(nw.esp_cdc_port, nw.esp_cdc_baud)
    try:
        esp.open()
        print(f"[MODE] ESP USB CDC open: {nw.esp_cdc_port} @ {nw.esp_cdc_baud}")
    except Exception as e:
        print(f"[MODE] ESP USB CDC open failed ({e}); vision messages will not reach ESP")

    search = SearchController(
        SearchConfig(
            min_z=cfg.Z_MIN,
            max_z=cfg.Z_MAX,
            start_z=cfg.NEUTRAL_Z,
            step_size=cfg.SEARCH_STEP_MM,
        )
    )
    set_active_search_controller(search)

    tracker = TrackingController(
        TrackingConfig(
            frame_width=cfg.CAMERA_WIDTH,
            frame_height=cfg.CAMERA_HEIGHT,
            deadzone_px=cfg.TRACKING_DEADZONE_PX,
            kp=cfg.TRACKING_KP,
            ki=cfg.TRACKING_KI,
            integral_max_px=cfg.TRACKING_INTEGRAL_MAX_PX,
            min_step_mm=cfg.TRACKING_MIN_STEP_MM,
            max_step_mm=cfg.TRACKING_MAX_STEP_MM,
            confidence_threshold=vcfg.VISION_BIRD_MIN_CONF,
            target_lost_frames=cfg.TRACKING_TARGET_LOST_FRAMES,
        )
    )
    set_active_tracking_controller(tracker)

    try:
        while True:
            if state == STATE_INIT:
                print("[STATE] INIT")
                start_vision()
                esp.send_vision(
                    mode="INIT",
                    frame_w=cfg.CAMERA_WIDTH,
                    frame_h=cfg.CAMERA_HEIGHT,
                )
                print("Initialization complete. Transitioning to SEARCH state.")
                state = STATE_SEARCH
                continue

            if state == STATE_SEARCH:
                detection = get_latest_detection()
                esp.send_vision(
                    mode="SEARCH",
                    frame_w=cfg.CAMERA_WIDTH,
                    frame_h=cfg.CAMERA_HEIGHT,
                )
                if detection.active_track is not None:
                    print(
                        f"[SEARCH] Bird acquired! Center: {detection.bbox_center}, "
                        f"Confidence: {detection.confidence:.2f}"
                    )
                    print("[STATE] SEARCH -> TRACK")
                    tracker.reset()
                    state = STATE_TRACK
                    continue

                time.sleep(0.002)
                continue

            if state == STATE_TRACK:
                detection = get_latest_detection()
                if detection.active_track is not None:
                    track_result = tracker.update(
                        detection.bbox_center, detection.confidence
                    )
                else:
                    track_result = tracker.update(None, 0.0)

                if tracker.is_target_lost():
                    print("[TRACK] Target lost!")
                    print("[STATE] TRACK -> SEARCH")
                    search.reset()
                    tracker.reset()
                    esp.send_vision(
                        mode="SEARCH",
                        frame_w=cfg.CAMERA_WIDTH,
                        frame_h=cfg.CAMERA_HEIGHT,
                    )
                    state = STATE_SEARCH
                    continue

                err = track_result.get("error_px")
                if track_result.get("should_move"):
                    print(
                        f"[TRACK] error={track_result['error_px']:.0f}px "
                        f"I={track_result['integral_px']:.0f} (CDC to ESP)"
                    )

                conf = (
                    float(detection.confidence)
                    if detection.active_track is not None
                    else None
                )
                esp.send_vision(
                    mode="TRACK",
                    frame_w=cfg.CAMERA_WIDTH,
                    frame_h=cfg.CAMERA_HEIGHT,
                    error_px=float(err) if err is not None else None,
                    confidence=conf,
                    target_locked=bool(track_result.get("target_locked")),
                )
                time.sleep(0.002)
                continue

            if state == STATE_SHUTDOWN:
                print("[STATE] SHUTDOWN")
                stop_vision()
                print("Shutdown complete.")
                break
    finally:
        set_active_tracking_controller(None)
        set_active_search_controller(None)
        try:
            stop_vision()
        except Exception:
            pass
        try:
            from Tools.Scripts.Start_Stream import stop_all_streams

            stop_all_streams()
        except Exception:
            pass
        try:
            esp.close()
        except Exception:
            pass
