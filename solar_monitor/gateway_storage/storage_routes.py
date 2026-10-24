"""Web routes for the logging settings (Local Gateway & Storage module).

How often readings are written to the database and how long they are kept.
The form for these lives on the Reports page.
"""

import os

from flask import Blueprint, jsonify, request

from solar_monitor import config
from solar_monitor.gateway_storage import database, ingest_pipeline
from solar_monitor.web_helpers import err

bp = Blueprint("gateway_storage", __name__)


@bp.route("/api/settings/logging", methods=["GET"])
def api_logging_get():
    settings = database.get_logging_settings()
    with database.connect() as conn:
        count, oldest = conn.execute("SELECT COUNT(*), MIN(ts) FROM readings").fetchone()
    path = config.db_path()
    settings.update({"rows": count, "oldest_ts": oldest,
                     "db_bytes": os.path.getsize(path) if os.path.exists(path) else 0})
    return jsonify(settings)


@bp.route("/api/settings/logging", methods=["PUT"])
def api_logging_put():
    data = request.get_json(silent=True) or {}
    try:
        interval, retention = int(data["log_interval_s"]), int(data["retention_days"])
    except (KeyError, TypeError, ValueError):
        return err("Both values must be whole numbers.")
    if not 5 <= interval <= 60:
        return err("Log interval must be between 5 and 60 seconds.")
    if not 7 <= retention <= 3650:
        return err("Keep data for between 7 and 3650 days.")
    database.save_logging_settings(interval, retention)
    ingest_pipeline.invalidate_settings()
    return api_logging_get()
