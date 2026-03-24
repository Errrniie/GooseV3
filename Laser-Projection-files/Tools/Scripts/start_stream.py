"""
start_stream.py - Jetson → Laptop low-latency H.264 UDP video stream.

Usage (on Jetson):
    python3 start_stream.py <LAPTOP_IP>

Then on the laptop, receive with something like:
    gst-launch-1.0 udpsrc port=5000 caps="application/x-rtp, media=video, encoding-name=H264, payload=96" \
        ! rtph264depay ! avdec_h264 ! videoconvert ! autovideosink

This module also exposes helpers so other scripts (like Main_basic_test)
can start the same stream programmatically.
"""

import sys
import subprocess
from Config import network_config


def build_gst_cmd(laptop_ip: str, port: int = None) -> list:
    """
    Build the gst-launch-1.0 command line for the UDP H.264 stream.
    Uses STREAM_PORT from network_config if port is not specified.
    """
    if port is None:
        port = network_config.STREAM_PORT
    
    pipeline = (
        "nvarguscamerasrc ! "
        "video/x-raw(memory:NVMM),width=3840,height=2160,framerate=30/1 ! "
        "nvvidconv ! video/x-raw,format=BGRx ! "
        "videoconvert ! "
        "x264enc tune=zerolatency speed-preset=fast bitrate=25000 key-int-max=15 ! "
        "rtph264pay config-interval=1 pt=96 ! "
        f"udpsink host={laptop_ip} port={port} sync=false"
    )
    return ["gst-launch-1.0"] + pipeline.split()


def run_stream_blocking(laptop_ip: str, port: int = None) -> None:
    """
    Start the video stream and block until gst-launch exits.
    Equivalent to running the command by hand.
    """
    cmd = build_gst_cmd(laptop_ip, port)
    print(f"[STREAM] Running (blocking): {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def start_stream_background(laptop_ip: str, port: int = None) -> subprocess.Popen:
    """
    Start the video stream in the background.
    Returns a Popen handle so the caller can manage the process.
    Uses STREAM_PORT from network_config if port is not specified.
    """
    cmd = build_gst_cmd(laptop_ip, port)
    print(f"[STREAM] Starting background stream: {' '.join(cmd)}")
    proc = subprocess.Popen(cmd)
    return proc


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
