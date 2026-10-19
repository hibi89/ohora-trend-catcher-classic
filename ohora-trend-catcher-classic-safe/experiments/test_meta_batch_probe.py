"""Offline checks only; the real Meta API is never contacted."""
import csv
import importlib.util
import json
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch

SRC = Path(__file__).with_name("meta_batch_probe.py")
spec = importlib.util.spec_from_file_location("meta_batch_probe", SRC)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def source(path):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["account_key", "username", "country", "image_url"])
        w.writeheader()
        for i in range(294):
            w.writerow({"account_key": f"KR_{i+1:03d}", "username": f"nail.{i}",
                        "country": "KR", "image_url": "x"})


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "account_list.csv"
        source(self.path)
        self.accounts = probe.accounts_for_keys(self.path, ["KR_001", "KR_002"])

    def test_dry_run_zero_api_calls(self):
        with patch.object(probe, "execute_once") as send:
            self.assertEqual(probe.main(["--source", str(self.path), "--keys", "KR_001"]), 0)
            send.assert_not_called()

    def test_batch_request_fields_and_limit(self):
        ops = probe.build_operations(self.accounts, "12345678", 10)
        self.assertEqual(len(ops), 2)
        self.assertTrue(all(x["method"] == "GET" for x in ops))
        self.assertIn("media.limit%2810%29", ops[0]["relative_url"])
        self.assertIn("children.limit%2850%29", ops[0]["relative_url"])

    def test_stats_carousel_and_missing_likes(self):
        body = {"business_discovery": {"media": {"data": [
            {"media_type": "CAROUSEL_ALBUM", "like_count": None, "comments_count": 3,
             "children": {"data": [{"media_type": "IMAGE", "media_url": "some_url"},
                                     {"media_type": "VIDEO", "thumbnail_url": "t"}]}},
            {"media_type": "IMAGE", "media_url": "image_url", "like_count": 0,
             "comments_count": 0},
        ]}}}
        r = probe.stats_for_result(200, body, self.accounts[0])
        self.assertEqual(r["posts"], 2)
        self.assertEqual(r["carousels"], 1)
        self.assertEqual(r["carousel_children"], 2)
        self.assertEqual(r["image_urls"], 2)
        self.assertEqual(r["likes_missing"], 1)

    def test_batch_failures_and_rate_limit(self):
        arr = [{"code": 200, "body": json.dumps({"business_discovery": {"media": {"data": []}}})},
               {"code": 403, "body": json.dumps({"error": {"code": 4}})}]
        h = Message(); h["X-App-Usage"] = '{"total_time":100,"call_count":21}'
        r = probe.summarize(arr, self.accounts, 200, h, 1.23, 10)
        self.assertEqual(r["successful_accounts"], 1)
        self.assertTrue(r["rate_limited"])
        self.assertEqual(r["outer_app_usage"]["total_time"], 100)

    def test_bad_source_and_max_accounts_fail_without_request(self):
        with self.assertRaises(ValueError):
            probe.accounts_for_keys(self.path, ["KR_001"] * 2)
        with self.assertRaises(ValueError):
            probe.accounts_for_keys(self.path, [f"KR_{i+1:03d}" for i in range(11)])
        self.assertEqual(probe.main(["--source", str(self.path), "--keys", "UNKNOWN"]), 2)

    def test_live_single_call_and_safe_report(self):
        good = [{"code": 200, "body": json.dumps({"business_discovery": {"media": {"data": []}}})}]
        h = Message(); h["X-App-Usage"] = '{"total_time":25}'
        out = Path(self.tmp.name) / "output"
        with patch.object(probe, "execute_once", return_value=(200, good, h, .44)) as send, \
             patch.object(probe, "load_env", return_value={"META_ACCESS_TOKEN": "secret-SHOULD-NOT-APPEAR",
                                                            "META_IG_USER_ID": "12345",
                                                            "META_GRAPH_VERSION": "v26.0"}):
            rc = probe.main(["--source", str(self.path), "--keys", "KR_001", "--live",
                             "--output-dir", str(out)])
        self.assertEqual(rc, 0)
        send.assert_called_once()
        report = next(out.glob("*.json")).read_text()
        self.assertNotIn("secret-SHOULD-NOT-APPEAR", report)
        self.assertEqual(json.loads(report)["outer_app_usage"]["total_time"], 25)


if __name__ == "__main__":
    unittest.main()
