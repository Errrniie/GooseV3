"""
ESP32 motor/vision commands over **USB CDC** (serial), separate from laser HTTP.

- One JSON object per line (newline-delimited), UTF-8.
- Add user to ``dialout`` on Linux: ``sudo usermod -aG dialout $USER`` then re-login.
- Default device is often ``/dev/ttyACM0`` or ``/dev/ttyUSB0`` when the ESP enumerates as CDC.

**Schema** (vision updates from Normal_Mode):

.. code-block:: json

   {"type":"vision","mode":"INIT"|"SEARCH"|"TRACK","error_px":null,"error_norm":null,
    "confidence":null,"frame_w":1920,"frame_h":1080,"target_locked":false}

- ``mode``: high-level state for the ESP search/track state machine.
- ``error_px``: horizontal offset, pixels (positive = target right of image center); null in SEARCH.
- ``error_norm``: ``error_px / (frame_w/2)`` in roughly [-1, 1] when applicable; null in SEARCH.
- ``confidence``: bird detection confidence when tracking.
- ``target_locked``: from TrackingController when in TRACK.

Laser on/off remains HTTP to ``esp32_ip`` (see ``Domains/Laser/Esp_32.py``).
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Optional

# Lazy import serial in open() so import of this module works without hardware.


def build_vision_line(
    *,
    mode: str,
    frame_w: int,
    frame_h: int,
    error_px: Optional[float] = None,
    confidence: Optional[float] = None,
    target_locked: bool = False,
) -> str:
    """Single NDJSON line for the ESP firmware."""
    half = max(1.0, frame_w / 2.0)
    err_norm: Optional[float] = None
    if error_px is not None:
        err_norm = float(error_px) / half
    payload: dict[str, Any] = {
        "type": "vision",
        "mode": mode,
        "error_px": error_px,
        "error_norm": err_norm,
        "confidence": confidence,
        "frame_w": int(frame_w),
        "frame_h": int(frame_h),
        "target_locked": bool(target_locked),
    }
    return json.dumps(payload, separators=(",", ":")) + "\n"


class EspUsbClient:
    """
    Non-blocking best-effort writer to a USB serial port.
    Failed writes are logged once; optional minimum interval between sends.
    """

    def __init__(
        self,
        port: str,
        baud: int = 115200,
        min_interval_s: float = 1.0 / 60.0,
    ) -> None:
        self._port = port
        self._baud = int(baud)
        self._min_interval_s = max(0.0, float(min_interval_s))
        self._ser: Any = None
        self._lock = threading.Lock()
        self._last_send_t = 0.0
        self._warned = False

    def open(self) -> None:
        import serial

        self._ser = serial.Serial(self._port, self._baud, timeout=0.2)
        self._warned = False

    def close(self) -> None:
        with self._lock:
            if self._ser is not None:
                try:
                    self._ser.close()
                except Exception:
                    pass
                self._ser = None

    def is_open(self) -> bool:
        return self._ser is not None and getattr(self._ser, "is_open", False)

    def send_line(self, line: str) -> None:
        """Write a preformatted line (include trailing newline)."""
        now = time.monotonic()
        if self._min_interval_s > 0 and (now - self._last_send_t) < self._min_interval_s:
            return
        with self._lock:
            if self._ser is None or not getattr(self._ser, "is_open", False):
                return
            try:
                self._ser.write(line.encode("utf-8"))
                self._ser.flush()
                self._last_send_t = time.monotonic()
            except Exception as e:
                if not self._warned:
                    print(f"[ESP-CDC] write failed ({e}); further errors suppressed")
                    self._warned = True

    def send_vision(
        self,
        *,
        mode: str,
        frame_w: int,
        frame_h: int,
        error_px: Optional[float] = None,
        confidence: Optional[float] = None,
        target_locked: bool = False,
    ) -> None:
        line = build_vision_line(
            mode=mode,
            frame_w=frame_w,
            frame_h=frame_h,
            error_px=error_px,
            confidence=confidence,
            target_locked=target_locked,
        )
        self.send_line(line)
