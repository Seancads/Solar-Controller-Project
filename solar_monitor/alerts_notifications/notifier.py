"""Outgoing notifications: webhook (generic/Slack/Discord), Telegram, email.

This is an extra feature, not one of the seven capstone modules.

In-app alerts (the alerts page, the nav badge, the toast) always work and
need no setup. Everything here is optional and off by default.

Only the standard library is used (urllib, smtplib), so there is nothing
extra to install.
"""

import copy
import json
import os
import queue
import smtplib
import ssl
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from email.message import EmailMessage

from solar_monitor.gateway_storage import database

SEVERITY_ORDER = {"info": 0, "warning": 1, "critical": 2}
WEBHOOK_FORMATS = ("generic", "slack", "discord")
EMAIL_SECURITY = ("none", "starttls", "ssl")
CHANNELS = ("webhook", "telegram", "email")

# Overridable so tests can point at a local fake instead of the real API.
TELEGRAM_API_BASE = os.environ.get("SOLAR_TELEGRAM_API", "https://api.telegram.org")

# Fields that are secrets: never sent back to the browser.
SECRET_FIELDS = {
    "webhook": ("url",),          # Discord/Slack webhook URLs contain a token
    "telegram": ("bot_token",),
    "email": ("password",),
}

DEFAULT_CONFIG = {
    "min_severity": "warning",
    "notify_on_resolve": True,
    "cooldown_s": 300,
    "webhook": {"enabled": False, "url": "", "format": "generic"},
    "telegram": {"enabled": False, "bot_token": "", "chat_id": ""},
    "email": {
        "enabled": False, "host": "", "port": 587, "security": "starttls",
        "username": "", "password": "", "from": "", "to": "",
    },
}

_last_sent = {}          # (device_id, rule_type) -> time of last triggered send
_last_sent_lock = threading.Lock()


# ------------------------------------------------------------------ config
def get_config(mask=True):
    """Saved config merged over defaults. With mask=True secrets are removed
    and replaced by "<field>_set" booleans (safe to send to the browser)."""
    saved = database.get_setting("notifications", {}) or {}
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    for key, val in saved.items():
        if key in CHANNELS and isinstance(val, dict):
            cfg[key].update(val)
        elif key in cfg:
            cfg[key] = val
    if mask:
        for channel, fields in SECRET_FIELDS.items():
            for field in fields:
                cfg[channel][field + "_set"] = bool(cfg[channel].get(field))
                cfg[channel][field] = ""
    return cfg


def _is_email(addr):
    return "@" in addr and "." in addr.split("@")[-1] and " " not in addr


def save_config(patch):
    """Merge a partial config from the UI. Secrets that are missing/None are
    left unchanged. Returns (config, error). error is None on success."""
    if not isinstance(patch, dict):
        return None, "Invalid data."
    cfg = get_config(mask=False)

    if "min_severity" in patch:
        if patch["min_severity"] not in SEVERITY_ORDER:
            return None, "Minimum severity must be info, warning or critical."
        cfg["min_severity"] = patch["min_severity"]
    if "notify_on_resolve" in patch:
        cfg["notify_on_resolve"] = bool(patch["notify_on_resolve"])
    if "cooldown_s" in patch:
        try:
            cooldown = int(patch["cooldown_s"])
        except (TypeError, ValueError):
            return None, "Cooldown must be a whole number of seconds."
        if not 0 <= cooldown <= 86400:
            return None, "Cooldown must be between 0 and 86400 seconds."
        cfg["cooldown_s"] = cooldown

    for channel in CHANNELS:
        incoming = patch.get(channel)
        if incoming is None:
            continue
        if not isinstance(incoming, dict):
            return None, "Invalid %s settings." % channel
        for field, value in incoming.items():
            if field.endswith("_set") or field not in cfg[channel]:
                continue
            if field in SECRET_FIELDS.get(channel, ()) and value is None:
                continue                      # unchanged secret
            if field == "enabled":
                value = bool(value)
            elif field == "port":
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    return None, "Email port must be a number."
                if not 1 <= value <= 65535:
                    return None, "Email port must be between 1 and 65535."
            else:
                value = "" if value is None else str(value).strip()
            cfg[channel][field] = value

    # Validate whatever ended up saved.
    wh, tg, em = cfg["webhook"], cfg["telegram"], cfg["email"]
    if wh["format"] not in WEBHOOK_FORMATS:
        return None, "Webhook format must be generic, slack or discord."
    if wh["url"] and not wh["url"].lower().startswith(("http://", "https://")):
        return None, "Webhook URL must start with http:// or https://."
    if em["security"] not in EMAIL_SECURITY:
        return None, "Email security must be none, starttls or ssl."
    if em["from"] and not _is_email(em["from"]):
        return None, "The 'from' email address doesn't look valid."
    for addr in [a.strip() for a in em["to"].split(",") if a.strip()]:
        if not _is_email(addr):
            return None, "'%s' doesn't look like an email address." % addr

    if wh["enabled"] and not wh["url"]:
        return None, "Webhook is enabled but has no URL."
    if tg["enabled"] and not (tg["bot_token"] and tg["chat_id"]):
        return None, "Telegram is enabled but needs both a bot token and a chat ID."
    if em["enabled"] and not (em["host"] and em["from"] and em["to"]):
        return None, "Email is enabled but needs a server, a 'from' address and a 'to' address."

    database.set_setting("notifications", cfg)
    return get_config(mask=True), None


# ----------------------------------------------------------------- senders
def _http_post_json(url, body, timeout=8):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "SolarMonitor/1.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read(2000)


def _send_webhook(cfg, text, alert, event):
    fmt = cfg["format"]
    if fmt == "slack":
        body = {"text": text}
    elif fmt == "discord":
        body = {"content": text}
    else:
        body = {
            "event": event,
            "severity": alert["severity"],
            "device": alert["device_name"],
            "rule": alert["rule_type"],
            "message": text,
            "value": alert.get("value"),
            "threshold": alert.get("threshold"),
            "time": datetime.fromtimestamp(alert["started_at"]).isoformat(timespec="seconds"),
        }
    status, _ = _http_post_json(cfg["url"], body)
    return "HTTP %s" % status


def _send_telegram(cfg, text):
    url = "%s/bot%s/sendMessage" % (TELEGRAM_API_BASE.rstrip("/"), cfg["bot_token"])
    status, _ = _http_post_json(url, {"chat_id": cfg["chat_id"], "text": text})
    return "HTTP %s" % status


def _send_email(cfg, subject, text):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg["from"]
    msg["To"] = cfg["to"]
    msg.set_content(text)
    context = ssl.create_default_context()
    if cfg["security"] == "ssl":
        server = smtplib.SMTP_SSL(cfg["host"], int(cfg["port"]), timeout=10, context=context)
    else:
        server = smtplib.SMTP(cfg["host"], int(cfg["port"]), timeout=10)
    with server:
        server.ehlo()
        if cfg["security"] == "starttls":
            server.starttls(context=context)
            server.ehlo()
        if cfg["username"]:
            server.login(cfg["username"], cfg["password"])
        server.send_message(msg)
    return "sent"


def _describe_error(exc):
    """A short, secret-free explanation of why a send failed."""
    if isinstance(exc, urllib.error.HTTPError):
        extra = ""
        try:
            payload = json.loads(exc.read(2000).decode("utf-8", "replace"))
            extra = payload.get("description") or payload.get("message") or ""
        except Exception:
            pass
        return ("HTTP %s %s" % (exc.code, extra)).strip()
    if isinstance(exc, urllib.error.URLError):
        return "Could not connect: %s" % (exc.reason,)
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return "Email login was rejected (check username/password or app password)."
    return "%s: %s" % (type(exc).__name__, exc)


def _send_one(channel, cfg, subject, text, alert, event):
    """Send via one channel. Returns (ok, detail)."""
    try:
        if channel == "webhook":
            return True, _send_webhook(cfg["webhook"], text, alert, event)
        if channel == "telegram":
            return True, _send_telegram(cfg["telegram"], text)
        if channel == "email":
            return True, _send_email(cfg["email"], subject, text)
    except Exception as exc:  # network errors etc. must never crash the app
        return False, _describe_error(exc)
    return False, "Unknown channel"


def _log(channel, event, ok, detail, alert_id=None):
    with database.connect() as conn:
        conn.execute(
            "INSERT INTO notification_log (ts, channel, event, ok, detail, alert_id)"
            " VALUES (?,?,?,?,?,?)",
            (database.now(), channel, event, 1 if ok else 0, (detail or "")[:300], alert_id),
        )


def recent_log(limit=20):
    with database.connect() as conn:
        rows = conn.execute(
            "SELECT ts, channel, event, ok, detail FROM notification_log"
            " ORDER BY id DESC LIMIT ?", (int(limit),)
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- dispatch
def _format(event, alert):
    if event == "resolved":
        return "[RESOLVED] " + alert["message"], "Solar Monitor: resolved - " + alert["message"]
    tag = alert["severity"].upper()
    return "[%s] %s" % (tag, alert["message"]), "Solar Monitor: %s" % alert["message"]


def dispatch(event, alert, now=None):
    """Decide whether and where to send one alert event, then send it.
    Runs on the worker thread (or directly in tests)."""
    now = time.time() if now is None else now
    cfg = get_config(mask=False)
    channels = [c for c in CHANNELS if cfg[c]["enabled"]]
    if not channels:
        return []

    if event == "resolved":
        # Only tell people about a recovery if we told them about the problem.
        fresh = _get_alert(alert["id"])
        if not cfg["notify_on_resolve"] or not fresh or not fresh["notified"]:
            return []
        alert = fresh
    else:
        if SEVERITY_ORDER.get(alert["severity"], 0) < SEVERITY_ORDER[cfg["min_severity"]]:
            return []
        key = (alert["device_id"], alert["rule_type"])
        with _last_sent_lock:
            last = _last_sent.get(key)
            if last is not None and now - last < cfg["cooldown_s"]:
                _log("all", event, False, "skipped: cooldown (%ds)" % cfg["cooldown_s"], alert["id"])
                return []
            _last_sent[key] = now

    text, subject = _format(event, alert)
    results = []
    for channel in channels:
        ok, detail = _send_one(channel, cfg, subject, text, alert, event)
        _log(channel, event, ok, detail, alert["id"])
        results.append((channel, ok, detail))

    if event == "triggered" and any(ok for _, ok, _ in results):
        with database.connect() as conn:
            conn.execute("UPDATE alerts SET notified = 1 WHERE id = ?", (alert["id"],))
    return results


def _get_alert(alert_id):
    with database.connect() as conn:
        row = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
    return dict(row) if row else None


def send_test(channel):
    """Send a test message through one channel using the SAVED settings."""
    if channel not in CHANNELS:
        return False, "Unknown channel."
    cfg = get_config(mask=False)
    probe = {
        "id": None, "device_id": None, "device_name": "Test device",
        "rule_type": "test", "severity": "info", "value": None, "threshold": None,
        "started_at": database.now(),
        "message": "This is a test notification from your Solar Monitor.",
    }
    # The channel must be configured, but doesn't have to be switched on yet.
    probe_cfg = copy.deepcopy(cfg)
    probe_cfg[channel]["enabled"] = True
    text, subject = _format("test", probe)
    ok, detail = _send_one(channel, probe_cfg, subject, text, probe, "test")
    _log(channel, "test", ok, detail)
    return ok, detail


# ------------------------------------------------------------------ worker
_queue = queue.Queue()
_worker = None
_worker_lock = threading.Lock()


def _run():
    while True:
        event, alert = _queue.get()
        try:
            dispatch(event, alert)
        except Exception:
            pass          # a notification problem must never take the app down


def enqueue(event, alert):
    """Hand an alert event to the background sender; returns immediately so a
    slow webhook can't delay incoming sensor readings."""
    global _worker
    with _worker_lock:
        if _worker is None:
            _worker = threading.Thread(target=_run, name="notifier", daemon=True)
            _worker.start()
    _queue.put((event, alert))
