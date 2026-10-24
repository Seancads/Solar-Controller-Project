"""Web routes for the Reports page (Automated Logging & Export module)."""

from datetime import datetime

from flask import Blueprint, Response, jsonify, render_template, request, send_from_directory, stream_with_context

from solar_monitor.account_management import device_registry
from solar_monitor.logging_export import csv_export, report_data, scheduled_reports
from solar_monitor.web_helpers import device_from_args, err

bp = Blueprint("logging_export", __name__)


@bp.route("/reports")
def reports_page():
    return render_template("logging_export/reports.html")


def _report_context():
    """Parse device + date range from the query string.
    Returns (device, range, error_response)."""
    device = device_from_args()
    if device is None:
        return None, None, err("Choose a device first.", 404)
    try:
        span = report_data.parse_range(request.args.get("range", "24h"),
                                       request.args.get("from"), request.args.get("to"))
    except ValueError as exc:
        return None, None, err(str(exc))
    return device, span, None


@bp.route("/api/reports/summary")
def api_report_summary():
    device, span, problem = _report_context()
    if problem:
        return problem
    report = scheduled_reports.build_report(device, span["start"], span["end"], span["label"])
    return jsonify({
        "label": span["label"], "start": span["start"], "end": span["end"],
        "bucket_name": report["bucket_name"], "summary": report["summary"],
        "table": report["table"],
    })


@bp.route("/api/reports/export.csv")
def api_report_export():
    device, span, problem = _report_context()
    if problem:
        return problem
    kind = request.args.get("kind", "summary")
    stamp = datetime.now().strftime("%Y%m%d")
    if kind == "raw":
        body = stream_with_context(csv_export.raw_csv_stream(device["id"], span["start"], span["end"]))
    else:
        kind = "summary"
        table = report_data.buckets(device["id"], span["start"], span["end"])
        body = csv_export.summary_csv(table)
    filename = "solar_%s_%s_%s.csv" % (scheduled_reports.slug(device["name"]), kind, stamp)
    return Response(body, mimetype="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="%s"' % filename})


@bp.route("/reports/print")
def report_print():
    device, span, problem = _report_context()
    if problem:
        return problem
    report = scheduled_reports.build_report(device, span["start"], span["end"], span["label"])
    return render_template("logging_export/report_print.html", report=report, standalone=False)


@bp.route("/api/reports/generate", methods=["POST"])
def api_report_generate():
    data = request.get_json(silent=True) or {}
    device = next((d for d in device_registry.list_devices() if d["id"] == data.get("device")), None)
    if device is None:
        return err("Choose a device first.", 404)
    try:
        span = report_data.parse_range(data.get("range", "24h"), data.get("from"), data.get("to"))
    except ValueError as exc:
        return err(str(exc))
    report = scheduled_reports.build_report(device, span["start"], span["end"], span["label"])
    if report["summary"]["n"] == 0:
        return err("There is no logged data in that range, so there is nothing to save.")
    names = scheduled_reports.save_report(device, report, scheduled_reports.manual_stem(device))
    return jsonify({"ok": True, "files": names})


@bp.route("/api/reports/saved")
def api_reports_saved():
    return jsonify(scheduled_reports.list_saved())


@bp.route("/reports/files/<name>")
def report_file(name):
    if not scheduled_reports.valid_saved_name(name):
        return err("No such report.", 404)
    return send_from_directory(scheduled_reports.REPORTS_DIR, name,
                               as_attachment=name.endswith(".csv"))

