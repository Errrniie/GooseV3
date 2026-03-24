"""
FastAPI test API for basic GooseV3 control:
- MJPEG camera stream from Jetson CSI camera
- Z-axis movement via MOVE_Z macro
- Laser ON/OFF control
- Emergency stop / restart
- TMC diagnostics trigger

This is intended for laptop-side GUI testing before the full system
is wired up.
"""

from typing import Optional
import time

import cv2
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from Motion.Moonraker_ws_v2 import MoonrakerWSClient

app = FastAPI(title="GooseV3 Test API", version="0.2.0")


# Controllers and clients are attached from the Jetson test main script
motion_controller = None     # type: ignore[var-annotated]
laser_controller = None      # type: ignore[var-annotated]
moonraker_client: MoonrakerWSClient | None = None


def attach_motion_controller(motion) -> None:
    global motion_controller
    motion_controller = motion
    print("[TEST_API] MotionController attached")


def attach_laser_controller(laser) -> None:
    global laser_controller
    laser_controller = laser
    print("[TEST_API] LaserController attached")


def attach_moonraker_client(client: MoonrakerWSClient) -> None:
    global moonraker_client
    moonraker_client = client
    print("[TEST_API] MoonrakerWSClient attached")


# ============================================================================
# Request models
# ============================================================================


class MoveZRequest(BaseModel):
    delta_mm: float
    velocity: Optional[float] = None


class DumpTMCRequest(BaseModel):
    stepper: str  # e.g. "stepper_z", "stepper_x", "stepper_y"


# ============================================================================
# Z-axis control
# ============================================================================


@app.post("/z/move")
def move_z(body: MoveZRequest):
    """
    Relative Z movement using MOVE_Z macro via MotionController.
    """
    if motion_controller is None:
        return {"status": "error", "error": "MotionController not attached on Jetson"}

    # MotionController already uses MOVE_Z + waits for 'complete'
    motion_controller.move_z_relative_blocking(
        body.delta_mm,
        velocity=body.velocity,
    )
    return {
        "status": "ok",
        "delta_mm": body.delta_mm,
        "velocity": body.velocity if body.velocity is not None else 2.0,
    }


# ============================================================================
# Laser control
# ============================================================================


@app.post("/laser/on")
def laser_on():
    if laser_controller is None:
        return {"status": "error", "error": "LaserController not attached on Jetson"}
    ok = laser_controller.turn_on()
    return {"status": "ok" if ok else "error"}


@app.post("/laser/off")
def laser_off():
    if laser_controller is None:
        return {"status": "error", "error": "LaserController not attached on Jetson"}
    ok = laser_controller.turn_off()
    return {"status": "ok" if ok else "error"}


# ============================================================================
# EMERGENCY STOP / RESTART / TMC DIAGNOSTICS
# ============================================================================


def _require_moonraker():
    if moonraker_client is None:
        raise RuntimeError("Moonraker client not attached on Jetson")


@app.post("/emergency_stop")
def emergency_stop():
    """
    Trigger Klipper emergency stop: M112.
    """
    try:
        _require_moonraker()
        assert moonraker_client is not None
        moonraker_client.call(
            "printer.gcode.script",
            {"script": "M112"},
            timeout_s=5.0,
        )
        return {"status": "ok", "script": "M112"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.post("/firmware_restart")
def firmware_restart():
    """
    Recover from M112 by issuing FIRMWARE_RESTART.
    """
    try:
        _require_moonraker()
        assert moonraker_client is not None
        moonraker_client.call(
            "printer.gcode.script",
            {"script": "FIRMWARE_RESTART"},
            timeout_s=10.0,
        )
        return {"status": "ok", "script": "FIRMWARE_RESTART"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.post("/klipper_restart")
def klipper_restart():
    """
    Full Klipper restart: RESTART.
    """
    try:
        _require_moonraker()
        assert moonraker_client is not None
        moonraker_client.call(
            "printer.gcode.script",
            {"script": "RESTART"},
            timeout_s=10.0,
        )
        return {"status": "ok", "script": "RESTART"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.post("/tmc/dump")
def tmc_dump(body: DumpTMCRequest):
    """
    Request DUMP_TMC for a specific stepper.
    The detailed DRV_STATUS lines will come back via notify_gcode_response
    on the Moonraker websocket; we are not parsing them here yet.
    """
    script = f"DUMP_TMC STEPPER={body.stepper}"
    try:
        _require_moonraker()
        assert moonraker_client is not None
        moonraker_client.call(
            "printer.gcode.script",
            {"script": script},
            timeout_s=5.0,
        )
        return {"status": "ok", "script": script}
    except Exception as e:
        return {"status": "error", "error": str(e), "script": script}


# ============================================================================
# CAMERA MJPEG STREAM
# ============================================================================

# Try to use YoloInterface's camera if available, otherwise fall back to our own
def _get_camera_frame():
    """
    Get a frame from the camera.
    First tries to use YoloInterface's camera (if vision is running),
    otherwise falls back to opening our own camera.
    """
    # Try to import and use YoloInterface's camera
    # Import the module, not the variable, so we get the latest value
    try:
        import YoloModel.YoloInterface as yolo_module
        yolo_camera = yolo_module.camera
        if yolo_camera is not None:
            frame = yolo_camera.get_frame()
            if frame is not None:
                return frame
            else:
                # Frame is None - camera might not be ready yet
                pass
        else:
            # Camera is None - vision might not be started yet
            pass
    except (ImportError, AttributeError) as e:
        # Camera not available yet - will fall back
        pass
    except Exception as e:
        print(f"[TEST_API] Error accessing YoloInterface camera: {e}")
        import traceback
        traceback.print_exc()
    
    # Fallback: open our own camera (only if YoloInterface camera not available)
    # Use V4L2 backend like CameraThread does (for /dev/video0)
    global _camera_initialized, _camera_cap
    if not _camera_initialized:
        try:
            print("[TEST_API] YoloInterface camera not available, initializing fallback camera...")
            print("[TEST_API] Opening /dev/video0 using V4L2 backend...")
            # Use same approach as CameraThread: V4L2 backend with MJPG codec
            _camera_cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
            if not _camera_cap.isOpened():
                print("[TEST_API] ERROR: Failed to open /dev/video0 via V4L2")
                print("[TEST_API] Trying alternative: GStreamer pipeline...")
                # Try GStreamer as fallback
                pipeline = (
                    "v4l2src device=/dev/video0 ! "
                    "video/x-raw,width=640,height=480,framerate=30/1 ! "
                    "videoconvert ! video/x-raw,format=BGR ! appsink"
                )
                _camera_cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
                if not _camera_cap.isOpened():
                    print("[TEST_API] ERROR: Failed to open camera via both V4L2 and GStreamer")
                    return None
                print("[TEST_API] Camera opened via GStreamer fallback")
            else:
                # Configure V4L2 camera like CameraThread does
                _camera_cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
                _camera_cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                _camera_cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                _camera_cap.set(cv2.CAP_PROP_FPS, 30)
                _camera_cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                print("[TEST_API] Camera opened via V4L2, configured: 640x480@30fps MJPG")
            _camera_initialized = True
            print("[TEST_API] Fallback camera initialized successfully for /video stream")
        except Exception as e:
            print(f"[TEST_API] ERROR: Exception initializing fallback camera: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    if _camera_cap is not None:
        try:
            ret, frame = _camera_cap.read()
            if ret and frame is not None:
                return frame
        except Exception as e:
            print(f"[TEST_API] Error reading from fallback camera: {e}")
    
    return None


_camera_initialized = False
_camera_cap = None


def _video_generator():
    """
    Generate MJPEG video stream frames.
    Uses YoloInterface's camera if available, otherwise falls back to own camera.
    """
    frame_count = 0
    error_count = 0
    last_log_time = time.time()
    
    while True:
        try:
            frame = _get_camera_frame()
            if frame is None:
                error_count += 1
                # Log errors periodically (every 5 seconds)
                if time.time() - last_log_time > 5.0:
                    print(f"[TEST_API] Video stream: No frame available (errors: {error_count})")
                    last_log_time = time.time()
                time.sleep(0.033)  # ~30 FPS
                continue

            # Reset error count on successful frame
            if error_count > 0:
                print(f"[TEST_API] Video stream: Frame received (recovered from {error_count} errors)")
                error_count = 0

            ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if not ok:
                error_count += 1
                continue

            frame_count += 1
            if frame_count % 100 == 0:
                print(f"[TEST_API] Video stream: Sent {frame_count} frames")

            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n"
            )
        except Exception as e:
            print(f"[TEST_API] Error in video generator: {e}")
            error_count += 1
            time.sleep(0.1)


@app.get("/")
def root():
    """Root endpoint - redirects to video stream info."""
    print("[TEST_API] Root endpoint (/) accessed")
    return {
        "message": "GooseV3 Test API",
        "endpoints": {
            "video": "GET /video - MJPEG camera stream (use this URL in browser!)",
            "test_frame": "GET /test_frame - Single JPEG frame (for testing)",
            "z_move": "POST /z/move - Move Z axis",
            "laser_on": "POST /laser/on - Turn laser ON",
            "laser_off": "POST /laser/off - Turn laser OFF",
            "emergency_stop": "POST /emergency_stop - Emergency stop",
            "firmware_restart": "POST /firmware_restart - Firmware restart",
            "klipper_restart": "POST /klipper_restart - Klipper restart",
            "tmc_dump": "POST /tmc/dump - TMC diagnostics",
        },
        "video_stream": "Access http://<JETSON_IP>:8000/video in your browser to view camera feed",
        "note": "IMPORTANT: You must access /video (not /) to see the video stream!"
    }


@app.get("/test_frame")
def test_frame():
    """
    Test endpoint: Returns a single JPEG frame from the camera.
    Useful for debugging camera access issues.
    """
    print("[TEST_API] /test_frame endpoint accessed")
    frame = _get_camera_frame()
    if frame is None:
        return {"error": "No frame available from camera. Check terminal output for details."}
    
    ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        return {"error": "Failed to encode frame as JPEG"}
    
    from fastapi.responses import Response
    return Response(content=jpeg.tobytes(), media_type="image/jpeg")


@app.get("/video")
def video():
    """
    MJPEG stream from Jetson camera (CSI) using GStreamer + OpenCV.
    View from laptop at: http://<JETSON_IP>:8000/video
    
    This endpoint streams live video frames as MJPEG.
    Open this URL directly in a browser or MJPEG-compatible viewer.
    """
    print("[TEST_API] ========================================")
    print("[TEST_API] /video endpoint accessed - starting video stream")
    print("[TEST_API] ========================================")
    try:
        response = StreamingResponse(
            _video_generator(),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )
        print("[TEST_API] StreamingResponse created successfully")
        return response
    except Exception as e:
        print(f"[TEST_API] ERROR creating StreamingResponse: {e}")
        import traceback
        traceback.print_exc()
        return {"error": f"Failed to start video stream: {e}"}

