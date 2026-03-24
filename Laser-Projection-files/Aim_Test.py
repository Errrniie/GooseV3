"""
Aim_Test.py - Unified Laser Aiming Test

This is a clean implementation that uses GroundAim as the SINGLE source of truth
for all aiming calculations. No duplicate geometry, no angle tracking hacks.

Pipeline:
1. Input: distance in inches
2. Convert: inches → meters
3. Compute: GroundAim.get_motor_deltas_for_ground_hit(x_m=0, z_m=distance_m)
4. Command: Absolute motor position = neutral + delta
5. Send: G1 X{x_mm} Y{y_mm} to Klipper

All geometry, half-angle physics, and roll compensation live ONLY in GroundAim.
"""

import math
import time
import serial
import threading
import re

from Motion.Moonraker_ws_v2 import MoonrakerWSClient
from Motion.Home import home
from Laser.LaserEnable import LaserController
import Laser.GroundAim as GroundAim
from Laser.Calibration import (
    LASER_HEIGHT_M,
    print_calibration_summary
)
from Config import network_config as net_cfg

# ESP32 IMU settings (Serial)
ESP32_SERIAL_PORT = "/dev/ttyUSB1"
ESP32_BAUD_RATE = 115200

# IMU mounting offset: The roll reading when platform is actually level
# If IMU reads 90° when platform is level (off-axis mounting), set this to 90.0
ROLL_OFFSET_DEG = 90.0

# =============================================================================
# UNIT CONVERSION HELPERS
# =============================================================================

def inches_to_meters(inches: float) -> float:
    """Convert inches to meters."""
    return inches * 0.0254

def feet_to_meters(feet: float) -> float:
    """Convert feet to meters."""
    return feet * 0.3048

# =============================================================================
# ESP32 IMU READER (Serial) - Updates GroundAim.PLATFORM_ROLL_RAD
# =============================================================================

def esp32_reader_thread(serial_port: str, stop_event: threading.Event, 
                        connection_status: dict) -> None:
    """
    Background thread that reads ESP32 serial data and updates GroundAim.PLATFORM_ROLL_RAD.
    
    Roll compensation is applied ONLY inside GroundAim - this thread just provides the data.
    
    Expected serial format: PITCH:XX.XX,ROLL:YY.YY
    """
    print(f"[IMU] Connecting to ESP32 on {serial_port}...")
    
    try:
        ser = serial.Serial(serial_port, ESP32_BAUD_RATE, timeout=1)
        time.sleep(0.5)
        print(f"[IMU] ✓ Connected on {serial_port}")
        connection_status['connected'] = True
        
        pattern = re.compile(r'PITCH:([\-\d.]+),ROLL:([\-\d.]+)')
        
        while not stop_event.is_set():
            try:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if not line:
                    continue
                    
                match = pattern.search(line)
                if match:
                    roll_deg = float(match.group(2))
                    
                    # Apply offset for off-axis IMU mounting
                    effective_roll_deg = roll_deg - ROLL_OFFSET_DEG
                    roll_rad = math.radians(effective_roll_deg)
                    
                    # Update GroundAim module (the ONLY place roll compensation is applied)
                    GroundAim.PLATFORM_ROLL_RAD = roll_rad
                    
            except (UnicodeDecodeError, ValueError):
                continue
                
        ser.close()
        print("[IMU] Thread stopped.")
        
    except serial.SerialException as e:
        print(f"[IMU] ✗ Connection failed: {e}")
        connection_status['connected'] = False

# =============================================================================
# MOTOR COMMAND HELPERS
# =============================================================================

def move_relative(ws: MoonrakerWSClient, dx_mm: float, dy_mm: float) -> None:
    """
    Send relative position command to Klipper using Move macro.
    """
    gcode = f"Move x={dx_mm:.3f} y={dy_mm:.3f}"
    ws.send_gcode(gcode)

# =============================================================================
# MAIN AIMING LOOP
# =============================================================================

def main():
    # Print calibration summary on startup for verification
    print_calibration_summary()
    
    print("=" * 70)
    print("LASER AIM TEST - Unified GroundAim Pipeline")
    print("=" * 70)
    
    # Connect to Moonraker
    ws = MoonrakerWSClient(net_cfg.MOONRAKER_WS_URL)
    ws.connect()
    
    # Initialize laser controller
    laser = LaserController()
    
    # Start ESP32 IMU reader thread
    stop_event = threading.Event()
    connection_status = {'connected': False}
    esp32_thread = threading.Thread(
        target=esp32_reader_thread,
        args=(ESP32_SERIAL_PORT, stop_event, connection_status),
        daemon=True
    )
    esp32_thread.start()
    time.sleep(2)
    
    if not connection_status['connected']:
        print("\n" + "=" * 70)
        print("ERROR: ESP32 IMU not available. Roll compensation disabled.")
        print("Continuing without IMU - accuracy may be affected.")
        print("=" * 70 + "\n")
    else:
        print(f"[IMU] ✓ Roll compensation active")
    
    # Home motors
    print("\n[INIT] Homing motors...")
    try:
        home(ws, timeout=30.0)
        print("[INIT] ✓ Homing complete")
    except Exception as e:
        print(f"[INIT] ✗ Homing failed: {e}")
        ws.close()
        return
    
    # Turn on laser
    print("[INIT] Turning laser ON...")
    if laser.turn_on():
        print("[INIT] ✓ Laser ON")
    else:
        print("[INIT] ✗ Laser failed to turn on")
        ws.close()
        return
    
    # Track last commanded deltas for relative positioning
    last_dy_mm = 0.0
    last_dx_mm = 0.0
    
    print("\n" + "=" * 70)
    print("READY - Commands:")
    print("  <number>     - Aim at distance in inches")
    print("  p <dist> <size> - Start square pattern (dist=inches, size=feet)")
    print("  s            - Stop pattern")
    print("  Ctrl+C       - Quit")
    print("=" * 70)
    
    # Import pattern functions (lazy import to avoid circular deps)
    from Laser.DeterrencePattern import start_square_pattern, stop_pattern
    
    # Main loop
    while True:
        try:
            user_input = input("\nCommand: ").strip().lower()
        except KeyboardInterrupt:
            break
        
        if not user_input:
            continue
        
        # Parse command
        parts = user_input.split()
        cmd = parts[0]
        
        # Stop pattern command
        if cmd == 's':
            stop_pattern(ws)
            continue
        
        # Pattern command: p <distance> <size>
        if cmd == 'p':
            if len(parts) < 2:
                print("Usage: p <distance_inches> [size_feet]")
                print("  Example: p 140 0.5")
                continue
            try:
                dist = float(parts[1])
                size = float(parts[2]) if len(parts) > 2 else 0.5
                start_square_pattern(ws, dist, size)
            except ValueError:
                print("Invalid numbers.")
            continue
        
        # Direct aim command (just a number)
        try:
            dist_inches = float(cmd)
        except ValueError:
            print("Unknown command. Use a number, 'p <dist> <size>', or 's'.")
            continue
        
        if dist_inches <= 0:
            print("Distance must be positive.")
            continue
        
        # =====================================================================
        # UNIFIED AIMING PIPELINE
        # =====================================================================
        
        # Step 1: Convert inches → meters
        z_m = inches_to_meters(dist_inches)
        x_m = 0.0  # Straight ahead
        
        # Step 2: Get motor deltas from GroundAim (THE source of truth)
        # This handles: geometry, half-angle physics, roll compensation, unit conversion
        try:
            dx_mm, dy_mm = GroundAim.get_motor_deltas_for_ground_hit(x_m, z_m)
        except ValueError as e:
            print(f"Error: {e}")
            continue
        
        # Step 3: Compute relative move from current position
        # dy_mm is the delta from neutral needed to hit target
        # We need to move from last position to new position
        rel_dx = dx_mm - last_dx_mm
        rel_dy = dy_mm - last_dy_mm
        
        # Step 4: Validation logging
        print(f"\n[AIMING] ─────────────────────────────────────────────────────")
        print(f"  Input distance:     {dist_inches:.1f} inches = {z_m:.4f} m")
        print(f"  Platform roll:      {math.degrees(GroundAim.PLATFORM_ROLL_RAD):.2f}°")
        print(f"  Motor deltas:       ΔX={dx_mm:+.3f} mm, ΔY={dy_mm:+.3f} mm")
        print(f"  Relative move:      ΔX={rel_dx:+.3f} mm, ΔY={rel_dy:+.3f} mm")
        print(f"───────────────────────────────────────────────────────────────")
        
        # Step 5: Send relative position command
        move_relative(ws, rel_dx, rel_dy)
        
        # Update tracking
        last_dx_mm = dx_mm
        last_dy_mm = dy_mm
        
        time.sleep(0.1)
    
    # Cleanup
    print("\n" + "=" * 70)
    print("Shutting down...")
    stop_event.set()
    laser.turn_off()
    time.sleep(0.3)
    ws.close()
    print("✓ Disconnected. Laser OFF.")
    print("=" * 70)

if __name__ == "__main__":
    main()
