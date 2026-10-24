"""Alert rules and the engine that evaluates them.

This is an extra feature, not one of the seven capstone modules.

How it behaves (these choices avoid the classic "alarm fatigue"):
  * A rule only fires after the condition has held for `confirm_n`
    readings in a row, so one noisy reading doesn't trigger anything.
  * It only resolves after `confirm_n` good readings in a row, so a value
    hovering around the threshold doesn't flap on and off.
  * The low-voltage rule has "active hours" (default 07:00-17:00) because a
    solar panel's voltage naturally collapses at night.
  * An alert stays open until it genuinely clears. Acknowledging only marks
    it as seen.
"""

import threading
import time
from datetime import datetime

from solar_monitor.account_management import device_registry
from solar_monitor.alerts_notifications import notifier
from solar_monitor.gateway_storage import database

RULE_META = {
    "low_voltage": {"label": "Low voltage", "field": "voltage", "op": "lt", "unit": "V",
                    "help": "Panel voltage drops below the threshold (during active hours)."},
    "high_voltage": {"label": "High voltage", "field": "voltage", "op": "gt", "unit": "V",
                     "help": "Panel voltage rises above the threshold."},
    "high_current": {"label": "High current", "field": "current", "op": "gt", "unit": "A",
                     "help": "Current rises above the threshold."},
    "device_offline": {"label": "Device offline", "field": None, "op": None, "unit": "s",
                       "help": "A device stops sending data for this many seconds."},
}
SEVERITIES = ("info", "warning", "critical")

_lock = threading.RLock()
_streaks = {}       # (device_id, rule_type) -> {"bad": n, "good": n}
_active = {}        # (device_id, rule_type) -> alert id
_loaded = False
_rules_cache = None
START_TS = time.time()      # offline checks give devices a grace period after a restart


# ------------------------------------------------------------------- rules
def _row_to_rule(row):
    rule = dict(row)
    rule["enabled"] = bool(rule["enabled"])
    meta = RULE_META.get(rule["type"], {})
    rule["label"] = meta.get("label", rule["type"])
    rule["unit"] = meta.get("unit", "")
    rule["help"] = meta.get("help", "")
    return rule


def get_rules():
    global _rules_cache
    with _lock:
        if _rules_cache is None:
            with database.connect() as conn:
                rows = conn.execute("SELECT * FROM alert_rules").fetchall()
            order = list(RULE_META)
            rules = [_row_to_rule(r) for r in rows if r["type"] in RULE_META]
            rules.sort(key=lambda r: order.index(r["type"]))
            _rules_cache = rules
        return [dict(r) for r in _rules_cache]


def invalidate_rules():
    global _rules_cache
    with _lock:
        _rules_cache = None


def _valid_hhmm(text):
    try:
        parts = text.split(":")
        return len(parts) == 2 and 0 <= int(parts[0]) <= 23 and 0 <= int(parts[1]) <= 59
    except (AttributeError, ValueError):
        return False


def _minutes(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def update_rules(items):
    """Validate and save rules from the UI. Returns (rules, error)."""
    if not isinstance(items, list):
        return None, "Invalid data."
    clean = []
    for item in items:
        if not isinstance(item, dict) or item.get("type") not in RULE_META:
            return None, "Unknown rule."
        label = RULE_META[item["type"]]["label"]
        try:
            threshold = float(item["threshold"])
        except (KeyError, TypeError, ValueError):
            return None, "%s: threshold must be a number." % label
        if not 0 < threshold <= 100000 or threshold != threshold:
            return None, "%s: threshold must be greater than 0." % label
        severity = item.get("severity")
        if severity not in SEVERITIES:
            return None, "%s: severity must be info, warning or critical." % label
        try:
            confirm_n = int(item.get("confirm_n", 3))
        except (TypeError, ValueError):
            return None, "%s: 'confirm after' must be a whole number." % label
        if not 1 <= confirm_n <= 20:
            return None, "%s: 'confirm after' must be between 1 and 20." % label

        a_from, a_to = item.get("active_from") or None, item.get("active_to") or None
        if item["type"] != "low_voltage":
            a_from = a_to = None          # active hours only make sense for low voltage
        elif (a_from or a_to):
            if not (_valid_hhmm(a_from) and _valid_hhmm(a_to)):
                return None, "%s: active hours must be set as HH:MM for both start and end." % label
            if a_from == a_to:
                return None, "%s: active hours start and end can't be the same." % label
        clean.append((int(bool(item.get("enabled"))), threshold, severity,
                      a_from, a_to, confirm_n, item["type"]))

    with database.connect() as conn:
        conn.executemany(
            "UPDATE alert_rules SET enabled=?, threshold=?, severity=?, active_from=?,"
            " active_to=?, confirm_n=? WHERE type=?", clean)
    invalidate_rules()
    # A rule that was just switched off should close its open alerts.
    for rule in get_rules():
        if not rule["enabled"]:
            _resolve_all_of_type(rule["type"], "rule disabled")
    return get_rules(), None


def _in_active_hours(rule, ts):
    if not rule["active_from"] or not rule["active_to"]:
        return True
    lt = datetime.fromtimestamp(ts)
    now_min = lt.hour * 60 + lt.minute
    start, end = _minutes(rule["active_from"]), _minutes(rule["active_to"])
    if start < end:
        return start <= now_min < end
    return now_min >= start or now_min < end          # overnight window


def rule_active_now(rule_type, ts=None):
    """False when a rule exists but its active hours exclude right now."""
    ts = time.time() if ts is None else ts
    rule = next((r for r in get_rules() if r["type"] == rule_type), None)
    return bool(rule and rule["enabled"] and _in_active_hours(rule, ts))


# ------------------------------------------------------------------ engine
def _ensure_loaded():
    """After a restart, remember which alerts were still open."""
    global _loaded
    with _lock:
        if _loaded:
            return
        with database.connect() as conn:
            rows = conn.execute(
                "SELECT id, device_id, rule_type FROM alerts WHERE resolved_at IS NULL"
            ).fetchall()
        for r in rows:
            if r["device_id"] is not None:
                _active[(r["device_id"], r["rule_type"])] = r["id"]
        _loaded = True


def reset_state():
    """Forget in-memory state (used by tests)."""
    global _loaded, _rules_cache
    with _lock:
        _streaks.clear()
        _active.clear()
        _loaded = False
        _rules_cache = None


def _message(rule, device_name, value):
    t, thr = rule["type"], rule["threshold"]
    if t == "low_voltage":
        return "Low voltage on %s: %.1f V (below %g V)" % (device_name, value, thr)
    if t == "high_voltage":
        return "High voltage on %s: %.1f V (above %g V)" % (device_name, value, thr)
    if t == "high_current":
        return "High current on %s: %.2f A (above %g A)" % (device_name, value, thr)
    return "%s stopped sending data (no data for %d s)" % (device_name, int(value))


def _step(device, rule, bad, value, confirm, ts):
    key = (device["id"], rule["type"])
    with _lock:
        s = _streaks.setdefault(key, {"bad": 0, "good": 0})
        if bad:
            s["bad"] += 1
            s["good"] = 0
        else:
            s["good"] += 1
            s["bad"] = 0
        active_id = _active.get(key)
        if active_id is None and s["bad"] >= confirm:
            _trigger(device, rule, value, ts)
        elif active_id is not None and s["good"] >= confirm:
            _resolve(key, ts)


def _trigger(device, rule, value, ts):
    message = _message(rule, device["name"], value)
    with database.connect() as conn:
        cur = conn.execute(
            "INSERT INTO alerts (device_id, device_name, rule_type, severity, message,"
            " value, threshold, started_at) VALUES (?,?,?,?,?,?,?,?)",
            (device["id"], device["name"], rule["type"], rule["severity"], message,
             float(value), rule["threshold"], int(ts)))
        alert_id = cur.lastrowid
    _active[(device["id"], rule["type"])] = alert_id
    notifier.enqueue("triggered", get_alert(alert_id))


def _resolve(key, ts, note=None):
    alert_id = _active.pop(key, None)
    if alert_id is None:
        return
    with database.connect() as conn:
        conn.execute("UPDATE alerts SET resolved_at = ? WHERE id = ? AND resolved_at IS NULL",
                     (int(ts), alert_id))
        if note:
            conn.execute("UPDATE alerts SET message = message || ? WHERE id = ?",
                         (" (%s)" % note, alert_id))
    notifier.enqueue("resolved", get_alert(alert_id))


def _resolve_all_of_type(rule_type, note):
    _ensure_loaded()
    with _lock:
        for key in [k for k in _active if k[1] == rule_type]:
            _resolve(key, time.time(), note)
            _streaks.pop(key, None)


def device_removed(device_id, note="device removed or disabled"):
    """Close a device's open alerts when it is deleted or disabled."""
    _ensure_loaded()
    with _lock:
        for key in [k for k in _active if k[0] == device_id]:
            _resolve(key, time.time(), note)
        for key in [k for k in _streaks if k[0] == device_id]:
            _streaks.pop(key, None)


def evaluate_reading(device, reading):
    """Called for every incoming reading."""
    _ensure_loaded()
    ts = reading["ts"]
    for rule in get_rules():
        if rule["type"] == "device_offline":
            # Data is arriving, so the device is (back) online.
            _step(device, rule, False, 0, 1, ts)
            continue
        if not rule["enabled"]:
            continue
        value = reading[RULE_META[rule["type"]]["field"]]
        if RULE_META[rule["type"]]["op"] == "lt":
            bad = value < rule["threshold"]
        else:
            bad = value > rule["threshold"]
        bad = bad and _in_active_hours(rule, ts)
        _step(device, rule, bad, value, rule["confirm_n"], ts)


def check_offline(now=None, status_window=None, last_seen_fn=None):
    """Called about once a second by the watchdog. `status_window(device)` is
    the engine's own "how long before a device counts as offline" so the
    alert never fires earlier than the status pill changes. `last_seen_fn`
    returns the live "last data" time; without it the (possibly stale)
    database value is used."""
    _ensure_loaded()
    now = time.time() if now is None else now
    rule = next((r for r in get_rules() if r["type"] == "device_offline"), None)
    if rule is None or not rule["enabled"]:
        return
    for device in device_registry.list_devices():
        seen = last_seen_fn(device) if last_seen_fn else device["last_seen"]
        if not device["enabled"] or not seen:
            continue                        # disabled, or never connected
        # Give devices time to reconnect after a server restart.
        last_seen = max(seen, START_TS)
        limit = rule["threshold"]
        if status_window:
            limit = max(limit, status_window(device))
        age = now - last_seen
        _step(device, rule, age > limit, age, 1, now)


# ----------------------------------------------------------------- queries
def get_alert(alert_id):
    with database.connect() as conn:
        row = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
    return dict(row) if row else None


def _present(row, now):
    a = dict(row)
    a["notified"] = bool(a["notified"])
    if a["resolved_at"]:
        a["state"] = "resolved"
        a["duration_s"] = a["resolved_at"] - a["started_at"]
    else:
        a["state"] = "acknowledged" if a["acknowledged_at"] else "active"
        a["duration_s"] = int(now) - a["started_at"]
    return a


def list_alerts(status="all", limit=100, device_id=None):
    sql, args = "SELECT * FROM alerts", []
    where = []
    if status == "active":
        where.append("resolved_at IS NULL")
    elif status == "resolved":
        where.append("resolved_at IS NOT NULL")
    if device_id is not None:
        where.append("device_id = ?")
        args.append(device_id)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(int(limit))
    with database.connect() as conn:
        rows = conn.execute(sql, args).fetchall()
    now = time.time()
    return [_present(r, now) for r in rows]


def summary():
    with database.connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS active,"
            " COALESCE(SUM(acknowledged_at IS NULL), 0) AS unacknowledged,"
            " COALESCE(SUM(severity = 'critical'), 0) AS critical"
            " FROM alerts WHERE resolved_at IS NULL").fetchone()
        latest = conn.execute("SELECT COALESCE(MAX(id), 0) FROM alerts").fetchone()[0]
        newest = conn.execute(
            "SELECT id, severity, message FROM alerts WHERE resolved_at IS NULL"
            " ORDER BY id DESC LIMIT 3").fetchall()
    return {
        "active": row["active"], "unacknowledged": row["unacknowledged"],
        "critical": row["critical"], "latest_id": latest,
        "newest": [dict(r) for r in newest],
    }


def acknowledge(alert_id):
    with database.connect() as conn:
        cur = conn.execute(
            "UPDATE alerts SET acknowledged_at = ? WHERE id = ? AND acknowledged_at IS NULL"
            " AND resolved_at IS NULL", (database.now(), alert_id))
        return cur.rowcount > 0


def acknowledge_all():
    with database.connect() as conn:
        cur = conn.execute(
            "UPDATE alerts SET acknowledged_at = ? WHERE acknowledged_at IS NULL"
            " AND resolved_at IS NULL", (database.now(),))
        return cur.rowcount
