"""Hardware Acquisition: what the ESP32 sends, how it is checked, and the simulator."""

import unittest

from helpers import Base  # noqa: E402
from solar_monitor.account_management import device_registry  # noqa: E402
from solar_monitor.gateway_storage import database  # noqa: E402
from solar_monitor.hardware_acquisition import reading_validation  # noqa: E402
from solar_monitor.hardware_acquisition import simulator  # noqa: E402
from solar_monitor.analytics_visualization import live_data  # noqa: E402


class TestValidation(unittest.TestCase):
    def test_accepts_good_values(self):
        self.assertEqual(reading_validation.validate_reading(18.2, 2.0), (18.2, 2.0, 36.4))
        self.assertEqual(reading_validation.validate_reading("18", "2")[2], 36.0)

    def test_rejects_bad_values(self):
        for v, i in [(None, 1), (1, None), (True, 1), ("abc", 1), (float("nan"), 1),
                     (float("inf"), 1), (-1, 1), (101, 1), (10, 51), (10, -1)]:
            with self.assertRaises(ValueError, msg=repr((v, i))):
                reading_validation.validate_reading(v, i)

    def test_tiny_negative_current_is_clamped(self):
        self.assertEqual(reading_validation.validate_reading(18, -0.05)[1], 0.0)

    def test_explicit_power_is_range_checked(self):
        with self.assertRaises(ValueError):
            reading_validation.validate_reading(18, 2, 99999)


class TestIngestApi(Base):
    def post(self, key, body, raw=False):
        headers = {"X-API-Key": key} if key else {}
        if raw:
            return self.client.post("/api/ingest", data=body, headers=headers,
                                    content_type="application/json")
        return self.client.post("/api/ingest", json=body, headers=headers)

    def test_requires_valid_key(self):
        self.assertEqual(self.post(None, {"voltage": 18, "current": 2}).status_code, 401)
        self.assertEqual(self.post("nope", {"voltage": 18, "current": 2}).status_code, 401)

    def test_good_reading_updates_everything(self):
        r = self.post(self.dev["api_key"], {"voltage": 18.2, "current": 2.0, "firmware": "1.2.3",
                                            "rssi": -61, "uptime_s": 99})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["config"]["sample_interval_s"], 2)
        devices = self.client.get("/api/devices").get_json()
        d = devices[0]
        self.assertEqual((d["firmware"], d["rssi"], d["uptime_s"], d["status"]),
                         ("1.2.3", -61, 99, "online"))
        live = self.client.get("/api/live?device=%d" % d["id"]).get_json()
        self.assertEqual(live["reading"]["voltage"], 18.2)

    def test_bad_payloads_are_rejected(self):
        k = self.dev["api_key"]
        self.assertEqual(self.post(k, "not json", raw=True).status_code, 400)
        self.assertEqual(self.post(k, "[1,2]", raw=True).status_code, 400)
        self.assertEqual(self.post(k, {"voltage": 18}).status_code, 400)
        self.assertEqual(self.post(k, {"voltage": 500, "current": 1}).status_code, 400)
        self.assertEqual(self.post(k, {"voltage": "x", "current": 1}).status_code, 400)
        self.assertIsNone(live_data.live_payload(self.dev)["reading"])      # nothing stored

    def test_junk_metadata_is_ignored_not_trusted(self):
        r = self.post(self.dev["api_key"], {"voltage": 18, "current": 2, "rssi": 9999,
                                            "uptime_s": -5, "firmware": "x" * 500})
        self.assertEqual(r.status_code, 200)
        d = self.client.get("/api/devices").get_json()[0]
        self.assertIsNone(d["rssi"])
        self.assertIsNone(d["uptime_s"])
        self.assertEqual(len(d["firmware"]), 32)

    def test_disabled_and_simulated_devices_are_refused(self):
        device_registry.update_device(self.dev["id"], enabled=False)
        self.assertEqual(self.post(self.dev["api_key"], {"voltage": 18, "current": 2}).status_code, 403)
        sim = device_registry.create_device("Sim", simulated=True)
        self.assertEqual(self.post(sim["api_key"], {"voltage": 18, "current": 2}).status_code, 403)

    def test_config_endpoint(self):
        r = self.client.get("/api/device/config", headers={"X-API-Key": self.dev["api_key"]})
        self.assertEqual(r.get_json()["config"], {"sample_interval_s": 2, "enabled": True})
        self.assertEqual(self.client.get("/api/device/config").status_code, 401)

    def test_oversized_body_is_refused(self):
        r = self.post(self.dev["api_key"], "x" * 40000, raw=True)
        self.assertEqual(r.status_code, 413)


class TestSimulator(Base):
    def test_default_device_created_once(self):
        with database.connect() as conn:
            conn.execute("DELETE FROM devices")
        simulator.ensure_default_device()
        simulator.ensure_default_device()
        devices = device_registry.list_devices()
        self.assertEqual(len(devices), 1)
        self.assertTrue(devices[0]["simulated"])


if __name__ == "__main__":
    unittest.main()
