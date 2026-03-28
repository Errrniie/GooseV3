"""
Best-effort primary IPv4 for this host (non-loopback).

Uses a UDP socket "route" probe so no packets need to leave the LAN.

Ethernet IPv4 skips Wi-Fi by excluding interfaces that expose
``/sys/class/net/<iface>/wireless`` (Linux).
"""

from __future__ import annotations

import fcntl
import re
import socket
import struct
import subprocess
import sys
from pathlib import Path


def get_primary_ipv4() -> str | None:
    """
    Return the IPv4 address used for default outbound traffic, or None if unknown.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("203.0.113.1", 80))
            addr = s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return None
    if not addr or addr.startswith("127."):
        return None
    return addr


# Linux: SIOCGIFADDR — IPv4 address assigned to an interface
_SIOCGIFADDR = 0x8915


def _ipv4_for_interface_linux(ifname: str) -> str | None:
    if sys.platform != "linux":
        return None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            packed = struct.pack(
                "256s",
                ifname.encode("utf-8")[:15].ljust(256, b"\0"),
            )
            res = fcntl.ioctl(s.fileno(), _SIOCGIFADDR, packed)
        finally:
            s.close()
    except OSError:
        return None
    # sockaddr_in.sin_addr at offset 20 after struct ifreq name (x86 layout)
    return socket.inet_ntoa(res[20:24])


def _ipv4_via_ip_addr(ifname: str) -> str | None:
    """Fallback: parse ``ip -4 -o addr show dev <iface>`` (BusyBox/full ip)."""
    try:
        out = subprocess.check_output(
            ["ip", "-4", "-o", "addr", "show", "dev", ifname],
            text=True,
            timeout=3,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)/", out)
    return m.group(1) if m else None


def _ethernet_interface_names() -> list[str]:
    """Interface names that are not loopback, not Wi-Fi, not typical virtual bridges."""
    net_path = Path("/sys/class/net")
    if not net_path.is_dir():
        return []
    names: list[str] = []
    for p in sorted(net_path.iterdir()):
        name = p.name
        if name == "lo":
            continue
        if name.startswith(("docker", "br-", "veth", "virbr")):
            continue
        if (p / "wireless").exists():
            continue
        names.append(name)
    return names


def _ordered_ethernet_names(candidates: list[str]) -> list[str]:
    """Prefer eth*, then en*, then the rest (stable order)."""
    preferred: list[str] = []
    for prefix in ("eth", "eno", "enp", "ens"):
        preferred.extend(
            sorted(n for n in candidates if n.startswith(prefix))
        )
    rest = sorted(n for n in candidates if n not in preferred)
    return preferred + rest


def get_ethernet_ipv4() -> str | None:
    """
    IPv4 on a non-Wi-Fi interface (best effort on Linux).

    Excludes interfaces that have ``.../wireless`` under sysfs (e.g. ``wlan0``).
    Tries physical-style names first (``eth0``, ``eno*``, ``enp*``, ...).
    """
    candidates = _ethernet_interface_names()
    if not candidates:
        return None
    for ifname in _ordered_ethernet_names(candidates):
        ip = _ipv4_for_interface_linux(ifname)
        if not ip or ip.startswith("127."):
            ip = _ipv4_via_ip_addr(ifname)
        if ip and not ip.startswith("127."):
            return ip
    return None
