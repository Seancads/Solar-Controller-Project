"""The path every reading takes (Local Gateway & Storage module).

Every reading - from a real ESP32 posting to /api/ingest or from the built-in
simulator - goes through `ingest()`. That one function:

  1. updates the live state the dashboard shows (latest value, today's peak,
     min/max, energy)               -> live_state.py
  2. logs a reading to the database every `log_interval_s` seconds
                                    -> database.py
  3. hands the reading to the alert engine
                                    -> alerts_notifications/alert_engine.py

Values must already be validated (hardware_acquisition/reading_validation.py).
Because the simulator uses the same path as a real device, replacing it with
your ESP32 changes nothing else in the system.
"""

import logging
import time
from datetime import datetime

from solar_monitor.account_management import device_registry
from solar_monitor.alerts_notifications import alert_engine
from solar_monitor.gateway_storage import database, live_state

log = logging.getLogger("solar.ingest")


_settings_cache = {"at": 0, "value": None}


def logging_settings():
    now = time.time()
    if _settings_cache["value"] is None or now - _settings_cache["at"] > 5:
        _settings_cache["value"] = database.get_logging_settings()
        _settings_cache["at"] = now
    return _settings_cache["value"]


def invalidate_settings():
    _settings_cache["value"] = None


def ingest(device, voltage, current, power=None, meta=None, now_ts=None):
    """Process one reading. Values must already be validated."""
    ts = time.time() if now_ts is None else now_ts
    meta = meta or {}
    if power is None:
        power = voltage * current
    reading = {
        "ts": int(ts),
        "timestamp": datetime.fromtimestamp(ts).strftime("%H:%M:%S"),
        "voltage": round(voltage, 2),
        "current": round(current, 2),
        "power": round(power, 2),
    }
    to_log = None

    with live_state.LOCK:
        st = live_state.get_state(device)
        day, day_start, day_end = live_state.day_bounds(ts)
        if st.day != day:
            st.start_day(day, day_start, day_end)

        # Energy = power x time. A long gap (device was offline) is NOT
        # integrated, otherwise reconnecting would invent hours of energy.
        if st.last_ts is not None:
            gap = ts - st.last_ts
            if 0 < gap <= max(3 * device["sample_interval_s"], 10):
                added = power * gap / 3600.0
                st.energy_wh += added
                st.energy_since_log += added
        st.last_ts = ts

        if power > st.peak_power:
            st.peak_power = power
        for key, value in (("voltage", voltage), ("current", current), ("power", power)):
            r = st.ranges[key]
            if r["min"] is None or value < r["min"]:
                r["min"] = value
            if r["max"] is None or value > r["max"]:
                r["max"] = value

        st.last_seen = ts
        for attr in ("firmware", "ip", "rssi", "uptime_s"):
            if meta.get(attr) is not None:
                setattr(st, attr, meta[attr])
        st.history.append(reading)
        st.latest = reading

        interval = logging_settings()["log_interval_s"]
        if st.last_log_ts is None or ts - st.last_log_ts >= interval:
            to_log = (st.energy_since_log, st.firmware, st.ip, st.rssi, st.uptime_s)
            st.energy_since_log = 0.0
            st.last_log_ts = ts

    if to_log:
        try:
            database.insert_reading(device["id"], ts, voltage, current, power, to_log[0])
            device_registry.save_runtime(device["id"], ts, to_log[1], to_log[2], to_log[3], to_log[4])
        except Exception:
            # Logging trouble (e.g. disk full) must not stop live monitoring.
            log.exception("Could not log reading for device %s", device["id"])

    try:
        alert_engine.evaluate_reading(device, reading)
    except Exception:
        log.exception("Alert evaluation failed for device %s", device["id"])
    return reading
