from __future__ import annotations
from typing import Any, Dict, Optional
import threading
import time


class MotionController:
    """
    Fixed-rate streaming motion controller for Moonraker.
    
    This is the ONLY place where command timing exists in the system.
    
    Behavior:
    - Maintains a fixed-rate send loop (configurable Hz)
    - On each tick: reads latest intent, converts to G-code, sends command
    - Uses intent coalescing / deadband to avoid micro-jitter
    - Does NOT wait for motion completion or inspect queue depth
    - Z axis uses RELATIVE positioning: tracks last commanded Z and sends deltas
    
    This is a velocity-limited streaming controller, not a serialized executor.
    """

    def __init__(self, moonraker: Any, config: Dict[str, Any]):
        """
        moonraker : MoonrakerWSClient
        config: dict with axis limits, neutral pose, speeds:
            {
                "limits": {"x": [min, max], "y": [min, max], "z": [min, max]},
                "neutral": {"x": float, "y": float, "z": float},
                "speeds": {"travel": float, "z": float},
                "angular_velocity": float,  # deg/s for search
                "send_rate_hz": float,  # optional, default 30
            }
        """
        self._client = moonraker
        self._limits = config.get("limits", {})
        self._neutral = config.get("neutral", {})
        self._speeds = config.get("speeds", {})
        self._lock = threading.Lock()

        # Fixed-rate timing (sole owner of timing in the system)
        self._send_rate_hz: float = config.get("send_rate_hz", 5.0)
        self._send_period_s: float = 1.0 / self._send_rate_hz
        self._last_send_time: float = 0.0

        # Geometry: degrees to mm conversion (from config)
        self._z_deg_to_mm: float = config.get("mm_per_degree", 8.0 / 360.0)

        # Feedrate multiplier for smooth streaming (from config)
        self._feedrate_multiplier: float = config.get("feedrate_multiplier", 2.0)

        # Configured angular velocity (from config)
        self._angular_velocity: float = config.get("angular_velocity", 60.0)

        # Current intent (target position - absolute values from behavior modules)
        self._intent: Dict[str, Optional[float]] = {"x": None, "y": None, "z": None}
        # Last target actually sent (for X/Y absolute tracking)
        self._last_sent: Dict[str, Optional[float]] = {"x": None, "y": None, "z": None}

        # Relative Z tracking: last commanded Z position (absolute value in mm)
        # Used to compute delta for relative motion commands
        self._last_commanded_z: Optional[float] = None

        # Deadband disabled for smooth streaming
        self._deadband_z: float = 0.0

    def apply_runtime_config(self, config: Dict[str, Any]) -> None:
        """
        Update streaming parameters and limits from the same dict shape as __init__.
        Call after API/config manager changes so a running controller picks up new values.
        """
        with self._lock:
            if "limits" in config:
                self._limits = config["limits"]
            if "neutral" in config:
                self._neutral = config["neutral"]
            if "speeds" in config:
                self._speeds = config["speeds"]
            if "send_rate_hz" in config:
                self._send_rate_hz = float(config["send_rate_hz"])
                self._send_period_s = 1.0 / self._send_rate_hz
            if "mm_per_degree" in config:
                self._z_deg_to_mm = float(config["mm_per_degree"])
            if "feedrate_multiplier" in config:
                self._feedrate_multiplier = float(config["feedrate_multiplier"])
            if "angular_velocity" in config:
                self._angular_velocity = float(config["angular_velocity"])

    # -- Intent Setting (non-blocking, called by behavior modules) --

    def set_intent(
        self,
        *,
        x: Optional[float] = None,
        y: Optional[float] = None,
        z: Optional[float] = None,
        angle: Optional[float] = None,
    ) -> None:
        """
        Set target position intent. Non-blocking.
        Use 'angle' (degrees) for Z axis angular control.
        Unspecified axes are not affected.
        """
        with self._lock:
            if x is not None:
                self._intent["x"] = x
            if y is not None:
                self._intent["y"] = y
            if z is not None:
                self._intent["z"] = z
            if angle is not None:
                # Convert angle (degrees) to Z mm
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

    # -- Fixed-rate update (called from main loop) --

    def update(self) -> None:
        """
        Fixed-rate streaming update. Safe to call every frame.
        
        - Enforces send rate limiting (e.g., 5 Hz)
        - Reads current intent (absolute positions from behavior modules)
        - For Z axis: computes delta from last commanded position, sends relative move
        - For X/Y: sends absolute moves via MOVE command
        - Does NOT block or wait for motion completion
        """
        now = time.monotonic()
        
        # Rate limiting: only send at configured frequency
        if (now - self._last_send_time) < self._send_period_s:
            return
        
        with self._lock:
            # Snapshot intent
            tgt = self._intent.copy()

            # --- Handle Z axis with relative positioning ---
            target_z = tgt.get("z")
            delta_z: Optional[float] = None
            clamped_z: Optional[float] = None

            if target_z is not None:
                # Clamp target to limits
                lo, hi = self._limits.get("z", (None, None))
                clamped_z = float(target_z)
                if lo is not None:
                    clamped_z = max(lo, clamped_z)
                if hi is not None:
                    clamped_z = min(hi, clamped_z)

                # Compute delta from last commanded position
                if self._last_commanded_z is None:
                    # First command: assume we're at the target (no delta)
                    # This gets initialized properly in move_blocking during INIT
                    delta_z = 0.0
                else:
                    delta_z = clamped_z - self._last_commanded_z

                # Apply deadband to avoid micro-jitter
                if abs(delta_z) <= self._deadband_z:
                    delta_z = None  # No meaningful change

            # --- Handle X/Y with absolute positioning (if needed) ---
            prev = self._last_sent.copy()
            xy_move: Dict[str, float] = {}
            for axis in ("x", "y"):
                if tgt[axis] is not None:
                    if prev[axis] is None or tgt[axis] != prev[axis]:
                        # Clamp to limits
                        lo, hi = self._limits.get(axis, (None, None))
                        v = float(tgt[axis])
                        if lo is not None:
                            v = max(lo, v)
                        if hi is not None:
                            v = min(hi, v)
                        xy_move[axis] = v

            # Check if there's anything to send
            has_z_move = delta_z is not None and delta_z != 0.0
            has_xy_move = len(xy_move) > 0

            if not has_z_move and not has_xy_move:
                return  # No meaningful change

            # --- Compute feedrate ---
            # Base feedrate from angular velocity: deg/s * (mm/deg) * 60 = mm/min
            base_feedrate = self._angular_velocity * self._z_deg_to_mm * 60.0
            # Overspeed so motor finishes before next command
            f = base_feedrate * self._feedrate_multiplier

            # --- Send commands ---
            if has_z_move and not has_xy_move:
                # Z-only move: use relative positioning (G91)
                cmd = f"Move z={delta_z:.4f} F{f:.0f}"
                self._client.send_gcode(cmd)
                self._last_send_time = now

                # Update internal state
                self._last_commanded_z = clamped_z
                self._last_sent["z"] = clamped_z

            elif has_xy_move:
                # X/Y move (with or without Z): use MOVE command for X/Y, relative for Z
                if has_z_move:
                    # Combined move: X/Y         + Z relative
                    # Send Z relative first, then X/Y absolute
                    z_cmd = f"Move z={delta_z:.4f} F{f:.0f}"
                    self._client.send_gcode(z_cmd)
                    self._last_commanded_z = clamped_z
                    self._last_sent["z"] = clamped_z

                # Send X/Y absolute move
                parts = []
                for axis in ("x", "y"):
                    if axis in xy_move:
                        parts.append(f"{axis}={xy_move[axis]:.3f}")
                        self._last_sent[axis] = xy_move[axis]

                if parts:
                    travel_f = max(f, self._speeds.get("travel", 800))
                    xy_cmd = f"MOVE {' '.join(parts)} SPEED={travel_f:.0f}"
                    self._client.send_gcode(xy_cmd)

                self._last_send_time = now
                print(f"[Motion] XY move: {xy_move}")

    # -- Blocking move (for INIT/SHUTDOWN only) --

    def move_blocking(self, timeout: float = 10.0) -> bool:
        """
        Force-send current intent and wait briefly for motion to start.
        Only for INIT/SHUTDOWN sequences, never for SEARCH or TRACK.
        
        Uses ABSOLUTE positioning (G90) to establish known position.
        Initializes _last_commanded_z for subsequent relative streaming.
        Returns True immediately (no queue inspection).
        """
        # Force send regardless of rate limit
        with self._lock:
            tgt = self._intent.copy()
            
            # Clamp all axes and build absolute move command
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
                # Use standard G-code for absolute positioning
                f = self._speeds.get("travel", 2000)
                parts = []
                for axis in ("x", "y", "z"):
                    if axis in clamped:
                        parts.append(f"{axis.upper()}{clamped[axis]:.3f}")

                # G90 = absolute positioning, G0 = rapid move
                cmd = f"G90\nG0 {' '.join(parts)} F{f:.0f}"
                self._client.send_gcode(cmd)
                self._last_send_time = time.monotonic()

                # Initialize _last_commanded_z for relative streaming
                if "z" in clamped:
                    self._last_commanded_z = clamped["z"]
                    print(f"[Motion] Blocking move complete. Z initialized to {self._last_commanded_z:.3f}mm")

        # Brief pause to allow motion to start (not waiting for completion)
        time.sleep(0.5)
        return True

    def set_current_z(self, z_mm: float) -> None:
        """Initialize the logical Z position (e.g., after homing)."""
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
        Send a relative Z move and block until Moonraker acknowledges completion.
        
        Uses G91 (relative) + G0 + M400 (wait for moves) + G90 (back to absolute).
        Blocks until the command response is received from Moonraker.
        
        Args:
            z_delta: Relative Z movement in mm (positive = up, negative = down)
            timeout: Timeout for blocking call
            
        Returns:
            True on success
        """
        with self._lock:
            # Velocity for MOVE_Z macro (V parameter)
            v = velocity if velocity is not None else 2.0

            # Update internal Z tracking (target position after this move)
            if self._last_commanded_z is not None:
                self._last_commanded_z += z_delta
                # Clamp to limits
                lo, hi = self._limits.get("z", (None, None))
                if lo is not None:
                    self._last_commanded_z = max(lo, self._last_commanded_z)
                if hi is not None:
                    self._last_commanded_z = min(hi, self._last_commanded_z)
                self._last_sent["z"] = self._last_commanded_z

        # Use MOVE_Z macro and wait for RESPOND 'complete'
        cmd = f"MOVE_Z D={z_delta:.2f} V={v:.2f}"
        print(f"[Motion] Sending to Moonraker: {cmd}")
        # This relies on MoonrakerWSClient.send_gcode_and_wait_complete
        self._client.send_gcode_and_wait_complete(cmd, timeout_s=timeout)

        if self._last_commanded_z is not None:
            print(f"[Motion] Z{z_delta:+.3f}mm complete -> Z={self._last_commanded_z:.3f}mm")
        else:
            print(f"[Motion] Z{z_delta:+.3f}mm complete")
        return True

    # -- State accessors --

    @property
    def target_intent(self) -> Dict[str, Optional[float]]:
        """Snapshot copy of current intent."""
        with self._lock:
            return self._intent.copy()

    @property
    def last_sent_target(self) -> Dict[str, Optional[float]]:
        """Snapshot copy of last-sent, for debug."""
        with self._lock:
            return self._last_sent.copy()