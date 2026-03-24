"""
Main_basic_test.py - Minimal end-to-end test entrypoint.

Runs a FastAPI server on the Jetson that exposes:
- /z/move     : Relative Z movement via MOVE_Z macro
- /laser/on   : Turn laser ON
- /laser/off  : Turn laser OFF

PLUS, optionally starts a UDP H.264 stream to the laptop using
start_stream.py (if you pass the laptop IP as an argument).

NO YOLO, NO tracking logic - this is just for basic HW + networking tests
driven from a laptop GUI or curl.
"""

import sys
import uvicorn

from Domains.Motion.moonraker_client import MoonrakerWSClient
from Domains.Motion.controller import MotionController
from Domains.Motion.homing import home
from Domains.Laser.esp32 import LaserController
import Config.motion_config as motion_cfg
from Config import network_config as net_cfg
from Networking import test_api
import start_stream


def build_motion_controller(ws_client: MoonrakerWSClient) -> MotionController:
    """
    Create a MotionController using the current motion_config values.
    Focused on Z axis for this test, but X/Y limits are also provided.
    """
    cfg = {
        "limits": {
            "x": [motion_cfg.X_MIN, motion_cfg.X_MAX],
            "y": [motion_cfg.Y_MIN, motion_cfg.Y_MAX],
            "z": [motion_cfg.Z_MIN, motion_cfg.Z_MAX],
        },
        "neutral": {
            "x": motion_cfg.NEUTRAL_X,
            "y": motion_cfg.NEUTRAL_Y,
            "z": motion_cfg.NEUTRAL_Z,
        },
        "speeds": {
            "travel": motion_cfg.TRAVEL_SPEED,
            "z": motion_cfg.Z_SPEED,
        },
        # Use default timing/geometry; Z moves use MOVE_Z anyway
        "send_rate_hz": motion_cfg.SEND_RATE_HZ,
        "mm_per_degree": motion_cfg.MM_PER_DEGREE,
        "feedrate_multiplier": motion_cfg.FEEDRATE_MULTIPLIER,
        "angular_velocity": motion_cfg.SEARCH_ANGULAR_VELOCITY,
    }
    return MotionController(ws_client, cfg)


def main():
    print("\n=== GooseV3 BASIC TEST MAIN ===")
    print("Connecting to Moonraker at:", net_cfg.MOONRAKER_WS_URL)

    # Get laptop IP from command-line argument or config file
    if len(sys.argv) >= 2:
        laptop_ip = sys.argv[1]
        print(f"[TEST] Using laptop IP from command-line: {laptop_ip}")
    else:
        laptop_ip = net_cfg.LAPTOP_IP
        if laptop_ip is None:
            print("[TEST] No laptop IP configured (LAPTOP_IP=None) - video stream will NOT be started")
        else:
            print(f"[TEST] Using laptop IP from Config/network_config.py: {laptop_ip}")

    # 1) Connect to Moonraker
    ws_client = MoonrakerWSClient(net_cfg.MOONRAKER_WS_URL)
    ws_client.connect()
    print("[TEST] Connected to Moonraker")

    # 2) Optional: home once so Z moves are in a known range
    print("[TEST] Homing printer (can be commented out if not desired)...")
    try:
        home(ws_client, timeout=30.0)
        print("[TEST] Homing complete")
    except Exception as e:
        print(f"[TEST] Homing failed or skipped: {e}")

    # 3) Motion + laser controllers
    motion = build_motion_controller(ws_client)
    laser = LaserController()

    # Initialize logical Z after homing (assume homed at 0.0mm for now)
    try:
        motion.set_current_z(0.0)
    except Exception as e:
        print(f"[TEST] Failed to initialize logical Z: {e}")

    # 4) Attach controllers and Moonraker client to the test API
    test_api.attach_motion_controller(motion)
    test_api.attach_laser_controller(laser)
    test_api.attach_moonraker_client(ws_client)

    # 5) Optionally start video stream in background (uses config port)
    stream_proc = None
    if laptop_ip:
        try:
            stream_proc = start_stream.start_stream_background(laptop_ip, net_cfg.STREAM_PORT)
            print(f"[TEST] Video stream started to {laptop_ip}:{net_cfg.STREAM_PORT}")
        except Exception as e:
            print(f"[TEST] Failed to start video stream: {e}")

    print("\n[TEST] Starting FastAPI server on 0.0.0.0:8000")
    print("  - Video stream (UDP/H.264) to laptop: use your GStreamer receiver")
    print("  - Move Z:            POST http://<JETSON_IP>:8000/z/move  {\"delta_mm\": 1.0}")
    print("  - Laser ON:          POST http://<JETSON_IP>:8000/laser/on")
    print("  - Laser OFF:         POST http://<JETSON_IP>:8000/laser/off")
    print("  - Emergency stop:    POST http://<JETSON_IP>:8000/emergency_stop")
    print("  - Firmware restart:  POST http://<JETSON_IP>:8000/firmware_restart")
    print("  - Klipper restart:   POST http://<JETSON_IP>:8000/klipper_restart")
    print("  - TMC dump (Z):      POST http://<JETSON_IP>:8000/tmc/dump {'stepper': 'stepper_z'}")
    print()

    # 6) Run FastAPI app (blocks until interrupted)
    try:
        uvicorn.run(test_api.app, host="0.0.0.0", port=8000)
    finally:
        if stream_proc is not None:
            print("[TEST] Terminating video stream process...")
            stream_proc.terminate()


if __name__ == "__main__":
    main()

