"""
Video streaming helpers (Jetson → laptop preview).

**Capture is in** ``Domains/Vision/Camera.py``: **nvarguscamerasrc** (Argus) → BGR
``appsink`` for YOLO. Optional preview uses a **TCP** thread (length-prefixed JPEG on
``STREAM_PORT``), not GStreamer RTP/UDP.

``UNIFIED_PIPELINE_INCLUDE_UDP``: when True and ``LAPTOP_IP`` is set, ``CameraThread``
starts the TCP JPEG sender (name kept for config compatibility).

CLI ``python3 Start_Stream.py <laptop_ip>`` starts the same vision stack as ``yolo_test``
(stream + YOLO). For preview-only, use orchestrator **test** mode or rely on this script.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

# Allow `python Tools/Scripts/Start_Stream.py` — project root must be on sys.path for Config.*
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Unified vision (CameraThread): when False, Argus → appsink only — no TCP JPEG sender thread.
UNIFIED_PIPELINE_INCLUDE_UDP = True

_stream_lock = threading.Lock()
_stream_processes: list = []


def stop_all_streams() -> None:
    """Legacy no-op: standalone gst-launch subprocesses are no longer used for the camera."""
    with _stream_lock:
        _stream_processes.clear()


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python3 Start_Stream.py <laptop_ip>")
        print(
            "Uses Argus nvarguscamerasrc + BGR appsink + optional TCP JPEG (same as vision modes). "
            "Ensure Config/ and runtime config are set (copy project to PYTHONPATH)."
        )
        sys.exit(1)

    from Config.Manager import init_config
    import Config.Network_Config as net_cfg
    from Domains.Vision.Interface import start_vision, stop_vision

    init_config()
    net_cfg.LAPTOP_IP = sys.argv[1]
    print(f"[STREAM] connect laptop to Jetson TCP port {net_cfg.STREAM_PORT} (JPEG); LAPTOP_IP={net_cfg.LAPTOP_IP}")
    start_vision()
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\n[STREAM] stopping…")
    finally:
        stop_vision()


if __name__ == "__main__":
    main()
