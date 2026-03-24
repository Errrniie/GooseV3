"""
Human_tracking_test.py - YOLO-based human tracking with SEARCH/TRACK state machine.

Behavior:
- Connect to Moonraker and home printer
- Start YOLO vision pipeline
- SEARCH mode: Oscillate Z between Z_MIN and Z_MAX (1mm steps) until target found
- TRACK mode: Move camera center toward detected person using TrackingController
- Uses direct MOVE_Z commands (same as z_latency_test.py) - not MotionController

State machine:
- SEARCH: Z oscillates min → max → min until person detected
- TRACK: Z adjusts to center person horizontally
- Returns to SEARCH if target is lost

You can view video via UDP stream (automatically started if LAPTOP_IP is configured).
"""

import sys
import os
import time
import threading
import uvicorn

# Add project root to Python path so imports work from subdirectory
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from Domains.Motion.Moonraker_Client import MoonrakerWSClient
from Domains.Motion.Homing import home
import Config.Motion_Config as motion_cfg
import Config.Network_Config as net_cfg
from Domains.Vision.Interface import start_vision, stop_vision, get_latest_detection
from Domains.Behavior.Tracking import TrackingController, TrackingConfig
from Domains.Behavior.Search import SearchController, SearchConfig
from Networking import test_api


def main():
    print("\n=== GooseV3 HUMAN TRACKING TEST ===")
    print("Moonraker URL:", net_cfg.MOONRAKER_WS_URL)

    # State machine states
    STATE_SEARCH = "SEARCH"
    STATE_TRACK = "TRACK"
    state = STATE_SEARCH

    # 1) Connect to Moonraker
    moonraker = MoonrakerWSClient(net_cfg.MOONRAKER_WS_URL)
    moonraker.connect()
    print("[TRACKTEST] Connected to Moonraker")

    # 2) Home printer
    print("[TRACKTEST] Homing printer...")
    try:
        home(moonraker, timeout=30.0)
        print("[TRACKTEST] Homing complete")
    except Exception as e:
        print(f"[TRACKTEST] Homing failed or skipped: {e}")

    # 3) Initialize logical Z position (starts at neutral_z from config)
    z_current = motion_cfg.NEUTRAL_Z
    print(f"[TRACKTEST] Logical Z starting at {z_current:.2f}mm (neutral_z from config)")

    # 4) Attach Moonraker client to FastAPI for emergency controls
    test_api.attach_moonraker_client(moonraker)
    print("[TRACKTEST] Moonraker client attached to FastAPI")

    # 5) Start YOLO vision
    # CameraThread will automatically start UDP H.264 streaming to LAPTOP_IP from Config/network_config.py
    # Uses nvarguscamerasrc via GStreamer (same method as test_camera.py)
    print(f"[TRACKTEST] Starting vision system...")
    if net_cfg.LAPTOP_IP is not None:
        print(f"[TRACKTEST] Video streaming will start automatically to {net_cfg.LAPTOP_IP}:{net_cfg.STREAM_PORT}")
    else:
        print("[TRACKTEST] No LAPTOP_IP configured - video streaming disabled")
    start_vision()
    
    # Give camera a moment to initialize before starting FastAPI
    print("[TRACKTEST] Waiting for camera to initialize...")
    time.sleep(1.0)
    
    # Verify camera is accessible
    try:
        from Domains.Vision.Interface import camera as yolo_camera
        if yolo_camera is not None:
            test_frame = yolo_camera.get_frame()
            if test_frame is not None:
                print(f"[TRACKTEST] Camera ready: {test_frame.shape}")
            else:
                print("[TRACKTEST] Warning: Camera initialized but no frame available yet")
        else:
            print("[TRACKTEST] Warning: Camera is None")
    except Exception as e:
        print(f"[TRACKTEST] Warning: Could not verify camera: {e}")

    # 6) Search controller - oscillates Z between min and max
    # Always use NEUTRAL_Z from config as the starting position
    search = SearchController(
        SearchConfig(
            min_z=motion_cfg.Z_MIN,
            max_z=motion_cfg.Z_MAX,
            start_z=motion_cfg.NEUTRAL_Z,  # Always use neutral_z from config
            step_size=1.0,  # 1mm steps
        )
    )
    # Sync SearchController to the actual starting position (ensures they match)
    search.sync_to_position(motion_cfg.NEUTRAL_Z)
    print(f"[TRACKTEST] SearchController synced to {motion_cfg.NEUTRAL_Z:.2f}mm")

    # 7) Tracking controller - centers camera on detected person
    tracking_cfg = TrackingConfig(
        frame_width=3840,
        frame_height=2160,
        deadzone_px=40,
        kp=0.003,
        max_step_mm=2.0,
        min_step_mm=0.05,
        confidence_threshold=0.5,
    )
    tracker = TrackingController(tracking_cfg)

    print("\n[TRACKTEST] System ready.")
    print("  - SEARCH mode: Z oscillates between {:.1f}mm and {:.1f}mm".format(
        motion_cfg.Z_MIN, motion_cfg.Z_MAX))
    print("  - TRACK mode: Z adjusts to center detected person")
    print("\n[TRACKTEST] Starting FastAPI server on 0.0.0.0:8000")
    print("  - Camera feed:        http://<JETSON_IP>:8000/video")
    print("  - Emergency stop:     POST http://<JETSON_IP>:8000/emergency_stop")
    print("  - Firmware restart:   POST http://<JETSON_IP>:8000/firmware_restart")
    print("  - Klipper restart:    POST http://<JETSON_IP>:8000/klipper_restart")
    print("  - TMC dump:           POST http://<JETSON_IP>:8000/tmc/dump")
    print("\nPress Ctrl+C to stop.\n")

    # Start FastAPI server in a separate thread
    def run_fastapi():
        uvicorn.run(test_api.app, host="0.0.0.0", port=8000, log_level="info")

    api_thread = threading.Thread(target=run_fastapi, daemon=True)
    api_thread.start()
    print("[TRACKTEST] FastAPI server started in background thread")

    try:
        while True:
            detection = get_latest_detection()

            if state == STATE_SEARCH:
                # Check for person detection - transition to TRACK if found
                if detection.has_target and detection.confidence >= tracking_cfg.confidence_threshold:
                    print(
                        f"[SEARCH] Person detected! Center: {detection.bbox_center}, "
                        f"Confidence: {detection.confidence:.2f}"
                    )
                    print("[STATE] SEARCH → TRACK")
                    tracker.reset()
                    state = STATE_TRACK
                    continue

                # No target - continue search pattern (oscillate Z)
                step = search.update()
                z_delta = step["z_delta"]
                
                # SearchController.update() already ensures bounds, but add safety clamp anyway
                proposed_z = z_current + z_delta
                if proposed_z < motion_cfg.Z_MIN:
                    z_delta = motion_cfg.Z_MIN - z_current
                    # Only sync position, don't reset direction (let SearchController handle it)
                    search._current_z = motion_cfg.Z_MIN
                elif proposed_z > motion_cfg.Z_MAX:
                    z_delta = motion_cfg.Z_MAX - z_current
                    # Only sync position, don't reset direction (let SearchController handle it)
                    search._current_z = motion_cfg.Z_MAX
                
                if abs(z_delta) > 0.01:  # Only move if meaningful
                    # Use same movement method as z_latency_test.py
                    cmd = f"MOVE_Z D={z_delta:.2f} V=2.00"
                    print(f"[SEARCH] Moving Z: {cmd}")
                    moonraker.send_gcode_and_wait_complete(cmd, timeout_s=10.0)
                    
                    # Update logical Z position
                    z_current += z_delta
                    # Sync SearchController's internal position (but NOT direction - let it continue oscillating)
                    search._current_z = z_current
                    print(f"[SEARCH] Z={z_current:.2f}mm (searching...)")
                else:
                    # If we're at a limit, just sync position - SearchController already flipped direction
                    search._current_z = z_current
                continue

            elif state == STATE_TRACK:
                # Check if target is lost - transition back to SEARCH
                if tracker.is_target_lost():
                    print("[TRACK] Target lost!")
                    print("[STATE] TRACK → SEARCH")
                    # Sync SearchController to current position using the new sync method
                    search.sync_to_position(z_current)
                    state = STATE_SEARCH
                    continue

                # Compute tracking intent
                track_result = tracker.update(detection.bbox_center, detection.confidence)

                # If tracking says we should move, send the command
                if track_result["should_move"]:
                    z_delta = track_result["z_delta"]
                    
                    # Clamp to limits
                    proposed_z = z_current + z_delta
                    if proposed_z < motion_cfg.Z_MIN:
                        z_delta = motion_cfg.Z_MIN - z_current
                    elif proposed_z > motion_cfg.Z_MAX:
                        z_delta = motion_cfg.Z_MAX - z_current
                    
                    if abs(z_delta) > 0.01:  # Only move if meaningful
                        # Use same movement method as z_latency_test.py
                        cmd = f"MOVE_Z D={z_delta:.2f} V=2.00"
                        print(
                            f"[TRACK] error={track_result['error_px']:.0f}px → "
                            f"z_delta={z_delta:+.3f}mm"
                        )
                        moonraker.send_gcode_and_wait_complete(cmd, timeout_s=10.0)
                        
                        # Update logical Z position
                        z_current += z_delta
                        print(f"[TRACK] Z={z_current:.2f}mm (tracking)")
                else:
                    # In deadzone - no movement needed
                    time.sleep(0.01)
                continue

    except KeyboardInterrupt:
        print("\n[TRACKTEST] Stopped by user")

    finally:
        # Stop YOLO vision (will also stop streaming if it was started)
        stop_vision()
        # Disconnect Moonraker
        try:
            moonraker.close()
        except Exception:
            pass
        print("[TRACKTEST] Disconnected from Moonraker")


if __name__ == "__main__":
    main()

