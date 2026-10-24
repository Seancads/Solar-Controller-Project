"""The app as a whole: error handling."""

import unittest

from helpers import Base  # noqa: E402


class TestApp(Base):
    def test_api_errors_are_json(self):
        r = self.client.get("/api/nope")
        self.assertEqual((r.status_code, r.is_json), (404, True))
        r = self.client.post("/api/live")
        self.assertEqual((r.status_code, r.is_json), (405, True))


if __name__ == "__main__":
    unittest.main()
