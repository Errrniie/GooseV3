# Distance/Calibration.py
"""
Video-based calibration module.
Supports offline video calibration using mouse clicks on distance markers.
"""

import cv2
import sys
import os

# Adjust the Python path to include the root directory of the project
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from Distance.VideoHandler import VideoHandler, draw_video_controls, handle_video_key, resize_for_display
from Distance.Storage import create_calibration


class VideoCalibrator:
    """
    Handles the video calibration process.
    User navigates video and clicks on distance markers to capture Y-pixel values.
    """

    def __init__(self, name, video_path, zoom_label, distances):
        """
        Initialize the calibrator.
        
        Args:
            name: Calibration name
            video_path: Path to the video file
            zoom_label: Label describing the zoom setting
            distances: List of distance values (feet) in increasing order
        """
        self.name = name
        self.video_path = video_path
        self.zoom_label = zoom_label
        self.distances = distances
        
        self.video = None
        self.calibration_points = []
        self.current_distance_idx = 0
        
        # Mouse state
        self.last_click = None  # (x, y) in original frame coords
        self.mouse_pos = None   # Current mouse position for crosshair
        self.display_scale = 1.0  # Scale factor for converting display coords to original
    
    def _mouse_callback(self, event, x, y, flags, param):
        """Handle mouse events."""
        # Convert display coordinates to original frame coordinates
        orig_x = int(x / self.display_scale)
        orig_y = int(y / self.display_scale)
        
        if event == cv2.EVENT_MOUSEMOVE:
            self.mouse_pos = (orig_x, orig_y)
        
        elif event == cv2.EVENT_LBUTTONDOWN:
            if self.current_distance_idx < len(self.distances):
                current_dist = self.distances[self.current_distance_idx]
                y_pixel = orig_y
                
                self.calibration_points.append((y_pixel, current_dist))
                self.current_distance_idx += 1
                self.last_click = (orig_x, orig_y)
                
                print(f"Captured: Y={y_pixel} at {current_dist} ft "
                      f"({len(self.calibration_points)}/{len(self.distances)})")
    
    def _draw_calibration_overlay(self, frame, scale=1.0):
        """Draw calibration-specific overlay on frame (scaled for display)."""
        h, w = frame.shape[:2]
        
        # Draw center line
        cv2.line(frame, (w // 2, 0), (w // 2, h - 40), (200, 200, 200), 1)
        
        # Draw mouse crosshair if available (already in display coords)
        if self.mouse_pos:
            mx = int(self.mouse_pos[0] * scale)
            my = int(self.mouse_pos[1] * scale)
            # Horizontal line
            cv2.line(frame, (0, my), (w, my), (0, 255, 255), 1)
            # Vertical line
            cv2.line(frame, (mx, 0), (mx, h), (0, 255, 255), 1)
            # Display Y coordinate at mouse (show original coords)
            cv2.putText(frame, f"Y: {self.mouse_pos[1]}", (mx + 10, my - 10),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA)
        
        # Draw captured points (scale Y to display)
        for i, (y, dist) in enumerate(self.calibration_points):
            y_scaled = int(y * scale)
            cv2.line(frame, (0, y_scaled), (w, y_scaled), (255, 100, 0), 1)
            cv2.putText(frame, f"{dist}ft", (w - 70, y_scaled - 5),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 100, 0), 1, cv2.LINE_AA)
        
        return frame
    
    def _create_extra_text(self):
        """Create extra text lines for the overlay."""
        lines = []
        
        if self.current_distance_idx < len(self.distances):
            current_dist = self.distances[self.current_distance_idx]
            lines.append(f"CLICK on marker at: {current_dist} ft")
            lines.append(f"Progress: {len(self.calibration_points)}/{len(self.distances)}")
        else:
            lines.append("All points captured!")
            lines.append("[S] Save calibration  [Q] Quit")
        
        return lines
    
    def run(self):
        """
        Run the calibration process.
        
        Returns:
            True if calibration was saved, False if cancelled
        """
        self.video = VideoHandler(self.video_path)
        
        if not self.video.open():
            return False
        
        window_name = f"Calibration: {self.name}"
        cv2.namedWindow(window_name)
        cv2.setMouseCallback(window_name, self._mouse_callback)
        
        print("\n" + "="*60)
        print("VIDEO CALIBRATION MODE")
        print("="*60)
        print("Controls:")
        print("  [CLICK] - Capture point at mouse position")
        print("  [SPACE] - Play/Pause video")
        print("  [<] [>] or [,] [.] - Step frame backward/forward")
        print("  [U] - Undo last capture")
        print("  [S] - Save calibration (when complete)")
        print("  [Q] or [ESC] - Quit without saving")
        print("="*60 + "\n")
        
        try:
            while True:
                frame = self.video.get_frame()
                if frame is None:
                    break
                
                # Resize for display FIRST, then draw overlays for crisp text
                vis_resized, self.display_scale = resize_for_display(frame.copy(), max_width=1280, max_height=720)
                
                # Draw overlays on resized frame (scale geometric elements)
                vis_resized = self._draw_calibration_overlay(vis_resized, scale=self.display_scale)
                extra_text = self._create_extra_text()
                vis_resized = draw_video_controls(vis_resized, self.video, extra_text)
                
                cv2.imshow(window_name, vis_resized)
                
                key = cv2.waitKey(30) & 0xFF
                
                # Handle video controls
                should_quit, action = handle_video_key(key, self.video)
                if should_quit:
                    print("Calibration cancelled.")
                    break
                
                # Handle calibration-specific keys
                elif key == ord('u') or key == ord('U'):
                    self._handle_undo()
                
                elif key == ord('s') or key == ord('S'):
                    if self._handle_save():
                        return True
        
        finally:
            self.video.close()
            cv2.destroyAllWindows()
        
        return False
    
    def _handle_undo(self):
        """Handle undo key press."""
        if self.calibration_points:
            removed = self.calibration_points.pop()
            self.current_distance_idx -= 1
            print(f"Undone: Y={removed[0]} at {removed[1]} ft")
        else:
            print("No points to undo.")
    
    def _handle_save(self):
        """Handle save key press. Returns True if saved successfully."""
        if len(self.calibration_points) < 2:
            print("Need at least 2 calibration points to save.")
            return False
        
        metadata = self.video.get_metadata()
        metadata["source_type"] = "video"
        metadata["zoom_label"] = self.zoom_label
        metadata["resolution"] = {
            "width": metadata.pop("width"),
            "height": metadata.pop("height")
        }
        
        success = create_calibration(
            name=self.name,
            metadata=metadata,
            distance_list=self.distances[:len(self.calibration_points)],
            calibration_points=self.calibration_points
        )
        
        if success:
            print(f"\nCalibration '{self.name}' saved with {len(self.calibration_points)} points.")
        
        return success


def run_video_calibration():
    """
    Interactive function to set up and run a video calibration.
    Prompts user for all required information.
    """
    print("\n" + "="*60)
    print("CREATE NEW VIDEO CALIBRATION")
    print("="*60)
    
    # Get calibration name
    name = input("\nEnter calibration name: ").strip()
    if not name:
        print("Name cannot be empty.")
        return False
    
    # Get video path
    video_path = input("Enter video file path: ").strip()
    if not os.path.isfile(video_path):
        print(f"Video file not found: {video_path}")
        return False
    
    # Get zoom label
    zoom_label = input("Enter zoom label (e.g., '1x', '2x', 'wide'): ").strip()
    if not zoom_label:
        zoom_label = "default"
    
    # Get number of calibration points
    try:
        num_points = int(input("Enter number of calibration points: ").strip())
        if num_points < 2:
            print("Need at least 2 calibration points.")
            return False
    except ValueError:
        print("Invalid number.")
        return False
    
    # Get distance values
    print(f"\nEnter {num_points} distance values (in feet), in increasing order:")
    distances = []
    for i in range(num_points):
        try:
            dist = float(input(f"  Distance {i+1}: ").strip())
            if distances and dist <= distances[-1]:
                print("Distances must be increasing.")
                return False
            distances.append(dist)
        except ValueError:
            print("Invalid distance value.")
            return False
    
    print(f"\nCalibration setup:")
    print(f"  Name: {name}")
    print(f"  Video: {video_path}")
    print(f"  Zoom: {zoom_label}")
    print(f"  Distances: {distances}")
    
    confirm = input("\nProceed with calibration? (y/n): ").strip().lower()
    if confirm != 'y':
        print("Calibration cancelled.")
        return False
    
    # Run calibration
    calibrator = VideoCalibrator(name, video_path, zoom_label, distances)
    return calibrator.run()


# Legacy support - keep old calibration style available
def run_legacy_calibration():
    """Run the original live-camera calibration (kept for backward compatibility)."""
    from Distance.Storage import save_calibration_data
    
    KNOWN_DISTANCES = list(range(10, 70, 5))
    calibration = []
    
    cap = cv2.VideoCapture(4)
    if not cap.isOpened():
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            print("Error: Could not open camera.")
            return
    
    last_click = None
    frame_w, frame_h = None, None

    def mouse_cb(event, x, y, flags, param):
        nonlocal last_click
        if event == cv2.EVENT_LBUTTONDOWN:
            if len(calibration) < len(KNOWN_DISTANCES):
                d = KNOWN_DISTANCES[len(calibration)]
                calibration.append((y, d))
                last_click = (x, y)
                print(f"Captured y={y} at distance={d} ft")

    cv2.namedWindow("calibrate")
    cv2.setMouseCallback("calibrate", mouse_cb)

    while cap.isOpened() and len(calibration) < len(KNOWN_DISTANCES):
        ret, frame = cap.read()
        if not ret:
            break

        if frame_w is None: 
            frame_h, frame_w = frame.shape[:2]

        cx = frame_w // 2
        cv2.line(frame, (cx, 0), (cx, frame_h), (200, 200, 200), 1)

        if last_click is not None:
            cv2.circle(frame, last_click, 5, (0, 0, 255), -1)

        idx = len(calibration)
        if idx < len(KNOWN_DISTANCES):
            label = f"Click ground point at {KNOWN_DISTANCES[idx]} ft"
        else:
            label = "Calibration complete"

        cv2.putText(frame, label, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 
                   1.0, (0, 255, 0), 2, cv2.LINE_AA)
        cv2.imshow("calibrate", frame)

        if cv2.waitKey(1) == 27:
            break

    cap.release()
    cv2.destroyAllWindows()

    if calibration:
        print("Calibration data:", calibration)
        save_calibration_data(calibration)


if __name__ == "__main__":
    run_video_calibration()
