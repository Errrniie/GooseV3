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

import Config.Network_Config as net_cfg
import Config.Motion_Config as motion_cfg

app = FastAPI(title="GooseV3 Control API", version="0.3.0")


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
    return {
        "jetson_ip": jetson,
        "peer_ip": net_cfg.LAPTOP_IP,
        "stream_port": net_cfg.STREAM_PORT,
        "control_api_port": net_cfg.CONTROL_API_PORT,
    }


@app.post("/system/handshake")
def post_system_handshake(body: HandshakeRequest):
    """
    Client sends its IPv4; we save it to Config/Network_Config.py as LAPTOP_IP
    (video stream target) and return this device's Ethernet IPv4 so both sides can store it.
    """
    path = net_cfg.__file__
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    text = _patch_assignment_line(
        text, "LAPTOP_IP", f'"{body.client_ip}"'
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)

    import importlib

    importlib.reload(net_cfg)

    jetson = get_ethernet_ipv4()
    print(
        f"[CONTROL] Handshake: peer LAPTOP_IP -> {body.client_ip}; "
        f"jetson_ip={jetson!r} (Ethernet)"
    )
    return {
        "status": "ok",
        "jetson_ip": jetson,
        "peer_ip_saved": body.client_ip,
        "stream_port": net_cfg.STREAM_PORT,
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
    Return current network-related config values.
    """
    return {
        "moonraker_host": net_cfg.MOONRAKER_HOST,
        "moonraker_port": net_cfg.MOONRAKER_PORT,
        "moonraker_ws_path": net_cfg.MOONRAKER_WS_PATH,
        "esp32_ip": net_cfg.ESP32_IP,
        "laptop_ip": net_cfg.LAPTOP_IP,
        "stream_port": net_cfg.STREAM_PORT,
    }


def _patch_assignment_line(text: str, name: str, new_value: str) -> str:
    """
    Very small helper to replace a single `NAME = ...` line in a config .py file.
    We keep it explicit to avoid clever parsing.
    """
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.lstrip().startswith(f"{name} ="):
            indent = line[: len(line) - len(line.lstrip())]
            lines[i] = f"{indent}{name} = {new_value}"
            break
    return "\n".join(lines) + "\n"


@app.post("/config/network")
def update_network_config(update: NetworkConfigUpdate):
    """
    Update selected fields in Config/network_config.py.
    Only fields provided in the payload are changed.
    """
    path = net_cfg.__file__
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    changed = {}

    if update.moonraker_host is not None:
        text = _patch_assignment_line(
            text, "MOONRAKER_HOST", f'"{update.moonraker_host}"'
        )
        changed["moonraker_host"] = update.moonraker_host

    if update.moonraker_port is not None:
        text = _patch_assignment_line(text, "MOONRAKER_PORT", str(update.moonraker_port))
        changed["moonraker_port"] = update.moonraker_port

    if update.esp32_ip is not None:
        text = _patch_assignment_line(text, "ESP32_IP", f'"{update.esp32_ip}"')
        changed["esp32_ip"] = update.esp32_ip

    if changed:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    # Re-import to reflect changes for future reads in this process
    import importlib

    importlib.reload(net_cfg)

    return {
        "updated": changed,
        "current": {
            "moonraker_host": net_cfg.MOONRAKER_HOST,
            "moonraker_port": net_cfg.MOONRAKER_PORT,
            "moonraker_ws_path": net_cfg.MOONRAKER_WS_PATH,
            "esp32_ip": net_cfg.ESP32_IP,
            "laptop_ip": net_cfg.LAPTOP_IP,
            "stream_port": net_cfg.STREAM_PORT,
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
    return {
        "x_min": motion_cfg.X_MIN,
        "x_max": motion_cfg.X_MAX,
        "y_min": motion_cfg.Y_MIN,
        "y_max": motion_cfg.Y_MAX,
        "z_min": motion_cfg.Z_MIN,
        "z_max": motion_cfg.Z_MAX,
        "neutral_x": motion_cfg.NEUTRAL_X,
        "neutral_y": motion_cfg.NEUTRAL_Y,
        "neutral_z": motion_cfg.NEUTRAL_Z,
        "travel_speed": motion_cfg.TRAVEL_SPEED,
        "z_speed": motion_cfg.Z_SPEED,
        "send_rate_hz": motion_cfg.SEND_RATE_HZ,
        "feedrate_multiplier": motion_cfg.FEEDRATE_MULTIPLIER,
    }


@app.post("/config/motion")
def update_motion_config(update: MotionConfigUpdate):
    """
    Update selected fields in Config/motion_config.py.
    Only fields provided in the payload are changed.
    """
    path = motion_cfg.__file__
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    changed = {}

    def apply(field_name: str, cfg_name: str, value):
        nonlocal text
        if value is None:
            return
        text = _patch_assignment_line(text, cfg_name, str(value))
        changed[field_name] = value

    apply("x_min", "X_MIN", update.x_min)
    apply("x_max", "X_MAX", update.x_max)
    apply("y_min", "Y_MIN", update.y_min)
    apply("y_max", "Y_MAX", update.y_max)
    apply("z_min", "Z_MIN", update.z_min)
    apply("z_max", "Z_MAX", update.z_max)

    apply("neutral_x", "NEUTRAL_X", update.neutral_x)
    apply("neutral_y", "NEUTRAL_Y", update.neutral_y)
    apply("neutral_z", "NEUTRAL_Z", update.neutral_z)

    apply("travel_speed", "TRAVEL_SPEED", update.travel_speed)
    apply("z_speed", "Z_SPEED", update.z_speed)

    apply("send_rate_hz", "SEND_RATE_HZ", update.send_rate_hz)
    apply("feedrate_multiplier", "FEEDRATE_MULTIPLIER", update.feedrate_multiplier)

    if changed:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    import importlib

    importlib.reload(motion_cfg)

    return {
        "updated": changed,
        "current": get_motion_config(),
    }


# Note: Core.Orchestrator starts this app in a background thread. To run the API alone:
#   ./venv/bin/uvicorn Interfaces.API.Control_Api:app --host 0.0.0.0 --port 8000

