#!/usr/bin/env python3
"""
Example client: pair with the Jetson Control API (POST /system/handshake).

Usage (from laptop, after you know Jetson IP or mDNS):
  python3 handshake_client_example.py http://192.168.1.50:8000

Uses only the standard library. Sends this machine's IPv4 as client_ip;
response JSON includes jetson_ip to store on the client side.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import urllib.error
import urllib.request


def _primary_ipv4() -> str | None:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("203.0.113.1", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="POST /system/handshake to GooseV3 Jetson")
    parser.add_argument(
        "base_url",
        help="Control API base URL, e.g. http://10.0.0.5:8000",
    )
    parser.add_argument(
        "--client-ip",
        dest="client_ip",
        default=None,
        help="Override client IPv4 (default: auto-detect)",
    )
    args = parser.parse_args()

    client_ip = args.client_ip or _primary_ipv4()
    if not client_ip:
        print("Could not determine client IPv4; pass --client-ip", file=sys.stderr)
        sys.exit(1)

    base = args.base_url.rstrip("/")
    url = f"{base}/system/handshake"
    body = json.dumps({"client_ip": client_ip}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(e.read().decode("utf-8", errors="replace"), file=sys.stderr)
        sys.exit(e.code)
    except urllib.error.URLError as e:
        print(f"Request failed: {e}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(data, indent=2))
    jetson = data.get("jetson_ip")
    if jetson:
        print(f"\nStore Jetson IP on this machine: {jetson}")


if __name__ == "__main__":
    main()
