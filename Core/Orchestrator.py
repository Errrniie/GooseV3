"""
Orchestrator.py - Starts the control API, waits for a mode from ModeManager, then runs that pipeline.
"""

from pathlib import Path
import sys

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Config.Manager import init_config

init_config()

import atexit
import signal
import threading

import uvicorn

import Config.Network_Config as net_cfg
from Interfaces.API.Control_Api import app as control_app
from Core.ModeManager import wait_for_pipeline
from Networking.Local_IP import get_ethernet_ipv4


def _cleanup_video_streams() -> None:
    """Stop vision (Argus/GStreamer + optional TCP JPEG thread + legacy hooks)."""
    try:
        from Domains.Vision.Interface import stop_vision

        stop_vision()
    except Exception:
        pass
    try:
        from Tools.Scripts.Start_Stream import stop_all_streams

        stop_all_streams()
    except Exception:
        pass


_shutdown_hooks_installed = False


def _install_shutdown_hooks() -> None:
    global _shutdown_hooks_installed
    if _shutdown_hooks_installed:
        return
    _shutdown_hooks_installed = True
    atexit.register(_cleanup_video_streams)

    def _on_signal(_signum, _frame) -> None:
        _cleanup_video_streams()
        sys.exit(0)

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)


def _start_control_api() -> None:
    host = net_cfg.CONTROL_API_HOST
    port = net_cfg.CONTROL_API_PORT
    uvicorn.run(
        control_app,
        host=host,
        port=port,
        log_level="info",
    )


def run() -> None:
    _install_shutdown_hooks()
    api_thread = threading.Thread(
        target=_start_control_api,
        name="control-api",
        daemon=True,
    )
    api_thread.start()
    jetson_ip = get_ethernet_ipv4()
    if jetson_ip:
        print(f"[ORCH] This device Ethernet IPv4: {jetson_ip}")
    else:
        print(
            "[ORCH] Could not determine Ethernet IPv4 "
            "(cable unplugged or no non-Wi-Fi interface with an address)"
        )
    print(
        f"[ORCH] Control API on port {net_cfg.CONTROL_API_PORT} "
        f"(POST /system/handshake, POST /system/mode {{\"mode\": \"normal\"|\"test\"|\"yolo_test\"}})"
    )

    print("[ORCH] Waiting for mode selection…")
    pipeline = wait_for_pipeline()
    print("[ORCH] Mode selected; starting pipeline.")
    pipeline()
