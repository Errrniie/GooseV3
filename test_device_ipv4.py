#!/usr/bin/env python3
"""Print this device's primary IPv4 (for quick checks). Run from project root."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from Networking.Local_IP import get_ethernet_ipv4


def main() -> None:
    ip = get_ethernet_ipv4()
    if ip:
        print(ip)
    else:
        print(
            "Could not determine Ethernet IPv4 (no non-Wi-Fi interface with an address?).",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
