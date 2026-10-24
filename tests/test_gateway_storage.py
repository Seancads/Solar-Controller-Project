"""Local Gateway & Storage: ingest, live state, logging to the database."""

import unittest
import logging
from datetime import datetime

from helpers import BASE, Base, reset_live_state  # noqa: E402
from solar_monitor.gateway_storage import database  # noqa: E402
from solar_monitor.gateway_storage import live_state  # noqa: E402
from solar_monitor.analytics_visualization import live_data  # noqa: E402


class TestIngestAndLogging(Base):
    def test_logging_interval_and_energy_add_up(self):
        for k in range(11):                         # t = 0, 2, ... 20 s
            self.feed(18.0, 2.0, BASE + 2 * k)
        with database.connect() as conn:
            rows = conn.execute("SELECT ts, energy_wh FROM readings ORDER BY ts").fetchall()
        self.assertEqual([r["ts"] - int(BASE) for r in rows], [0, 10, 20])
        expected = 36.0 * 20 / 3600.0               # 36 W for 20 s
        self.assertAlmostEqual(sum(r["energy_wh"] for r in rows), expected, places=6)
        live = live_data.live_payload(self.dev)
        self.assertAlmostEqual(live["energy_wh"], expected, places=3)
        self.assertEqual(live["peak_power"], 36.0)

    def test_long_gap_is_not_integrated(self):
        self.feed(18.0, 2.0, BASE)
        self.feed(18.0, 2.0, BASE + 600)            # device was away for 10 minutes
        self.assertEqual(live_data.live_payload(self.dev)["energy_wh"], 0)

    def test_today_figures_survive_a_restart(self):
        for k in range(11):
            self.feed(18.0, 2.0 + k * 0.1, BASE + 2 * k)
        before = live_data.live_payload(self.dev)
        reset_live_state()                          # simulate restarting the server
        self.feed(18.0, 2.0, BASE + 30)
        after = live_data.live_payload(self.dev)
        self.assertGreaterEqual(after["peak_power"], before["peak_power"] - 1e-6)
        self.assertGreater(after["energy_wh"], 0)
        self.assertLessEqual(after["ranges"]["power"]["min"], before["ranges"]["power"]["min"])

    def test_day_rollover_resets_today_figures(self):
        late = datetime(2026, 6, 15, 23, 59, 50).timestamp()
        self.feed(20.0, 3.0, late)
        self.assertEqual(live_data.live_payload(self.dev)["peak_power"], 60.0)
        self.feed(10.0, 1.0, late + 20)             # just after midnight
        live = live_data.live_payload(self.dev)
        self.assertEqual(live["peak_power"], 10.0)
        self.assertEqual(live["day"], "2026-06-16")

    def test_history_is_capped(self):
        for k in range(live_state.HISTORY_POINTS + 25):
            self.feed(18.0, 2.0, BASE + 2 * k)
        self.assertEqual(len(live_data.history_payload(self.dev)), live_state.HISTORY_POINTS)

    def test_logging_failure_does_not_break_live_view(self):
        orig = database.insert_reading
        database.insert_reading = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk full"))
        logging.disable(logging.CRITICAL)          # the app logs this error on purpose
        try:
            self.feed(18.0, 2.0, BASE)
        finally:
            logging.disable(logging.NOTSET)
            database.insert_reading = orig
        self.assertEqual(live_data.live_payload(self.dev)["reading"]["voltage"], 18.0)


class TestLiveState(Base):
    def test_status_follows_data_freshness(self):
        self.assertEqual(live_state.device_status(self.dev, now=BASE)[0], "never")
        self.feed(18.0, 2.0, BASE)
        self.assertEqual(live_state.device_status(self.dev, now=BASE + 5)[0], "online")
        self.assertEqual(live_state.device_status(self.dev, now=BASE + 60)[0], "offline")
        self.assertEqual(live_state.device_status(dict(self.dev, enabled=False), now=BASE)[0], "disabled")


if __name__ == "__main__":
    unittest.main()
