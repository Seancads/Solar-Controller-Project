"""Data Analytics & Visualization: analytics from logged data."""

import unittest

from datetime import datetime, timedelta

from helpers import Base  # noqa: E402
from solar_monitor.gateway_storage import database  # noqa: E402
from solar_monitor.analytics_visualization import logged_analytics  # noqa: E402


class TestLoggedAnalytics(Base):
    def test_daily_aggregates_and_hourly_profile(self):
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        with database.connect() as conn:
            for day_back in (2, 1, 0):
                for hour, power in ((8, 20.0), (12, 40.0), (20, 0.0)):
                    ts = (today - timedelta(days=day_back)).replace(hour=hour).timestamp()
                    conn.execute("INSERT INTO readings (device_id, ts, voltage, current, power, energy_wh)"
                                 " VALUES (?,?,?,?,?,?)", (self.dev["id"], int(ts), 18.0, power / 18, power, power / 10))
        days = logged_analytics.daily_aggregates(self.dev, 7)
        self.assertEqual(len(days), 3)
        d = days[0]
        self.assertEqual((d["peak_power_w"], d["avg_power_w"]), (40.0, 30.0))   # night reading excluded from avg
        self.assertAlmostEqual(d["total_energy_wh"], 6.0)
        self.assertAlmostEqual(d["efficiency_pct"], 60.0)                        # 30 W of 50 W
        self.assertEqual([x["partial"] for x in days], [False, False, True])     # today is incomplete
        hourly = logged_analytics.hourly_profile(self.dev, 7)
        self.assertEqual(len(hourly), 24)
        self.assertEqual((hourly[8]["avg_power_w"], hourly[12]["avg_power_w"], hourly[3]["avg_power_w"]),
                         (20.0, 40.0, 0.0))

    def test_api_sources(self):
        sim = self.client.get("/api/analytics?days=7").get_json()
        self.assertEqual(len(sim), 7)
        logged = self.client.get("/api/analytics?source=logged&days=7&device=%d" % self.dev["id"]).get_json()
        self.assertEqual(logged, [])                                  # nothing logged yet
        self.assertEqual(self.client.get("/api/analytics?source=logged&device=999").status_code, 404)
        self.assertEqual(len(self.client.get("/api/analytics/hourly?source=logged&device=%d" % self.dev["id"]).get_json()), 24)


if __name__ == "__main__":
    unittest.main()
