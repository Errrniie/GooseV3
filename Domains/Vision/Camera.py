import cv2
import threading
import time
import subprocess
from typing import Optional
import Config.Network_Config as net_cfg
from Tools.Scripts.Start_Stream import (
    start_stream_background,
    unregister_stream_process,
)

class CameraThread:
    def __init__(self, index=0, width=1920, height=1080, fps=30):
        """
        Initialize camera using nvarguscamerasrc via GStreamer (same as streaming).
        This ensures consistency - both frame capture and streaming use the same camera source.
        
        Falls back to V4L2 if GStreamer pipeline fails.
        """
        # Try GStreamer pipeline with nvarguscamerasrc first (same as streaming)
        # This ensures frame capture and streaming use the same camera source
        pipeline = (
            f"nvarguscamerasrc ! "
            f"video/x-raw(memory:NVMM),width={width},height={height},framerate={fps}/1 ! "
            f"nvvidconv ! video/x-raw,format=BGRx ! "
            f"videoconvert ! video/x-raw,format=BGR ! "
            f"appsink"
        )
        
        print(f"[CAMERA] Attempting to open camera with nvarguscamerasrc (GStreamer)...")
        self.cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
        
        if not self.cap.isOpened():
            print(f"[CAMERA] GStreamer pipeline failed, falling back to V4L2...")
            # Fallback to V4L2 (for non-Jetson systems or if GStreamer fails)
            self.cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
            if not self.cap.isOpened():
                raise RuntimeError(f"Failed to open camera with both GStreamer and V4L2")
            
            # Configure V4L2 camera
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            self.cap.set(cv2.CAP_PROP_FPS, fps)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 0)
            print(f"[CAMERA] Camera opened via V4L2 fallback")
        else:
            print(f"[CAMERA] Camera opened via nvarguscamerasrc (GStreamer) - matches streaming method")

        self._lock = threading.Lock()
        self._frame = None
        self._running = False
        self._thread = None
        self._stream_process: Optional[subprocess.Popen] = None

    def start(self):
        """Start camera capture and automatically start streaming if laptop IP is configured."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True
        )
        self._thread.start()
        
        # Automatically start video streaming if laptop IP is configured
        # Uses same nvarguscamerasrc source as frame capture for consistency
        if net_cfg.LAPTOP_IP is not None:
            try:
                print(f"[CAMERA] Starting automatic video stream to {net_cfg.LAPTOP_IP}:{net_cfg.STREAM_PORT}")
                self._stream_process = start_stream_background(
                    net_cfg.LAPTOP_IP, net_cfg.STREAM_PORT
                )
                print("[CAMERA] Video stream started automatically (using same nvarguscamerasrc as frame capture)")
            except Exception as e:
                print(f"[CAMERA] Warning: Failed to start automatic video stream: {e}")
                self._stream_process = None
        else:
            print("[CAMERA] No laptop IP configured (LAPTOP_IP=None) - video streaming disabled")

    def _loop(self):
        while self._running:
            ret, frame = self.cap.read()
            if not ret:
                time.sleep(0.005)
                continue
            with self._lock:
                self._frame = frame

    def get_frame(self):
        with self._lock:
            return self._frame

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
        
        # Stop video stream if it's running
        if self._stream_process is not None:
            proc = self._stream_process
            self._stream_process = None
            try:
                print("[CAMERA] Stopping video stream...")
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=3.0)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=2.0)
                unregister_stream_process(proc)
                print("[CAMERA] Video stream stopped")
            except Exception as e:
                print(f"[CAMERA] Warning: Error stopping video stream: {e}")
                try:
                    unregister_stream_process(proc)
                except Exception:
                    pass
        
        self.cap.release()
