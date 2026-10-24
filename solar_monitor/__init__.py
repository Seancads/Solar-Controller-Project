"""Solar Monitor: an ESP32 measures a solar panel and this app logs and shows it.

Each folder next to this file is one module of the capstone project:

  account_management/        register and pair devices (ESP32 + API key)
  hardware_acquisition/      what the ESP32 sends, and the checks on it
  gateway_storage/           receives readings, keeps live state, writes the database
  analytics_visualization/   Dashboard and Analytics pages
  logging_export/            Reports page, CSV export, scheduled daily reports
  security_access_control/   password gate (roles are not built yet)
  alerts_notifications/      extra: alerts, Slack/Telegram/email messages

Not built yet, so not here: Automated Load Control (relays) and role-based
access control (Admin / Technician).

`create_app()` builds the web app. `start_services()` starts the background
threads. run.py calls both.
"""

import logging

from flask import Flask, Response, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from solar_monitor.account_management import device_routes
from solar_monitor.alerts_notifications import routes as alert_routes
from solar_monitor.analytics_visualization import routes as analytics_routes
from solar_monitor.gateway_storage import background_tasks, database, storage_routes
from solar_monitor.hardware_acquisition import ingest_routes, simulator
from solar_monitor.logging_export import routes as report_routes
from solar_monitor.logging_export import scheduled_reports
from solar_monitor.security_access_control import password_gate
from solar_monitor.web_helpers import err


def create_app():
    app = Flask(__name__)
    # While developing, never let the browser reuse an old copy of the JS/CSS.
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024         # device posts are tiny

    database.init_db()                                     # safe to repeat

    password_gate.install(app, open_paths=ingest_routes.DEVICE_PATHS)

    for module in (device_routes, ingest_routes, storage_routes, analytics_routes,
                   report_routes, alert_routes):
        app.register_blueprint(module.bp)

    @app.errorhandler(Exception)
    def handle_error(exc):
        is_api = request.path.startswith("/api/")
        if isinstance(exc, HTTPException):
            return (jsonify({"error": exc.description}), exc.code) if is_api else exc
        logging.getLogger("solar.app").exception("Unhandled error on %s", request.path)
        if is_api:
            return err("Something went wrong on the server.", 500)
        return Response("Something went wrong on the server.", 500)

    return app


def start_services(app):
    """Start everything that runs on its own: the simulator, the offline
    watchdog, old-data cleanup and the daily reports."""
    database.init_db()
    simulator.ensure_default_device()

    def render_report_html(report):
        with app.app_context():
            return render_template("logging_export/report_print.html",
                                   report=report, standalone=True)

    scheduled_reports.set_renderer(render_report_html)
    background_tasks.maintenance_hooks.append(scheduled_reports.daily_reports_job)
    background_tasks.start()
