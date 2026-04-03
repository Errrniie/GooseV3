from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional


class MotionController:
    """
    Moonraker-facing motion helper: blocking Z via MOVE_Z, absolute G0 for init/shutdown.

    SEARCH/TRACK use move_z_relative_blocking (MOVE_Z D=… V=…). Travel feedrate comes from
    speeds[\"travel\"] for G0 / MOVE XY. Runtime motion API updates apply via apply_runtime_config.
    """

    def __init__(self, moonraker: Any, config: Dict[str, Any]):
        """
        config keys:
            limits, neutral, speeds: {\"travel\": mm/min},
            mm_per_degree (Z mm per degree for set_intent angle),
            move_z_velocity (default V= for MOVE_Z when velocity not passed),
        """
        self._client = moonraker
        self._limits = config.get("limits", {})
        self._neutral = config.get("neutral", {})
        self._speeds = config.get("speeds", {})
        self._lock = threading.Lock()

        self._z_deg_to_mm: float = config.get("mm_per_degree", 8.0 / 360.0)
        self._move_z_velocity: float = float(config.get("move_z_velocity", 2.0))

        self._intent: Dict[str, Optional[float]] = {"x": None, "y": None, "z": None}
        self._last_sent: Dict[str, Optional[float]] = {"x": None, "y": None, "z": None}
        self._last_commanded_z: Optional[float] = None
        self._deadband_z: float = 0.0

    def apply_runtime_config(self, config: Dict[str, Any]) -> None:
        """Refresh limits, speeds, geometry, and MOVE_Z V default from config manager / API."""
        with self._lock:
            if "limits" in config:
                self._limits = config["limits"]
            if "neutral" in config:
                self._neutral = config["neutral"]
            if "speeds" in config:
                self._speeds = config["speeds"]
            if "mm_per_degree" in config:
                self._z_deg_to_mm = float(config["mm_per_degree"])
            if "move_z_velocity" in config:
                self._move_z_velocity = float(config["move_z_velocity"])

    def set_intent(
        self,
        *,
        x: Optional[float] = None,
        y: Optional[float] = None,
        z: Optional[float] = None,
        angle: Optional[float] = None,
    ) -> None:
        """Set target position intent (non-blocking). Use angle (degrees) to set Z in mm."""
        with self._lock:
            if x is not None:
                self._intent["x"] = x
            if y is not None:
                self._intent["y"] = y
            if z is not None:
                self._intent["z"] = z
            if angle is not None:
                self._intent["z"] = angle * self._z_deg_to_mm

    def set_neutral_intent(self, z: Optional[float] = None) -> None:
        """Set intent to neutral pose. Optional z override."""
        with self._lock:
            for axis in ("x", "y", "z"):
                val = self._neutral.get(axis)
                if val is not None:
                    self._intent[axis] = val
            if z is not None:
                self._intent["z"] = z

    def move_blocking(self, timeout: float = 10.0) -> bool:
        """
        INIT/SHUTDOWN only: G90 + G0 to current intent. Initializes logical Z for relative moves.
        """
        with self._lock:
            tgt = self._intent.copy()

            clamped: Dict[str, float] = {}
            for axis in ("x", "y", "z"):
                val = tgt.get(axis)
                if val is not None:
                    lo, hi = self._limits.get(axis, (None, None))
                    v = float(val)
                    if lo is not None:
                        v = max(lo, v)
                    if hi is not None:
                        v = min(hi, v)
                    clamped[axis] = v
                    self._last_sent[axis] = v

            if clamped:
                f = self._speeds.get("travel", 2000)
                parts = []
                for axis in ("x", "y", "z"):
                    if axis in clamped:
                        parts.append(f"{axis.upper()}{clamped[axis]:.3f}")

                cmd = f"G90\nG0 {' '.join(parts)} F{f:.0f}"
                self._client.send_gcode(cmd)

                if "z" in clamped:
                    self._last_commanded_z = clamped["z"]
                    print(
                        f"[Motion] Blocking move complete. Z initialized to {self._last_commanded_z:.3f}mm"
                    )

        time.sleep(0.5)
        return True

    def set_current_z(self, z_mm: float) -> None:
        """Initialize logical Z (e.g. after homing)."""
        with self._lock:
            self._last_commanded_z = z_mm
            self._last_sent["z"] = z_mm
            print(f"[Motion] Current logical Z set to {z_mm:.3f}mm")

    def move_z_relative_blocking(
        self,
        z_delta: float,
        timeout: float = 10.0,
        velocity: Optional[float] = None,
    ) -> bool:
        """
        MOVE_Z D=… V=… and wait for completion. If velocity is None, uses configured move_z_velocity
        (runtime-updatable via API / apply_runtime_config).
        """
        with self._lock:
            v = float(velocity if velocity is not None else self._move_z_velocity)

            if self._last_commanded_z is not None:
                self._last_commanded_z += z_delta
                lo, hi = self._limits.get("z", (None, None))
                if lo is not None:
                    self._last_commanded_z = max(lo, self._last_commanded_z)
                if hi is not None:
                    self._last_commanded_z = min(hi, self._last_commanded_z)
                self._last_sent["z"] = self._last_commanded_z

        cmd = f"MOVE_Z D={z_delta:.2f} V={v:.2f}"
        print(f"[Motion] Sending to Moonraker: {cmd}")
        self._client.send_gcode_and_wait_complete(cmd, timeout_s=timeout)

        if self._last_commanded_z is not None:
            print(f"[Motion] Z{z_delta:+.3f}mm complete -> Z={self._last_commanded_z:.3f}mm")
        else:
            print(f"[Motion] Z{z_delta:+.3f}mm complete")
        return True

    @property
    def target_intent(self) -> Dict[str, Optional[float]]:
        with self._lock:
            return self._intent.copy()

    @property
    def last_sent_target(self) -> Dict[str, Optional[float]]:
        with self._lock:
            return self._last_sent.copy()

    @property
    def logical_z_mm(self) -> Optional[float]:
        with self._lock:
            if self._last_commanded_z is None:
                return None
            return float(self._last_commanded_z)
