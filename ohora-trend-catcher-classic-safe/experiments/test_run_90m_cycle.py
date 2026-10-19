"""Network-free tests for disabled 2-app business-hour scheduler."""
from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_90m_cycle as runner

KST = timezone(timedelta(hours=9))


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.config_path = self.base / "local.json"
        self.source = self.base / "accounts.csv"
        self.source.write_text("fixture header,not used in mocked collector\n")
        self.a = self.base / "app_a.env.local"
        self.b = self.base / "app_b.env.local"
        self.a.write_text("META_ACCESS_TOKEN=DUMMY_A\nMETA_IG_USER_ID=123\nMETA_APP_ID=1001\n")
        self.b.write_text("META_ACCESS_TOKEN=DUMMY_B\nMETA_IG_USER_ID=456\nMETA_APP_ID=2002\n")
        self.config = {
            "schedule_enabled": False, "separate_authorized_apps_confirmed": False,
            "cycle_minutes": 90, "weekdays": [0,1,2,3,4],
            "business_hours_kst": {"start": "09:00", "end": "18:00"},
            "source": "accounts.csv",
            "apps": {
                "A": {"enabled": False, "env_file": "app_a.env.local",
                      "output_dir": "backfill_A"},
                "B": {"enabled": False, "env_file": "app_b.env.local",
                      "output_dir": "backfill_B"},
            }
        }
        self.write()

    def write(self):
        self.config_path.write_text(json.dumps(self.config), encoding="utf-8")

    def enable(self):
        self.config["schedule_enabled"] = True
        self.config["separate_authorized_apps_confirmed"] = True
        self.config["apps"]["A"]["enabled"] = True
        self.config["apps"]["B"]["enabled"] = True
        self.write()

    def test_preview_does_not_call_api_or_write_anything(self):
        original = self.base / "backfill_A"
        with patch.object(runner.backfill, "main") as backend:
            self.assertEqual(0, runner.main(["--config", str(self.config_path)]))
            backend.assert_not_called()
        self.assertFalse(original.exists())

    def test_disabled_scheduler_never_calls_backend(self):
        with patch.object(runner.backfill, "main") as backend:
            self.assertEqual(0, runner.main(["--config", str(self.config_path), "--live"]))
            backend.assert_not_called()

    def test_business_hours_and_minimum_reserve(self):
        day = datetime(2026, 10, 16, 12, 0, tzinfo=KST)  # Friday
        self.assertTrue(runner.eligible_business_window(self.config, day))
        self.assertFalse(runner.eligible_business_window(
            self.config, day.replace(hour=17, minute=30)))
        self.assertFalse(runner.eligible_business_window(
            self.config, day.replace(hour=8)))
        self.assertFalse(runner.eligible_business_window(
            self.config, day + timedelta(days=1)))
        with self.assertRaises(ValueError):
            runner.eligible_business_window(
                dict(self.config, business_hours_kst={"start": None,"end":None}), day)

    def test_refuses_same_meta_token_or_app_id(self):
        self.enable()
        self.assertEqual(2, len(runner.verify_pair(self.config_path, self.config)))
        self.b.write_text("META_ACCESS_TOKEN=DUMMY_A\nMETA_IG_USER_ID=456\nMETA_APP_ID=2002\n")
        with self.assertRaisesRegex(ValueError, "different"):
            runner.verify_pair(self.config_path, self.config)
        self.b.write_text("META_ACCESS_TOKEN=DUMMY_B\nMETA_IG_USER_ID=456\nMETA_APP_ID=1001\n")
        with self.assertRaisesRegex(ValueError, "different"):
            runner.verify_pair(self.config_path, self.config)

    def test_enabled_authorized_window_dispatches_both_slots(self):
        self.enable()
        day = datetime(2026, 10, 16, 12, 0, tzinfo=KST)
        with patch.object(runner, "now_kst", return_value=day), \
             patch.object(runner.backfill, "main", return_value=0) as backend:
            self.assertEqual(0, runner.main(["--config", str(self.config_path), "--live"]))
            self.assertEqual(2, backend.call_count)
            self.assertIn("A", backend.call_args_list[0].args[0])
            self.assertIn("B", backend.call_args_list[1].args[0])
            self.assertIn("--live", backend.call_args_list[0].args[0])

    def test_skips_with_expired_or_missing_b_credentials(self):
        self.enable()
        self.b.unlink()
        with patch.object(runner, "now_kst",
                          return_value=datetime(2026,10,16,12,0,tzinfo=KST)), \
             patch.object(runner.backfill, "main") as backend:
            self.assertEqual(2, runner.main(["--config", str(self.config_path), "--live"]))
            backend.assert_not_called()

    def test_stops_before_running_if_separate_apps_unconfirmed(self):
        self.enable()
        self.config["separate_authorized_apps_confirmed"] = False
        self.write()
        with patch.object(runner, "now_kst",
                          return_value=datetime(2026,10,16,12,0,tzinfo=KST)), \
             patch.object(runner.backfill, "main") as backend:
            self.assertEqual(2, runner.main(["--config", str(self.config_path), "--live"]))
            backend.assert_not_called()


if __name__ == "__main__":
    unittest.main()
