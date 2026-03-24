
import time
from YoloModel.Detection import detect_human
from YoloModel.CameraThread import CameraThread
import cv2
import threading
import queue

# --- Globals ---
camera = None
_vision_thread = None
_vision_queue = queue.Queue(maxsize=1)

# --- Stop Events ---
_stop_event = threading.Event()

# --- Constants ---
_VISION_LOOP_INTERVAL = 0.05  # Process frames at 10Hz

def start_vision():
    """Initializes and starts all vision-related threads."""
    global camera, _vision_thread
    print("Vision system starting...")

    if camera is None:
        # Using a lower-level camera index for testing if 4 is not available
        try:
            camera = CameraThread(index=4, width=3840, height=2160, fps=30)
        except Exception:
            print("Could not open camera at index 4, trying index 0.")
            camera = CameraThread(index=0, width=3840, height=2160, fps=30)

    _stop_event.clear()
    
    # Start all threads
    camera.start()
    
    _vision_thread = threading.Thread(target=_vision_worker, daemon=True)
    _vision_thread.start()
    
    print("Vision system started.")

def stop_vision():
    """Stops all vision-related threads and releases resources."""
    global camera, _vision_thread
    print("Vision system stopping...")
    
    _stop_event.set()

    if camera:
        camera.stop()
        camera = None

    if _vision_thread and _vision_thread.is_alive():
        _vision_thread.join()
        _vision_thread = None

    print("Vision system stopped.")

def get_feet_center(bbox):
    if bbox is None:
        return None
    x1, y1, x2, y2 = bbox
    return (int((x1 + x2) / 2), y2)

def _vision_worker():
    """
    Dedicated thread for running object detection at a controlled rate.
    """
    while not _stop_event.is_set():
        loop_start_time = time.time()

        frame = camera.get_frame()
        if frame is None:
            time.sleep(0.01)
            continue
        
        human, center, bbox, conf = detect_human(frame)
        feet_center = get_feet_center(bbox)
        
        try:
            _vision_queue.put_nowait((human, center, bbox, conf, frame, feet_center))
        except queue.Full:
            pass

        elapsed_time = time.time() - loop_start_time
        sleep_time = _VISION_LOOP_INTERVAL - elapsed_time
        if sleep_time > 0:
            time.sleep(sleep_time)

def detect_human_live():
    """Non-blocking call to get the latest detection result."""
    try:
        return _vision_queue.get_nowait()
    except queue.Empty:
        return False, None, None, 0.0, None, None
