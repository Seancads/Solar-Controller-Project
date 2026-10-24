"""Alerts and notifications (extra feature, not one of the seven modules)."""

import unittest
import json
import time
from datetime import datetime

from helpers import BASE, Base, FakeHTTP, FakeSMTP  # noqa: E402
from solar_monitor.alerts_notifications import alert_engine  # noqa: E402
from solar_monitor.alerts_notifications import notifier  # noqa: E402
from solar_monitor.account_management import device_registry  # noqa: E402
from solar_monitor.gateway_storage import database  # noqa: E402
from solar_monitor.gateway_storage import ingest_pipeline  # noqa: E402
from solar_monitor.gateway_storage import live_state  # noqa: E402
from solar_monitor.hardware_acquisition import simulator  # noqa: E402


class TestAlerts(Base):
    def count(self):
        return len([e for e in self.events if e[0] == "triggered"])

    def test_needs_consecutive_readings_to_trigger(self):
        self.feed(10.0, 2.0, BASE)
        self.feed(10.0, 2.0, BASE + 2)
        self.assertEqual(alert_engine.summary()["active"], 0)
        self.feed(10.0, 2.0, BASE + 4)
        self.assertEqual(alert_engine.summary()["active"], 1)
        self.assertEqual(self.count(), 1)

    def test_one_noisy_reading_does_nothing(self):
        for k, v in enumerate([18, 18, 10, 18, 18, 10, 18, 18]):
            self.feed(v, 2.0, BASE + 2 * k)
        self.assertEqual(alert_engine.summary()["active"], 0)

    def test_no_duplicates_and_it_resolves(self):
        for k in range(8):
            self.feed(10.0, 2.0, BASE + 2 * k)
        self.assertEqual(self.count(), 1)
        for k in range(8, 11):
            self.feed(18.0, 2.0, BASE + 2 * k)
        self.assertEqual(alert_engine.summary()["active"], 0)
        self.assertEqual([e[0] for e in self.events], ["triggered", "resolved"])
        a = alert_engine.list_alerts("resolved")[0]
        self.assertEqual(a["state"], "resolved")
        self.assertIn("Low voltage on Panel A", a["message"])

    def test_hovering_at_the_threshold_does_not_flap(self):
        pattern = [10, 10, 10, 18, 10, 18, 10, 18, 18, 18]       # recovers only at the end
        for k, v in enumerate(pattern):
            self.feed(v, 2.0, BASE + 2 * k)
        self.assertEqual(self.count(), 1)

    def test_low_voltage_is_ignored_at_night(self):
        night = datetime(2026, 6, 15, 22, 0, 0).timestamp()
        for k in range(10):
            self.feed(0.5, 0.0, night + 2 * k)
        self.assertEqual(alert_engine.summary()["active"], 0)

    def test_high_voltage_and_current_rules(self):
        for k in range(3):
            self.feed(23.5, 4.0, BASE + 2 * k)
        kinds = sorted(a["rule_type"] for a in alert_engine.list_alerts("active"))
        self.assertEqual(kinds, ["high_current", "high_voltage"])

    def test_offline_detection_and_recovery(self):
        self.feed(18.0, 2.0, BASE)
        alert_engine.check_offline(now=BASE + 10, status_window=live_state.online_window)
        self.assertEqual(alert_engine.summary()["active"], 0)
        alert_engine.check_offline(now=BASE + 120, status_window=live_state.online_window)
        active = alert_engine.list_alerts("active")
        self.assertEqual([a["rule_type"] for a in active], ["device_offline"])
        self.assertIn("stopped sending data", active[0]["message"])
        self.feed(18.0, 2.0, BASE + 130)                          # it came back
        self.assertEqual(alert_engine.summary()["active"], 0)

    def test_slow_logging_does_not_cause_false_offline_alerts(self):
        """Regression: "last seen" used to come from the database, which is only
        updated when a reading is LOGGED. With a 60 s log interval a healthy
        device looked stale for up to a minute and raised a false alarm."""
        database.save_logging_settings(60, 90)
        ingest_pipeline.invalidate_settings()
        for k in range(45):                                        # 90 s of readings, every 2 s
            t = BASE + 2 * k
            self.feed(18.0, 2.0, t)
            alert_engine.check_offline(now=t + 1, status_window=live_state.online_window,
                                 last_seen_fn=live_state.last_seen)
        self.assertEqual(alert_engine.summary()["active"], 0)

    def test_database_last_seen_alone_would_have_failed(self):
        """Documents why the fix matters: the stale database value triggers."""
        database.save_logging_settings(60, 90)
        ingest_pipeline.invalidate_settings()
        for k in range(45):
            t = BASE + 2 * k
            self.feed(18.0, 2.0, t)
            alert_engine.check_offline(now=t + 1, status_window=live_state.online_window)   # old behaviour
        # It fired (then cleared itself at the next log write): a false alarm.
        self.assertGreaterEqual(len(alert_engine.list_alerts("all")), 1)

    def test_devices_that_never_connected_do_not_alert(self):
        alert_engine.check_offline(now=BASE + 9999, status_window=live_state.online_window)
        self.assertEqual(alert_engine.summary()["active"], 0)

    def test_grace_period_after_server_restart(self):
        self.feed(18.0, 2.0, BASE)
        alert_engine.START_TS = BASE + 1000                             # server "just started"
        alert_engine.check_offline(now=BASE + 1010, status_window=live_state.online_window)
        self.assertEqual(alert_engine.summary()["active"], 0)
        alert_engine.check_offline(now=BASE + 1100, status_window=live_state.online_window)
        self.assertEqual(alert_engine.summary()["active"], 1)

    def test_open_alerts_survive_a_restart_without_duplicating(self):
        for k in range(3):
            self.feed(10.0, 2.0, BASE + 2 * k)
        alert_engine.reset_state()                                      # "restart"
        for k in range(3, 9):
            self.feed(10.0, 2.0, BASE + 2 * k)
        self.assertEqual(len(alert_engine.list_alerts("all")), 1)
        for k in range(9, 12):
            self.feed(18.0, 2.0, BASE + 2 * k)
        self.assertEqual(alert_engine.summary()["active"], 0)

    def test_acknowledge(self):
        for k in range(3):
            self.feed(10.0, 2.0, BASE + 2 * k)
        aid = alert_engine.list_alerts("active")[0]["id"]
        self.assertEqual(alert_engine.summary()["unacknowledged"], 1)
        self.assertEqual(self.client.post("/api/alerts/%d/ack" % aid).status_code, 200)
        self.assertEqual(self.client.post("/api/alerts/%d/ack" % aid).status_code, 404)
        self.assertEqual(alert_engine.summary()["unacknowledged"], 0)
        self.assertEqual(alert_engine.summary()["active"], 1)           # still open until it clears
        self.assertEqual(alert_engine.list_alerts("active")[0]["state"], "acknowledged")

    def test_rule_validation_and_disabling_closes_alerts(self):
        rules = self.client.get("/api/alert-rules").get_json()
        self.assertEqual([r["type"] for r in rules],
                         ["low_voltage", "high_voltage", "high_current", "device_offline"])

        def put(mutate):
            copy = json.loads(json.dumps(rules))
            mutate(copy)
            return self.client.put("/api/alert-rules", json=copy)

        self.assertEqual(put(lambda r: r[0].update(threshold="abc")).status_code, 400)
        self.assertEqual(put(lambda r: r[0].update(threshold=-3)).status_code, 400)
        self.assertEqual(put(lambda r: r[0].update(severity="loud")).status_code, 400)
        self.assertEqual(put(lambda r: r[0].update(confirm_n=0)).status_code, 400)
        self.assertEqual(put(lambda r: r[0].update(active_from="25:00", active_to="17:00")).status_code, 400)
        self.assertEqual(put(lambda r: r[0].update(active_from="08:00", active_to="08:00")).status_code, 400)
        self.assertEqual(put(lambda r: r[0].update(threshold=14.5, severity="critical")).status_code, 200)

        for k in range(3):
            self.feed(10.0, 2.0, BASE + 2 * k)
        self.assertEqual(alert_engine.summary()["active"], 1)
        self.assertEqual(put(lambda r: r[0].update(enabled=False)).status_code, 200)
        self.assertEqual(alert_engine.summary()["active"], 0)

    def test_simulated_fault_raises_an_alert(self):
        sim = device_registry.create_device("Sim", simulated=True, sample_interval_s=2)
        t = BASE
        for _ in range(3):
            simulator.simulate_tick(now=t)
            t += 2
        self.assertEqual(alert_engine.summary()["active"], 0)
        simulator.inject_fault(sim["id"], "high_voltage")
        simulator._sim[sim["id"]]["until"] = t + 100                 # fault window in test time
        for _ in range(6):
            simulator.simulate_tick(now=t)
            t += 2
        self.assertIn("high_voltage", [a["rule_type"] for a in alert_engine.list_alerts("active")])


class TestNotifier(Base):
    def setUp(self):
        Base.setUp(self)             # enqueue stays stubbed: tests call dispatch() explicitly
        self.web = FakeHTTP()
        self.addCleanup(self.web.close)
        self.alert = {"id": None, "device_id": 1, "device_name": "Panel A", "rule_type": "low_voltage",
                      "severity": "warning", "value": 12.0, "threshold": 16.0,
                      "started_at": int(BASE), "message": "Low voltage on Panel A: 12.0 V (below 16 V)"}

    def save(self, **channels):
        cfg, error = notifier.save_config(channels)
        self.assertIsNone(error, error)
        return cfg

    def test_secrets_are_masked_and_preserved(self):
        self.save(webhook={"enabled": True, "url": self.web.url + "/hook", "format": "slack"})
        masked = self.client.get("/api/notifications").get_json()
        self.assertEqual(masked["webhook"]["url"], "")
        self.assertTrue(masked["webhook"]["url_set"])
        self.assertNotIn(self.web.url, json.dumps(masked))
        # Saving without touching the secret must keep it.
        self.client.put("/api/notifications", json={"webhook": {"format": "discord", "url": None}})
        self.assertEqual(notifier.get_config(mask=False)["webhook"]["url"], self.web.url + "/hook")
        # An empty string clears it.
        r = self.client.put("/api/notifications", json={"webhook": {"enabled": False, "url": ""}})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(notifier.get_config()["webhook"]["url_set"])

    def test_validation(self):
        bad = [{"min_severity": "loud"}, {"cooldown_s": -1}, {"cooldown_s": "x"},
               {"webhook": {"enabled": True, "url": ""}},
               {"webhook": {"url": "ftp://x"}}, {"webhook": {"format": "xml"}},
               {"telegram": {"enabled": True, "bot_token": "", "chat_id": ""}},
               {"email": {"enabled": True, "host": "h"}}, {"email": {"port": 99999}},
               {"email": {"from": "nope"}}, {"email": {"to": "a@b.com, nope"}}]
        for patch in bad:
            self.assertEqual(self.client.put("/api/notifications", json=patch).status_code, 400,
                             msg=repr(patch))

    def test_webhook_formats(self):
        for fmt, key in (("slack", "text"), ("discord", "content"), ("generic", "message")):
            self.web.requests.clear()
            self.save(webhook={"enabled": True, "url": self.web.url + "/h", "format": fmt})
            notifier._last_sent.clear()
            results = notifier.dispatch("triggered", dict(self.alert, id=1))
            self.assertTrue(results[0][1], results)
            body = self.web.requests[0]["body"]
            self.assertIn("Low voltage on Panel A", body[key])
            if fmt == "generic":
                self.assertEqual((body["event"], body["severity"], body["device"]),
                                 ("triggered", "warning", "Panel A"))

    def test_telegram(self):
        notifier.TELEGRAM_API_BASE = self.web.url
        self.addCleanup(setattr, notifier, "TELEGRAM_API_BASE", "https://api.telegram.org")
        self.save(telegram={"enabled": True, "bot_token": "123:ABC", "chat_id": "42"})
        results = notifier.dispatch("triggered", dict(self.alert, id=1))
        self.assertTrue(results[0][1])
        req = self.web.requests[0]
        self.assertEqual(req["path"], "/bot123:ABC/sendMessage")
        self.assertEqual(req["body"]["chat_id"], "42")

    def test_email(self):
        smtp = FakeSMTP()
        self.addCleanup(smtp.close)
        self.save(email={"enabled": True, "host": "127.0.0.1", "port": smtp.port, "security": "none",
                         "from": "solar@example.com", "to": "me@example.com"})
        results = notifier.dispatch("triggered", dict(self.alert, id=1))
        self.assertTrue(results[0][1], results)
        self.assertIn("Low voltage on Panel A", smtp.messages[0])
        self.assertIn("Subject: Solar Monitor", smtp.messages[0])

    def test_failure_is_reported_not_raised_and_hides_secrets(self):
        self.web.status = 500
        self.save(webhook={"enabled": True, "url": self.web.url + "/h"})
        ok, detail = notifier.send_test("webhook")
        self.assertFalse(ok)
        self.assertIn("500", detail)
        notifier.TELEGRAM_API_BASE = "http://127.0.0.1:1"            # nothing listens here
        self.addCleanup(setattr, notifier, "TELEGRAM_API_BASE", "https://api.telegram.org")
        self.save(telegram={"enabled": True, "bot_token": "SECRETTOKEN", "chat_id": "1"})
        ok, detail = notifier.send_test("telegram")
        self.assertFalse(ok)
        self.assertNotIn("SECRETTOKEN", detail)
        logged = json.dumps(notifier.recent_log())
        self.assertNotIn("SECRETTOKEN", logged)

    def test_severity_filter_cooldown_and_resolve_rules(self):
        self.save(min_severity="critical", cooldown_s=300,
                  webhook={"enabled": True, "url": self.web.url + "/h"})
        self.assertEqual(notifier.dispatch("triggered", dict(self.alert, id=1)), [])    # warning < critical
        crit = dict(self.alert, id=1, severity="critical")
        self.assertEqual(len(notifier.dispatch("triggered", crit, now=1000)), 1)
        self.assertEqual(notifier.dispatch("triggered", crit, now=1100), [])            # cooldown
        self.assertEqual(len(notifier.dispatch("triggered", crit, now=1400)), 1)        # cooldown over

    def test_resolved_message_only_after_a_sent_problem_message(self):
        self.save(webhook={"enabled": True, "url": self.web.url + "/h"})
        for k in range(3):
            self.feed(10.0, 2.0, BASE + 2 * k)
        a = alert_engine.list_alerts("active")[0]
        for k in range(3, 6):
            self.feed(18.0, 2.0, BASE + 2 * k)
        self.assertEqual(notifier.dispatch("resolved", a), [])          # never notified -> silent
        notifier.dispatch("triggered", a)
        self.assertEqual(len(notifier.dispatch("resolved", a)), 1)
        self.assertIn("[RESOLVED]", self.web.requests[-1]["body"]["message"])

    def test_background_queue_delivers_without_blocking(self):
        notifier.enqueue = self._orig_enqueue                     # the real thing
        self.save(webhook={"enabled": True, "url": self.web.url + "/h", "format": "slack"})
        started = time.time()
        for k in range(3):
            self.feed(10.0, 2.0, BASE + 2 * k)                    # raises a low-voltage alert
        self.assertLess(time.time() - started, 1.0)               # sending didn't block ingest
        deadline = time.time() + 5
        while not self.web.requests and time.time() < deadline:
            time.sleep(0.05)
        self.assertEqual(len(self.web.requests), 1)
        self.assertIn("Low voltage", self.web.requests[0]["body"]["text"])

    def test_nothing_is_sent_when_no_channel_enabled(self):
        self.assertEqual(notifier.dispatch("triggered", dict(self.alert, id=1)), [])
        self.assertEqual(self.web.requests, [])


if __name__ == "__main__":
    unittest.main()
