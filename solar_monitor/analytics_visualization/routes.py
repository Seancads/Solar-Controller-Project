"""Web routes for the Dashboard and Analytics pages (Data Analytics & Visualization module)."""

from flask import Blueprint, jsonify, render_template, request

from solar_monitor.analytics_visualization import demo_data, live_data, logged_analytics
from solar_monitor.web_helpers import device_from_args, err, int_arg

bp = Blueprint("analytics_visualization", __name__)


# -------------------------------------------------------------------- pages
@bp.route("/")
def dashboard_page():
    return render_template("analytics_visualization/dashboard.html")


@bp.route("/analytics")
def analytics_page():
    return render_template("analytics_visualization/analytics.html")


# ------------------------------------------------------- live data (dashboard)
@bp.route("/api/live")
def api_live():
    device = device_from_args()
    if device is None:
        return err("No such device.", 404)
    return jsonify(live_data.live_payload(device))


@bp.route("/api/history")
def api_history():
    device = device_from_args()
    if device is None:
        return err("No such device.", 404)
    return jsonify(live_data.history_payload(device))


# ---------------------------------------------------------------- analytics
@bp.route("/api/analytics")
def api_analytics():
    days = int_arg("days", demo_data.ANALYTICS_DAYS, 1, demo_data.ANALYTICS_DAYS)
    if request.args.get("source") == "logged":
        device = device_from_args()
        if device is None:
            return err("No such device.", 404)
        return jsonify(logged_analytics.daily_aggregates(device, days))
    return jsonify(demo_data.get_daily_history()[-days:])


@bp.route("/api/analytics/hourly")
def api_analytics_hourly():
    days = int_arg("days", demo_data.ANALYTICS_DAYS, 1, demo_data.ANALYTICS_DAYS)
    if request.args.get("source") == "logged":
        device = device_from_args()
        if device is None:
            return err("No such device.", 404)
        return jsonify(logged_analytics.hourly_profile(device, days))
    return jsonify(demo_data.generate_hourly_profile(demo_data.get_daily_history()[-days:]))
