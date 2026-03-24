import requests
from typing import Optional
from Config import network_config as net_cfg

ESP32_IP = net_cfg.ESP32_IP
BASE_URL = net_cfg.ESP32_BASE_URL

# Timeout for HTTP requests (in seconds)
REQUEST_TIMEOUT = 2.0


class LaserController:
    """
    Controller for ESP32-based laser system.
    Controls pin 25 on ESP32 via HTTP requests.
    """
    
    def __init__(self, ip_address: str = ESP32_IP):
        """
        Initialize the laser controller.
        
        Args:
            ip_address: IP address of the ESP32 (default: 192.168.8.186)
        """
        self.ip_address = ip_address
        self.base_url = f"http://{ip_address}"
        self._last_state = None
        
    def turn_on(self) -> bool:
        """
        Turn the laser ON (set pin 25 HIGH).
        
        Returns:
            True if successful, False otherwise
        """
        try:
            response = requests.get(
                f"{self.base_url}/high",
                timeout=REQUEST_TIMEOUT
            )
            if response.status_code == 200:
                self._last_state = True
                print(f"Laser turned ON")
                return True
            else:
                print(f"Failed to turn laser ON: HTTP {response.status_code}")
                return False
        except requests.exceptions.RequestException as e:
            print(f"Error turning laser ON: {e}")
            return False
    
    def turn_off(self) -> bool:
        """
        Turn the laser OFF (set pin 25 LOW).
        
        Returns:
            True if successful, False otherwise
        """
        try:
            response = requests.get(
                f"{self.base_url}/low",
                timeout=REQUEST_TIMEOUT
            )
            if response.status_code == 200:
                self._last_state = False
                print(f"Laser turned OFF")
                return True
            else:
                print(f"Failed to turn laser OFF: HTTP {response.status_code}")
                return False
        except requests.exceptions.RequestException as e:
            print(f"Error turning laser OFF: {e}")
            return False
    
    def get_status(self) -> Optional[str]:
        """
        Get the current state of the laser.
        
        Returns:
            "HIGH" or "LOW" if successful, None if failed
        """
        try:
            response = requests.get(
                f"{self.base_url}/status",
                timeout=REQUEST_TIMEOUT
            )
            if response.status_code == 200:
                data = response.json()
                state = data.get("state")
                print(f"Laser status: {state}")
                return state
            else:
                print(f"Failed to get status: HTTP {response.status_code}")
                return None
        except requests.exceptions.RequestException as e:
            print(f"Error getting status: {e}")
            return None
    
    def set_state(self, enable: bool) -> bool:
        """
        Set the laser state.
        
        Args:
            enable: True to turn ON, False to turn OFF
            
        Returns:
            True if successful, False otherwise
        """
        if enable:
            return self.turn_on()
        else:
            return self.turn_off()


# Module-level functions for simple usage
_default_controller = None


def get_controller() -> LaserController:
    """Get or create the default laser controller instance."""
    global _default_controller
    if _default_controller is None:
        _default_controller = LaserController()
    return _default_controller


def laser_on() -> bool:
    """Turn the laser ON. Simple module-level function."""
    return get_controller().turn_on()


def laser_off() -> bool:
    """Turn the laser OFF. Simple module-level function."""
    return get_controller().turn_off()


def laser_status() -> Optional[str]:
    """Get laser status. Simple module-level function."""
    return get_controller().get_status()


# For backward compatibility with old interface
class Controller(LaserController):
    """Legacy class name for backward compatibility."""
    
    def set_laser(self, enable: bool):
        """Legacy method for backward compatibility."""
        self.set_state(enable)


if __name__ == "__main__":
    # Test the laser controller
    print("Testing Laser Controller...")
    print(f"ESP32 IP: {ESP32_IP}")
    print("-" * 40)
    
    controller = LaserController()
    
    # Get initial status
    print("\nChecking initial status:")
    controller.get_status()
    
    # Test turning on
    print("\nTurning laser ON:")
    controller.turn_on()
    
    import time
    time.sleep(1)
    
    # Test turning off
    print("\nTurning laser OFF:")
    controller.turn_off()
    
    print("\nTest complete!")

