"""Finding this computer's address, so an ESP32 on the same network can reach it."""

import socket

from flask import request

from solar_monitor import config


def lan_ip():
    """This computer's address on the local network (what the ESP32 must use)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))          # no packet is actually sent
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "YOUR_COMPUTER_IP"


def server_base_url():
    """URL the ESP32 should use. 'localhost' would point at the ESP32 itself,
    so swap it for this computer's LAN address."""
    host = request.host
    name, _, port = host.partition(":")
    if name in ("localhost", "127.0.0.1") or host.startswith("[::1]"):
        host = "%s:%s" % (lan_ip(), port or config.port())
    return "%s://%s" % (request.scheme, host)
