"""Reading the log for a report (Automated Logging & Export module).

Turns a date range ("last 24 hours", or custom dates) into a start/end time,
and summarises the logged readings in that range, either as one set of
totals (`summary`) or as time buckets for a table or chart (`buckets`).
"""

import time
from datetime import datetime, timedelta

from solar_monitor.gateway_storage import database
from solar_monitor.time_utils import start_of_day

PRESETS = {
    "1h": (3600, "Last hour"),
    "6h": (6 * 3600, "Last 6 hours"),
    "24h": (86400, "Last 24 hours"),
    "7d": (7 * 86400, "Last 7 days"),
    "30d": (30 * 86400, "Last 30 days"),
}
BUCKETS = (60, 300, 900, 3600, 21600, 86400)      # seconds
MAX_ROWS = 400                                     # keep tables readable
MAX_SPAN_DAYS = 366


def _parse_day(text):
    try:
        return datetime.strptime(text, "%Y-%m-%d")
    except (TypeError, ValueError):
        raise ValueError("Dates must look like 2026-09-30.")


def parse_range(preset, date_from=None, date_to=None, now=None):
    """Turn a preset (or custom dates) into {"start", "end", "label"}."""
    now = time.time() if now is None else now
    if preset == "today":
        return {"start": start_of_day(now).timestamp(), "end": now, "label": "Today"}
    if preset in PRESETS:
        seconds, label = PRESETS[preset]
        return {"start": now - seconds, "end": now, "label": label}
    if preset == "custom":
        first, last = _parse_day(date_from), _parse_day(date_to)
        start = first.timestamp()
        end = min((last + timedelta(days=1)).timestamp(), now)
        if start >= end:
            raise ValueError("The start date must be on or before the end date, and not in the future.")
        if (end - start) > MAX_SPAN_DAYS * 86400:
            raise ValueError("Please choose a range of %d days or less." % MAX_SPAN_DAYS)
        label = "%s to %s" % (first.strftime("%b %d, %Y"), last.strftime("%b %d, %Y"))
        return {"start": start, "end": end, "label": label}
    raise ValueError("Unknown date range.")


def pick_bucket(span_seconds):
    for bucket in BUCKETS:
        if span_seconds / float(bucket) <= MAX_ROWS:
            return bucket
    return BUCKETS[-1]


def bucket_name(bucket):
    if bucket < 3600:
        return "%d min" % (bucket // 60)
    if bucket < 86400:
        return "%d h" % (bucket // 3600)
    return "1 day"


def _local_offset(ts):
    return int(datetime.fromtimestamp(ts).astimezone().utcoffset().total_seconds())


def _label(ts, bucket):
    dt = datetime.fromtimestamp(ts)
    if bucket >= 86400:
        return dt.strftime("%a %b %d")
    if bucket >= 3600:
        return dt.strftime("%b %d %H:00")
    return dt.strftime("%b %d %H:%M")


# --------------------------------------------------------------- summaries
def summary(device_id, start, end):
    with database.connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n, AVG(voltage) AS avg_v, AVG(current) AS avg_i,"
            " AVG(power) AS avg_p, MAX(power) AS peak_p, MIN(voltage) AS min_v,"
            " MAX(voltage) AS max_v, COALESCE(SUM(energy_wh), 0) AS energy_wh,"
            " MIN(ts) AS first_ts, MAX(ts) AS last_ts"
            " FROM readings WHERE device_id = ? AND ts >= ? AND ts < ?",
            (device_id, int(start), int(end))).fetchone()
    out = dict(row)
    for key in ("avg_v", "avg_i", "avg_p", "peak_p", "min_v", "max_v"):
        out[key] = round(out[key], 3) if out[key] is not None else None
    out["energy_wh"] = round(out["energy_wh"], 3)
    return out


def buckets(device_id, start, end, bucket=None):
    bucket = bucket or pick_bucket(end - start)
    offset = _local_offset(start)
    with database.connect() as conn:
        rows = conn.execute(
            "SELECT ((ts + ?) / ?) * ? - ? AS b, AVG(voltage) AS av, AVG(current) AS ai,"
            " AVG(power) AS ap, MAX(power) AS mp, COALESCE(SUM(energy_wh), 0) AS e,"
            " COUNT(*) AS n FROM readings WHERE device_id = ? AND ts >= ? AND ts < ?"
            " GROUP BY b ORDER BY b",
            (offset, bucket, bucket, offset, device_id, int(start), int(end))).fetchall()
    return [{
        "start_ts": r["b"], "label": _label(r["b"], bucket),
        "avg_voltage": round(r["av"], 2), "avg_current": round(r["ai"], 3),
        "avg_power": round(r["ap"], 2), "peak_power": round(r["mp"], 2),
        "energy_wh": round(r["e"], 3), "samples": r["n"],
    } for r in rows]
