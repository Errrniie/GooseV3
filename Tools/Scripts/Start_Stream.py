"""
start_stream.py - Jetson → Laptop low-latency H.264 UDP video stream.

Usage (on Jetson):
    python3 start_stream.py <LAPTOP_IP>

Also exposes:
- build_unified_vision_pipeline_string — Gst.parse_launch graph (tee + appsink + optional UDP),
  aligned with Camera_test.py / production Domains/Vision/Camera.py.
- build_standalone_udp_pipeline_string — stream-only gst-launch (Test_Mode, CLI).

Normal-mode vision uses Gst + appsink (no OpenCV CAP_GSTREAMER); no second nvarguscamerasrc process.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from typing import Optional

import Config.Motion_Config as motion_cfg
import Config.Network_Config as network_config

# All background gst-launch processes; stopped by stop_all_streams() on shutdown.
_stream_lock = threading.Lock()
_stream_processes: list[subprocess.Popen] = []


def build_unified_vision_pipeline_string(
    width: int,
    height: int,
    fps: int,
    laptop_ip: Optional[str] = None,
    udp_port: Optional[int] = None,
) -> str:
    """
    Single Argus capture: tee splits NVMM to (1) BGR appsink for YOLO and (2) optional H.264/UDP.
    Matches Camera_test.py layout. Use with Gst.parse_launch(...); appsink name is ``sink``.
    """
    if udp_port is None:
        udp_port = network_config.STREAM_PORT

    base = (
        f"nvarguscamerasrc ! "
        f"video/x-raw(memory:NVMM),width={width},height={height},framerate={fps}/1 ! "
        f"tee name=t "
    )
    cpu_branch = (
        "t. ! queue leaky=2 max-size-buffers=2 ! "
        "nvvidconv ! video/x-raw,format=BGRx ! "
        "videoconvert ! video/x-raw,format=BGR ! "
        "appsink name=sink emit-signals=true max-buffers=1 drop=true sync=false "
    )
    if not laptop_ip:
        return base + cpu_branch

    gpu_branch = (
        "t. ! queue leaky=2 max-size-buffers=2 ! "
        "nvvidconv ! video/x-raw,format=I420 ! "
        "x264enc tune=zerolatency speed-preset=ultrafast bitrate=3000 key-int-max=15 ! "
        "rtph264pay config-interval=1 pt=96 ! "
        f"udpsink host={laptop_ip} port={udp_port} sync=false "
    )
    return base + cpu_branch + gpu_branch


def build_standalone_udp_pipeline_string(
    laptop_ip: str, port: Optional[int] = None
) -> str:
    """
    Stream-only: one nvarguscamerasrc → I420 → x264 → UDP (same encoder params as unified UDP branch).
    """
    if port is None:
        port = network_config.STREAM_PORT
    w, h = motion_cfg.CAMERA_WIDTH, motion_cfg.CAMERA_HEIGHT
    return (
        "nvarguscamerasrc ! "
        f"video/x-raw(memory:NVMM),width={w},height={h},framerate=30/1 ! "
        "nvvidconv ! video/x-raw,format=I420 ! "
        "x264enc tune=zerolatency speed-preset=ultrafast bitrate=3000 key-int-max=15 ! "
        "rtph264pay config-interval=1 pt=96 ! "
        f"udpsink host={laptop_ip} port={port} sync=false"
    )


def build_gst_cmd(laptop_ip: str, port: Optional[int] = None) -> list:
    """
    Build the gst-launch-1.0 argv list for a standalone UDP H.264 stream.
    """
    pipeline = build_standalone_udp_pipeline_string(laptop_ip, port)
    return ["gst-launch-1.0"] + pipeline.split()


def run_stream_blocking(laptop_ip: str, port: Optional[int] = None) -> None:
    cmd = build_gst_cmd(laptop_ip, port)
    print(f"[STREAM] Running (blocking): {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def start_stream_background(laptop_ip: str, port: Optional[int] = None) -> subprocess.Popen:
    cmd = build_gst_cmd(laptop_ip, port)
    print(f"[STREAM] Starting background stream: {' '.join(cmd)}")
    proc = subprocess.Popen(cmd)
    with _stream_lock:
        _stream_processes.append(proc)
    return proc


def unregister_stream_process(proc: subprocess.Popen) -> None:
    with _stream_lock:
        try:
            _stream_processes.remove(proc)
        except ValueError:
            pass


def stop_all_streams() -> None:
    """Terminate every registered UDP stream (Test_Mode / CLI gst-launch processes)."""
    with _stream_lock:
        procs = list(_stream_processes)
        _stream_processes.clear()
    for proc in procs:
        if proc.poll() is not None:
            continue
        try:
            proc.terminate()
            proc.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=2.0)
            except Exception:
                pass
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python3 start_stream.py <laptop_ip>")
        sys.exit(1)

    laptop_ip = sys.argv[1]
    try:
        run_stream_blocking(laptop_ip)
    except subprocess.CalledProcessError as e:
        print(f"[STREAM] gst-launch-1.0 exited with error: {e.returncode}")


if __name__ == "__main__":
    main()
