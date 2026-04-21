"""
Legacy full-system integration test (Moonraker, homing, motion, vision).

Removed with Moonraker. End-to-end validation is now: camera → YOLO → Normal_Mode
→ ``EspUsbClient`` JSON lines → ESP32 firmware.
"""

from __future__ import annotations


def main() -> None:
    print("[System_Integration_Test] Skipped: Moonraker path removed.")


if __name__ == "__main__":
    main()
