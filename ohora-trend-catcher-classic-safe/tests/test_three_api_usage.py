"""Offline usage/cooldown tests: synthetic headers, no HTTP."""
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "raw_v2"))
from three_api_coordinator import Coordinator
from three_api_usage import parse_usage, classify_failure, observe_headers


class UsageTests(unittest.TestCase):
    def test_app_usage_max(self):
        self.assertEqual(parse_usage({"X-App-Usage":
            '{"call_count": 84, "total_cputime": 12, "total_time": 3}'}), 84)

    def test_business_nested_usage(self):
        self.assertEqual(parse_usage({"x-business-use-case-usage":
            '{"123":[{"call_count": 88, "total_cputime": 30, "total_time": 22}]}'}), 88)

    def test_missing_or_malformed_fails_closed(self):
        self.assertIsNone(parse_usage({}))
        self.assertIsNone(parse_usage({"x-app-usage": "not-json"}))
        self.assertIsNone(parse_usage({"x-app-usage": "{}"}))

    def test_out_of_range_fails_closed(self):
        self.assertIsNone(parse_usage({"x-app-usage": '{"call_count":101}'}))

    def test_classify_rate_and_auth(self):
        self.assertEqual(classify_failure(429), "cooldown")
        self.assertEqual(classify_failure(400, {"code": 613}), "cooldown")
        self.assertEqual(classify_failure(401), "credentials_or_permissions")
        self.assertEqual(classify_failure(400, {"code": 190}), "credentials_or_permissions")
        self.assertEqual(classify_failure(503), "cooldown")

    def test_lane_isolated_cooldown(self):
        with tempfile.TemporaryDirectory() as folder:
            c = Coordinator(Path(folder) / "usage.sqlite")
            try:
                c.seed()
                t = datetime(2026, 10, 19, tzinfo=timezone.utc)
                result = observe_headers(c, "A",
                    {"X-App-Usage": '{"call_count":88}'}, now=t)
                self.assertTrue(result["halted"])
                self.assertIsNone(c.lease("A", now=t))
                self.assertIsNotNone(c.lease("B", now=t))
            finally:
                c.db.close()

    def test_missing_usage_halts(self):
        with tempfile.TemporaryDirectory() as folder:
            c = Coordinator(Path(folder) / "usage.sqlite")
            try:
                result = observe_headers(c, "C", {})
                self.assertTrue(result["halted"])
                self.assertIsNone(result["usage"])
            finally:
                c.db.close()


if __name__ == "__main__":
    unittest.main()
