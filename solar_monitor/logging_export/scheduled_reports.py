"""Saved and scheduled reports (Automated Logging & Export module).

A report is a CSV plus a printable, self-contained HTML page. They are saved
in the reports folder, either on request or automatically: `daily_reports_job`
runs about once a minute and writes yesterday's report for every device that
logged data, catching up after a restart if a day was missed.
"""

import os
import re
import threading
import time
from datetime import datetime, timedelta

from solar_monitor import config
from solar_monitor.account_management import device_registry
from solar_monitor.logging_export import csv_export, report_data
from solar_monitor.time_utils import start_of_day

REPORTS_DIR = config.reports_dir()

_render_html = None        # set at startup (the HTML page needs Flask's templates)


def set_renderer(fn):
    global _render_html
    _render_html = fn


def _nice_ceiling(value):
    """Round up to a tidy axis maximum (e.g. 43.2 -> 50)."""
    if value <= 0:
        return 1.0
    magnitude = 10 ** (len(str(int(value))) - 1) if value >= 1 else 1
    for step in (1, 2, 2.5, 5, 10):
        if value <= step * magnitude:
            return float(step * magnitude)
    return float(10 * magnitude)


def chart_geometry(table, width=720, height=200):
    """Pre-computed SVG coordinates for the printable report's power chart,
    so saved reports are self-contained (no scripts, no external files)."""
    if len(table) < 2:
        return None
    left, right, top, bottom = 46, 10, 10, 26
    plot_w, plot_h = width - left - right, height - top - bottom
    y_max = _nice_ceiling(max(b["peak_power"] for b in table))

    def point(i, value):
        x = left + plot_w * i / (len(table) - 1)
        y = top + plot_h * (1 - value / y_max)
        return "%.1f,%.1f" % (x, y)

    last = len(table) - 1
    return {
        "width": width, "height": height, "left": left, "right": width - right,
        "top": top, "bottom": top + plot_h,
        "avg": " ".join(point(i, b["avg_power"]) for i, b in enumerate(table)),
        "peak": " ".join(point(i, b["peak_power"]) for i, b in enumerate(table)),
        "y_ticks": [{"y": round(top + plot_h * (1 - f), 1), "label": ("%g" % round(y_max * f, 1))}
                    for f in (0, 0.25, 0.5, 0.75, 1)],
        "x_labels": [{"x": round(left + plot_w * i / last, 1), "label": table[i]["label"],
                      "anchor": "start" if i == 0 else ("end" if i == last else "middle")}
                     for i in (0, last // 2, last)],
    }


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:30] or "device"


def build_report(device, start, end, label):
    bucket = report_data.pick_bucket(end - start)
    table = report_data.buckets(device["id"], start, end, bucket)
    return {
        "device": device, "label": label, "start": start, "end": end,
        "start_text": datetime.fromtimestamp(start).strftime("%Y-%m-%d %H:%M"),
        "end_text": datetime.fromtimestamp(end).strftime("%Y-%m-%d %H:%M"),
        "generated_text": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "summary": report_data.summary(device["id"], start, end),
        "table": table,
        "bucket_name": report_data.bucket_name(bucket),
        "chart": chart_geometry(table),
    }


def save_report(device, report, stem):
    """Write <stem>.csv and <stem>.html into the reports folder."""
    os.makedirs(REPORTS_DIR, exist_ok=True)
    names = []
    csv_name = stem + ".csv"
    with open(os.path.join(REPORTS_DIR, csv_name), "w", newline="", encoding="utf-8") as fh:
        fh.write(csv_export.summary_csv(report["table"]))
    names.append(csv_name)
    if _render_html is not None:
        html_name = stem + ".html"
        with open(os.path.join(REPORTS_DIR, html_name), "w", encoding="utf-8") as fh:
            fh.write(_render_html(report))
        names.append(html_name)
    return names


def manual_stem(device):
    return "report_%s-%d_%s" % (slug(device["name"]), device["id"],
                                datetime.now().strftime("%Y%m%d-%H%M%S"))


def list_saved(limit=30):
    if not os.path.isdir(REPORTS_DIR):
        return []
    items = []
    for name in os.listdir(REPORTS_DIR):
        if valid_saved_name(name):
            path = os.path.join(REPORTS_DIR, name)
            items.append({"name": name, "size": os.path.getsize(path),
                          "mtime": int(os.path.getmtime(path)),
                          "kind": "daily" if name.startswith("daily_") else "report",
                          "format": name.rsplit(".", 1)[-1]})
    items.sort(key=lambda i: (i["mtime"], i["name"]), reverse=True)
    return items[:limit]


def valid_saved_name(name):
    return bool(re.match(r"^[a-z0-9._-]+\.(csv|html)$", name or "")) and ".." not in name \
        and os.path.isfile(os.path.join(REPORTS_DIR, name))


_daily_done = set()
_daily_lock = threading.Lock()


def daily_reports_job(now=None):
    """Save yesterday's report for every device that logged data that day.
    Runs from the maintenance loop; also catches up after a restart."""
    now = time.time() if now is None else now
    today = start_of_day(now)
    start, end = (today - timedelta(days=1)).timestamp(), today.timestamp()
    day_text = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    created = []
    for device in device_registry.list_devices():
        key = (device["id"], day_text)
        with _daily_lock:
            if key in _daily_done:
                continue
        stem = "daily_%s-%d_%s" % (slug(device["name"]), device["id"], day_text)
        if os.path.isfile(os.path.join(REPORTS_DIR, stem + ".csv")):
            with _daily_lock:
                _daily_done.add(key)
            continue
        if report_data.summary(device["id"], start, end)["n"] == 0:
            continue                      # nothing to report (yet)
        report = build_report(device, start, end, "Daily report, " + day_text)
        created.extend(save_report(device, report, stem))
        with _daily_lock:
            _daily_done.add(key)
    return created
