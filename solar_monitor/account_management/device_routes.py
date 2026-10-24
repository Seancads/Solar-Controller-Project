"""Web routes for the Devices page (Account Management module).

Register an ESP32, get its API key and a ready-made Arduino sketch, see its
status, rename/disable/delete it. Simulated devices can also be told to
misbehave, to demo the alerts.
"""

import os

from flask import Blueprint, Response, jsonify, render_template, request

from solar_monitor import config
from solar_monitor.account_management import device_registry
from solar_monitor.alerts_notifications import alert_engine
from solar_monitor.gateway_storage import live_state
from solar_monitor.hardware_acquisition import simulator
from solar_monitor.network_utils import server_base_url
from solar_monitor.web_helpers import err

bp = Blueprint("account_management", __name__)


@bp.route("/devices")
def devices_page():
    return render_template("account_management/devices.html")


def present_device(device):
    out = {k: device[k] for k in ("id", "name", "location", "simulated", "enabled",
                                  "sample_interval_s", "rated_watts", "created_at")}
    out.update(live_state.device_snapshot(device))
    out["api_key_hint"] = device["api_key"][-4:]
    out["online_window_s"] = live_state.online_window(device)
    return out


def clean_device_fields(data, creating, device_id=None):
    """Validate device form data. Returns (fields, error)."""
    if not isinstance(data, dict):
        return None, "Invalid data."
    fields = {}
    if creating or "name" in data:
        name = str(data.get("name", "")).strip()
        if not 1 <= len(name) <= 40 or any(ord(c) < 32 for c in name):
            return None, "Give the device a name (1-40 characters)."
        if device_registry.device_name_taken(name, exclude_id=device_id):
            return None, "A device called '%s' already exists." % name
        fields["name"] = name
    if "location" in data:
        location = str(data.get("location") or "").strip()
        if len(location) > 60 or any(ord(c) < 32 for c in location):
            return None, "Location must be 60 characters or fewer."
        fields["location"] = location
    if "sample_interval_s" in data:
        try:
            interval = int(data["sample_interval_s"])
        except (TypeError, ValueError):
            return None, "Sample interval must be a whole number of seconds."
        if not 1 <= interval <= 300:
            return None, "Sample interval must be between 1 and 300 seconds."
        fields["sample_interval_s"] = interval
    if "rated_watts" in data:
        try:
            watts = float(data["rated_watts"])
        except (TypeError, ValueError):
            return None, "Rated power must be a number."
        if not 1 <= watts <= 10000:
            return None, "Rated power must be between 1 and 10000 W."
        fields["rated_watts"] = watts
    if "enabled" in data:
        fields["enabled"] = bool(data["enabled"])
    return fields, None


@bp.route("/api/devices", methods=["GET"])
def api_devices():
    return jsonify([present_device(d) for d in device_registry.list_devices()])


@bp.route("/api/devices", methods=["POST"])
def api_device_create():
    data = request.get_json(silent=True)
    fields, error = clean_device_fields(data, creating=True)
    if error:
        return err(error)
    simulated_flag = bool(data.get("simulated"))
    device = device_registry.create_device(
        fields["name"], fields.get("location", ""), simulated_flag,
        fields.get("sample_interval_s", 2 if simulated_flag else 5),
        fields.get("rated_watts", 50.0))
    out = present_device(device)
    out["api_key"] = device["api_key"]        # shown right after creation
    return jsonify(out), 201


def _device_or_404(device_id):
    device = device_registry.get_device(device_id)
    return device, (None if device else err("No such device.", 404))


@bp.route("/api/devices/<int:device_id>", methods=["PATCH"])
def api_device_update(device_id):
    device, problem = _device_or_404(device_id)
    if problem:
        return problem
    fields, error = clean_device_fields(request.get_json(silent=True), creating=False,
                                        device_id=device_id)
    if error:
        return err(error)
    updated = device_registry.update_device(device_id, **fields)
    if device["enabled"] and not updated["enabled"]:
        alert_engine.device_removed(device_id, "device disabled")
    return jsonify(present_device(updated))


@bp.route("/api/devices/<int:device_id>", methods=["DELETE"])
def api_device_delete(device_id):
    device, problem = _device_or_404(device_id)
    if problem:
        return problem
    alert_engine.device_removed(device_id, "device deleted")
    device_registry.delete_device(device_id)
    live_state.forget_device(device_id)
    simulator.forget_device(device_id)
    return jsonify({"ok": True})


@bp.route("/api/devices/<int:device_id>/key", methods=["GET"])
def api_device_key(device_id):
    device, problem = _device_or_404(device_id)
    if problem:
        return problem
    base = server_base_url()
    return jsonify({"api_key": device["api_key"], "server_url": base,
                    "ingest_url": base + "/api/ingest"})


@bp.route("/api/devices/<int:device_id>/regenerate-key", methods=["POST"])
def api_device_regenerate(device_id):
    device, problem = _device_or_404(device_id)
    if problem:
        return problem
    updated = device_registry.regenerate_key(device_id)
    base = server_base_url()
    return jsonify({"api_key": updated["api_key"], "server_url": base,
                    "ingest_url": base + "/api/ingest"})


@bp.route("/api/devices/<int:device_id>/sketch", methods=["GET"])
def api_device_sketch(device_id):
    """An Arduino sketch for this device with its server address and API key
    already filled in."""
    device, problem = _device_or_404(device_id)
    if problem:
        return problem
    path = os.path.join(config.FIRMWARE_DIR, "esp32_sender.template.ino")
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    safe_name = "".join(c for c in device["name"] if c.isalnum() or c in " -_")[:40]
    for token, value in (("__DEVICE_NAME__", safe_name), ("__SERVER_URL__", server_base_url()),
                         ("__API_KEY__", device["api_key"]),
                         ("__INTERVAL__", str(device["sample_interval_s"]))):
        text = text.replace(token, value)
    return Response(text, mimetype="text/plain", headers={
        "Content-Disposition": 'attachment; filename="solar_monitor_esp32.ino"'})


@bp.route("/api/devices/<int:device_id>/simulate", methods=["POST"])
def api_device_simulate(device_id):
    """Make a simulated device misbehave for a short time, to demo alerts."""
    device, problem = _device_or_404(device_id)
    if problem:
        return problem
    if not device["simulated"] or not device["enabled"]:
        return err("Only enabled simulated devices can be used for this.")
    data = request.get_json(silent=True) or {}
    fault = data.get("fault")
    if fault not in simulator.FAULTS:
        return err("Choose one of: %s." % ", ".join(simulator.FAULTS))
    simulator.inject_fault(device_id, fault)
    rule_for = {"offline": "device_offline"}.get(fault, fault)
    warning = None
    if not alert_engine.rule_active_now(rule_for):
        warning = ("This alert rule is switched off or outside its active hours right now, "
                   "so no alert will be raised. Check the Alerts > Rules tab.")
    return jsonify({"ok": True, "seconds": simulator.FAULTS[fault]["seconds"],
                    "label": simulator.FAULTS[fault]["label"], "warning": warning})
