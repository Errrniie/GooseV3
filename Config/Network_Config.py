"""
Network configuration for Goose Deterrence System.

All IPs and network endpoints that can change from location to location
should be defined here so they can be updated in one place.
"""

# =============================================================================
# Moonraker (Klipper API) connection
# =============================================================================

# Printer / Moonraker host IP (update this when you move networks)
MOONRAKER_HOST = "192.168.8.146"

# Moonraker HTTP port (usually 7125)
MOONRAKER_PORT = 7125

# WebSocket path used by Moonraker
MOONRAKER_WS_PATH = "/websocket"

# Full WebSocket URL used by all MoonrakerWSClient instances
MOONRAKER_WS_URL = f"ws://{MOONRAKER_HOST}:{MOONRAKER_PORT}{MOONRAKER_WS_PATH}"


# =============================================================================
# ESP32 Laser Controller
# =============================================================================

# ESP32 laser controller IP (update this when the ESP32 changes networks)
ESP32_IP = "192.168.8.186"

# Convenience: base HTTP URL for ESP32
ESP32_BASE_URL = f"http://{ESP32_IP}"


# =============================================================================
# Video Streaming (H.264 UDP stream to laptop)
# =============================================================================

# Laptop IP for video streaming (set to None to disable automatic streaming)
# If set, the camera will automatically start streaming whenever it's initialized
LAPTOP_IP = "192.168.8.154"

# UDP port for video stream
STREAM_PORT = 5000


# =============================================================================
# Control API (FastAPI) — started by Core.Orchestrator before mode selection
# =============================================================================

CONTROL_API_HOST = "0.0.0.0"
CONTROL_API_PORT = 8000

