"""
Motion Latency Test Script (Z-axis oscillation)

Measures round-trip latency for MOVE_Z macros via Moonraker WebSocket,
while oscillating Z between:

    Z = 3 → 7 → 0 → 7 → 0 → ...

Each step is 1mm in logical Z, and we wait for the RESPOND "complete"
message from the MOVE_Z macro (which should include M400 inside the
macro so motion is finished before 'complete' is sent).
"""

import time

from Domains.Motion.moonraker_client import MoonrakerWSClient
from Domains.Motion.homing import home
from Config import network_config as net_cfg


def run_latency_test():
    """
    Home the printer, then oscillate Z between 3, 7, and 0 in 1mm steps.
    For each MOVE_Z, measure latency between send and 'complete'.
    """

    # Connect to Moonraker
    moonraker = MoonrakerWSClient(net_cfg.MOONRAKER_WS_URL)
    moonraker.connect()
    print("[INIT] Connected to Moonraker")

    # Home the printer (blocking)
    print("[INIT] Homing printer...")
    home(moonraker, timeout=30.0)
    print("[INIT] Homing complete")

    # Logical Z starts at 3mm after homing (per your description)
    z_current = 3.0
    print(f"[INIT] Logical Z starting at {z_current:.1f}mm")

    # Print CSV header
    print("\n" + "=" * 80)
    print("Z OSCILLATION LATENCY TEST RESULTS")
    print("=" * 80)
    print("step_index,z_current,z_delta_mm,send_time_s,receive_time_s,delta_t_s,step_hz")

    step_index = 0
    direction = +1.0  # start moving up toward 7

    try:
        while True:
            # Flip direction at boundaries 7 and 0
            if direction > 0 and z_current >= 7.0:
                direction = -1.0
            elif direction < 0 and z_current <= 0.0:
                direction = +1.0

            # Next logical step of 1mm in current direction
            z_delta = 1.0 * direction

            # Clamp so we never go outside [0, 7]
            proposed = z_current + z_delta
            if proposed > 7.0:
                z_delta = 7.0 - z_current
            elif proposed < 0.0:
                z_delta = 0.0 - z_current

            step_index += 1

            # Measure latency using MOVE_Z and RESPOND "complete"
            send_time = time.perf_counter()
            cmd = f"MOVE_Z D={z_delta:.2f} V=5.00"
            print(f"[ZLAT] Sending: {cmd}")
            moonraker.send_gcode_and_wait_complete(cmd, timeout_s=10.0)
            receive_time = time.perf_counter()

            delta_t = receive_time - send_time
            step_hz = 1.0 / delta_t if delta_t > 0 else 0.0

            # Update logical Z
            z_current += z_delta

            # Print CSV row
            print(
                f"{step_index},{z_current:.2f},{z_delta:+.2f},"
                f"{send_time:.6f},{receive_time:.6f},{delta_t:.6f},{step_hz:.2f}"
            )

    except KeyboardInterrupt:
        print("\n[ZLAT] Latency test stopped by user")

    finally:
        moonraker.close()
        print("[ZLAT] Disconnected from Moonraker")


if __name__ == "__main__":
    run_latency_test()
