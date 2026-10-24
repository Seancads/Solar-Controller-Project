"""Analytics from what was actually logged (Data Analytics & Visualization module).

Same shape as demo_data.py, so the Analytics page can show either source.
"""

import time
from datetime import timedelta

from solar_monitor.gateway_storage import database
from solar_monitor.time_utils import start_of_day


def daily_aggregates(device, days, today=None):
    """One record per local calendar day that has logged data, shaped like
    the simulated history so the Analytics page can use either."""
    today_dt = start_of_day(time.time() if today is None else today)
    start = (today_dt - timedelta(days=days - 1)).timestamp()
    interval = database.get_logging_settings()["log_interval_s"]
    with database.connect() as conn:
        rows = conn.execute(
            "SELECT date(ts, 'unixepoch', 'localtime') AS day, MAX(power) AS peak,"
            " COALESCE(SUM(energy_wh), 0) AS energy,"
            " AVG(CASE WHEN power >= 1 THEN power END) AS avg_p,"
            " AVG(CASE WHEN power >= 1 THEN voltage END) AS avg_v,"
            " SUM(CASE WHEN power >= 1 THEN 1 ELSE 0 END) AS producing"
            " FROM readings WHERE device_id = ? AND ts >= ? GROUP BY day ORDER BY day",
            (device["id"], int(start))).fetchall()
    today_text = today_dt.strftime("%Y-%m-%d")
    out = []
    for r in rows:
        avg_p = r["avg_p"] or 0.0
        out.append({
            "date": r["day"],
            "peak_power_w": round(r["peak"] or 0, 1),
            "avg_power_w": round(avg_p, 1),
            "total_energy_wh": round(r["energy"], 1),
            "avg_voltage": round(r["avg_v"] or 0, 2),
            # Approximate: how many logged readings showed output x log interval.
            "sunlight_hours": round((r["producing"] or 0) * interval / 3600.0, 1),
            "efficiency_pct": round(avg_p / device["rated_watts"] * 100, 1),
            "partial": r["day"] == today_text,
        })
    return out


def hourly_profile(device, days, today=None):
    """Average power for each hour of the day (local time) over `days` days."""
    today_dt = start_of_day(time.time() if today is None else today)
    start = (today_dt - timedelta(days=days - 1)).timestamp()
    with database.connect() as conn:
        rows = conn.execute(
            "SELECT CAST(strftime('%H', ts, 'unixepoch', 'localtime') AS INTEGER) AS h,"
            " AVG(power) AS p FROM readings WHERE device_id = ? AND ts >= ? GROUP BY h",
            (device["id"], int(start))).fetchall()
    by_hour = {r["h"]: r["p"] for r in rows}
    return [{"hour": h, "avg_power_w": round(by_hour.get(h) or 0.0, 1)} for h in range(24)]
