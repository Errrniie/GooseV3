"""
Legacy basic HW test (Moonraker + MOVE_Z).

Moonraker and the old ``MotionController`` module were removed; motors are driven
from the ESP32 using vision lines on USB CDC (see ``Modes/Normal_Mode.py``).
Replace this script with ESP/CDC integration tests when needed.
"""

from __future__ import annotations


def main() -> None:
    print(
        "[Basic_Test] Skipped: this entrypoint depended on Moonraker (removed). "
        "Use Normal_Mode + ESP USB CDC for motion."
    )


if __name__ == "__main__":
    main()
