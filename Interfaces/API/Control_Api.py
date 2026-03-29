"""
Simple FastAPI control server for GooseV3.

Run this on the Jetson, then send HTTP requests from your laptop to:
  http://<JETSON_IP>:8000/start_tracking
  http://<JETSON_IP>:8000/stop_tracking
  http://<JETSON_IP>:8000/move_laser
  http://<JETSON_IP>:8000/system/modes
  http://<JETSON_IP>:8000/system/mode  (POST JSON {\"mode\": \"normal\"} or \"test\")
  http://<JETSON_IP>:8000/system/network  (GET — Jetson + peer/stream info)
  http://<JETSON_IP>:8000/system/handshake  (POST JSON {\"client_ip\": \"<laptop IPv4>\"})

Right now this is a thin test harness:
  - It toggles in-process flags
  - It logs commands (e.g. move_laser) to stdout

Later we can wire these endpoints into real motion / tracking code.
"""

import ipaddress

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, field_validator

from Core.ModeManager import list_registered_modes, select_mode
from Networking.Local_IP import get_ethernet_ipv4

from Config.Manager import get_config_manager, init_config
from Domains.Motion.Runtime import notify_motion_config_changed

init_config()

app = FastAPI(title="GooseV3 Control API", version="0.4.0")


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
    z_speed: float | None = None

    # Timing
    send_rate_hz: float | None = None
    feedrate_multiplier: float | None = None


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
    Test endpoint to drive laser motion parameters from the network.
    For now this only logs; later we can hook into MotionController / laser code.
    """
    print(f"[CONTROL] move_laser requested: x={payload.x}, y={payload.y}")
    # TODO: integrate with MotionController and/or LaserEnable here
    return {"status": "ok", "x": payload.x, "y": payload.y}


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
    """
    Return a subset of motion config values that are safe to tweak at runtime.
    """
    m = get_config_manager().motion
    return {
        "x_min": m.x_min,
        "x_max": m.x_max,
        "y_min": m.y_min,
        "y_max": m.y_max,
        "z_min": m.z_min,
        "z_max": m.z_max,
        "neutral_x": m.neutral_x,
        "neutral_y": m.neutral_y,
        "neutral_z": m.neutral_z,
        "travel_speed": m.travel_speed,
        "z_speed": m.z_speed,
        "send_rate_hz": m.send_rate_hz,
        "feedrate_multiplier": m.feedrate_multiplier,
    }


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


# Note: Core.Orchestrator starts this app in a background thread. To run the API alone:
#   ./venv/bin/uvicorn Interfaces.API.Control_Api:app --host 0.0.0.0 --port 8000

