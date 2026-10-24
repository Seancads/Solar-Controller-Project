"""Account Management: registering and pairing devices."""

import unittest
import json

from helpers import BASE, Base  # noqa: E402
from solar_monitor.alerts_notifications import alert_engine  # noqa: E402


class TestDeviceApi(Base):
    def test_create_update_delete(self):
        r = self.client.post("/api/devices", json={"name": " Roof ESP ", "location": "Roof",
                                                   "sample_interval_s": 5, "rated_watts": 100})
        self.assertEqual(r.status_code, 201)
        body = r.get_json()
        self.assertEqual(body["name"], "Roof ESP")
        self.assertGreater(len(body["api_key"]), 20)
        did = body["id"]
        r = self.client.patch("/api/devices/%d" % did, json={"name": "Garage", "enabled": False})
        self.assertEqual((r.get_json()["name"], r.get_json()["status"]), ("Garage", "disabled"))
        self.assertEqual(self.client.delete("/api/devices/%d" % did).status_code, 200)
        self.assertEqual(self.client.get("/api/live?device=%d" % did).status_code, 404)

    def test_validation(self):
        bad = [{"name": ""}, {"name": "x" * 41}, {"name": "ok", "sample_interval_s": 0},
               {"name": "ok", "sample_interval_s": "abc"}, {"name": "ok", "rated_watts": -5},
               {"name": "Panel A"}, {"name": "panel a"}]
        for payload in bad:
            self.assertEqual(self.client.post("/api/devices", json=payload).status_code, 400,
                             msg=repr(payload))

    def test_regenerating_key_invalidates_old_one(self):
        old = self.dev["api_key"]
        new = self.client.post("/api/devices/%d/regenerate-key" % self.dev["id"]).get_json()["api_key"]
        self.assertNotEqual(old, new)
        self.assertEqual(self.client.post("/api/ingest", json={"voltage": 18, "current": 2},
                                          headers={"X-API-Key": old}).status_code, 401)
        self.assertEqual(self.client.post("/api/ingest", json={"voltage": 18, "current": 2},
                                          headers={"X-API-Key": new}).status_code, 200)

    def test_key_endpoint_never_points_at_localhost(self):
        r = self.client.get("/api/devices/%d/key" % self.dev["id"],
                            headers={"Host": "localhost:5000"}).get_json()
        self.assertNotIn("localhost", r["ingest_url"])
        self.assertTrue(r["ingest_url"].endswith(":5000/api/ingest"))

    def test_list_never_exposes_full_key(self):
        listing = json.dumps(self.client.get("/api/devices").get_json())
        self.assertNotIn(self.dev["api_key"], listing)

    def test_deleting_a_device_closes_its_alerts(self):
        for k in range(3):
            self.feed(10.0, 2.0, BASE + 2 * k)
        self.assertEqual(alert_engine.summary()["active"], 1)
        self.client.delete("/api/devices/%d" % self.dev["id"])
        self.assertEqual(alert_engine.summary()["active"], 0)

    def test_sketch_is_prefilled(self):
        r = self.client.get("/api/devices/%d/sketch" % self.dev["id"])
        text = r.get_data(as_text=True)
        self.assertIn(self.dev["api_key"], text)
        self.assertNotIn("__API_KEY__", text)
        self.assertNotIn("__SERVER_URL__", text)
        self.assertNotIn("localhost", text)


if __name__ == "__main__":
    unittest.main()
