"""Synthetic HTTP envelope integration: zero network calls."""
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "raw_v2"))
from three_api_coordinator import Coordinator
from three_api_evidence import PageEvidenceStore
from three_api_http_fixture import stage_fixture_envelope


class EnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.c = Coordinator(Path(self.tmp.name) / "fixture.sqlite")
        self.addCleanup(self.c.db.close)
        self.c.seed()
        self.e = PageEvidenceStore(self.c)
        self.now = datetime(2026, 10, 19, tzinfo=timezone.utc)
        self.job = self.c.lease("A", now=self.now)

    def envelope(self, usage=20, status=200, body=None):
        if body is None:
            body = {"data": [{"id": "p1", "caption": "nail"}]}
        return {"status": status, "headers": {
            "X-App-Usage": '{"call_count": %s}' % usage}, "body": body}

    def count(self):
        return self.c.db.execute("SELECT COUNT(*) FROM staging_posts").fetchone()[0]

    def test_healthy_response_commits(self):
        result = stage_fixture_envelope(self.c, self.e, self.job,
                                        self.envelope(), now=self.now)
        self.assertEqual(result["status"], "staged")
        self.assertEqual(self.count(), 1)

    def test_threshold_blocks_before_staging(self):
        result = stage_fixture_envelope(self.c, self.e, self.job,
                                        self.envelope(85), now=self.now)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(self.count(), 0)
        self.assertIsNone(self.c.lease("A", now=self.now))

    def test_missing_header_blocks(self):
        response = self.envelope()
        response["headers"] = {}
        result = stage_fixture_envelope(self.c, self.e, self.job,
                                        response, now=self.now)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(self.count(), 0)

    def test_rate_limit_blocks(self):
        response = self.envelope(status=429, body={"error": {"code": 613}})
        result = stage_fixture_envelope(self.c, self.e, self.job,
                                        response, now=self.now)
        self.assertEqual(result["reason"], "cooldown")
        self.assertEqual(self.count(), 0)

    def test_permission_error_blocks(self):
        response = self.envelope(status=403, body={"error": {"code": 200}})
        result = stage_fixture_envelope(self.c, self.e, self.job,
                                        response, now=self.now)
        self.assertEqual(result["reason"], "credentials_or_permissions")
        self.assertEqual(self.count(), 0)

    def test_bad_media_rolls_back(self):
        with self.assertRaises(ValueError):
            stage_fixture_envelope(self.c, self.e, self.job,
                self.envelope(body={"data": [{"caption": "missing id"}]}),
                now=self.now)
        self.assertEqual(self.count(), 0)


if __name__ == "__main__":
    unittest.main()
