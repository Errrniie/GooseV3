from Motion.Moonraker_ws_v2 import MoonrakerWSClient
import time


def home(ws_client: MoonrakerWSClient, timeout: float = 30.0) -> None:
    """
    Perform a full homing cycle.
    Blocking. Explicit use only (INIT / SHUTDOWN).
    
    Uses synchronous RPC call which blocks until G28 completes.
    """
    # Send homing command via blocking RPC call
    ws_client.call(
        "printer.gcode.script",
        {"script": "G28"},
        timeout_s=timeout
    )
    
    # Brief pause to ensure printer state settles
    time.sleep(0.5)