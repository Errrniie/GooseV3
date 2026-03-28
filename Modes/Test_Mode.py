"""Test / development pipeline: broadcast camera H.264 stream to the laptop."""

import subprocess
import time

import Config.Network_Config as net_cfg
from Tools.Scripts.Start_Stream import (
    start_stream_background,
    unregister_stream_process,
)


def run() -> None:
    """
    Start the Jetson → laptop UDP H.264 stream (gst-launch) and run until stopped.
    Uses LAPTOP_IP and STREAM_PORT from Config/Network_Config.py.
    """
    if net_cfg.LAPTOP_IP is None:
        print(
            "[MODE] Test_Mode: LAPTOP_IP is None in Config/Network_Config.py — "
            "set it to your laptop IP to enable streaming."
        )
        return

    print(
        f"[MODE] Test_Mode: broadcasting to {net_cfg.LAPTOP_IP}:{net_cfg.STREAM_PORT} "
        "(receive on laptop with gst-launch / your player)"
    )
    proc = start_stream_background(net_cfg.LAPTOP_IP, net_cfg.STREAM_PORT)
    print("[MODE] Test_Mode: stream running. Ctrl+C to stop.")

    try:
        while proc.poll() is None:
            time.sleep(0.5)
        print(f"[MODE] Test_Mode: stream process exited ({proc.returncode})")
    except KeyboardInterrupt:
        print("\n[MODE] Test_Mode: stopping stream…")
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        try:
            unregister_stream_process(proc)
        except Exception:
            pass
