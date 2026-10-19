"""End-to-end quota-gated offline fixture tests, no network or secrets."""
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "raw_v2"))
from three_api_offline_runner import OfflineThreeApiRunner


def roster():
    return [{"ordinal": i, "key": "key%d" % i, "username": "nail%d" % i}
            for i in range(1, 295)]


def envelope(usage, after=None, status=200):
    page = {"data": [{"id": "post-%s" % (after or "head")}]}
    if after is None:
        page["paging"] = {"next": "https://graph.facebook.com/next?access_token=SECRET",
                          "cursors": {"after": "cursor1"}}
    return {"status": status,
            "headers": {"X-App-Usage": '{"call_count": %d}' % usage},
            "body": page}


class EnvelopeRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = datetime(2026, 10, 19, tzinfo=timezone.utc)

    def runner(self, fetch):
        runner = OfflineThreeApiRunner(Path(self.tmp.name) / "runner.sqlite",
                                       roster(), fetch, envelope_fixture=True)
        self.addCleanup(runner.close)
        runner.seed()
        return runner

    def test_a_to_c_cursor_and_secret_url_removed(self):
        seen = []
        def fetch(intent, cursor):
            seen.append((intent["lane"], cursor))
            return envelope(20, after=cursor)
        runner = self.runner(fetch)
        self.assertEqual(runner.run_one("A", now=self.now)["status"], "staged")
        self.assertEqual(runner.run_one("C", now=self.now)["status"], "staged")
        self.assertEqual(seen, [("A", None), ("C", "cursor1")])
        self.assertEqual(runner.coordinator.db.execute(
            "SELECT COUNT(*) FROM staging_posts").fetchone()[0], 2)
        self.assertNotIn("SECRET", str(runner.coordinator.db.execute(
            "SELECT payload_json FROM staging_posts").fetchall()))

    def test_threshold_blocks_without_staging(self):
        runner = self.runner(lambda intent, cursor: envelope(85))
        result = runner.run_one("A", now=self.now)
        self.assertEqual(result["status"], "blocked")
        self.assertIsNone(runner.coordinator.lease("A", now=self.now))
        self.assertEqual(runner.coordinator.db.execute(
            "SELECT COUNT(*) FROM staging_posts").fetchone()[0], 0)

    def test_missing_usage_blocks(self):
        def fetch(intent, cursor):
            result = envelope(20)
            result["headers"] = {}
            return result
        runner = self.runner(fetch)
        self.assertEqual(runner.run_one("A", now=self.now)["status"], "blocked")

    def test_http_error_blocks(self):
        runner = self.runner(lambda intent, cursor: envelope(20, status=429))
        self.assertEqual(runner.run_one("A", now=self.now)["reason"], "cooldown")


if __name__ == "__main__":
    unittest.main()
