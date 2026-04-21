"""
Yolo Test — camera + YOLO + Control API only (no USB CDC motors / laser).

Starts the same vision stack as Normal mode (`start_vision`): Argus
(``nvarguscamerasrc``) → BGR **appsink** → YOLO; when ``LAPTOP_IP`` is set and
``UNIFIED_PIPELINE_INCLUDE_UDP`` is True, a **TCP** thread sends **JPEG** preview on ``STREAM_PORT``.
Use ``Tools/Scripts/Start_Stream.py`` for CLI-only startup of this stack.

The Control API is already running in the orchestrator process before this mode
runs; use GET /vision/detection, GET/POST /config/vision, etc.

Select via POST /system/mode with {"mode": "yolo_test"} (see GET /system/modes).
"""

from __future__ import annotations

import atexit
import time

from Config.Manager import init_config
import Config.Network_Config as net_cfg
from Domains.Vision.Interface import start_vision, stop_vision
from Tools.Scripts.Start_Stream import UNIFIED_PIPELINE_INCLUDE_UDP


def _stop_vision_on_process_exit() -> None:
    """Last-chance vision shutdown if the process exits without returning from run()."""
    try:
        stop_vision()
    except Exception:
        pass


_yolo_atexit_registered = False


def run() -> None:
    global _yolo_atexit_registered
    init_config()
    # Belt-and-suspenders with Orchestrator atexit/signals: ensure vision stops on any exit.
    if not _yolo_atexit_registered:
        atexit.register(_stop_vision_on_process_exit)
        _yolo_atexit_registered = True

    print("[MODE] YoloTest: no motors — camera + YOLO + API only.")
    if net_cfg.LAPTOP_IP and UNIFIED_PIPELINE_INCLUDE_UDP:
        print(
            f"[MODE] YoloTest: TCP JPEG preview — connect to Jetson:{net_cfg.STREAM_PORT} "
            f"(flag LAPTOP_IP={net_cfg.LAPTOP_IP})."
        )
    elif net_cfg.LAPTOP_IP:
        print(
            f"[MODE] YoloTest: LAPTOP_IP {net_cfg.LAPTOP_IP} — "
            "TCP preview disabled (UNIFIED_PIPELINE_INCLUDE_UDP=False) or use Test_Mode/start_stream.py."
        )
    else:
        print(
            "[MODE] YoloTest: LAPTOP_IP unset — capture + YOLO only; "
            "POST /system/handshake to save peer IP."
        )

    start_vision()
    print("[MODE] YoloTest: vision running. Ctrl+C to stop.")

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\n[MODE] YoloTest: interrupt received…")
    finally:
        try:
            stop_vision()
        except Exception as e:
            print(f"[MODE] YoloTest: vision shutdown warning: {e}")
        print("[MODE] YoloTest: stopped.")
