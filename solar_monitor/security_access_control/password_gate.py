"""Optional shared password for the web pages (Security & Access Control module).

This is only a gate, not Role-Based Access Control. With SOLAR_ADMIN_PASSWORD
set, the browser asks for that password (any username) before showing
anything; without it, anyone on the network can open the app.

Not built yet: user accounts and roles (Admin can switch relays and change
thresholds, Technician can only view and export). When that is added it
belongs in this folder.
"""

import hmac
import os

from flask import Response, request


def install(app, open_paths=()):
    """Protect every address except `open_paths` (the ESP32 uses API keys there)."""

    @app.before_request
    def require_login():
        password = os.environ.get("SOLAR_ADMIN_PASSWORD")
        if not password or request.path in open_paths:
            return None
        auth = request.authorization
        if auth and auth.password and hmac.compare_digest(
                auth.password.encode("utf-8"), password.encode("utf-8")):
            return None
        return Response("Login required.", 401, {"WWW-Authenticate": 'Basic realm="Solar Monitor"'})
