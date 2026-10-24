"""Automated Logging & Export: reports, CSV export, scheduled daily reports."""

import unittest
import csv
import io
import time
from datetime import datetime, timedelta

from helpers import BASE, Base  # noqa: E402
from solar_monitor.gateway_storage import database  # noqa: E402
from solar_monitor.logging_export import csv_export  # noqa: E402
from solar_monitor.logging_export import report_data  # noqa: E402
from solar_monitor.logging_export import scheduled_reports  # noqa: E402


class TestReports(Base):
    def seed(self, days=3, per_hour=6, power=30.0):
        """Rows every 10 minutes for the last few days, each worth a known energy."""
        end = int(time.time()) // 600 * 600
        start = end - days * 86400
        with database.connect() as conn:
            for ts in range(start, end, 600):
                conn.execute("INSERT INTO readings (device_id, ts, voltage, current, power, energy_wh)"
                             " VALUES (?,?,?,?,?,?)", (self.dev["id"], ts, 18.0, power / 18.0, power, 1.0))
        return start, end

    def test_parse_range(self):
        now = BASE
        r = report_data.parse_range("24h", now=now)
        self.assertEqual((r["end"] - r["start"], r["label"]), (86400, "Last 24 hours"))
        t = report_data.parse_range("today", now=now)
        self.assertEqual(datetime.fromtimestamp(t["start"]).hour, 0)
        c = report_data.parse_range("custom", "2026-06-01", "2026-06-03", now=now)
        self.assertEqual(round((c["end"] - c["start"]) / 86400), 3)
        capped = report_data.parse_range("custom", "2026-06-10", "2026-12-31", now=now)
        self.assertEqual(capped["end"], now)                       # future is cut off
        for args in [("nope",), ("custom", "bad", "2026-06-01"), ("custom", "2026-06-05", "2026-06-01"),
                     ("custom", "2027-01-01", "2027-02-01"), ("custom", "2024-01-01", "2026-06-01")]:
            with self.assertRaises(ValueError, msg=repr(args)):
                report_data.parse_range(*args, now=now)

    def test_bucket_choice_keeps_tables_short(self):
        day = 86400
        expected = {3600: 60, day: 300, 7 * day: 3600, 30 * day: 21600, 366 * day: day}
        for span, bucket in expected.items():
            self.assertEqual(report_data.pick_bucket(span), bucket, span)
            self.assertLessEqual(span / bucket, report_data.MAX_ROWS)

    def test_summary_and_buckets_agree(self):
        start, end = self.seed(days=2)
        s = report_data.summary(self.dev["id"], start, end)
        self.assertEqual(s["n"], 2 * 144)
        self.assertEqual(s["energy_wh"], 2 * 144 * 1.0)
        self.assertEqual((s["avg_p"], s["peak_p"]), (30.0, 30.0))
        table = report_data.buckets(self.dev["id"], start, end)
        self.assertEqual(sum(b["samples"] for b in table), s["n"])
        self.assertAlmostEqual(sum(b["energy_wh"] for b in table), s["energy_wh"])

    def test_csv_exports(self):
        start, end = self.seed(days=1)
        table = report_data.buckets(self.dev["id"], start, end)
        rows = list(csv.reader(io.StringIO(csv_export.summary_csv(table))))
        self.assertEqual(rows[0], csv_export.SUMMARY_HEADER)
        self.assertEqual(len(rows) - 1, len(table))
        raw = list(csv.reader(io.StringIO("".join(csv_export.raw_csv_stream(self.dev["id"], start, end)))))
        self.assertEqual(len(raw) - 1, 144)
        r = self.client.get("/api/reports/export.csv?device=%d&range=7d&kind=raw" % self.dev["id"])
        self.assertEqual(r.status_code, 200)
        self.assertIn("attachment", r.headers["Content-Disposition"])
        self.assertIn("solar_panel-a_raw_", r.headers["Content-Disposition"])

    def test_report_api_and_errors(self):
        self.seed(days=2)
        r = self.client.get("/api/reports/summary?device=%d&range=24h" % self.dev["id"]).get_json()
        self.assertGreater(r["summary"]["n"], 100)
        self.assertEqual(self.client.get("/api/reports/summary?device=999").status_code, 404)
        self.assertEqual(self.client.get("/api/reports/summary?range=custom&from=x&to=y").status_code, 400)

    def test_saved_reports_and_filename_safety(self):
        self.seed(days=1)
        scheduled_reports.set_renderer(lambda rep: "<html>%s</html>" % rep["label"])
        self.addCleanup(scheduled_reports.set_renderer, None)
        r = self.client.post("/api/reports/generate", json={"device": self.dev["id"], "range": "24h"})
        self.assertEqual(r.status_code, 200)
        names = r.get_json()["files"]
        self.assertEqual(sorted(n.rsplit(".", 1)[1] for n in names), ["csv", "html"])
        served = self.client.get("/reports/files/" + names[0])
        self.assertEqual(served.status_code, 200)
        served.close()
        for bad in ("../app.py", "..%2Fapp.py", "x.txt", "nothere.csv"):
            self.assertEqual(self.client.get("/reports/files/" + bad).status_code, 404, bad)

    def test_empty_range_cannot_be_saved(self):
        r = self.client.post("/api/reports/generate", json={"device": self.dev["id"], "range": "1h"})
        self.assertEqual(r.status_code, 400)

    def test_daily_job_creates_yesterdays_report_once(self):
        scheduled_reports.set_renderer(lambda rep: "<html></html>")
        self.addCleanup(scheduled_reports.set_renderer, None)
        now = time.time()
        yesterday_noon = (datetime.fromtimestamp(now).replace(hour=12, minute=0, second=0, microsecond=0)
                          - timedelta(days=1)).timestamp()
        with database.connect() as conn:
            for k in range(5):
                conn.execute("INSERT INTO readings (device_id, ts, voltage, current, power, energy_wh)"
                             " VALUES (?,?,?,?,?,?)", (self.dev["id"], int(yesterday_noon) + k * 10, 18, 2, 36, 0.5))
        created = scheduled_reports.daily_reports_job(now=now)
        self.assertEqual(len(created), 2)
        self.assertTrue(all(n.startswith("daily_panel-a-") for n in created))
        self.assertEqual(scheduled_reports.daily_reports_job(now=now), [])                # not repeated
        self.assertEqual(len(scheduled_reports.list_saved()), 2)

    def test_logging_settings(self):
        self.assertEqual(self.client.put("/api/settings/logging",
                                         json={"log_interval_s": 2, "retention_days": 30}).status_code, 400)
        self.assertEqual(self.client.put("/api/settings/logging",
                                         json={"log_interval_s": 5, "retention_days": 3}).status_code, 400)
        r = self.client.put("/api/settings/logging", json={"log_interval_s": 30, "retention_days": 14})
        self.assertEqual((r.get_json()["log_interval_s"], r.get_json()["retention_days"]), (30, 14))
        self.feed(18.0, 2.0, BASE)
        self.feed(18.0, 2.0, BASE + 20)
        with database.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0], 1)

    def test_old_readings_are_purged(self):
        with database.connect() as conn:
            conn.execute("INSERT INTO readings (device_id, ts, voltage, current, power) VALUES (?,?,?,?,?)",
                         (self.dev["id"], 1000, 1, 1, 1))
        self.assertEqual(database.purge_readings_before(5000), 1)


if __name__ == "__main__":
    unittest.main()
