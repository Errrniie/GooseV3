"""
Camera capture via **nvarguscamerasrc** (Argus CSI). V4L2 exposes only RG10 Bayer here;
YOLO uses **BGR** from a GStreamer **appsink**.

GStreamer pipeline (YOLO only):
  nvarguscamerasrc (NVMM) → nvvidconv → BGR → appsink

Optional **TCP** preview: separate thread listens on ``STREAM_PORT``, accepts one client,
encodes each 1280×720 BGR frame with **GStreamer** ``appsrc`` → ``nvjpegenc`` (quality 85) →
``appsink``, then sends **length-prefixed JPEG** bytes over TCP.
Toggled by ``Tools.Scripts.Start_Stream.UNIFIED_PIPELINE_INCLUDE_UDP`` and
``Config.Network_Config.LAPTOP_IP`` (name kept for config compatibility).
"""

from __future__ import annotations

import socket
import struct
import threading
import time
from typing import Any, Callable, Optional

import cv2
import numpy as np

import Config.Motion_Config as mcfg
import Config.Network_Config as net_cfg
from Tools.Scripts.Start_Stream import UNIFIED_PIPELINE_INCLUDE_UDP


class CameraThread:
    """
    GStreamer Argus → BGR appsink for YOLO; optional TCP JPEG stream on a daemon thread.
    """

    def __init__(
        self,
        sensor_id: Optional[int] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        fps: Optional[int] = None,
    ) -> None:
        self._sensor_id = int(sensor_id if sensor_id is not None else mcfg.CAMERA_ARGUS_SENSOR_ID)
        self._width = int(width if width is not None else mcfg.CAMERA_WIDTH)
        self._height = int(height if height is not None else mcfg.CAMERA_HEIGHT)
        self._fps = int(fps if fps is not None else mcfg.CAMERA_FPS)

        self._lock = threading.Lock()
        self._frame: Optional[Any] = None
        self._running = False
        self._gst_thread: Optional[threading.Thread] = None
        self._stream_thread: Optional[threading.Thread] = None
        self._stream_server_sock: Optional[socket.socket] = None
        self._main_loop = None
        self._pipeline = None
        self._Gst: Any = None
        self._appsink = None

        stream = self._wants_stream()
        print(
            f"[CAMERA] Argus sensor-id={self._sensor_id} ({self._width}x{self._height} @ {self._fps}fps)"
            f"{'; TCP JPEG preview on port ' + str(net_cfg.STREAM_PORT) if stream else ''}…"
        )

    def _wants_stream(self) -> bool:
        return bool(net_cfg.LAPTOP_IP and UNIFIED_PIPELINE_INCLUDE_UDP)

    @staticmethod
    def _tcp_jpeg_encode_nvjpeg(
        Gst: Any,
        app_src: Any,
        app_sink: Any,
        frame_bgr_720p: np.ndarray,
        pts_ns: list,
    ) -> Optional[bytes]:
        """
        One BGR 1280×720 frame: appsrc → videoconvert → I420 → nvjpegenc → appsink; JPEG bytes or None.
        ``pts_ns`` is a one-element list holding cumulative PTS in ns (mutated).
        """
        if frame_bgr_720p.shape != (720, 1280, 3):
            return None
        if frame_bgr_720p.dtype != np.uint8 or not frame_bgr_720p.flags["C_CONTIGUOUS"]:
            frame_bgr_720p = np.ascontiguousarray(frame_bgr_720p, dtype=np.uint8)

        n = int(frame_bgr_720p.nbytes)
        buf = Gst.Buffer.new_allocate(None, n, None)
        ok, mapinfo = buf.map(Gst.MapFlags.WRITE)
        if not ok:
            return None
        try:
            mapinfo.data[:] = frame_bgr_720p.tobytes()
        finally:
            buf.unmap(mapinfo)

        period = Gst.SECOND // max(1, int(mcfg.CAMERA_FPS))
        buf.pts = pts_ns[0]
        buf.duration = period
        pts_ns[0] += period

        ret = app_src.emit("push-buffer", buf)
        if ret != Gst.FlowReturn.OK and ret != Gst.FlowReturn.FLUSHING:
            return None

        sample = app_sink.emit("try-pull-sample", Gst.SECOND // 2)
        if sample is None:
            return None
        jbuf = sample.get_buffer()
        if jbuf is None:
            return None
        ok2, mi = jbuf.map(Gst.MapFlags.READ)
        if not ok2:
            return None
        try:
            return bytes(mi.data)
        finally:
            jbuf.unmap(mi)

    def _build_tcp_jpeg_pipeline(self, Gst: Any) -> tuple[Any, Any, Any]:
        """appsrc → BGR caps → videoconvert → I420 capsfilter → nvjpegenc → appsink (JPEG bytes)."""
        fps = int(mcfg.CAMERA_FPS)
        pl_str = (
            f"appsrc name=src is-live=true format=time ! "
            f"video/x-raw,format=BGR,width=1280,height=720,framerate={fps}/1 ! "
            f"videoconvert ! "
            f"video/x-raw,format=I420 ! "
            f"nvjpegenc quality=85 ! "
            f"appsink name=sink emit-signals=false max-buffers=1 drop=true sync=false"
        )
        pipeline = Gst.parse_launch(pl_str)
        app_src = pipeline.get_by_name("src")
        app_sink = pipeline.get_by_name("sink")
        if app_src is None or app_sink is None:
            raise RuntimeError("TCP JPEG pipeline: src/sink not found")
        return pipeline, app_src, app_sink

    def _build_pipeline_string(self) -> str:
        """Argus → BGR → appsink only (no tee / no RTP/UDP in GStreamer)."""
        w, h, f = self._width, self._height, self._fps
        sid = self._sensor_id
        return (
            f"nvarguscamerasrc sensor-id={sid} ! "
            f"video/x-raw(memory:NVMM),width={w},height={h},framerate={f}/1 ! "
            f"nvvidconv flip-method=0 ! "
            f"video/x-raw,width={w},height={h},format=BGRx ! "
            f"videoconvert ! video/x-raw,format=BGR ! "
            "queue max-size-buffers=2 leaky=downstream ! "
            "appsink name=sink emit-signals=true max-buffers=1 drop=true sync=false "
        )

    def _start_stream_sender(self, get_frame_fn: Callable[[], Optional[Any]]) -> None:
        """Listen on STREAM_PORT; send length-prefixed JPEG frames from ``get_frame_fn``."""
        if not self._wants_stream():
            return

        def sender_loop() -> None:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._stream_server_sock = server
            try:
                server.bind(("0.0.0.0", net_cfg.STREAM_PORT))
                server.listen(1)
                while self._running:
                    print(
                        f"[STREAM] Waiting for laptop on port {net_cfg.STREAM_PORT} (TCP/JPEG)..."
                    )
                    try:
                        conn, addr = server.accept()
                    except OSError:
                        return
                    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    conn.setblocking(False)
                    print(f"[STREAM] Laptop connected: {addr}")

                    import gi

                    gi.require_version("Gst", "1.0")
                    from gi.repository import Gst

                    Gst.init(None)
                    jpeg_pipe: Any = None
                    app_src = None
                    app_sink = None
                    try:
                        jpeg_pipe, app_src, app_sink = self._build_tcp_jpeg_pipeline(Gst)
                        ret = jpeg_pipe.set_state(Gst.State.PLAYING)
                        if ret == Gst.StateChangeReturn.FAILURE:
                            print("[STREAM] TCP nvjpegenc pipeline failed to PLAYING")
                            jpeg_pipe.set_state(Gst.State.NULL)
                            jpeg_pipe = None
                            app_src = app_sink = None
                        else:
                            jpeg_pipe.get_state(Gst.SECOND)
                    except Exception as e:
                        print(f"[STREAM] TCP JPEG pipeline build failed ({e}); no preview.")
                        jpeg_pipe = None
                        app_src = app_sink = None

                    try:
                        pts_ns = [0]
                        while self._running and jpeg_pipe is not None:
                            frame = get_frame_fn()
                            if frame is None:
                                time.sleep(0.001)
                                continue

                            small = cv2.resize(frame, (1280, 720))
                            data = self._tcp_jpeg_encode_nvjpeg(
                                Gst, app_src, app_sink, small, pts_ns
                            )
                            if not data:
                                continue

                            try:
                                conn.sendall(struct.pack(">I", len(data)) + data)
                            except BlockingIOError:
                                pass
                            except (BrokenPipeError, ConnectionResetError, OSError):
                                print("[STREAM] Laptop disconnected, waiting for reconnect...")
                                break
                    finally:
                        if jpeg_pipe is not None:
                            try:
                                jpeg_pipe.set_state(Gst.State.NULL)
                                jpeg_pipe.get_state(Gst.CLOCK_TIME_NONE)
                            except Exception:
                                pass
                        try:
                            conn.close()
                        except Exception:
                            pass
            finally:
                try:
                    server.close()
                except Exception:
                    pass
                if self._stream_server_sock is server:
                    self._stream_server_sock = None

        self._stream_thread = threading.Thread(target=sender_loop, name="tcp-jpeg-stream", daemon=True)
        self._stream_thread.start()

    def _on_new_sample(self, sink) -> Any:
        Gst = self._Gst
        sample = sink.emit("pull-sample")
        if sample is None:
            return Gst.FlowReturn.ERROR
        buf = sample.get_buffer()
        caps = sample.get_caps()
        if caps is None or caps.get_size() < 1:
            return Gst.FlowReturn.ERROR
        struct = caps.get_structure(0)
        width = struct.get_value("width")
        height = struct.get_value("height")
        success, map_info = buf.map(Gst.MapFlags.READ)
        if not success:
            return Gst.FlowReturn.ERROR
        try:
            frame = np.frombuffer(map_info.data, dtype=np.uint8).reshape((height, width, 3)).copy()
        finally:
            buf.unmap(map_info)
        with self._lock:
            self._frame = frame
        return Gst.FlowReturn.OK

    def _run_main_loop(self) -> None:
        from gi.repository import GLib

        self._main_loop = GLib.MainLoop()
        ret = self._pipeline.set_state(self._Gst.State.PLAYING)
        if ret == self._Gst.StateChangeReturn.FAILURE:
            print("[CAMERA] Pipeline failed to reach PLAYING")
        self._main_loop.run()

    def start(self) -> None:
        if self._running:
            return
        self._running = True

        import gi

        gi.require_version("Gst", "1.0")
        from gi.repository import Gst, GLib  # noqa: F401

        Gst.init(None)
        self._Gst = Gst

        pipeline_str = self._build_pipeline_string()
        try:
            self._pipeline = Gst.parse_launch(pipeline_str)
        except Exception as e:
            self._running = False
            raise RuntimeError(f"GStreamer Argus pipeline parse failed: {e}") from e

        self._appsink = self._pipeline.get_by_name("sink")
        if self._appsink is None:
            self._running = False
            self._pipeline = None
            self._Gst = None
            raise RuntimeError("appsink name=sink not found in Argus pipeline")

        self._appsink.connect("new-sample", self._on_new_sample)

        self._gst_thread = threading.Thread(target=self._run_main_loop, name="gst-argus", daemon=True)
        self._gst_thread.start()
        time.sleep(0.2)

        self._start_stream_sender(self.get_frame)

        print("[CAMERA] Capture running (Argus → BGR appsink → YOLO).")
        if self._wants_stream():
            print(
                f"[CAMERA] TCP JPEG preview: listen 0.0.0.0:{net_cfg.STREAM_PORT} "
                f"(connect from laptop; LAPTOP_IP={net_cfg.LAPTOP_IP} is the flag, not the bind)."
            )
        elif net_cfg.LAPTOP_IP and not UNIFIED_PIPELINE_INCLUDE_UDP:
            print(
                "[CAMERA] LAPTOP_IP set but stream disabled "
                "(Start_Stream.UNIFIED_PIPELINE_INCLUDE_UDP=False)."
            )

    def get_frame(self):
        with self._lock:
            return self._frame

    def stop(self) -> None:
        self._running = False

        if self._stream_server_sock is not None:
            try:
                self._stream_server_sock.close()
            except Exception:
                pass
            self._stream_server_sock = None

        if self._stream_thread and self._stream_thread.is_alive():
            self._stream_thread.join(timeout=3.0)
        self._stream_thread = None

        if self._main_loop:
            try:
                self._main_loop.quit()
            except Exception:
                pass

        if self._gst_thread and self._gst_thread.is_alive():
            self._gst_thread.join(timeout=8.0)
        self._gst_thread = None
        self._main_loop = None

        if self._pipeline is not None and self._Gst is not None:
            try:
                self._pipeline.set_state(self._Gst.State.NULL)
                self._pipeline.get_state(self._Gst.CLOCK_TIME_NONE)
            except Exception:
                pass
            self._pipeline = None
        self._Gst = None
        self._appsink = None

        print("[CAMERA] Argus capture stopped.")
