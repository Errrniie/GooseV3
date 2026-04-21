"""Test / dev pipeline: same vision stack as YOLO modes — Argus + optional TCP JPEG preview."""

import time

from Config.Manager import init_config
import Config.Network_Config as net_cfg
from Domains.Vision.Interface import start_vision, stop_vision


def run() -> None:
    """
    Argus capture (BGR appsink) with optional TCP JPEG sender thread,
    same single path as ``yolo_test`` / ``normal``. One GStreamer pipeline, no extra process.
    """
    init_config()

    if net_cfg.LAPTOP_IP is None:
        print(
            "[MODE] Test_Mode: LAPTOP_IP is None in Config/Network_Config.py — "
            "set it to your laptop IP to enable TCP preview (flag)."
        )
        print("[MODE] Test_Mode: starting vision anyway (capture + idle workers).")

    print(
        f"[MODE] Test_Mode: Argus + TCP JPEG on port {net_cfg.STREAM_PORT} "
        f"(if LAPTOP_IP set and streaming enabled)"
    )
    start_vision()
    print("[MODE] Test_Mode: running. Ctrl+C to stop.")

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\n[MODE] Test_Mode: stopping…")
    finally:
        stop_vision()
