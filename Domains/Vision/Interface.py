import os
import signal
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from Domains.Vision.Camera import CameraThread
from Domains.Vision.Detection import detect_objects
import Config.Motion_Config as mcfg
import Config.Vision_Config as vcfg
import cv2
import threading
import queue

# =============================================================================
# Shared Vision State (latest-state model, not a queue)
# =============================================================================


@dataclass
class VisionState:
    """
    Latest vision snapshot. ``has_target`` / bbox / confidence mirror the active
    **bird** used for tracking (bird-only); see ``detections`` and ``active_track``.
    """

    timestamp: float = 0.0
    has_target: bool = False
    bbox_center: Optional[Tuple[int, int]] = None
    bbox: Optional[Tuple[int, int, int, int]] = None
    confidence: float = 0.0
    detections: List[Dict[str, Any]] = field(default_factory=list)
    active_track: Optional[Dict[str, Any]] = None


# Thread-safe latest state
_vision_state = VisionState()
_vision_state_lock = threading.Lock()

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

    If LAPTOP_IP is set and streaming is enabled, a **TCP** thread sends JPEG previews
    (separate from GStreamer; see ``CameraThread``).
    """
    global camera, _display_thread, _vision_thread
    print("Vision system starting...")

    if camera is None:
        camera = CameraThread(
            sensor_id=mcfg.CAMERA_ARGUS_SENSOR_ID,
            width=mcfg.CAMERA_WIDTH,
            height=mcfg.CAMERA_HEIGHT,
            fps=mcfg.CAMERA_FPS,
        )

    _stop_event.clear()

    camera.start()

    _vision_thread = threading.Thread(target=_vision_worker, daemon=True)
    _vision_thread.start()

    _display_thread = threading.Thread(target=_display_worker, daemon=True)
    _display_thread.start()

    print("Vision system started.")


def stop_vision():
    """
    Stops all vision-related threads and releases the camera (including TCP preview if any).

    Workers are joined before tearing down capture so no code uses frames mid-shutdown.
    """
    global camera, _display_thread, _vision_thread
    print("Vision system stopping...")

    _stop_event.set()

    if _vision_thread and _vision_thread.is_alive():
        _vision_thread.join(timeout=10.0)
        _vision_thread = None

    if _display_thread and _display_thread.is_alive():
        _display_thread.join(timeout=5.0)
        _display_thread = None

    if camera:
        camera.stop()
        camera = None

    if _HAS_DISPLAY:
        cv2.destroyAllWindows()
    print("Vision system stopped.")


def _build_public_detections_and_active(raw: List[Dict[str, Any]]) -> tuple:
    """Filter for API list; pick highest-confidence bird >= bird_min for tracking."""
    pid = int(vcfg.VISION_CLASS_PERSON_ID)
    bid = int(vcfg.VISION_CLASS_BIRD_ID)
    hmin = float(vcfg.VISION_HUMAN_MIN_CONF)
    ymin = float(vcfg.VISION_YOLO_MIN_CONF)
    bmin = float(vcfg.VISION_BIRD_MIN_CONF)
    md = int(vcfg.VISION_MAX_DETECTIONS)

    pub: List[Dict[str, Any]] = []
    for d in raw:
        cid = int(d["class_id"])
        c = float(d["confidence"])
        if cid == pid and c >= hmin:
            pub.append(dict(d))
        elif cid == bid and c >= ymin:
            pub.append(dict(d))

    pub.sort(key=lambda x: -x["confidence"])
    pub = pub[:md]

    birds_ok = [d for d in raw if int(d["class_id"]) == bid and float(d["confidence"]) >= bmin]
    if not birds_ok:
        active = None
    else:
        best = max(birds_ok, key=lambda x: x["confidence"])
        active = dict(best)

    return pub, active


def _vision_worker():
    """
    Runs YOLO continuously; updates shared state with multi-detections + bird active_track.
    """
    global _vision_state

    while not _stop_event.is_set():
        frame = camera.get_frame()
        if frame is None:
            time.sleep(0.005)
            continue

        f = frame.copy()
        raw = detect_objects(f)
        pub, active = _build_public_detections_and_active(raw)

        with _vision_state_lock:
            _vision_state.timestamp = time.time()
            _vision_state.detections = pub
            _vision_state.active_track = active
            _vision_state.has_target = active is not None
            if active is not None:
                x1, y1, x2, y2 = active["bbox"]
                _vision_state.bbox = (x1, y1, x2, y2)
                cx, cy = active["center"]
                _vision_state.bbox_center = (cx, cy)
                _vision_state.confidence = float(active["confidence"])
            else:
                _vision_state.bbox = None
                _vision_state.bbox_center = None
                _vision_state.confidence = 0.0

        try:
            _display_queue.put_nowait((f, pub, active))
        except queue.Full:
            pass


def _bbox_key(b: List[int]) -> Tuple[int, int, int, int]:
    return int(b[0]), int(b[1]), int(b[2]), int(b[3])


def _display_worker():
    if not _HAS_DISPLAY:
        print("[VISION] No display available (DISPLAY not set) - skipping visualization")
        while not _stop_event.is_set():
            try:
                _display_queue.get(timeout=0.1)
            except queue.Empty:
                if _stop_event.is_set():
                    break
        return

    active_key: Optional[Tuple[int, int, int, int]] = None

    while not _stop_event.is_set():
        try:
            frame, pub, active = _display_queue.get(timeout=0.1)
            vis = frame.copy()
            if active is not None:
                active_key = _bbox_key(active["bbox"])
            else:
                active_key = None

            bid = int(vcfg.VISION_CLASS_BIRD_ID)
            pid = int(vcfg.VISION_CLASS_PERSON_ID)

            for d in pub:
                x1, y1, x2, y2 = d["bbox"]
                cid = int(d["class_id"])
                cf = float(d["confidence"])
                is_active = active_key is not None and _bbox_key(d["bbox"]) == active_key
                if is_active:
                    color = (0, 0, 255)
                    thickness = 3
                elif cid == bid:
                    color = (0, 255, 255)
                    thickness = 2
                else:
                    color = (0, 200, 0)
                    thickness = 2
                cv2.rectangle(vis, (x1, y1), (x2, y2), color, thickness)
                cv2.putText(
                    vis,
                    f"{d['class_name']} {cf:.2f}",
                    (x1, max(0, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    color,
                    1,
                )

            h, w = vis.shape[:2]
            cv2.drawMarker(
                vis,
                (w // 2, h // 2),
                (255, 0, 0),
                cv2.MARKER_CROSS,
                20,
                2,
            )

            cv2.imshow(_WINDOW_NAME, vis)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                os.kill(os.getpid(), signal.SIGINT)
        except queue.Empty:
            if _stop_event.is_set():
                break


# =============================================================================
# Public API - Latest State Model (no queues, no blocking)
# =============================================================================


def get_latest_detection() -> VisionState:
    """
    Non-blocking read of the latest VisionState copy.
    Stale frames clear targets and detection lists (VISION_STALENESS_S).
    """
    with _vision_state_lock:
        state = VisionState(
            timestamp=_vision_state.timestamp,
            has_target=_vision_state.has_target,
            bbox_center=_vision_state.bbox_center,
            bbox=_vision_state.bbox,
            confidence=_vision_state.confidence,
            detections=[dict(d) for d in _vision_state.detections],
            active_track=(
                dict(_vision_state.active_track) if _vision_state.active_track else None
            ),
        )

    age = time.time() - state.timestamp
    if age > float(mcfg.VISION_STALENESS_S):
        state.has_target = False
        state.bbox_center = None
        state.bbox = None
        state.confidence = 0.0
        state.detections = []
        state.active_track = None

    return state


def detect_human_live():
    """
    Legacy API. Returns (has_target, bbox_center, bbox, confidence, class_id).
    class_id is the active bird's class when has_target else None.
    """
    state = get_latest_detection()
    cid = (
        int(state.active_track["class_id"])
        if state.active_track is not None
        else None
    )
    return state.has_target, state.bbox_center, state.bbox, state.confidence, cid


def show_frame(frame, bbox=None, conf=None):
    """Non-blocking frame display (legacy single-box)."""
    try:
        _display_queue.put_nowait((frame, [], None))
    except queue.Full:
        pass
