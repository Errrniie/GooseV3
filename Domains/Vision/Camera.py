"""
CSI camera: single GStreamer graph (Gst.parse_launch) — tee → appsink (BGR for YOLO) + optional UDP.

Aligned with Camera_test.py / Tools/Scripts/Start_Stream.build_unified_vision_pipeline_string.
Falls back to V4L2 + OpenCV if Gst is unavailable or parse fails.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Optional

import cv2
import numpy as np

import Config.Network_Config as net_cfg
from Tools.Scripts.Start_Stream import build_unified_vision_pipeline_string


class CameraThread:
    def __init__(self, index: int = 0, width: int = 1920, height: int = 1080, fps: int = 30):
        self._index = index
        self._width = width
        self._height = height
        self._fps = fps

        self._lock = threading.Lock()
        self._frame: Optional[Any] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._main_loop = None
        self._pipeline: Any = None
        self._cap = None
        self._v4l2_fallback = False
        self._Gst: Any = None

        lip = net_cfg.LAPTOP_IP if net_cfg.LAPTOP_IP else None
        pipeline_str = build_unified_vision_pipeline_string(
            width,
            height,
            fps,
            laptop_ip=lip,
            udp_port=net_cfg.STREAM_PORT,
        )

        print("[CAMERA] Opening unified GStreamer pipeline (Gst.parse_launch + tee + appsink)...")
        if lip:
            print(f"[CAMERA] UDP branch in same pipeline → {lip}:{net_cfg.STREAM_PORT}")

        try:
            import gi

            gi.require_version("Gst", "1.0")
            from gi.repository import Gst, GLib  # noqa: F401

            Gst.init(None)
            self._pipeline = Gst.parse_launch(pipeline_str)
            appsink = self._pipeline.get_by_name("sink")
            if appsink is None:
                raise RuntimeError("appsink name=sink not found in pipeline")
            appsink.connect("new-sample", self._on_new_sample)
            self._Gst = Gst
        except Exception as e:
            if self._pipeline is not None:
                try:
                    import gi

                    gi.require_version("Gst", "1.0")
                    from gi.repository import Gst as GstCleanup

                    self._pipeline.set_state(GstCleanup.State.NULL)
                except Exception:
                    pass
                self._pipeline = None
            self._Gst = None
            print(f"[CAMERA] GStreamer pipeline failed ({e}), falling back to V4L2...")
            if lip:
                print(
                    "[CAMERA] LAPTOP_IP is set but V4L2 cannot share Argus UDP in-process; "
                    "UDP auto-stream disabled. Use Modes/Test_Mode or Tools/Scripts/start_stream.py "
                    "for laptop video."
                )
            self._setup_v4l2_fallback()

    def _setup_v4l2_fallback(self) -> None:
        self._v4l2_fallback = True
        self._cap = cv2.VideoCapture(self._index, cv2.CAP_V4L2)
        if not self._cap.isOpened():
            raise RuntimeError("Failed to open camera with V4L2 fallback")
        self._cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        self._cap.set(cv2.CAP_PROP_FPS, self._fps)
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        print("[CAMERA] Camera opened via V4L2 fallback")

    def _on_new_sample(self, sink) -> Any:
        Gst = self._Gst
        sample = sink.emit("pull-sample")
        if sample is None:
            return Gst.FlowReturn.ERROR
        buf = sample.get_buffer()
        caps = sample.get_caps()
        width = caps.get_structure(0).get_value("width")
        height = caps.get_structure(0).get_value("height")
        success, map_info = buf.map(Gst.MapFlags.READ)
        if not success:
            return Gst.FlowReturn.ERROR
        frame = np.frombuffer(map_info.data, dtype=np.uint8).reshape((height, width, 3)).copy()
        buf.unmap(map_info)
        with self._lock:
            self._frame = frame
        return Gst.FlowReturn.OK

    def _run_gst_main_loop(self) -> None:
        from gi.repository import GLib

        self._main_loop = GLib.MainLoop()
        ret = self._pipeline.set_state(self._Gst.State.PLAYING)
        if ret == self._Gst.StateChangeReturn.FAILURE:
            print("[CAMERA] Pipeline failed to reach PLAYING")
        self._main_loop.run()

    def _loop_v4l2(self) -> None:
        while self._running:
            ret, frame = self._cap.read()
            if not ret:
                time.sleep(0.005)
                continue
            with self._lock:
                self._frame = frame

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        if self._v4l2_fallback:
            self._thread = threading.Thread(target=self._loop_v4l2, daemon=True)
        else:
            self._thread = threading.Thread(target=self._run_gst_main_loop, daemon=True)
        self._thread.start()
        if not self._v4l2_fallback and net_cfg.LAPTOP_IP:
            print("[CAMERA] Capture running; H.264 UDP uses the same pipeline (no extra gst-launch).")
        elif not net_cfg.LAPTOP_IP:
            print("[CAMERA] LAPTOP_IP=None — capture only, no UDP branch.")

    def get_frame(self):
        with self._lock:
            return self._frame

    def stop(self) -> None:
        self._running = False
        if self._v4l2_fallback:
            if self._thread:
                self._thread.join(timeout=2.0)
            if self._cap:
                self._cap.release()
                self._cap = None
            return

        if self._main_loop:
            self._main_loop.quit()
        if self._thread:
            self._thread.join(timeout=3.0)
        if self._pipeline:
            self._pipeline.set_state(self._Gst.State.NULL)
            self._pipeline = None
