#!/usr/bin/env python3
"""
Legacy demo script — production capture lives in ``Domains/Vision/Camera.py``.

Use the orchestrator (``yolo_test`` / ``test``) or ``Tools/Scripts/Start_Stream.py`` for
Argus + YOLO + optional TCP JPEG preview.
"""

print(
    "Camera_test.py: use Interfaces/CLI/Main.py + POST /system/mode "
        '{"mode": "yolo_test"} or `python3 Tools/Scripts/Start_Stream.py <laptop_ip>`'
)
