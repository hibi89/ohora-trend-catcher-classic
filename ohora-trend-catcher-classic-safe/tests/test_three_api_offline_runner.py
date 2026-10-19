"""Offline-only three-lane runner integration tests (no credentials/HTTP)."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "raw_v2"))
from three_api_offline_runner import OfflineThreeApiRunner


def accounts():
    return [
        {"ordinal": i, "key": "KR_%03d" % i, "username": "nails_%d" % i}
        for i in range(1, 295)
    ]


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def runner(self, fixture):
        runner = OfflineThreeApiRunner(
            Path(self.tmp.name) / "staging.sqlite", accounts(), fixture
        )
        self.addCleanup(runner.close)
        runner.seed()
        return runner

    def test_lane_a_stages_first_page(self):
        seen = []
        def fixture(intent, cursor):
            seen.append((intent["account_ordinal"], intent["logical_page"], cursor))
            return {"data": [{"id": "p1"}]}
        runner = self.runner(fixture)
        result = runner.run_one("A")
        self.assertEqual(result["status"], "staged")
        self.assertEqual(seen, [(1, 1, None)])
        self.assertEqual(runner.coordinator.db.execute(
            "SELECT COUNT(*) FROM staging_posts"
        ).fetchone()[0], 1)

    def test_a_to_c_verified_page_chain(self):
        seen = []
        def fixture(intent, cursor):
            seen.append((intent["logical_page"], cursor))
            if intent["logical_page"] == 1:
                return {"data": [{"id": "p1"}], "paging": {
                    "next": "https://graph.facebook.com/next",
                    "cursors": {"after": "cursor1"}}}
            return {"data": [{"id": "p2"}]}
        runner = self.runner(fixture)
        first = runner.run_one("A")
        second = runner.run_one("C")
        self.assertEqual((first["page"], second["page"]), (1, 2))
        self.assertEqual(seen, [(1, None), (2, "cursor1")])
        self.assertEqual(runner.coordinator.db.execute(
            "SELECT COUNT(*) FROM staging_posts"
        ).fetchone()[0], 2)

    def test_invalid_response_does_not_acknowledge(self):
        runner = self.runner(lambda intent, cursor: {
            "data": [{"id": "p1"}],
            "paging": {"next": "https://graph.facebook.com/next"},
        })
        with self.assertRaises(ValueError):
            runner.run_one("A")
        db = runner.coordinator.db
        self.assertEqual(db.execute("SELECT COUNT(*) FROM staging_posts").fetchone()[0], 0)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM page_evidence").fetchone()[0], 0)
        self.assertEqual(db.execute(
            "SELECT state FROM jobs WHERE account_ordinal=1 AND page=1"
        ).fetchone()[0], "leased")

    def test_fixture_failure_keeps_lease(self):
        def fixture(intent, cursor):
            raise RuntimeError("synthetic fixture failure")
        runner = self.runner(fixture)
        with self.assertRaisesRegex(RuntimeError, "synthetic"):
            runner.run_one("A")
        self.assertEqual(runner.coordinator.db.execute(
            "SELECT COUNT(*) FROM page_evidence"
        ).fetchone()[0], 0)

    def test_no_work_on_terminal_page_two(self):
        runner = self.runner(lambda intent, cursor: {"data": [{"id": "p1"}]})
        runner.run_one("A")
        self.assertEqual(runner.run_one("C")["status"], "no_eligible_job")


if __name__ == "__main__":
    unittest.main()
