"""Little helpers used by the route files of several modules."""

from flask import jsonify, request

from solar_monitor.account_management import device_registry


def err(message, status=400):
    return jsonify({"error": message}), status


def int_arg(name, default, low, high):
    """A whole-number query parameter, clamped to [low, high]."""
    try:
        value = int(request.args.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


def device_from_args():
    """The device named by ?device=ID, or the first enabled one."""
    devices = device_registry.list_devices()
    raw = request.args.get("device")
    if raw is not None:
        try:
            wanted = int(raw)
        except ValueError:
            return None
        return next((d for d in devices if d["id"] == wanted), None)
    enabled = [d for d in devices if d["enabled"]]
    return (enabled or devices or [None])[0]
