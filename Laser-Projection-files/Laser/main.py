
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import laser controller
from Laser.LaserEnable import LaserController

def main():
    """Simple console interface to control the laser."""
    print("=" * 50)
    print("LASER CONTROL SYSTEM")
    print("=" * 50)
    from Config import network_config as net_cfg
    print(f"ESP32 IP: {net_cfg.ESP32_IP}")
    print("-" * 50)
    
    # Initialize laser controller
    try:
        laser = LaserController()
        print("Laser controller initialized successfully!")
    except Exception as e:
        print(f"Error initializing laser controller: {e}")
        return
    
    # Get initial status
    print("\nChecking laser status...")
    laser.get_status()
    
    print("\n" + "-" * 50)
    print("Commands:")
    print("  'on'   - Turn laser ON")
    print("  'off'  - Turn laser OFF")
    print("  'status' - Check laser status")
    print("  'quit' - Exit program")
    print("-" * 50)
    
    # Main command loop
    while True:
        try:
            command = input("\nEnter command: ").strip().lower()
            
            if command == 'on':
                if laser.turn_on():
                    print("✓ Laser is now ON")
                else:
                    print("✗ Failed to turn laser ON")
            
            elif command == 'off':
                if laser.turn_off():
                    print("✓ Laser is now OFF")
                else:
                    print("✗ Failed to turn laser OFF")
            
            elif command == 'status':
                status = laser.get_status()
                if status:
                    print(f"✓ Current state: {status}")
                else:
                    print("✗ Failed to get status")
            
            elif command in ['quit', 'exit', 'q']:
                print("\nTurning laser OFF before exit...")
                laser.turn_off()
                print("Goodbye!")
                break
            
            else:
                print(f"Unknown command: '{command}'")
                print("Valid commands: on, off, status, quit")
        
        except KeyboardInterrupt:
            print("\n\nCtrl+C detected. Turning laser OFF...")
            laser.turn_off()
            print("Exiting...")
            break
        
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    main()
