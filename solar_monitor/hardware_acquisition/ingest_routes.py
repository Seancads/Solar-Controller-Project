"""The two web addresses the ESP32 talks to (Hardware Acquisition module).

The ESP32 posts a reading to /api/ingest with its API key in the X-API-Key
header, and the reply tells it how often to send. The sketch for the ESP32 is
firmware/esp32_sender.template.ino.
"""

import time

from flask import Blueprint, jsonify, request

from solar_monitor.account_management import device_registry
from solar_monitor.gateway_storage import ingest_pipeline
from solar_monitor.hardware_acquisition import reading_validation
from solar_monitor.web_helpers import err

bp = Blueprint("hardware_acquisition", __name__)

# These two addresses use the device's API key instead of the web password.
DEVICE_PATHS = ("/api/ingest", "/api/device/config")


def _authenticated_device():
    return device_registry.get_device_by_key(request.headers.get("X-API-Key", ""))


def _device_config(device):
    return {"sample_interval_s": device["sample_interval_s"], "enabled": device["enabled"]}


@bp.route("/api/ingest", methods=["POST"])
def api_ingest():
    """The ESP32 posts a reading here. See firmware/esp32_sender.template.ino."""
    device = _authenticated_device()
    if device is None:
        return err("Unknown or missing API key (send it in the X-API-Key header).", 401)
    if not device["enabled"]:
        return err("This device is disabled.", 403)
    if device["simulated"]:
        return err("Simulated devices don't accept external readings.", 403)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return err("Send a JSON object, for example {\"voltage\": 18.2, \"current\": 2.1}.")
    try:
        voltage, current, power = reading_validation.validate_reading(
            data.get("voltage"), data.get("current"), data.get("power"))
    except ValueError as exc:
        return err(str(exc))

    meta = {"ip": request.remote_addr}
    firmware = data.get("firmware")
    if isinstance(firmware, str):
        meta["firmware"] = firmware.strip()[:32]
    for key, low, high in (("rssi", -130, 0), ("uptime_s", 0, 10 ** 9)):
        value = data.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and low <= value <= high:
            meta[key] = int(value)

    ingest_pipeline.ingest(device, voltage, current, power, meta)
    return jsonify({"ok": True, "config": _device_config(device), "server_time": int(time.time())})


@bp.route("/api/device/config", methods=["GET"])
def api_device_config():
    device = _authenticated_device()
    if device is None:
        return err("Unknown or missing API key.", 401)
    return jsonify({"config": _device_config(device), "server_time": int(time.time())})
