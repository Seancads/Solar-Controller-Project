"""A pretend ESP32, so the whole system works with no hardware (Hardware Acquisition module).

A simulated device produces readings with a slow random walk and sends them
through the same `ingest()` path as a real device. It can also be told to
misbehave for a short while (see FAULTS) to demo the alerts.
"""

import random
import time

from solar_monitor.account_management import device_registry
from solar_monitor.gateway_storage import ingest_pipeline
from solar_monitor.hardware_acquisition import reading_validation

FAULTS = {
    "low_voltage": {"seconds": 20, "label": "low voltage"},
    "high_voltage": {"seconds": 20, "label": "high voltage"},
    "high_current": {"seconds": 20, "label": "high current"},
    "offline": {"seconds": 45, "label": "going offline"},
}


_sim = {}      # device_id -> {"v", "i", "next", "fault", "until"}


def inject_fault(device_id, fault):
    """Force a simulated device to misbehave for a short time (for demos)."""
    if fault not in FAULTS:
        raise ValueError("Unknown fault.")
    until = time.time() + FAULTS[fault]["seconds"]
    s = _sim.setdefault(device_id, {"v": 18.0, "i": 2.0, "next": 0})
    s["fault"], s["until"] = fault, until
    return until


def simulate_tick(now=None):
    now = time.time() if now is None else now
    for device in device_registry.list_devices():
        if not device["simulated"] or not device["enabled"]:
            continue
        s = _sim.setdefault(device["id"], {"v": 18.0, "i": 2.0, "next": 0})
        if now < s["next"]:
            continue
        s["next"] = now + device["sample_interval_s"]

        fault = s.get("fault") if s.get("until", 0) > now else None
        if fault == "offline":
            continue                              # stay silent so the watchdog notices

        # A slow random walk looks like a panel following the sun.
        s["v"] = max(0, min(22, s["v"] + random.uniform(-0.3, 0.3)))
        s["i"] = max(0, min(4, s["i"] + random.uniform(-0.15, 0.15)))
        voltage, current = s["v"], s["i"]
        if fault == "low_voltage":
            voltage = 12.0 + random.uniform(-0.2, 0.2)
        elif fault == "high_voltage":
            voltage = 23.5 + random.uniform(-0.2, 0.2)
        elif fault == "high_current":
            current = 4.5 + random.uniform(-0.1, 0.1)

        v, i, p = reading_validation.validate_reading(voltage, current)
        ingest_pipeline.ingest(device, v, i, p, meta={"firmware": "simulator"}, now_ts=now)


def forget_device(device_id):
    _sim.pop(device_id, None)


def reset():
    """Drop all simulator state (used by tests)."""
    _sim.clear()


def ensure_default_device():
    """First run: add a simulated device so the dashboard has data to show."""
    if not device_registry.list_devices():
        device_registry.create_device("Simulated panel", "Built-in simulator", simulated=True,
                                      sample_interval_s=2, rated_watts=50)

