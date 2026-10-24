"""Shared test tools: a throwaway database, fake web/SMTP servers, a base test class.

Each test file is named after the module it covers (test_<module>.py).
Run all of them from the project folder with:

    python3 -m unittest discover -s tests -v

Uses a throwaway database, local fake servers for notifications, and
controlled timestamps, so it never touches your real data or the internet.
"""

import json
import os
import socketserver
import sys
import tempfile
import threading
import unittest
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SOLAR_DB", os.path.join(tempfile.mkdtemp(), "bootstrap.db"))

from solar_monitor import create_app  # noqa: E402
from solar_monitor.account_management import device_registry  # noqa: E402
from solar_monitor.alerts_notifications import alert_engine, notifier  # noqa: E402
from solar_monitor.gateway_storage import database, ingest_pipeline, live_state  # noqa: E402
from solar_monitor.hardware_acquisition import simulator  # noqa: E402
from solar_monitor.logging_export import scheduled_reports  # noqa: E402

APP = create_app()

# A fixed moment at 10:00 local time, inside low-voltage "active hours".
BASE = datetime(2026, 6, 15, 10, 0, 0).timestamp()


def reset_live_state():
    """Forget everything held in memory (as if the server had just started)."""
    live_state.reset_all()
    simulator.reset()
    ingest_pipeline.invalidate_settings()


class FakeHTTP(object):
    """A tiny local web server that records what it receives."""

    def __init__(self, status=200):
        outer = self
        self.requests = []
        self.status = status

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                outer.requests.append({"path": self.path, "body": json.loads(body or b"{}")})
                self.send_response(outer.status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok": true, "description": "fake says no"}')

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d" % self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class FakeSMTP(object):
    """Minimal SMTP server (no auth/TLS) that stores received messages."""

    def __init__(self):
        outer = self
        self.messages = []

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                w = lambda s: self.wfile.write((s + "\r\n").encode())
                w("220 fake ready")
                while True:
                    line = self.rfile.readline().decode().strip()
                    cmd = line.upper()
                    if not line:
                        return
                    if cmd.startswith(("EHLO", "HELO")):
                        w("250 fake")
                    elif cmd.startswith(("MAIL", "RCPT")):
                        w("250 OK")
                    elif cmd == "DATA":
                        w("354 go")
                        data = []
                        while True:
                            l = self.rfile.readline().decode()
                            if l.strip() == ".":
                                break
                            data.append(l)
                        outer.messages.append("".join(data))
                        w("250 queued")
                    elif cmd == "QUIT":
                        w("221 bye")
                        return
                    else:
                        w("250 OK")

        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["SOLAR_DB"] = os.path.join(self.tmp, "test.db")
        os.environ.pop("SOLAR_ADMIN_PASSWORD", None)
        scheduled_reports.REPORTS_DIR = os.path.join(self.tmp, "reports")
        scheduled_reports._daily_done.clear()
        database.init_db()
        reset_live_state()
        alert_engine.reset_state()
        alert_engine.START_TS = 0
        notifier._last_sent.clear()
        self.events = []
        self._orig_enqueue = notifier.enqueue
        notifier.enqueue = lambda event, alert: self.events.append((event, alert))
        self.client = APP.test_client()
        self.dev = device_registry.create_device("Panel A", "Roof", sample_interval_s=2, rated_watts=50)

    def tearDown(self):
        notifier.enqueue = self._orig_enqueue

    def feed(self, voltage, current, ts, device=None):
        return ingest_pipeline.ingest(device or self.dev, voltage, current, meta={}, now_ts=ts)
