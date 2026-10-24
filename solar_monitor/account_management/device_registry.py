"""Device registry (Account Management module): register an ESP32, give it an API key.

A device is the thing the ESP32 pairs with. It proves who it is by sending its
API key with every reading (see hardware_acquisition/ingest_routes.py).

Not built yet: user accounts, and linking a device to a user by MAC address.
Today every registered device is visible to everyone who can open the app.
"""

import hmac
import secrets

from solar_monitor.gateway_storage.database import connect, now

# ----------------------------------------------------------------- devices
def _device(row):
    if row is None:
        return None
    d = dict(row)
    d["simulated"] = bool(d["simulated"])
    d["enabled"] = bool(d["enabled"])
    return d


def new_api_key():
    return secrets.token_urlsafe(24)


def list_devices():
    with connect() as conn:
        rows = conn.execute("SELECT * FROM devices ORDER BY id").fetchall()
    return [_device(r) for r in rows]


def get_device(device_id):
    with connect() as conn:
        row = conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
    return _device(row)


def get_device_by_key(api_key):
    """Look a device up by API key using a constant-time comparison."""
    if not api_key:
        return None
    for dev in list_devices():
        if hmac.compare_digest(dev["api_key"], api_key):
            return dev
    return None


def device_name_taken(name, exclude_id=None):
    with connect() as conn:
        rows = conn.execute(
            "SELECT id FROM devices WHERE lower(name) = lower(?)", (name,)
        ).fetchall()
    return any(r["id"] != exclude_id for r in rows)


def create_device(name, location="", simulated=False, sample_interval_s=5, rated_watts=50.0):
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO devices (name, location, api_key, simulated, sample_interval_s,"
            " rated_watts, created_at) VALUES (?,?,?,?,?,?,?)",
            (name, location, new_api_key(), 1 if simulated else 0,
             int(sample_interval_s), float(rated_watts), now()),
        )
        device_id = cur.lastrowid
    return get_device(device_id)


_EDITABLE = {"name", "location", "enabled", "sample_interval_s", "rated_watts"}


def update_device(device_id, **fields):
    fields = {k: v for k, v in fields.items() if k in _EDITABLE}
    if not fields:
        return get_device(device_id)
    if "enabled" in fields:
        fields["enabled"] = 1 if fields["enabled"] else 0
    cols = ", ".join("%s = ?" % k for k in fields)
    with connect() as conn:
        conn.execute("UPDATE devices SET %s WHERE id = ?" % cols,
                     list(fields.values()) + [device_id])
    return get_device(device_id)


def regenerate_key(device_id):
    with connect() as conn:
        conn.execute("UPDATE devices SET api_key = ? WHERE id = ?", (new_api_key(), device_id))
    return get_device(device_id)


def delete_device(device_id):
    with connect() as conn:
        conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))


def save_runtime(device_id, last_seen, firmware=None, ip=None, rssi=None, uptime_s=None):
    """Persist "last seen" and device info so they survive a restart."""
    with connect() as conn:
        conn.execute(
            "UPDATE devices SET last_seen = ?, firmware = COALESCE(?, firmware),"
            " ip = COALESCE(?, ip), rssi = COALESCE(?, rssi),"
            " uptime_s = COALESCE(?, uptime_s) WHERE id = ?",
            (int(last_seen), firmware, ip, rssi, uptime_s, device_id),
        )

