#!/usr/bin/env python3
"""
Camera test script - streams H.264 UDP video to laptop (same as start_stream.py).
Usage: python3 test_camera.py [LAPTOP_IP]
  If LAPTOP_IP is not provided, uses LAPTOP_IP from Config/network_config.py
Press Ctrl+C to quit.
"""

import sys
import subprocess
import os

# Add current directory to path to import Config
sys.path.insert(0, os.path.dirname(__file__))
from Config import network_config

# Global stream process
_stream_proc = None


def build_gst_cmd(laptop_ip: str, port: int = 5000) -> list:
    """
    Build the gst-launch-1.0 command line for UDP H.264 stream.
    Same as start_stream.py - uses nvarguscamerasrc for Jetson optimization.
    """
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


def start_stream(laptop_ip: str, port: int = 5000) -> subprocess.Popen:
    """
    Start the UDP H.264 video stream to laptop (same as start_stream.py).
    Returns a Popen handle so the caller can manage the process.
    """
    cmd = build_gst_cmd(laptop_ip, port)
    print(f"[STREAM] Starting UDP H.264 stream: {' '.join(cmd)}")
    proc = subprocess.Popen(cmd)
    return proc


def test_camera():
    """Main test function."""
    global _stream_proc
    
    # Get laptop IP from command-line argument or config file
    if len(sys.argv) >= 2:
        laptop_ip = sys.argv[1]
        print(f"[CONFIG] Using laptop IP from command-line: {laptop_ip}")
    else:
        laptop_ip = network_config.LAPTOP_IP
        if laptop_ip is None:
            print("ERROR: LAPTOP_IP is not set in Config/network_config.py")
            print("Either set LAPTOP_IP in Config/network_config.py or provide it as an argument:")
            print("  python3 test_camera.py <LAPTOP_IP>")
            sys.exit(1)
        print(f"[CONFIG] Using laptop IP from Config/network_config.py: {laptop_ip}")
    
    # Get port from config file
    port = network_config.STREAM_PORT
    
    print("=" * 60)
    print("Camera Test Script - UDP H.264 Stream")
    print("=" * 60)
    print(f"\nStreaming to laptop IP: {laptop_ip}")
    print(f"Port: {port}")
    print(f"\nOn your laptop, run:")
    print(f'  gst-launch-1.0 udpsrc port={port} caps="application/x-rtp, media=video, encoding-name=H264, payload=96" \\')
    print("      ! rtph264depay ! avdec_h264 ! videoconvert ! autovideosink")
    print("\n" + "=" * 60)
    print("Press Ctrl+C to stop")
    print("=" * 60 + "\n")
    
    try:
        # Start UDP H.264 stream (same as start_stream.py)
        _stream_proc = start_stream(laptop_ip, port)
        
        # Wait for stream process
        _stream_proc.wait()
    except KeyboardInterrupt:
        print("\n\nStopping stream...")
    except Exception as e:
        print(f"\n\nERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if _stream_proc is not None:
            _stream_proc.terminate()
            try:
                _stream_proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                _stream_proc.kill()
            print("Stream stopped")
        
        print("\n" + "=" * 60)
        print("Stream ended")
        print("=" * 60)
        return True


if __name__ == "__main__":
    test_camera()
