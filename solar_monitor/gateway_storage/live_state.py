"""What each device is doing right now, kept in memory (Local Gateway & Storage module).

The dashboard reads from here, not from the database: latest reading, a short
history for the live chart, today's peak/min/max/energy, and whether the
device is online. Readings get here through ingest_pipeline.ingest().
"""

import threading
import time
from collections import deque
from datetime import timedelta

from solar_monitor.gateway_storage import database
from solar_monitor.time_utils import start_of_day

HISTORY_POINTS = 600          # 10 minutes even at one reading per second
LOCK = threading.RLock()
_states = {}


def day_bounds(ts):
    """("YYYY-MM-DD", start_ts, end_ts) of the local calendar day containing ts."""
    start = start_of_day(ts)
    end = start + timedelta(days=1)
    return start.strftime("%Y-%m-%d"), start.timestamp(), end.timestamp()


class DeviceState(object):
    """Everything the dashboard needs for one device, kept in memory."""

    def __init__(self, device):
        self.device_id = device["id"]
        self.history = deque(maxlen=HISTORY_POINTS)
        self.latest = None
        self.last_seen = device.get("last_seen")
        self.firmware = device.get("firmware")
        self.ip = device.get("ip")
        self.rssi = device.get("rssi")
        self.uptime_s = device.get("uptime_s")
        self.last_ts = None             # previous reading, for energy integration
        self.last_log_ts = None
        self.energy_since_log = 0.0
        self.day = None
        self._reset_day_values()

    def _reset_day_values(self):
        self.peak_power = 0.0
        self.energy_wh = 0.0
        self.ranges = {k: {"min": None, "max": None} for k in ("voltage", "current", "power")}

    def start_day(self, day, start_ts, end_ts):
        """Begin tracking a new calendar day, restoring whatever was already
        logged today (so a restart doesn't zero the dashboard)."""
        self.day = day
        self._reset_day_values()
        self.energy_since_log = 0.0
        stats = database.day_stats(self.device_id, start_ts, end_ts)
        if stats["n"]:
            self.peak_power = stats["max_p"] or 0.0
            self.energy_wh = stats["energy_wh"] or 0.0
            self.ranges = {
                "voltage": {"min": stats["min_v"], "max": stats["max_v"]},
                "current": {"min": stats["min_i"], "max": stats["max_i"]},
                "power": {"min": stats["min_p"], "max": stats["max_p"]},
            }
            self.last_log_ts = stats["last_ts"]


def get_state(device):
    with LOCK:
        st = _states.get(device["id"])
        if st is None:
            st = _states[device["id"]] = DeviceState(device)
        return st



def forget_device(device_id):
    with LOCK:
        _states.pop(device_id, None)


def reset_all():
    """Drop all in-memory state (used by tests)."""
    with LOCK:
        _states.clear()


def online_window(device):
    """Seconds without data before a device is shown as offline."""
    return max(10, 3 * device["sample_interval_s"] + 2)


def last_seen(device):
    """When this device last sent data. Uses the live in-memory value; the
    database copy is only refreshed when a reading is logged (every
    `log_interval_s`), so on its own it can look up to a minute stale."""
    st = _states.get(device["id"])
    if st and st.last_seen:
        return st.last_seen
    return device.get("last_seen")


def device_status(device, now=None):
    """Return (status, age_seconds). status is online/offline/never/disabled."""
    now = time.time() if now is None else now
    if not device["enabled"]:
        return "disabled", None
    last = last_seen(device)
    if not last:
        return "never", None
    age = max(0, now - last)
    return ("online" if age <= online_window(device) else "offline"), int(age)


def device_snapshot(device):
    """Small summary used on the devices page."""
    st = get_state(device)
    status, age = device_status(device)
    with LOCK:
        return {
            "status": status, "age_s": age,
            "reading": dict(st.latest) if st.latest else None,
            "firmware": st.firmware, "ip": st.ip, "rssi": st.rssi, "uptime_s": st.uptime_s,
            "last_seen": int(st.last_seen) if st.last_seen else None,
        }
