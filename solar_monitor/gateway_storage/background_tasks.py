"""The background threads that keep the system running by itself (Local Gateway & Storage module).

  * simulator   - generates readings for simulated devices
  * watchdog    - spots devices that stopped sending data
  * maintenance - old-data cleanup, plus anything added to `maintenance_hooks`
                  (the daily report job is added by solar_monitor/__init__.py)
"""

import logging
import threading
import time

from solar_monitor.alerts_notifications import alert_engine
from solar_monitor.gateway_storage import database, ingest_pipeline, live_state
from solar_monitor.hardware_acquisition import simulator

log = logging.getLogger("solar.background")

maintenance_hooks = []          # callables run about once a minute
_started = False
_start_lock = threading.Lock()


def _loop(fn, seconds, name):
    def run():
        while True:
            try:
                fn()
            except Exception:
                log.exception("Background task %s failed", name)
            time.sleep(seconds)
    threading.Thread(target=run, name=name, daemon=True).start()


_last_purge = [0.0]


def _purge_old_readings():
    # The DELETE scans the readings table, so only do it once an hour.
    if time.time() - _last_purge[0] < 3600:
        return
    _last_purge[0] = time.time()
    days = ingest_pipeline.logging_settings()["retention_days"]
    removed = database.purge_readings_before(time.time() - days * 86400)
    if removed:
        log.info("Removed %d readings older than %d days", removed, days)


def _maintenance():
    for hook in list(maintenance_hooks):
        try:
            hook()
        except Exception:
            log.exception("Maintenance hook failed")


def start():
    """Start the background threads (once)."""
    global _started
    with _start_lock:
        if _started:
            return
        _started = True
    maintenance_hooks.append(_purge_old_readings)
    _loop(simulator.simulate_tick, 1, "simulator")
    _loop(lambda: alert_engine.check_offline(status_window=live_state.online_window,
                                              last_seen_fn=live_state.last_seen), 1, "watchdog")
    _loop(_maintenance, 60, "maintenance")
