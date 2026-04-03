"""
Simple FastAPI control server for GooseV3.

Run this on the Jetson, then send HTTP requests from your laptop, e.g.:

  Laser (ESP32 power — see Domains/Laser/Esp_32.py):
    GET  http://<JETSON_IP>:8000/laser/status
    POST http://<JETSON_IP>:8000/laser/on
    POST http://<JETSON_IP>:8000/laser/off

  Tracking flags / legacy:
    POST http://<JETSON_IP>:8000/start_tracking
    POST http://<JETSON_IP>:8000/stop_tracking
    POST http://<JETSON_IP>:8000/move_laser   (body JSON {"x": float, "y": float} — reserved for future aim)

  Modes / pairing:
    GET  http://<JETSON_IP>:8000/system/modes
    POST http://<JETSON_IP>:8000/system/mode   (JSON {"mode": "normal"} or "test")
    GET  http://<JETSON_IP>:8000/system/network
    POST http://<JETSON_IP>:8000/system/handshake  (JSON {"client_ip": "<laptop IPv4>"})

  Config:
    GET/POST http://<JETSON_IP>:8000/config/network
    GET/POST http://<JETSON_IP>:8000/config/motion

  Vision (latest detection for laptop overlay):
    GET http://<JETSON_IP>:8000/vision/detection

ESP32 IP comes from runtime config (``esp32_ip``); set via POST /config/network if needed.
"""

import ipaddress
from dataclasses import asdict

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, field_validator

from Core.ModeManager import list_registered_modes, select_mode
from Networking.Local_IP import get_ethernet_ipv4

from Config.Manager import get_config_manager, init_config
from Domains.Laser.Esp_32 import LaserController
from Domains.Motion.Runtime import notify_motion_config_changed

init_config()

app = FastAPI(title="GooseV3 Control API", version="0.5.0")


def _esp_laser() -> LaserController:
    """Laser controller using current runtime ``esp32_ip`` (not a cached default)."""
    ip = get_config_manager().network.esp32_ip
    return LaserController(ip_address=ip)


# ============================================================================
# Request models
# ============================================================================


class MoveLaserRequest(BaseModel):
    x: float
    y: float


class NetworkConfigUpdate(BaseModel):
    moonraker_host: str | None = None
    moonraker_port: int | None = None
    esp32_ip: str | None = None


class ModeSelectRequest(BaseModel):
    mode: str


class HandshakeRequest(BaseModel):
    """Client sends its IPv4; server persists it as LAPTOP_IP and returns Jetson Ethernet IPv4."""

    client_ip: str

    @field_validator("client_ip")
    @classmethod
    def must_be_ipv4(cls, v: str) -> str:
        ipaddress.IPv4Address(v.strip())
        return v.strip()


class MotionConfigUpdate(BaseModel):
    # Axis limits
    x_min: float | None = None
    x_max: float | None = None
    y_min: float | None = None
    y_max: float | None = None
    z_min: float | None = None
    z_max: float | None = None

    # Neutral position
    neutral_x: float | None = None
    neutral_y: float | None = None
    neutral_z: float | None = None

    # Speeds
    travel_speed: float | None = None
    move_z_velocity: float | None = None

    search_angular_velocity: float | None = None
    rotation_distance_mm: float | None = None
    degrees_per_revolution: float | None = None
    max_angular_velocity: float | None = None

    # Camera, vision, tracking
    camera_width: int | None = None
    camera_height: int | None = None
    search_step_mm: float | None = None
    detection_confidence_threshold: float | None = None
    vision_staleness_s: float | None = None
    tracking_kp: float | None = None
    tracking_ki: float | None = None
    tracking_integral_max_px: float | None = None
    tracking_deadzone_px: int | None = None
    tracking_min_step_mm: float | None = None
    tracking_max_step_mm: float | None = None
    tracking_target_lost_frames: int | None = None


# Simple in-memory state flags (per-process)
tracking_enabled: bool = False


@app.get("/system/modes")
def get_system_modes():
    """List mode ids that can be passed to POST /system/mode."""
    return {"modes": list_registered_modes()}


@app.get("/system/network")
def get_system_network():
    """
    Jetson IPv4 (Ethernet), saved peer IP (LAPTOP_IP), and stream port — for pairing UIs.
    """
    jetson = get_ethernet_ipv4()
    n = get_config_manager().network
    return {
        "jetson_ip": jetson,
        "peer_ip": n.laptop_ip,
        "stream_port": n.stream_port,
        "control_api_port": n.control_api_port,
    }


@app.post("/system/handshake")
def post_system_handshake(body: HandshakeRequest):
    """
    Client sends its IPv4; we persist it as LAPTOP_IP (video stream target) in
    runtime_config.json and sync Config modules.
    """
    get_config_manager().update_network(laptop_ip=body.client_ip)

    jetson = get_ethernet_ipv4()
    print(
        f"[CONTROL] Handshake: peer LAPTOP_IP -> {body.client_ip}; "
        f"jetson_ip={jetson!r} (Ethernet)"
    )
    return {
        "status": "ok",
        "jetson_ip": jetson,
        "peer_ip_saved": body.client_ip,
        "stream_port": get_config_manager().network.stream_port,
    }


@app.post("/system/mode")
def post_system_mode(body: ModeSelectRequest):
    """
    Select which pipeline the orchestrator should run after it starts.
    Call this once the process is waiting for a mode.
    """
    if not select_mode(body.mode):
        raise HTTPException(
            status_code=400,
            detail=f"Unknown mode {body.mode!r}; use GET /system/modes",
        )
    return {"status": "ok", "mode": body.mode.strip().lower()}


@app.post("/start_tracking")
def start_tracking():
    global tracking_enabled
    tracking_enabled = True
    print("[CONTROL] Tracking enabled via API")
    return {"status": "tracking started", "tracking_enabled": tracking_enabled}


@app.post("/stop_tracking")
def stop_tracking():
    global tracking_enabled
    tracking_enabled = False
    print("[CONTROL] Tracking disabled via API")
    return {"status": "tracking stopped", "tracking_enabled": tracking_enabled}


@app.post("/move_laser")
def move_laser(payload: MoveLaserRequest):
    """
    Reserved for future mirror / aim commands (x, y in mm or logical units).
    ESP32 laser power: use POST /laser/on and POST /laser/off.
    """
    print(f"[CONTROL] move_laser requested: x={payload.x}, y={payload.y}")
    return {"status": "ok", "x": payload.x, "y": payload.y}


# ============================================================================
# Laser (ESP32 HTTP: /high, /low, /status)
# ============================================================================


@app.get("/laser/status")
def laser_status():
    """
    Query ESP32 for laser pin state (JSON ``state``: typically HIGH / LOW).
    """
    state = _esp_laser().get_status()
    if state is None:
        raise HTTPException(
            status_code=502,
            detail="Could not read laser status from ESP32 (check esp32_ip and device).",
        )
    return {
        "status": "ok",
        "laser_state": state,
        "esp32_ip": get_config_manager().network.esp32_ip,
    }


@app.post("/laser/on")
def laser_on():
    """Turn the laser ON via ESP32 (HTTP GET /high on the device)."""
    ok = _esp_laser().turn_on()
    if not ok:
        raise HTTPException(
            status_code=502,
            detail="Laser ON failed (ESP32 unreachable or non-200 from /high).",
        )
    return {
        "status": "ok",
        "laser": "on",
        "esp32_ip": get_config_manager().network.esp32_ip,
    }


@app.post("/laser/off")
def laser_off():
    """Turn the laser OFF via ESP32 (HTTP GET /low on the device)."""
    ok = _esp_laser().turn_off()
    if not ok:
        raise HTTPException(
            status_code=502,
            detail="Laser OFF failed (ESP32 unreachable or non-200 from /low).",
        )
    return {
        "status": "ok",
        "laser": "off",
        "esp32_ip": get_config_manager().network.esp32_ip,
    }


# ============================================================================
# Config: NETWORK (Moonraker + ESP32)
# ============================================================================


@app.get("/config/network")
def get_network_config():
    """
    Return current network-related config values (runtime + JSON).
    """
    n = get_config_manager().network
    return {
        "moonraker_host": n.moonraker_host,
        "moonraker_port": n.moonraker_port,
        "moonraker_ws_path": n.moonraker_ws_path,
        "esp32_ip": n.esp32_ip,
        "laptop_ip": n.laptop_ip,
        "stream_port": n.stream_port,
    }


@app.post("/config/network")
def update_network_config(update: NetworkConfigUpdate):
    """
    Update selected network fields; persisted to runtime_config.json.
    Only fields provided in the payload are changed.
    """
    mgr = get_config_manager()
    kwargs = {}
    if update.moonraker_host is not None:
        kwargs["moonraker_host"] = update.moonraker_host
    if update.moonraker_port is not None:
        kwargs["moonraker_port"] = update.moonraker_port
    if update.esp32_ip is not None:
        kwargs["esp32_ip"] = update.esp32_ip
    changed = dict(kwargs)
    if kwargs:
        mgr.update_network(**kwargs)
    n = mgr.network
    return {
        "updated": changed,
        "current": {
            "moonraker_host": n.moonraker_host,
            "moonraker_port": n.moonraker_port,
            "moonraker_ws_path": n.moonraker_ws_path,
            "esp32_ip": n.esp32_ip,
            "laptop_ip": n.laptop_ip,
            "stream_port": n.stream_port,
        },
    }


# ============================================================================
# Config: MOTION
# ============================================================================


@app.get("/config/motion")
def get_motion_config():
    """Full motion snapshot (same keys as persisted ``motion`` in runtime_config.json)."""
    return asdict(get_config_manager().motion)


@app.post("/config/motion")
def update_motion_config(update: MotionConfigUpdate):
    """
    Update selected motion fields; persisted to runtime_config.json and synced to Config modules.
    Only fields provided in the payload are changed.
    """
    raw = update.model_dump(exclude_unset=True, exclude_none=True)
    changed = dict(raw)
    if raw:
        get_config_manager().update_motion(**raw)
        notify_motion_config_changed()
    return {
        "updated": changed,
        "current": get_motion_config(),
    }


@app.get("/vision/detection")
def get_vision_detection():
    """
    Latest detection for client-side bbox overlay (poll ~10–30 Hz).
    ``bbox`` is ``[x1, y1, x2, y2]`` in pixels or null.
    """
    from Domains.Vision.Interface import get_latest_detection

    st = get_latest_detection()
    m = get_config_manager().motion
    bbox = (
        [int(x) for x in st.bbox]
        if st.bbox is not None
        else None
    )
    return {
        "has_target": st.has_target,
        "bbox": bbox,
        "confidence": st.confidence,
        "timestamp": st.timestamp,
        "frame_width": m.camera_width,
        "frame_height": m.camera_height,
    }


# Note: Core.Orchestrator starts this app in a background thread. To run the API alone:
#   ./venv/bin/uvicorn Interfaces.API.Control_Api:app --host 0.0.0.0 --port 8000

