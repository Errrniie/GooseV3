"""
Runtime configuration manager: single source of truth in memory + JSON persistence.

- On startup, merges defaults (from Config/*.py) with Config/runtime_config.json if present.
- Updates sync into Config.Network_Config, Config.Motion_Config, Config.Driver_Thresholds
  so existing `import Config.*` code sees current values.
- Thread-safe for API updates.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Optional, TypeVar

_CONFIG_DIR = Path(__file__).resolve().parent
RUNTIME_JSON = _CONFIG_DIR / "runtime_config.json"

_lock = threading.RLock()
_initialized = False
_manager: Optional["ConfigManager"] = None


@dataclass
class NetworkData:
    moonraker_host: str
    moonraker_port: int
    moonraker_ws_path: str
    esp32_ip: str
    laptop_ip: Optional[str]
    stream_port: int
    control_api_host: str
    control_api_port: int


@dataclass
class MotionData:
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    z_min: float
    z_max: float
    neutral_x: float
    neutral_y: float
    neutral_z: float
    travel_speed: float
    move_z_velocity: float
    search_angular_velocity: float
    rotation_distance_mm: float
    degrees_per_revolution: float
    max_angular_velocity: float
    # Camera / search / vision / tracking (see Config.Motion_Config)
    camera_width: int
    camera_height: int
    search_step_mm: float
    detection_confidence_threshold: float
    vision_staleness_s: float
    tracking_kp: float
    tracking_ki: float
    tracking_integral_max_px: float
    tracking_deadzone_px: int
    tracking_min_step_mm: float
    tracking_max_step_mm: float
    tracking_target_lost_frames: int


@dataclass
class DriverData:
    sg_result_min_ok: int
    sg_result_max_ok: int
    cs_min_ok: int
    cs_max_ok: int
    stallguard_expected: int
    ot_expected: int
    otpw_expected: int


def _defaults_from_modules() -> tuple[NetworkData, MotionData, DriverData]:
    import Config.Driver_Thresholds as dcfg
    import Config.Motion_Config as mcfg
    import Config.Network_Config as ncfg

    net = NetworkData(
        moonraker_host=ncfg.MOONRAKER_HOST,
        moonraker_port=int(ncfg.MOONRAKER_PORT),
        moonraker_ws_path=ncfg.MOONRAKER_WS_PATH,
        esp32_ip=ncfg.ESP32_IP,
        laptop_ip=ncfg.LAPTOP_IP if ncfg.LAPTOP_IP else None,
        stream_port=int(ncfg.STREAM_PORT),
        control_api_host=ncfg.CONTROL_API_HOST,
        control_api_port=int(ncfg.CONTROL_API_PORT),
    )
    motion = MotionData(
        x_min=float(mcfg.X_MIN),
        x_max=float(mcfg.X_MAX),
        y_min=float(mcfg.Y_MIN),
        y_max=float(mcfg.Y_MAX),
        z_min=float(mcfg.Z_MIN),
        z_max=float(mcfg.Z_MAX),
        neutral_x=float(mcfg.NEUTRAL_X),
        neutral_y=float(mcfg.NEUTRAL_Y),
        neutral_z=float(mcfg.NEUTRAL_Z),
        travel_speed=float(mcfg.TRAVEL_SPEED),
        move_z_velocity=float(mcfg.MOVE_Z_VELOCITY),
        search_angular_velocity=float(mcfg.SEARCH_ANGULAR_VELOCITY),
        rotation_distance_mm=float(mcfg.ROTATION_DISTANCE_MM),
        degrees_per_revolution=float(mcfg.DEGREES_PER_REVOLUTION),
        max_angular_velocity=float(mcfg.MAX_ANGULAR_VELOCITY),
        camera_width=int(mcfg.CAMERA_WIDTH),
        camera_height=int(mcfg.CAMERA_HEIGHT),
        search_step_mm=float(mcfg.SEARCH_STEP_MM),
        detection_confidence_threshold=float(mcfg.DETECTION_CONFIDENCE_THRESHOLD),
        vision_staleness_s=float(mcfg.VISION_STALENESS_S),
        tracking_kp=float(mcfg.TRACKING_KP),
        tracking_ki=float(mcfg.TRACKING_KI),
        tracking_integral_max_px=float(mcfg.TRACKING_INTEGRAL_MAX_PX),
        tracking_deadzone_px=int(mcfg.TRACKING_DEADZONE_PX),
        tracking_min_step_mm=float(mcfg.TRACKING_MIN_STEP_MM),
        tracking_max_step_mm=float(mcfg.TRACKING_MAX_STEP_MM),
        tracking_target_lost_frames=int(mcfg.TRACKING_TARGET_LOST_FRAMES),
    )
    driver = DriverData(
        sg_result_min_ok=int(dcfg.SG_RESULT_MIN_OK),
        sg_result_max_ok=int(dcfg.SG_RESULT_MAX_OK),
        cs_min_ok=int(dcfg.CS_MIN_OK),
        cs_max_ok=int(dcfg.CS_MAX_OK),
        stallguard_expected=int(dcfg.STALLGUARD_EXPECTED),
        ot_expected=int(dcfg.OT_EXPECTED),
        otpw_expected=int(dcfg.OTPW_EXPECTED),
    )
    return net, motion, driver


T = TypeVar("T")


def _merge_section(
    base: T,
    overlay: Optional[dict[str, Any]],
    cls: type[T],
) -> T:
    if not overlay:
        return base
    data = asdict(base)
    field_names = {f.name for f in fields(cls)}
    for key, value in overlay.items():
        if key not in field_names:
            continue
        if value is None:
            if key == "laptop_ip":
                data[key] = None
            continue
        ftype = next(f.type for f in fields(cls) if f.name == key)
        if ftype is float and isinstance(value, (int, str)):
            data[key] = float(value)
        elif ftype is int and isinstance(value, (int, float, str)):
            data[key] = int(value)
        else:
            data[key] = value
    return cls(**data)


class ConfigManager:
    """Holds network, motion, and driver snapshots; persists to runtime_config.json."""

    def __init__(self) -> None:
        self.network: NetworkData
        self.motion: MotionData
        self.driver: DriverData

    def load(self) -> None:
        """Load defaults, overlay JSON if present, sync to Config modules, write JSON if missing."""
        with _lock:
            net_d, mot_d, drv_d = _defaults_from_modules()
            if RUNTIME_JSON.is_file():
                with open(RUNTIME_JSON, encoding="utf-8") as f:
                    raw = json.load(f)
                net_d = _merge_section(net_d, raw.get("network"), NetworkData)
                mot_d = _merge_section(mot_d, raw.get("motion"), MotionData)
                drv_d = _merge_section(drv_d, raw.get("driver"), DriverData)
            self.network = net_d
            self.motion = mot_d
            self.driver = drv_d
            _sync_to_modules(self)
            if not RUNTIME_JSON.is_file():
                self.save()

    def save(self) -> None:
        """Atomically persist current state to runtime_config.json."""
        with _lock:
            payload = {
                "network": asdict(self.network),
                "motion": asdict(self.motion),
                "driver": asdict(self.driver),
            }
        tmp = RUNTIME_JSON.with_suffix(".json.tmp")
        text = json.dumps(payload, indent=2)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, RUNTIME_JSON)

    def update_network(self, **kwargs: Any) -> NetworkData:
        with _lock:
            cur = asdict(self.network)
            for k, v in kwargs.items():
                if k not in cur:
                    continue
                if k == "laptop_ip":
                    cur[k] = v
                    continue
                if v is None:
                    continue
                if k in ("moonraker_port", "stream_port", "control_api_port"):
                    cur[k] = int(v)
                else:
                    cur[k] = v
            self.network = NetworkData(**cur)
            _sync_to_modules(self)
            self.save()
            return self.network

    def update_motion(self, **kwargs: Any) -> MotionData:
        int_keys = frozenset(
            {
                "camera_width",
                "camera_height",
                "tracking_deadzone_px",
                "tracking_target_lost_frames",
            }
        )
        with _lock:
            cur = asdict(self.motion)
            for k, v in kwargs.items():
                if k not in cur or v is None:
                    continue
                if k in int_keys:
                    cur[k] = int(v)
                else:
                    cur[k] = float(v)
            self.motion = MotionData(**cur)
            _sync_to_modules(self)
            self.save()
            return self.motion

    def motion_controller_dict(self) -> dict[str, Any]:
        """Dict for Domains.Motion.Controller — all keys the controller understands."""
        m = self.motion
        mm_per_degree = m.rotation_distance_mm / m.degrees_per_revolution
        return {
            "limits": {
                "x": [m.x_min, m.x_max],
                "y": [m.y_min, m.y_max],
                "z": [m.z_min, m.z_max],
            },
            "neutral": {"x": m.neutral_x, "y": m.neutral_y, "z": m.neutral_z},
            "speeds": {"travel": m.travel_speed},
            "move_z_velocity": m.move_z_velocity,
            "mm_per_degree": mm_per_degree,
        }

    def tracking_config_dict(self) -> dict[str, Any]:
        """Dict for Domains.Behavior.TrackingController.apply_runtime_config."""
        m = self.motion
        return {
            "frame_width": m.camera_width,
            "frame_height": m.camera_height,
            "deadzone_px": m.tracking_deadzone_px,
            "kp": m.tracking_kp,
            "ki": m.tracking_ki,
            "integral_max_px": m.tracking_integral_max_px,
            "min_step_mm": m.tracking_min_step_mm,
            "max_step_mm": m.tracking_max_step_mm,
            "confidence_threshold": m.detection_confidence_threshold,
            "target_lost_frames": m.tracking_target_lost_frames,
        }


def _sync_to_modules(mgr: ConfigManager) -> None:
    import Config.Driver_Thresholds as dcfg
    import Config.Motion_Config as mcfg
    import Config.Network_Config as ncfg

    n = mgr.network
    ncfg.MOONRAKER_HOST = n.moonraker_host
    ncfg.MOONRAKER_PORT = n.moonraker_port
    ncfg.MOONRAKER_WS_PATH = n.moonraker_ws_path
    ncfg.MOONRAKER_WS_URL = (
        f"ws://{n.moonraker_host}:{n.moonraker_port}{n.moonraker_ws_path}"
    )
    ncfg.ESP32_IP = n.esp32_ip
    ncfg.ESP32_BASE_URL = f"http://{n.esp32_ip}"
    ncfg.LAPTOP_IP = n.laptop_ip
    ncfg.STREAM_PORT = n.stream_port
    ncfg.CONTROL_API_HOST = n.control_api_host
    ncfg.CONTROL_API_PORT = n.control_api_port

    mo = mgr.motion
    mcfg.X_MIN = mo.x_min
    mcfg.X_MAX = mo.x_max
    mcfg.Y_MIN = mo.y_min
    mcfg.Y_MAX = mo.y_max
    mcfg.Z_MIN = mo.z_min
    mcfg.Z_MAX = mo.z_max
    mcfg.NEUTRAL_X = mo.neutral_x
    mcfg.NEUTRAL_Y = mo.neutral_y
    mcfg.NEUTRAL_Z = mo.neutral_z
    mcfg.TRAVEL_SPEED = mo.travel_speed
    mcfg.MOVE_Z_VELOCITY = mo.move_z_velocity
    mcfg.SEARCH_ANGULAR_VELOCITY = mo.search_angular_velocity
    mcfg.ROTATION_DISTANCE_MM = mo.rotation_distance_mm
    mcfg.DEGREES_PER_REVOLUTION = mo.degrees_per_revolution
    mcfg.MM_PER_DEGREE = mo.rotation_distance_mm / mo.degrees_per_revolution
    mcfg.MAX_ANGULAR_VELOCITY = mo.max_angular_velocity
    mcfg.SEARCH_START_Z = mo.neutral_z
    mcfg.SEARCH_MIN_ANGLE = mcfg.z_mm_to_angle(mcfg.Z_MIN)
    mcfg.SEARCH_MAX_ANGLE = mcfg.z_mm_to_angle(mcfg.Z_MAX)
    mcfg.SEARCH_START_ANGLE = mcfg.z_mm_to_angle(mcfg.SEARCH_START_Z)

    mcfg.CAMERA_WIDTH = mo.camera_width
    mcfg.CAMERA_HEIGHT = mo.camera_height
    mcfg.SEARCH_STEP_MM = mo.search_step_mm
    mcfg.DETECTION_CONFIDENCE_THRESHOLD = mo.detection_confidence_threshold
    mcfg.VISION_STALENESS_S = mo.vision_staleness_s
    mcfg.TRACKING_KP = mo.tracking_kp
    mcfg.TRACKING_KI = mo.tracking_ki
    mcfg.TRACKING_INTEGRAL_MAX_PX = mo.tracking_integral_max_px
    mcfg.TRACKING_DEADZONE_PX = mo.tracking_deadzone_px
    mcfg.TRACKING_MIN_STEP_MM = mo.tracking_min_step_mm
    mcfg.TRACKING_MAX_STEP_MM = mo.tracking_max_step_mm
    mcfg.TRACKING_TARGET_LOST_FRAMES = mo.tracking_target_lost_frames

    d = mgr.driver
    dcfg.SG_RESULT_MIN_OK = d.sg_result_min_ok
    dcfg.SG_RESULT_MAX_OK = d.sg_result_max_ok
    dcfg.CS_MIN_OK = d.cs_min_ok
    dcfg.CS_MAX_OK = d.cs_max_ok
    dcfg.STALLGUARD_EXPECTED = d.stallguard_expected
    dcfg.OT_EXPECTED = d.ot_expected
    dcfg.OTPW_EXPECTED = d.otpw_expected


def get_config_manager() -> ConfigManager:
    global _manager
    with _lock:
        if _manager is None:
            _manager = ConfigManager()
        return _manager


def init_config() -> None:
    """Idempotent: load JSON + sync modules. Call from Orchestrator and Control API."""
    global _initialized
    with _lock:
        if _initialized:
            return
        _initialized = True
    get_config_manager().load()
