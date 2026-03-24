# Distance/VideoHandler.py
"""
Video playback handler with controls for calibration and testing.
Supports play/pause, step frame, and seeking.
"""

import cv2
import time


class VideoHandler:
    """Handles video file playback with interactive controls."""

    def __init__(self, video_path):
        """
        Initialize video handler.
        
        Args:
            video_path: Path to the video file
        """
        self.video_path = video_path
        self.cap = None
        self.is_paused = True  # Start paused for calibration
        self.current_frame = None
        self.frame_number = 0
        self.total_frames = 0
        self.fps = 30.0
        self.width = 0
        self.height = 0
        self._last_frame_time = 0
        
    def open(self):
        """Open the video file. Returns True on success."""
        self.cap = cv2.VideoCapture(self.video_path)
        if not self.cap.isOpened():
            print(f"Error: Could not open video file: {self.video_path}")
            return False
        
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
        self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.frame_number = 0
        
        # Read first frame
        self._read_next_frame()
        
        print(f"Video opened: {self.width}x{self.height} @ {self.fps:.1f} fps, {self.total_frames} frames")
        return True
    
    def close(self):
        """Release video resources."""
        if self.cap:
            self.cap.release()
            self.cap = None
    
    def _read_next_frame(self):
        """Read the next frame from the video."""
        if self.cap is None:
            return False
        
        ret, frame = self.cap.read()
        if ret:
            self.current_frame = frame
            self.frame_number = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES))
            return True
        return False
    
    def get_frame(self):
        """
        Get the current frame based on playback state.
        If playing, advances to next frame at proper FPS.
        If paused, returns current frame.
        
        Returns:
            Current frame or None if video ended
        """
        if self.cap is None:
            return None
        
        if self.is_paused:
            return self.current_frame
        
        # Control playback speed
        current_time = time.time()
        frame_interval = 1.0 / self.fps
        
        if current_time - self._last_frame_time >= frame_interval:
            if not self._read_next_frame():
                # Video ended, loop back to start
                self.seek_frame(0)
            self._last_frame_time = current_time
        
        return self.current_frame
    
    def toggle_pause(self):
        """Toggle play/pause state."""
        self.is_paused = not self.is_paused
        self._last_frame_time = time.time()
        return self.is_paused
    
    def step_forward(self, num_frames=1):
        """Step forward by specified number of frames."""
        if not self.is_paused:
            self.is_paused = True
        
        target_frame = min(self.frame_number + num_frames, self.total_frames - 1)
        if target_frame != self.frame_number:
            self.seek_frame(target_frame)
        return self.current_frame
    
    def step_backward(self, num_frames=1):
        """Step backward by specified number of frames."""
        if not self.is_paused:
            self.is_paused = True
        
        # Current frame_number is the frame we just read, so go back from there
        target_frame = max(self.frame_number - num_frames - 1, 0)
        self.seek_frame(target_frame)
        return self.current_frame
    
    def seek_frame(self, frame_num):
        """Seek to a specific frame number."""
        if self.cap is None:
            return False
        
        frame_num = max(0, min(frame_num, self.total_frames - 1))
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
        return self._read_next_frame()
    
    def seek_percent(self, percent):
        """Seek to a percentage of the video (0-100)."""
        frame_num = int((percent / 100.0) * self.total_frames)
        return self.seek_frame(frame_num)
    
    def get_metadata(self):
        """Get video metadata as a dictionary."""
        return {
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "total_frames": self.total_frames,
            "source_path": self.video_path
        }
    
    def get_progress_percent(self):
        """Get current playback position as percentage."""
        if self.total_frames == 0:
            return 0
        return (self.frame_number / self.total_frames) * 100
    
    def is_open(self):
        """Check if video is currently open."""
        return self.cap is not None and self.cap.isOpened()


def draw_video_controls(frame, video_handler, extra_text=None):
    """
    Draw video control overlay on frame.
    This should be called on the already-resized display frame for crisp text.
    
    Args:
        frame: Frame to draw on (will be modified) - should be display-sized
        video_handler: VideoHandler instance
        extra_text: Optional list of extra text lines to display
    
    Returns:
        Modified frame
    """
    h, w = frame.shape[:2]
    
    # Draw progress bar at bottom
    bar_height = 16
    bar_y = h - bar_height - 8
    bar_x = 10
    bar_width = w - 20
    
    # Background bar
    cv2.rectangle(frame, (bar_x, bar_y), (bar_x + bar_width, bar_y + bar_height), (50, 50, 50), -1)
    
    # Progress fill
    progress = video_handler.get_progress_percent() / 100.0
    fill_width = int(bar_width * progress)
    cv2.rectangle(frame, (bar_x, bar_y), (bar_x + fill_width, bar_y + bar_height), (0, 200, 0), -1)
    
    # Border
    cv2.rectangle(frame, (bar_x, bar_y), (bar_x + bar_width, bar_y + bar_height), (255, 255, 255), 1)
    
    # Frame counter
    frame_text = f"Frame: {video_handler.frame_number}/{video_handler.total_frames}"
    cv2.putText(frame, frame_text, (bar_x, bar_y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    
    # Play/Pause indicator
    status = "PAUSED" if video_handler.is_paused else "PLAYING"
    status_color = (0, 255, 255) if video_handler.is_paused else (0, 255, 0)
    cv2.putText(frame, status, (w - 90, bar_y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, status_color, 1, cv2.LINE_AA)
    
    # Control hints at top
    controls = "[SPACE] Pause  [,/.] x1  [A/D] x5  [J/L] x30  [;/'] x60  [Q] Quit"
    cv2.putText(frame, controls, (10, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1, cv2.LINE_AA)
    
    # Extra text lines
    if extra_text:
        y_offset = 45
        for line in extra_text:
            cv2.putText(frame, line, (10, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2, cv2.LINE_AA)
            y_offset += 28
    
    return frame


def handle_video_key(key, video_handler):
    """
    Handle common video control keys.
    
    Args:
        key: Key code from cv2.waitKey
        video_handler: VideoHandler instance
    
    Returns:
        Tuple of (should_quit, action_taken)
        action_taken is one of: 'pause', 'step_forward', 'step_backward', 
                                'fast_forward', 'fast_backward', 'quit', None
    """
    # Quit keys
    if key in [ord('q'), ord('Q'), 27]:  # Q or ESC
        return True, 'quit'
    
    # Play/Pause
    if key == ord(' '):  # Space
        video_handler.toggle_pause()
        return False, 'pause'
    
    # Step forward (1 frame): . or Right arrow
    # Arrow key codes vary by platform, common ones: 83 (Linux), 2555904 (Windows right)
    elif key == ord('.') or key == 83 or key == 0:  
        video_handler.step_forward(1)
        return False, 'step_forward'
    
    # Step backward (1 frame): , or Left arrow
    elif key == ord(',') or key == 81 or key == 1:
        video_handler.step_backward(1)
        return False, 'step_backward'
    
    # Fast forward (30 frames / ~1 sec): > or Shift+Right or ]
    elif key == ord('>') or key == ord(']') or key == ord('l') or key == ord('L'):
        video_handler.step_forward(30)
        return False, 'fast_forward'
    
    # Fast backward (30 frames / ~1 sec): < or Shift+Left or [
    elif key == ord('<') or key == ord('[') or key == ord('j') or key == ord('J'):
        video_handler.step_backward(30)
        return False, 'fast_backward'
    
    # Jump forward (5 frames): d or D
    elif key == ord('d') or key == ord('D'):
        video_handler.step_forward(5)
        return False, 'step_forward'
    
    # Jump backward (5 frames): a or A
    elif key == ord('a') or key == ord('A'):
        video_handler.step_backward(5)
        return False, 'step_backward'
    
    # Big jump forward (60 frames / ~2 sec): ' or "
    elif key == ord("'") or key == ord('"'):
        video_handler.step_forward(60)
        return False, 'fast_forward'
    
    # Big jump backward (60 frames / ~2 sec): ; or :
    elif key == ord(';') or key == ord(':'):
        video_handler.step_backward(60)
        return False, 'fast_backward'
    
    return False, None


def resize_for_display(frame, max_width=1280, max_height=720):
    """
    Resize a frame to fit within max dimensions while preserving aspect ratio.
    
    Args:
        frame: The frame to resize
        max_width: Maximum display width (default 1280)
        max_height: Maximum display height (default 720)
    
    Returns:
        Tuple of (resized_frame, scale_factor)
        scale_factor can be used to convert display coords back to original coords
    """
    if frame is None:
        return None, 1.0
    
    h, w = frame.shape[:2]
    
    # Calculate scale factor to fit within max dimensions
    scale_w = max_width / w
    scale_h = max_height / h
    scale = min(scale_w, scale_h, 1.0)  # Don't upscale, only downscale
    
    if scale >= 1.0:
        return frame, 1.0
    
    new_w = int(w * scale)
    new_h = int(h * scale)
    
    resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
    return resized, scale
