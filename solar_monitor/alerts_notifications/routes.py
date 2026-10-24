"""Web routes for the Alerts page (alerts_notifications package, an extra feature)."""

from flask import Blueprint, jsonify, render_template, request

from solar_monitor.alerts_notifications import alert_engine, notifier
from solar_monitor.web_helpers import err, int_arg

bp = Blueprint("alerts_notifications", __name__)


@bp.route("/alerts")
def alerts_page():
    return render_template("alerts_notifications/alerts.html")


@bp.route("/api/alerts")
def api_alerts():
    status = request.args.get("status", "all")
    if status not in ("all", "active", "resolved"):
        status = "all"
    return jsonify(alert_engine.list_alerts(status, int_arg("limit", 100, 1, 500)))


@bp.route("/api/alerts/summary")
def api_alerts_summary():
    return jsonify(alert_engine.summary())


@bp.route("/api/alerts/<int:alert_id>/ack", methods=["POST"])
def api_alert_ack(alert_id):
    if not alert_engine.acknowledge(alert_id):
        return err("That alert is already acknowledged, resolved, or doesn't exist.", 404)
    return jsonify({"ok": True})


@bp.route("/api/alerts/ack-all", methods=["POST"])
def api_alert_ack_all():
    return jsonify({"ok": True, "count": alert_engine.acknowledge_all()})


@bp.route("/api/alert-rules", methods=["GET"])
def api_rules_get():
    return jsonify(alert_engine.get_rules())


@bp.route("/api/alert-rules", methods=["PUT"])
def api_rules_put():
    rules, error = alert_engine.update_rules(request.get_json(silent=True))
    if error:
        return err(error)
    return jsonify(rules)


@bp.route("/api/notifications", methods=["GET"])
def api_notifications_get():
    return jsonify(notifier.get_config(mask=True))


@bp.route("/api/notifications", methods=["PUT"])
def api_notifications_put():
    cfg, error = notifier.save_config(request.get_json(silent=True))
    if error:
        return err(error)
    return jsonify(cfg)


@bp.route("/api/notifications/test", methods=["POST"])
def api_notifications_test():
    channel = (request.get_json(silent=True) or {}).get("channel")
    ok, detail = notifier.send_test(channel)
    return jsonify({"ok": ok, "detail": detail}), (200 if ok else 502)


@bp.route("/api/notifications/log")
def api_notifications_log():
    return jsonify(notifier.recent_log(20))
