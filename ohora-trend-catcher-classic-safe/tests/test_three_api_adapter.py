"""Offline adapter tests: ensure no credentials or Meta calls."""
import importlib.util
from pathlib import Path
import sys
import unittest

RAW = Path(__file__).resolve().parents[1] / "raw_v2"
sys.path.insert(0, str(RAW))
spec = importlib.util.spec_from_file_location("three_api_adapter", RAW / "three_api_adapter.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.accounts = [
            {"ordinal": i, "key": f"KR_{i:03d}", "username": f"user_{i}"}
            for i in range(1, 295)
        ]

    def test_front_intent_is_not_live(self):
        intent = mod.build_intent(
            {"account_ordinal": 1, "lane": "A", "page": 1, "phase": "front"},
            self.accounts)
        self.assertEqual(intent["post_limit"], 4)
        self.assertFalse(intent["meta_request_enabled"])
        self.assertFalse(intent["requires_verified_cursor"])

    def test_history_requires_cursor(self):
        intent = mod.build_intent(
            {"account_ordinal": 294, "lane": "C", "page": 3, "phase": "history"},
            self.accounts)
        self.assertTrue(intent["requires_verified_cursor"])
        self.assertEqual(intent["account_ordinal"], 294)

    def test_invalid_ordinal_rejected(self):
        with self.assertRaises(ValueError):
            mod.build_intent(
                {"account_ordinal": 295, "lane": "A", "page": 1, "phase": "front"},
                self.accounts)

    def test_invalid_lane_rejected(self):
        with self.assertRaises(ValueError):
            mod.build_intent(
                {"account_ordinal": 1, "lane": "D", "page": 1, "phase": "front"},
                self.accounts)


if __name__ == "__main__":
    unittest.main()
