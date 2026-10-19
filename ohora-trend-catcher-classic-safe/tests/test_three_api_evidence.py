"""Offline transactional page evidence tests."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "raw_v2"))
from three_api_coordinator import Coordinator
from three_api_evidence import PageEvidenceStore


def response(after=None):
    if after:
        return {"data": [{"id": "post"}],
                "paging": {"next": "https://graph.facebook.com/next",
                           "cursors": {"after": after}}}
    return {"data": [{"id": "post"}]}


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.c = Coordinator(Path(self.tmp.name) / "state.sqlite")
        # On Windows, SQLite connections must close before TemporaryDirectory cleanup.
        self.addCleanup(self.c.db.close)
        self.c.seed()
        self.e = PageEvidenceStore(self.c)

    def test_commit_and_predecessor_cursor(self):
        job = self.c.lease("A")
        self.assertEqual((job["account_ordinal"], job["page"]), (1, 1))
        edge = self.e.commit_page(job["id"], job["lease_id"], "stored-1", response("edge1"))
        self.assertEqual(edge["next_cursor"], "edge1")
        self.assertEqual(self.e.required_cursor(1, 2), "edge1")

    def test_uncommitted_predecessor_rejected(self):
        with self.assertRaises(ValueError):
            self.e.required_cursor(1, 2)

    def test_stale_lease_rejected(self):
        job = self.c.lease("A")
        with self.assertRaises(ValueError):
            self.e.commit_page(job["id"], "wrong", "stored-1", response("edge1"))
        self.assertEqual(self.c.db.execute("SELECT state FROM jobs WHERE id=?",
                         (job["id"],)).fetchone()[0], "leased")

    def test_bad_page_response_rolls_back(self):
        job = self.c.lease("A")
        with self.assertRaises(ValueError):
            self.e.commit_page(job["id"], job["lease_id"], "stored-1",
                               {"data": [], "paging": {"next": "url"}})
        self.assertEqual(self.c.db.execute("SELECT COUNT(*) FROM page_evidence")
                         .fetchone()[0], 0)

    def test_duplicate_receipt_commit_rejected(self):
        job = self.c.lease("A")
        self.e.commit_page(job["id"], job["lease_id"], "stored-1", response("edge1"))
        with self.assertRaises(ValueError):
            self.e.commit_page(job["id"], job["lease_id"], "stored-1", response("edge1"))



    def test_bare_completion_forbidden_once_evidence_enabled(self):
        job = self.c.lease("A")
        with self.assertRaises(RuntimeError):
            self.c.complete(job["id"], job["lease_id"])
        self.assertEqual(self.c.db.execute(
            "SELECT state FROM jobs WHERE id=?", (job["id"],)
        ).fetchone()[0], "leased")

    def test_terminal_page_prevents_next_page_leasing(self):
        job = self.c.lease("A")
        self.e.commit_page(job["id"], job["lease_id"], "stored-terminal",
                           response())
        self.assertIsNone(self.c.lease("C"))

    def test_second_page_uses_verified_cursor(self):
        job1 = self.c.lease("A")
        self.e.commit_page(job1["id"], job1["lease_id"], "stored-first",
                           response("edge1"))
        job2 = self.c.lease("C")
        self.assertEqual((job2["account_ordinal"], job2["page"]), (1, 2))
        with self.assertRaises(ValueError):
            self.e.commit_page(job2["id"], job2["lease_id"],
                               "stored-second", response("edge2"),
                               requested_cursor="other")
        self.assertEqual(self.c.db.execute(
            "SELECT COUNT(*) FROM page_evidence"
        ).fetchone()[0], 1)
        self.e.commit_page(job2["id"], job2["lease_id"], "stored-second",
                           response("edge2"), requested_cursor="edge1")
        saved = self.c.db.execute(
            "SELECT requested_cursor,response_cursor FROM page_evidence "
            "WHERE account_ordinal=1 AND page=2"
        ).fetchone()
        self.assertEqual(tuple(saved), ("edge1", "edge2"))

    def test_expired_lease_cannot_commit(self):
        from datetime import datetime, timedelta, timezone
        t = datetime(2026, 10, 19, tzinfo=timezone.utc)
        job = self.c.lease("A", now=t)
        with self.assertRaises(ValueError):
            self.e.commit_page(job["id"], job["lease_id"],
                               "stored-expired", response("edge1"),
                               now=t + timedelta(minutes=16))
        self.assertEqual(self.c.db.execute(
            "SELECT COUNT(*) FROM page_evidence"
        ).fetchone()[0], 0)

    def test_duplicate_receipt_rolls_back_other_job(self):
        import sqlite3
        job1 = self.c.lease("A")
        self.e.commit_page(job1["id"], job1["lease_id"],
                           "stored-shared", response("edge1"))
        job2 = self.c.lease("B")
        with self.assertRaises(sqlite3.IntegrityError):
            self.e.commit_page(job2["id"], job2["lease_id"],
                               "stored-shared", response("edge-other"))
        self.assertEqual(self.c.db.execute(
            "SELECT state FROM jobs WHERE id=?", (job2["id"],)
        ).fetchone()[0], "leased")

    def test_empty_next_page_fails_closed(self):
        job = self.c.lease("A")
        with self.assertRaises(ValueError):
            self.e.commit_page(job["id"], job["lease_id"], "stored-empty",
                               {"data": [], "paging": {
                                   "next": "https://graph.facebook.com/m",
                                   "cursors": {"after": "edge1"}}})
        self.assertEqual(self.c.db.execute(
            "SELECT COUNT(*) FROM page_evidence"
        ).fetchone()[0], 0)


    def test_staged_commit_is_atomic(self):
        job = self.c.lease("A")
        edge = self.e.commit_staged_page(
            job["id"], job["lease_id"], {
                "data": [{"id": "post-1", "caption": "nail"}],
                "paging": {"next": "https://graph.facebook.com/next",
                           "cursors": {"after": "edge1"}},
            })
        self.assertEqual(edge["next_cursor"], "edge1")
        self.assertEqual(self.c.db.execute(
            "SELECT COUNT(*) FROM staging_posts"
        ).fetchone()[0], 1)
        self.assertEqual(self.c.db.execute(
            "SELECT COUNT(*) FROM page_evidence"
        ).fetchone()[0], 1)
        self.assertEqual(self.c.db.execute(
            "SELECT state FROM jobs WHERE id=?", (job["id"],)
        ).fetchone()[0], "done")

    def test_staged_invalid_cursor_rolls_back_posts(self):
        job = self.c.lease("A")
        with self.assertRaises(ValueError):
            self.e.commit_staged_page(
                job["id"], job["lease_id"], {
                    "data": [{"id": "post-1"}],
                    "paging": {"next": "https://graph.facebook.com/next"},
                })
        self.assertEqual(self.c.db.execute(
            "SELECT COUNT(*) FROM staging_posts"
        ).fetchone()[0], 0)
        self.assertEqual(self.c.db.execute(
            "SELECT COUNT(*) FROM page_evidence"
        ).fetchone()[0], 0)

    def test_staged_duplicate_post_id_rejected(self):
        job = self.c.lease("A")
        with self.assertRaises(ValueError):
            self.e.commit_staged_page(job["id"], job["lease_id"], {
                "data": [{"id": "dup"}, {"id": "dup"}],
            })
        self.assertEqual(self.c.db.execute(
            "SELECT COUNT(*) FROM staging_posts"
        ).fetchone()[0], 0)

    def test_staged_stale_lease_rolls_back(self):
        job = self.c.lease("A")
        with self.assertRaises(ValueError):
            self.e.commit_staged_page(job["id"], "stale", {
                "data": [{"id": "post-1"}],
            })
        self.assertEqual(self.c.db.execute(
            "SELECT COUNT(*) FROM staging_posts"
        ).fetchone()[0], 0)

    def test_staged_limit_rejected(self):
        job = self.c.lease("A")
        with self.assertRaises(ValueError):
            self.e.commit_staged_page(job["id"], job["lease_id"], {
                "data": [{"id": str(i)} for i in range(5)],
            })


if __name__ == "__main__":
    unittest.main()
