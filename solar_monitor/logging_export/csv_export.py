"""CSV files for download (Automated Logging & Export module).

Two kinds: a summary table (one row per time bucket) and the raw log (every
logged reading, streamed so a big export never has to fit in memory).
"""

import csv
import io
from datetime import datetime

from solar_monitor.gateway_storage import database

SUMMARY_HEADER = ["Time", "Avg voltage (V)", "Avg current (A)", "Avg power (W)",
                  "Peak power (W)", "Energy (Wh)", "Samples"]


def _csv_lines(rows):
    buf = io.StringIO()
    writer = csv.writer(buf)
    for row in rows:
        writer.writerow(row)
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)


def summary_csv_rows(table):
    yield SUMMARY_HEADER
    for b in table:
        yield [datetime.fromtimestamp(b["start_ts"]).strftime("%Y-%m-%d %H:%M"),
               b["avg_voltage"], b["avg_current"], b["avg_power"],
               b["peak_power"], b["energy_wh"], b["samples"]]


def summary_csv(table):
    return "".join(_csv_lines(summary_csv_rows(table)))


def raw_csv_stream(device_id, start, end):
    """Every logged reading in the range, streamed so big exports don't need
    to fit in memory."""
    def rows():
        yield ["Time", "Voltage (V)", "Current (A)", "Power (W)", "Energy since previous (Wh)"]
        with database.connect() as conn:
            cur = conn.execute(
                "SELECT ts, voltage, current, power, energy_wh FROM readings"
                " WHERE device_id = ? AND ts >= ? AND ts < ? ORDER BY ts",
                (device_id, int(start), int(end)))
            while True:
                chunk = cur.fetchmany(1000)
                if not chunk:
                    break
                for r in chunk:
                    yield [datetime.fromtimestamp(r["ts"]).strftime("%Y-%m-%d %H:%M:%S"),
                           r["voltage"], r["current"], r["power"], round(r["energy_wh"], 5)]
    return _csv_lines(rows())
