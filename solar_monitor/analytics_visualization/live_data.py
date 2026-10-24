"""What the live dashboard shows (Data Analytics & Visualization module).

Both functions read the in-memory state kept by gateway_storage/live_state.py.
"""

import time

from solar_monitor.alerts_notifications import alert_engine
from solar_monitor.gateway_storage import live_state


def live_payload(device):
    st = live_state.get_state(device)
    status, age = live_state.device_status(device)
    with live_state.LOCK:
        return {
            "device": {"id": device["id"], "name": device["name"],
                       "location": device["location"], "simulated": device["simulated"],
                       "enabled": device["enabled"],
                       "sample_interval_s": device["sample_interval_s"]},
            "status": status,
            "age_s": age,
            "reading": dict(st.latest) if st.latest else None,
            "peak_power": round(st.peak_power, 2),
            "energy_wh": round(st.energy_wh, 3),
            "ranges": {k: dict(v) for k, v in st.ranges.items()},
            "day": st.day,
            "alerts": alert_engine.list_alerts("active", 10, device["id"]),
            "server_time": int(time.time()),
        }


def history_payload(device):
    st = live_state.get_state(device)
    with live_state.LOCK:
        return list(st.history)
