import os
import signal
import time
from Domains.Vision.Detection import detect_human
from Domains.Vision.Camera import CameraThread
import cv2
import threading
import queue
from dataclasses import dataclass
from typing import Optional, Tuple

# =============================================================================
# Shared Vision State (latest-state model, not a queue)
# =============================================================================

@dataclass
class VisionState:
    """Latest detection result. Overwritten continuously by vision thread."""
    timestamp: float = 0.0
    has_target: bool = False
    bbox_center: Optional[Tuple[int, int]] = None
    bbox: Optional[Tuple[int, int, int, int]] = None
    confidence: float = 0.0


# Thread-safe latest state
_vision_state = VisionState()
_vision_state_lock = threading.Lock()

# Staleness threshold: detections older than this are considered invalid
STALENESS_THRESHOLD_S = 0.5

# --- Globals ---
camera = None
_display_thread = None
_vision_thread = None
_display_queue = queue.Queue(maxsize=1)

# --- Stop Events ---
_stop_event = threading.Event()

# --- Constants ---
_WINDOW_NAME = "Goose Vision"
# Check if we have a display (for headless operation)
_HAS_DISPLAY = os.getenv("DISPLAY") is not None

def start_vision():
    """
    Initializes and starts all vision-related threads.
    
    Note: Video streaming is automatically started by CameraThread.start()
    if LAPTOP_IP is configured in Config/network_config.py
    """
    global camera, _display_thread, _vision_thread
    print("Vision system starting...")

    if camera is None:
        # Use /dev/video0 by default; adjust index if your camera is on a different device.
        camera = CameraThread(index=0, width=2048, height=1536, fps=30)
    
    _stop_event.clear()
    
    # Start all threads (CameraThread.start() will automatically start streaming if configured)
    camera.start()
    
    _vision_thread = threading.Thread(target=_vision_worker, daemon=True)
    _vision_thread.start()

    _display_thread = threading.Thread(target=_display_worker, daemon=True)
    _display_thread.start()
    
    print("Vision system started.")

def stop_vision():
    """
    Stops all vision-related threads and releases resources.
    
    Note: Video streaming is automatically stopped by CameraThread.stop()
    """
    global camera, _display_thread, _vision_thread
    print("Vision system stopping...")
    
    _stop_event.set()

    if camera:
        # CameraThread.stop() will automatically stop the video stream
        camera.stop()
        camera = None

    if _vision_thread and _vision_thread.is_alive():
        _vision_thread.join()
        _vision_thread = None
        
    if _display_thread and _display_thread.is_alive():
        _display_thread.join()
        _display_thread = None

    if _HAS_DISPLAY:
        cv2.destroyAllWindows()
    print("Vision system stopped.")

def _vision_worker():
    """
    Dedicated thread for running object detection continuously.
    Runs as fast as CUDA allows - no artificial rate limiting.
    Overwrites shared state on every frame.
    """
    global _vision_state
    
    while not _stop_event.is_set():
        frame = camera.get_frame()
        if frame is None:
            time.sleep(0.005)
            continue
        
        # --- YOLO inference (runs at full CUDA speed) ---
        human, center, bbox, conf, class_id = detect_human(frame)
        
        # --- Update shared state (atomic overwrite) ---
        with _vision_state_lock:
            _vision_state.timestamp = time.time()
            _vision_state.has_target = human
            _vision_state.bbox_center = center
            _vision_state.bbox = bbox
            _vision_state.confidence = conf
        
        # --- Push to display (non-blocking) ---
        try:
            _display_queue.put_nowait((frame, bbox, conf))
        except queue.Full:
            pass

def _display_worker():
    """Separate thread handles all visualization (only if display is available)"""
    if not _HAS_DISPLAY:
        # No display available - skip visualization
        print("[VISION] No display available (DISPLAY not set) - skipping visualization")
        while not _stop_event.is_set():
            try:
                _display_queue.get(timeout=0.1)
            except queue.Empty:
                if _stop_event.is_set():
                    break
        return
    
    # Display is available - show visualization
    while not _stop_event.is_set():
        try:
            frame, bbox, conf = _display_queue.get(timeout=0.1)
            vis = frame.copy()

            if bbox is not None:
                x1, y1, x2, y2 = bbox
                cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(
                    vis, f"{conf:.2f}", (x1, y1 - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1
                )

            h, w = vis.shape[:2]
            cv2.drawMarker(
                vis, (w // 2, h // 2),
                (255, 0, 0), cv2.MARKER_CROSS, 20, 2
            )

            cv2.imshow(_WINDOW_NAME, vis)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                # Same shutdown path as Ctrl+C (Orchestrator signal handler + stream cleanup)
                os.kill(os.getpid(), signal.SIGINT)
        except queue.Empty:
            if _stop_event.is_set():
                break


# =============================================================================
# Public API - Latest State Model (no queues, no blocking)
# =============================================================================

def get_latest_detection() -> VisionState:
    """
    Non-blocking read of the latest detection state.
    
    Returns a copy of the current VisionState.
    Automatically applies staleness check: if detection is older than
    STALENESS_THRESHOLD_S, returns has_target=False.
    
    Usage in Main.py:
        state = get_latest_detection()
        if state.has_target:
            cx, cy = state.bbox_center
            # use detection
    """
    with _vision_state_lock:
        # Copy current state
        state = VisionState(
            timestamp=_vision_state.timestamp,
            has_target=_vision_state.has_target,
            bbox_center=_vision_state.bbox_center,
            bbox=_vision_state.bbox,
            confidence=_vision_state.confidence,
        )
    
    # Apply staleness check
    age = time.time() - state.timestamp
    if age > STALENESS_THRESHOLD_S:
        state.has_target = False
        state.bbox_center = None
        state.bbox = None
        state.confidence = 0.0
    
    return state


def detect_human_live():
    """
    Legacy API - kept for backward compatibility.
    Returns (has_target, bbox_center, bbox, confidence, None).
    
    Note: frame is no longer returned (always None) since vision runs independently.
    """
    state = get_latest_detection()
    return state.has_target, state.bbox_center, state.bbox, state.confidence, None


def show_frame(frame, bbox=None, conf=None):
    """Non-blocking frame display."""
    try:
        _display_queue.put_nowait((frame, bbox, conf))
    except queue.Full:
        pass
