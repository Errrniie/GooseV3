#!/usr/bin/env python3
"""
SystemMain.py - Complete Goose Deterrence System Integration

Entry point that orchestrates:
1. Moonraker connection + homing + neutral positioning
2. Live camera calibration UI (mouse clicks + distance entry)
3. SEARCH/TRACK state machine with bird/person detection
4. Laser aiming via distance model + GroundAim
5. Deterrence pattern control with safety overrides
6. Clean shutdown on exceptions
"""

import cv2
import time
import threading
import numpy as np
from typing import Optional, List, Tuple, Dict
from dataclasses import dataclass

# Motion subsystem
from Domains.Motion.Moonraker_Client import MoonrakerWSClient
from Domains.Motion.Controller import MotionController
from Domains.Motion.Homing import home

# Laser subsystem (DO NOT MODIFY - already verified)
from Laser import LaserEnable
from Domains.Laser.Ground_Aim import get_motor_deltas_for_ground_hit
from Domains.Laser.Patterns import start_square_pattern, stop_pattern
from Domains.Laser.Calibration import X_NEUTRAL_MM, Y_NEUTRAL_MM, Y_MIN, Y_MAX, X_MIN, X_MAX

# Vision subsystem
from Domains.Vision.Camera import CameraThread
from Domains.Vision.Detection import detect_human

# Distance estimation
from Domains.Distance.Model import load_model, get_distance
from Distance import Storage

# Behavior
from Domains.Behavior.Search import SearchController, SearchConfig
from Domains.Behavior.Tracking import TrackingController, TrackingConfig
import Config.Network_Config as net_cfg


# =============================================================================
# CONFIGURATION CONSTANTS
# =============================================================================

# Camera
CAMERA_INDEX = 4
CAMERA_WIDTH = 1920
CAMERA_HEIGHT = 1080
CAMERA_FPS = 30

# YOLO target classes and confidence thresholds
TARGET_CLASSES = {
    "bird": 14,      # COCO class 14
    "person": 0,     # COCO class 0
}
CONF_THRESH = {
    "bird": 0.25,
    "person": 0.40,
}

# State machine thresholds
TRACK_CONFIRM_FRAMES = 5    # Consecutive detections needed to enter TRACK (was 15 - too high)
LOST_FRAMES_TO_EXIT = 60    # Lost frames before exiting TRACK - give tracking time to re-acquire

# Distance limits (safety clamps)
MIN_DISTANCE_FT = 3.0
MAX_DISTANCE_FT = 30.0

# Deterrence pattern
SQUARE_SIZE_FT = 1.0
PATTERN_SPEED = 12000
PATTERN_DWELL_MS = 100

# Motion config for MotionController
MOTION_CONFIG = {
    "limits": {
        "x": [X_MIN, X_MAX],
        "y": [Y_MIN, Y_MAX],
        "z": [0, 20],  # Z not used for laser axes
    },
    "neutral": {
        "x": X_NEUTRAL_MM,
        "y": Y_NEUTRAL_MM,
        "z": 10.0,
    },
    "speeds": {
        "travel": 6000,
        "z": 100,
    },
    "send_rate_hz": 0.5,
    "mm_per_degree": 8.0 / 360.0,
    "feedrate_multiplier": 2.0,
    "angular_velocity": 60.0,
}

# Search config (Z axis not used for galvo; kept for compatibility)
SEARCH_CONFIG = SearchConfig(
    min_z=0.0,
    max_z=20.0,
    start_z=10.0,
    step_size=1.0,
    initial_direction=1,
)

# Tracking config
TRACKING_CONFIG = TrackingConfig(
    frame_width=CAMERA_WIDTH,
    frame_height=CAMERA_HEIGHT,
    deadzone_px=50,           # Larger deadzone to avoid jitter
    kp=0.002,                 # Gentler proportional gain
    max_step_mm=1.5,          # Smaller max step to avoid overshooting
    min_step_mm=0.05,
    confidence_threshold=0.25, # Match CONF_THRESH["bird"]
)


# =============================================================================
# CALIBRATION POINT STORAGE (for UI)
# =============================================================================

@dataclass
class CalibrationPoint:
    """Single calibration point: pixel y-coord + known distance."""
    y_pixel: int
    distance_ft: float


# =============================================================================
# LIVE CAMERA CALIBRATION UI
# =============================================================================

class LiveCalibrationUI:
    """
    Interactive calibration UI using OpenCV window.
    User clicks target feet location, enters distance, repeat.
    """

    def __init__(self, camera_index: int, zoom_label: str):
        self.camera_index = camera_index
        self.zoom_label = zoom_label
        self.points: List[CalibrationPoint] = []
        self.current_frame = None
        self.window_name = "CALIBRATE DISTANCE - Click Target Feet"

    def run(self) -> Optional[List[Tuple[int, float]]]:
        """
        Run calibration UI. Returns list of (y_pixel, distance_ft) or None if aborted.
        """
        cap = cv2.VideoCapture(self.camera_index, cv2.CAP_V4L2)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
        cap.set(cv2.CAP_PROP_FPS, CAMERA_FPS)

        if not cap.isOpened():
            print("[CALIBRATION] ERROR: Cannot open camera")
            return None

        cv2.namedWindow(self.window_name)
        cv2.setMouseCallback(self.window_name, self._mouse_callback)

        print("\n" + "="*60)
        print("LIVE DISTANCE CALIBRATION")
        print("="*60)
        print("Instructions:")
        print("  1. Click on the FEET (bottom-center) of target at known distance")
        print("  2. Enter distance in feet when prompted")
        print("  3. Repeat for multiple distances (minimum 6 points)")
        print("  4. Press 'U' to undo last point")
        print("  5. Press 'S' to save and continue (need >= 6 points)")
        print("  6. Press 'Q' to abort and exit program")
        print("="*60 + "\n")

        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    time.sleep(0.01)
                    continue

                self.current_frame = frame.copy()
                display = self._draw_overlay(frame.copy())

                cv2.imshow(self.window_name, display)
                key = cv2.waitKey(1) & 0xFF

                if key == ord('q') or key == ord('Q'):
                    print("[CALIBRATION] Aborted by user")
                    cap.release()
                    cv2.destroyWindow(self.window_name)
                    return None

                elif key == ord('u') or key == ord('U'):
                    if self.points:
                        removed = self.points.pop()
                        print(f"[CALIBRATION] Removed point: y={removed.y_pixel}, dist={removed.distance_ft}ft")

                elif key == ord('s') or key == ord('S'):
                    if len(self.points) < 6:
                        print(f"[CALIBRATION] Need at least 6 points, have {len(self.points)}")
                    else:
                        print(f"[CALIBRATION] Saving {len(self.points)} points")
                        cap.release()
                        cv2.destroyWindow(self.window_name)
                        return [(p.y_pixel, p.distance_ft) for p in self.points]

        except Exception as e:
            print(f"[CALIBRATION] Exception: {e}")
            cap.release()
            cv2.destroyWindow(self.window_name)
            return None

    def _mouse_callback(self, event, x, y, flags, param):
        """Handle mouse clicks to record calibration points."""
        if event != cv2.EVENT_LBUTTONDOWN:
            return

        if self.current_frame is None:
            return

        # Prompt for distance
        print(f"\n[CALIBRATION] Clicked pixel: ({x}, {y})")
        try:
            dist_str = input("Enter known distance in feet: ").strip()
            distance_ft = float(dist_str)

            if distance_ft <= 0:
                print("[CALIBRATION] Invalid distance (must be > 0)")
                return

            point = CalibrationPoint(y_pixel=y, distance_ft=distance_ft)
            self.points.append(point)
            print(f"[CALIBRATION] Added point #{len(self.points)}: y={y}, dist={distance_ft}ft")

        except ValueError:
            print("[CALIBRATION] Invalid input, must be a number")
        except EOFError:
            print("[CALIBRATION] Input cancelled")

    def _draw_overlay(self, frame):
        """Draw instructions and calibration points on frame."""
        h, w = frame.shape[:2]

        # Instructions at top
        cv2.rectangle(frame, (0, 0), (w, 120), (0, 0, 0), -1)
        cv2.putText(frame, "Click target FEET location, then enter distance", 
                    (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        cv2.putText(frame, f"Points: {len(self.points)}/6 minimum", 
                    (10, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        cv2.putText(frame, "[U] Undo  [S] Save  [Q] Quit", 
                    (10, 85), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)

        # Draw crosshair at center
        center_x = w // 2
        center_y = h // 2
        cv2.line(frame, (center_x - 20, center_y), (center_x + 20, center_y), (0, 255, 0), 1)
        cv2.line(frame, (center_x, center_y - 20), (center_x, center_y + 20), (0, 255, 0), 1)

        # Draw existing calibration points
        for i, point in enumerate(self.points):
            cv2.circle(frame, (w // 2, point.y_pixel), 8, (0, 0, 255), 2)
            cv2.putText(frame, f"{i+1}: {point.distance_ft}ft", 
                        (w // 2 + 15, point.y_pixel + 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

        return frame


def run_live_distance_calibration(camera_index: int, zoom_label: str, save_name: str) -> Optional[List[Tuple[int, float]]]:
    """
    Run live calibration UI and save results.
    
    Returns:
        List of (y_pixel, distance_ft) tuples, or None if aborted
    """
    ui = LiveCalibrationUI(camera_index, zoom_label)
    points = ui.run()

    if points is None:
        return None

    # Validate monotonicity (y should increase or decrease consistently with distance)
    sorted_by_y = sorted(points, key=lambda p: p[0])
    sorted_by_dist = sorted(points, key=lambda p: p[1])
    
    print(f"\n[CALIBRATION] Validation:")
    print(f"  Points sorted by Y: {[(p[0], p[1]) for p in sorted_by_y[:3]]} ... {[(p[0], p[1]) for p in sorted_by_y[-3:]]}")
    print(f"  Points sorted by Distance: {[(p[0], p[1]) for p in sorted_by_dist[:3]]} ... {[(p[0], p[1]) for p in sorted_by_dist[-3:]]}")

    # Save to storage
    metadata = {
        "source_type": "live_camera",
        "source_path": f"camera_{camera_index}",
        "resolution": f"{CAMERA_WIDTH}x{CAMERA_HEIGHT}",
        "fps": CAMERA_FPS,
        "zoom_label": zoom_label,
    }

    success = Storage.create_calibration(
        name=save_name,
        metadata=metadata,
        distance_list=[p[1] for p in points],
        calibration_points=points
    )

    if success:
        print(f"[CALIBRATION] Saved as '{save_name}'")
        return points
    else:
        print(f"[CALIBRATION] Failed to save '{save_name}'")
        return None


# =============================================================================
# MAIN STATE MACHINE
# =============================================================================

class SystemState:
    """System state for orchestration."""
    
    def __init__(self):
        self.mode: str = "SEARCH"  # "SEARCH" or "TRACK"
        self.running: bool = True
        self.paused: bool = False
        
        # Target tracking
        self.track_confirm_count: int = 0
        self.lost_frame_count: int = 0
        self.current_target_class: Optional[str] = None
        
        # Pattern state
        self.pattern_active: bool = False
        self.laser_active: bool = False
        self.last_pattern_start_time: float = 0.0
        self.last_pattern_distance: Optional[float] = None


def main():
    """Main entry point for goose deterrence system."""
    
    print("\n" + "="*70)
    print("GOOSE DETERRENCE SYSTEM - STARTING")
    print("="*70 + "\n")
    
    # Initialize state
    state = SystemState()
    
    # Will hold initialized subsystems
    ws_client: Optional[MoonrakerWSClient] = None
    motion: Optional[MotionController] = None
    camera: Optional[CameraThread] = None
    laser_controller: Optional[LaserEnable.LaserController] = None
    search: Optional[SearchController] = None
    tracker: Optional[TrackingController] = None
    
    try:
        # =====================================================================
        # STEP 1: Connect to Moonraker
        # =====================================================================
        print("[INIT] Connecting to Moonraker...")
        ws_client = MoonrakerWSClient(net_cfg.MOONRAKER_WS_URL)
        ws_client.connect()
        print("[INIT] Moonraker connected")
        
        # =====================================================================
        # STEP 2: Initialize Motion Controller
        # =====================================================================
        print("[INIT] Initializing motion controller...")
        motion = MotionController(ws_client, MOTION_CONFIG)
        print("[INIT] Motion controller ready")
        
        # =====================================================================
        # STEP 3: Home and Move to Neutral (BLOCKING)
        # =====================================================================
        print("[INIT] Homing printer (this will take ~30 seconds)...")
        home(ws_client, timeout=30.0)
        print("[INIT] Homing complete")
        
        print(f"[INIT] Moving to neutral position: X={X_NEUTRAL_MM}, Y={Y_NEUTRAL_MM}")
        # Use absolute positioning with explicit G90
        ws_client.call(
            "printer.gcode.script",
            {"script": f"G90\nG1 X{X_NEUTRAL_MM} Y{Y_NEUTRAL_MM} F6000"},
            timeout_s=5.0
        )
        time.sleep(1.0)  # Let motion settle
        print("[INIT] Neutral position reached")
        
        # =====================================================================
        # STEP 4: Initialize Laser Controller (ensure OFF)
        # =====================================================================
        print("[INIT] Initializing laser controller...")
        laser_controller = LaserEnable.LaserController()
        laser_controller.turn_off()
        print("[INIT] Laser initialized (OFF)")
        
        # =====================================================================
        # STEP 5: Load or Create Calibration
        # =====================================================================
        print("\n" + "="*60)
        print("DISTANCE CALIBRATION")
        print("="*60)
        
        # Check for existing calibrations
        existing_cals = Storage.list_calibrations()
        
        calibration_points = None
        
        if existing_cals:
            print("\nExisting calibrations found:")
            for i, cal in enumerate(existing_cals):
                print(f"  [{i+1}] {cal['name']} ({cal['num_points']} points, {cal.get('zoom_label', 'unknown')})")
            print(f"  [N] Create NEW calibration")
            print(f"  [Q] Quit")
            
            while True:
                choice = input("\nSelect calibration (number, N, or Q): ").strip().upper()
                
                if choice == 'Q':
                    print("[INIT] Exiting...")
                    return
                elif choice == 'N':
                    # Create new calibration
                    break
                else:
                    try:
                        idx = int(choice) - 1
                        if 0 <= idx < len(existing_cals):
                            cal_name = existing_cals[idx]['name']
                            calibration_points = Storage.get_calibration_points(cal_name)
                            if calibration_points:
                                print(f"[INIT] Loaded calibration: {cal_name}")
                                break
                            else:
                                print(f"[ERROR] Failed to load calibration: {cal_name}")
                        else:
                            print("Invalid selection, try again.")
                    except ValueError:
                        print("Invalid input, enter a number, N, or Q.")
        
        # If no calibration loaded, run live calibration
        if calibration_points is None:
            print("\n[INIT] Starting live camera calibration...")
            calibration_name = f"live_cal_{int(time.time())}"
            zoom_label = "default"
            
            calibration_points = run_live_distance_calibration(
                camera_index=CAMERA_INDEX,
                zoom_label=zoom_label,
                save_name=calibration_name
            )
            
            if calibration_points is None:
                print("[INIT] Calibration aborted - exiting cleanly")
                return
        
        print(f"[INIT] Calibration ready with {len(calibration_points)} points")
        
        # =====================================================================
        # STEP 6: Load Distance Model
        # =====================================================================
        print("[INIT] Loading distance model...")
        load_model(calibration_points)
        print("[INIT] Distance model loaded")
        
        # =====================================================================
        # STEP 7: Start Camera Thread
        # =====================================================================
        print("[INIT] Starting camera thread...")
        camera = CameraThread(
            index=CAMERA_INDEX,
            width=CAMERA_WIDTH,
            height=CAMERA_HEIGHT,
            fps=CAMERA_FPS
        )
        camera.start()
        time.sleep(0.5)  # Let camera warm up
        print("[INIT] Camera running")
        
        # =====================================================================
        # STEP 8: Initialize Behavior Controllers
        # =====================================================================
        search = SearchController(SEARCH_CONFIG)
        tracker = TrackingController(TRACKING_CONFIG)
        print("[INIT] Behavior controllers initialized")
        
        # =====================================================================
        # STEP 9: Create Display Window
        # =====================================================================
        display_window = "Goose Deterrence System"
        cv2.namedWindow(display_window)
        print("[INIT] Display window created")
        
        print("\n" + "="*70)
        print("SYSTEM OPERATIONAL")
        print("="*70)
        print("Commands:")
        print("  [Q] Quit")
        print("  [P] Pause")
        print("  [R] Resume")
        print("="*70 + "\n")
        
        # =====================================================================
        # MAIN LOOP
        # =====================================================================
        last_log_time = time.time()
        last_motor_cmd_time = 0.0  # For rate limiting
        LOG_INTERVAL = 1.0  # Log status every second
        MOTOR_CMD_INTERVAL = 1.0  # 1Hz = 1 second between search commands (was 0.5)
        PATTERN_RESTART_DEBOUNCE = 1.5  # seconds before allowing pattern restart
        
        while state.running:
            loop_start = time.time()
            
            # Get latest frame
            frame = camera.get_frame()
            if frame is None:
                time.sleep(0.01)
                continue
            
            # Run detection
            has_target, bbox_center, bbox, confidence, class_id = detect_human(frame)
            
            # Determine detected class name
            detected_class = None
            if has_target and class_id is not None:
                if class_id == 0:
                    detected_class = "person"
                elif class_id == 14:
                    detected_class = "bird"
            
            # ================================================================
            # SAFETY: HUMAN DETECTED - Stop laser but CONTINUE searching
            # ================================================================
            if detected_class == "person":
                # Stop laser and pattern immediately
                if state.pattern_active:
                    stop_pattern(ws_client)
                    state.pattern_active = False
                if state.laser_active:
                    laser_controller.turn_off()
                    state.laser_active = False
                
                # Force back to SEARCH mode if we were tracking
                if state.mode == "TRACK":
                    print("[SAFETY] PERSON DETECTED - Switching to SEARCH mode")
                    state.mode = "SEARCH"
                    state.current_target_class = None
                    state.last_pattern_distance = None
                
                # Reset bird tracking counters (don't track when human present)
                state.track_confirm_count = 0
                state.lost_frame_count = 0
                
                # DON'T continue here - let the loop continue to SEARCH mode
                # so the Z motor keeps moving while searching
            
            # ================================================================
            # KEYBOARD INPUT
            # ================================================================
            key = cv2.waitKey(1) & 0xFF
            
            if key == ord('q') or key == ord('Q'):
                print("\n[MAIN] Shutdown requested by user")
                state.running = False
                continue
            
            elif key == ord('p') or key == ord('P'):
                if not state.paused:
                    print("[MAIN] PAUSED")
                    state.paused = True
                    if state.pattern_active:
                        stop_pattern(ws_client)
                        state.pattern_active = False
                    if state.laser_active:
                        laser_controller.turn_off()
                        state.laser_active = False
            
            elif key == ord('r') or key == ord('R'):
                if state.paused:
                    print("[MAIN] RESUMED")
                    state.paused = False
                    state.mode = "SEARCH"
                    state.track_confirm_count = 0
                    state.lost_frame_count = 0
            
            # Skip processing if paused
            if state.paused:
                # Draw paused overlay
                display = frame.copy()
                cv2.putText(display, "PAUSED", (50, 50), 
                           cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 255), 3)
                cv2.imshow(display_window, display)
                time.sleep(0.05)
                continue
            
            # ================================================================
            # STATE MACHINE: SEARCH MODE
            # ================================================================
            if state.mode == "SEARCH":
                # Ensure laser and pattern are OFF in search
                if state.pattern_active:
                    stop_pattern(ws_client)
                    state.pattern_active = False
                if state.laser_active:
                    laser_controller.turn_off()
                    state.laser_active = False
                
                # RATE LIMITING: Only call SearchController and send Z motion at 2Hz
                # This keeps SearchController internal state in sync with actual motor position
                current_time = time.time()
                if current_time - last_motor_cmd_time >= MOTOR_CMD_INTERVAL:
                    # Execute search pattern: call SearchController and send Z motion
                    search_result = search.update()
                    z_delta = search_result.get("z_delta", 0.0)
                    
                    if abs(z_delta) > 0.01:  # Only send if meaningful delta
                        # Use MOVE_Z macro and wait for completion before next command
                        v = MOTION_CONFIG["speeds"]["z"]
                        cmd = f"MOVE_Z D={z_delta:.3f} V={v:.0f}"
                        ws_client.send_gcode_and_wait_complete(cmd, timeout_s=10.0)
                        last_motor_cmd_time = current_time
                
                # Check for valid bird target to enter TRACK mode
                if has_target and detected_class == "bird" and confidence >= CONF_THRESH["bird"]:
                    state.track_confirm_count += 1
                    print(f"[SEARCH] Bird detected: conf={confidence:.2f}, confirm={state.track_confirm_count}/{TRACK_CONFIRM_FRAMES}")
                    
                    if state.track_confirm_count >= TRACK_CONFIRM_FRAMES:
                        print(f"[STATE] SEARCH -> TRACK (confirmed {state.track_confirm_count} frames)")
                        
                        # CRITICAL: Stop all pending motion commands before entering TRACK
                        # M400 waits for moves to finish, then we're in a known state
                        print("[STATE] Stopping search motion (M400)...")
                        ws_client.send_gcode("M400")  # Wait for pending moves to complete
                        time.sleep(0.1)  # Brief pause to ensure motion stopped
                        
                        state.mode = "TRACK"
                        state.track_confirm_count = 0
                        state.lost_frame_count = 0
                        state.current_target_class = "bird"
                        state.last_pattern_distance = None  # Reset for new track
                        tracker.reset()
                        search.reset()  # Reset search controller for next search
                else:
                    # Reset confirm count if no valid detection
                    if state.track_confirm_count > 0:
                        print(f"[SEARCH] Bird lost, resetting confirm count (was {state.track_confirm_count})")
                    state.track_confirm_count = 0
            
            # ================================================================
            # STATE MACHINE: TRACK MODE
            # ================================================================
            elif state.mode == "TRACK":
                # Check for valid bird target
                if not has_target or detected_class != "bird" or confidence < CONF_THRESH["bird"]:
                    state.lost_frame_count += 1
                    # Debug: log why we're losing frames
                    if state.lost_frame_count <= 5 or state.lost_frame_count % 10 == 0:
                        print(f"[TRACK] Lost frame {state.lost_frame_count}: has_target={has_target}, class={detected_class}, conf={confidence:.2f}")
                    
                    if state.lost_frame_count >= LOST_FRAMES_TO_EXIT:
                        print(f"[STATE] TRACK -> SEARCH (lost target {state.lost_frame_count} frames)")
                        state.mode = "SEARCH"
                        state.lost_frame_count = 0
                        state.track_confirm_count = 0
                        state.current_target_class = None
                        state.last_pattern_distance = None
                        
                        if state.pattern_active:
                            stop_pattern(ws_client)
                            state.pattern_active = False
                        if state.laser_active:
                            laser_controller.turn_off()
                            state.laser_active = False
                else:
                    # Valid target - reset lost counter
                    state.lost_frame_count = 0
                    
                    # PATTERN OWNERSHIP RULE:
                    # If pattern is active, FREEZE camera - don't move anything
                    # This prevents detection loss from camera movement
                    if state.pattern_active:
                        # Pattern is running - just log for monitoring
                        if bbox is not None and time.time() - last_log_time >= LOG_INTERVAL:
                            x1, y1, x2, y2 = bbox
                            feet_y = y2
                            distance_ft = get_distance(feet_y)
                            print(f"[TRACK] Pattern active, monitoring: dist={distance_ft:.1f}ft, conf={confidence:.2f}")
                            last_log_time = time.time()
                    else:
                        # Pattern NOT active - first center the bird, then start pattern
                        if bbox is not None:
                            x1, y1, x2, y2 = bbox
                            cx = (x1 + x2) // 2
                            cy = (y1 + y2) // 2
                            feet_x = cx
                            feet_y = y2  # Bottom of bbox
                            
                            # TRACKING: Move camera to center bird BEFORE starting pattern
                            tracking_result = tracker.update((cx, cy), confidence)
                            
                            if tracking_result["should_move"]:
                                z_delta = tracking_result["z_delta"]
                                # Rate limit camera tracking movements
                                current_time = time.time()
                                if current_time - last_motor_cmd_time >= MOTOR_CMD_INTERVAL:
                                    v = MOTION_CONFIG["speeds"]["z"]
                                    cmd = f"MOVE_Z D={z_delta:.3f} V={v:.0f}"
                                    ws_client.send_gcode_and_wait_complete(cmd, timeout_s=10.0)
                                    last_motor_cmd_time = current_time
                                    print(f"[TRACK] Centering bird: z_delta={z_delta:.3f}mm, error={tracking_result['error_px']:.0f}px")
                                # Don't start pattern yet - wait until centered
                                continue
                            
                            # Estimate distance from y-coordinate
                            distance_ft = get_distance(feet_y)
                            
                            # Clamp distance to safe range
                            if distance_ft < MIN_DISTANCE_FT or distance_ft > MAX_DISTANCE_FT:
                                print(f"[TRACK] Distance {distance_ft:.1f}ft out of range [{MIN_DISTANCE_FT}, {MAX_DISTANCE_FT}]")
                                state.lost_frame_count += 1
                            else:
                                # Check debounce timer to prevent rapid pattern restarts
                                current_time = time.time()
                                time_since_last_pattern = current_time - state.last_pattern_start_time
                                
                                if time_since_last_pattern < PATTERN_RESTART_DEBOUNCE:
                                    # Too soon to restart - wait
                                    pass
                                else:
                                    # Ready to aim and start pattern
                                    x_m = 0.0  # Straight ahead
                                    z_m = distance_ft * 0.3048  # feet to meters
                                    
                                    try:
                                        # Compute motor deltas from GroundAim
                                        dx_mm, dy_mm = get_motor_deltas_for_ground_hit(x_m, z_m)
                                        
                                        # Use Move macro (same as Aim_Test.py) for relative positioning
                                        # The Move macro handles positioning correctly
                                        print(f"[TRACK] Aiming at {distance_ft:.1f}ft: dx={dx_mm:+.3f}mm, dy={dy_mm:+.3f}mm")
                                        gcode = f"Move x={dx_mm:.3f} y={dy_mm:.3f}"
                                        ws_client.send_gcode(gcode)
                                        
                                        # Wait for aim to settle before starting pattern
                                        time.sleep(0.2)
                                        
                                        # START PATTERN (will own motion from now on)
                                        print(f"[TRACK] Starting deterrence pattern at {distance_ft:.1f}ft")
                                        laser_controller.turn_on()
                                        state.laser_active = True
                                        
                                        start_square_pattern(
                                            ws_client,
                                            target_dist_in=distance_ft * 12.0,
                                            square_size_ft=SQUARE_SIZE_FT,
                                            speed=PATTERN_SPEED,
                                            dwell_ms=PATTERN_DWELL_MS
                                        )
                                        
                                        state.pattern_active = True
                                        state.last_pattern_start_time = current_time
                                        state.last_pattern_distance = distance_ft
                                        
                                    except ValueError as e:
                                        print(f"[TRACK] GroundAim error: {e}")
                                        state.lost_frame_count += 1
            
            # ================================================================
            # DISPLAY
            # ================================================================
            display = frame.copy()
            
            # Draw mode indicator
            mode_color = (0, 255, 0) if state.mode == "TRACK" else (255, 255, 0)
            cv2.putText(display, f"MODE: {state.mode}", (10, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.8, mode_color, 2)
            
            # Draw detection bbox
            if has_target and bbox is not None:
                x1, y1, x2, y2 = bbox
                
                # Color based on class: RED for person, GREEN for bird
                bbox_color = (0, 0, 255) if detected_class == "person" else (0, 255, 0)
                cv2.rectangle(display, (x1, y1), (x2, y2), bbox_color, 2)
                
                # Show class and confidence
                label = f"{detected_class}: {confidence:.2f}"
                cv2.putText(display, label, (x1, y1 - 10),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, bbox_color, 2)
                
                # Draw feet point
                feet_x = (x1 + x2) // 2
                feet_y = y2
                cv2.circle(display, (feet_x, feet_y), 5, (0, 0, 255), -1)
                
                # Show distance estimate
                if state.mode == "TRACK":
                    distance_ft = get_distance(feet_y)
                    cv2.putText(display, f"{distance_ft:.1f}ft", (feet_x + 10, feet_y),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            
            # Draw laser/pattern status
            status_y = 60
            if state.laser_active:
                cv2.putText(display, "LASER: ON", (10, status_y),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
            if state.pattern_active:
                cv2.putText(display, "PATTERN: ACTIVE", (10, status_y + 30),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            
            # Show human warning when person detected
            if detected_class == "person":
                cv2.putText(display, "HUMAN DETECTED - LASER OFF", (10, status_y + 60),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
            
            cv2.imshow(display_window, display)
            
            # Frame rate limiting
            elapsed = time.time() - loop_start
            sleep_time = max(0.001, (1.0 / 30.0) - elapsed)
            time.sleep(sleep_time)
    
    except KeyboardInterrupt:
        print("\n[MAIN] Interrupted by user (Ctrl+C)")
    
    except Exception as e:
        print(f"\n[MAIN] EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # =====================================================================
        # CLEANUP (always executed)
        # =====================================================================
        print("\n[CLEANUP] Shutting down system...")
        
        # Stop pattern
        if ws_client is not None and state.pattern_active:
            try:
                print("[CLEANUP] Stopping deterrence pattern...")
                stop_pattern(ws_client)
            except Exception as e:
                print(f"[CLEANUP] Error stopping pattern: {e}")
        
        # Turn off laser
        if laser_controller is not None:
            try:
                print("[CLEANUP] Turning off laser...")
                laser_controller.turn_off()
            except Exception as e:
                print(f"[CLEANUP] Error turning off laser: {e}")
        
        # Stop camera
        if camera is not None:
            try:
                print("[CLEANUP] Stopping camera...")
                camera.stop()
            except Exception as e:
                print(f"[CLEANUP] Error stopping camera: {e}")
        
        # Close display
        try:
            cv2.destroyAllWindows()
        except:
            pass
        
        # Disconnect Moonraker
        if ws_client is not None:
            try:
                print("[CLEANUP] Disconnecting from Moonraker...")
                ws_client.close()
            except Exception as e:
                print(f"[CLEANUP] Error disconnecting: {e}")
        
        print("[CLEANUP] Shutdown complete")
        print("="*70 + "\n")


if __name__ == "__main__":
    main()
