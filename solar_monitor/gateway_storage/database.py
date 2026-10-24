"""SQLite storage for the Solar Monitor (Local Gateway & Storage module).

Everything that must survive a restart lives in one database file: registered
devices, logged readings, alerts, alert rules and settings.

This file owns the connection, the table layout, app settings and the
`readings` table. Other tables are used through their own modules:
  devices                    -> account_management/device_registry.py
  alerts, alert_rules        -> alerts_notifications/alert_engine.py
  notification_log           -> alerts_notifications/notifier.py

Only the Python standard library is used. Connections are opened per
operation (cheap for SQLite) so every thread can use this module safely.
"""

import contextlib
import json
import os
import sqlite3
import time

from solar_monitor import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT    NOT NULL,
    location          TEXT    NOT NULL DEFAULT '',
    api_key           TEXT    NOT NULL UNIQUE,
    simulated         INTEGER NOT NULL DEFAULT 0,
    enabled           INTEGER NOT NULL DEFAULT 1,
    sample_interval_s INTEGER NOT NULL DEFAULT 5,
    rated_watts       REAL    NOT NULL DEFAULT 50,
    created_at        INTEGER NOT NULL,
    last_seen         INTEGER,
    firmware          TEXT,
    ip                TEXT,
    rssi              INTEGER,
    uptime_s          INTEGER
);

CREATE TABLE IF NOT EXISTS readings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id  INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    ts         INTEGER NOT NULL,
    voltage    REAL    NOT NULL,
    current    REAL    NOT NULL,
    power      REAL    NOT NULL,
    energy_wh  REAL    NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_readings_dev_ts ON readings(device_id, ts);

CREATE TABLE IF NOT EXISTS alert_rules (
    type        TEXT PRIMARY KEY,
    enabled     INTEGER NOT NULL DEFAULT 1,
    threshold   REAL    NOT NULL,
    severity    TEXT    NOT NULL DEFAULT 'warning',
    active_from TEXT,
    active_to   TEXT,
    confirm_n   INTEGER NOT NULL DEFAULT 3
);

CREATE TABLE IF NOT EXISTS alerts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id       INTEGER REFERENCES devices(id) ON DELETE SET NULL,
    device_name     TEXT    NOT NULL,
    rule_type       TEXT    NOT NULL,
    severity        TEXT    NOT NULL,
    message         TEXT    NOT NULL,
    value           REAL,
    threshold       REAL,
    started_at      INTEGER NOT NULL,
    resolved_at     INTEGER,
    acknowledged_at INTEGER,
    notified        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_alerts_resolved ON alerts(resolved_at);
CREATE INDEX IF NOT EXISTS idx_alerts_started ON alerts(started_at);

CREATE TABLE IF NOT EXISTS notification_log (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       INTEGER NOT NULL,
    channel  TEXT    NOT NULL,
    event    TEXT    NOT NULL,
    ok       INTEGER NOT NULL,
    detail   TEXT,
    alert_id INTEGER
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# type, enabled, threshold, severity, active_from, active_to, confirm_n
DEFAULT_RULES = [
    ("low_voltage", 1, 16.0, "warning", "07:00", "17:00", 3),
    ("high_voltage", 1, 22.5, "critical", None, None, 3),
    ("high_current", 1, 3.5, "warning", None, None, 3),
    ("device_offline", 1, 30.0, "critical", None, None, 1),
]

DEFAULT_LOGGING = {"log_interval_s": 10, "retention_days": 90}


def now():
    return int(time.time())


@contextlib.contextmanager
def connect():
    conn = sqlite3.connect(config.db_path(), timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Create tables and seed default alert rules. Safe to call repeatedly."""
    os.makedirs(os.path.dirname(os.path.abspath(config.db_path())), exist_ok=True)
    with connect() as conn:
        # WAL lets the background logger write while pages are reading.
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        if conn.execute("SELECT COUNT(*) FROM alert_rules").fetchone()[0] == 0:
            conn.executemany(
                "INSERT INTO alert_rules (type, enabled, threshold, severity,"
                " active_from, active_to, confirm_n) VALUES (?,?,?,?,?,?,?)",
                DEFAULT_RULES,
            )



# ---------------------------------------------------------------- settings
def get_setting(key, default=None):
    with connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    try:
        return json.loads(row["value"])
    except ValueError:
        return default


def set_setting(key, value):
    with connect() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )


def get_logging_settings():
    saved = get_setting("logging", {}) or {}
    out = dict(DEFAULT_LOGGING)
    out.update({k: saved[k] for k in DEFAULT_LOGGING if k in saved})
    return out


def save_logging_settings(log_interval_s, retention_days):
    set_setting("logging", {
        "log_interval_s": int(log_interval_s),
        "retention_days": int(retention_days),
    })



# ---------------------------------------------------------------- readings
def insert_reading(device_id, ts, voltage, current, power, energy_wh):
    with connect() as conn:
        conn.execute(
            "INSERT INTO readings (device_id, ts, voltage, current, power, energy_wh)"
            " VALUES (?,?,?,?,?,?)",
            (device_id, int(ts), voltage, current, power, energy_wh),
        )


def day_stats(device_id, start_ts, end_ts):
    """Aggregate of what was logged in [start_ts, end_ts). Used to restore
    "today" figures after a restart."""
    with connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n, MIN(voltage) AS min_v, MAX(voltage) AS max_v,"
            " MIN(current) AS min_i, MAX(current) AS max_i,"
            " MIN(power) AS min_p, MAX(power) AS max_p,"
            " COALESCE(SUM(energy_wh), 0) AS energy_wh, MAX(ts) AS last_ts"
            " FROM readings WHERE device_id = ? AND ts >= ? AND ts < ?",
            (device_id, int(start_ts), int(end_ts)),
        ).fetchone()
    return dict(row)


def purge_readings_before(ts):
    with connect() as conn:
        cur = conn.execute("DELETE FROM readings WHERE ts < ?", (int(ts),))
        return cur.rowcount
