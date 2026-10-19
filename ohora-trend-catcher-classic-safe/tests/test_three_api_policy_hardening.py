"""Security and quota policy regression cases for offline HTTP fixtures."""
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "raw_v2"))
from three_api_coordinator import Coordinator
from three_api_evidence import PageEvidenceStore
from three_api_http_fixture import stage_fixture_envelope
from three_api_usage import parse_usage


class PolicyHardeningTests(unittest.TestCase):
    def test_regain_access_duration_is_not_utilization(self):
        headers = {"X-Business-Use-Case-Usage": (
            '{"123":[{"call_count":30,"total_cputime":15,'
            '"total_time":10,"estimated_time_to_regain_access":999}]}' )}
        self.assertEqual(parse_usage(headers), 30)

    def test_error_payload_with_http_200_blocks_and_halts(self):
        with tempfile.TemporaryDirectory() as folder:
            c = Coordinator(Path(folder) / "test.sqlite")
            try:
                c.seed()
                e = PageEvidenceStore(c)
                now = datetime(2026, 10, 19, tzinfo=timezone.utc)
                job = c.lease("A", now=now)
                envelope = {"status": 200,
                    "headers": {"X-App-Usage": '{"call_count":10}'},
                    "body": {"error": {"code": 190, "message": "invalid token"}}}
                result = stage_fixture_envelope(c, e, job, envelope, now=now)
                self.assertEqual(result["status"], "blocked")
                self.assertEqual(result["reason"], "api_error_envelope")
                self.assertIsNone(c.lease("A", now=now))
                self.assertEqual(c.db.execute(
                    "SELECT COUNT(*) FROM staging_posts").fetchone()[0], 0)
            finally:
                c.db.close()


if __name__ == "__main__":
    unittest.main()
