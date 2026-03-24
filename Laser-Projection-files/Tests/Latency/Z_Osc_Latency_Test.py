"""
Z_osc_latency_test.py - Measure Z-axis MOVE_Z command latency / effective Hz.

Behavior:
- Connect to Moonraker
- Home the printer (so Z is known)
- Assume homed Z corresponds to logical Z = 3.0mm
- Then oscillate Z between:
      3 -> 7 -> 0 -> 7 -> 0 -> ...
  using MOVE_Z macros via MotionController.move_z_relative_blocking
- For each MOVE_Z, measure:
      time from send to 'complete' response
  and log the effective step rate (Hz).

No YOLO, no tracking, no camera/laser logic.
This is purely for motion/response timing experiments.
"""

import time

from Domains.Motion.Moonraker_Client import MoonrakerWSClient
from Domains.Motion.Controller import MotionController
from Domains.Motion.Homing import home
import Config.Motion_Config as motion_cfg
import Config.Network_Config as net_cfg


def build_motion_controller(ws_client: MoonrakerWSClient) -> MotionController:
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
        "send_rate_hz": motion_cfg.SEND_RATE_HZ,
        "mm_per_degree": motion_cfg.MM_PER_DEGREE,
        "feedrate_multiplier": motion_cfg.FEEDRATE_MULTIPLIER,
        "angular_velocity": motion_cfg.SEARCH_ANGULAR_VELOCITY,
    }
    return MotionController(ws_client, cfg)


def main():
    print("\n=== GooseV3 Z OSCILLATION LATENCY TEST ===")
    print("Moonraker URL:", net_cfg.MOONRAKER_WS_URL)

    # 1) Connect to Moonraker
    ws_client = MoonrakerWSClient(net_cfg.MOONRAKER_WS_URL)
    ws_client.connect()
    print("[ZTEST] Connected to Moonraker")

    # 2) Home printer
    print("[ZTEST] Homing printer...")
    try:
        home(ws_client, timeout=30.0)
        print("[ZTEST] Homing complete")
    except Exception as e:
        print(f"[ZTEST] Homing failed or skipped: {e}")

    # 3) Motion controller
    motion = build_motion_controller(ws_client)

    # Assumed homed Z logical position
    current_z = 3.0
    try:
        motion.set_current_z(current_z)
    except Exception as e:
        print(f"[ZTEST] Failed to initialize logical Z: {e}")

    targets = [7.0, 0.0]  # oscillate between 7 and 0 (starting from 3)

    print("\n[ZTEST] Starting oscillation: 3 -> 7 -> 0 -> 7 -> 0 -> ...")
    print("Press Ctrl+C to stop.\n")

    step_index = 0
    try:
        while True:
            for target in targets:
                delta = target - current_z
                step_index += 1

                t0 = time.perf_counter()
                # Velocity None → default 2.0 inside MotionController
                motion.move_z_relative_blocking(delta, velocity=None)
                t1 = time.perf_counter()

                dt = t1 - t0
                hz = 1.0 / dt if dt > 0 else 0.0

                print(
                    f"[ZTEST] step={step_index:04d} "
                    f"{current_z:.2f} -> {target:.2f} (ΔZ={delta:+.2f}) "
                    f"dt={dt*1000:.1f} ms  ~{hz:.2f} Hz"
                )

                current_z = target

    except KeyboardInterrupt:
        print("\n[ZTEST] Stopped by user (Ctrl+C)")

    finally:
        try:
            ws_client.close()
        except Exception:
            pass
        print("[ZTEST] Disconnected from Moonraker")


if __name__ == "__main__":
    main()

