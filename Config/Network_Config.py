"""
Network configuration for Goose Deterrence System.

All IPs and network endpoints that can change from location to location
should be defined here so they can be updated in one place.
"""

# =============================================================================
# ESP32 — USB CDC (vision / motor hints to firmware; not the laser HTTP API)
# =============================================================================

# Serial device when ESP enumerates as USB CDC (Jetson/Linux)
ESP_CDC_PORT = "/dev/ttyACM0"
ESP_CDC_BAUD = 115200


# =============================================================================
# ESP32 Laser Controller (HTTP — separate from CDC)
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

