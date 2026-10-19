"""Offline tests for read-only three-API cursor/checkpoint policy."""
import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest

RAW = Path(__file__).resolve().parents[1] / "raw_v2"
spec = importlib.util.spec_from_file_location("three_api_checkpoints", RAW / "three_api_checkpoints.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class CheckpointTests(unittest.TestCase):
    def test_head_is_allowed(self):
        self.assertEqual(mod.page_request_policy(1)["cursor"], None)
        self.assertTrue(mod.page_request_policy(1)["allowed"])

    def test_history_fails_closed_without_chain(self):
        self.assertFalse(mod.page_request_policy(2)["allowed"])
        self.assertFalse(mod.page_request_policy(3, verified_chain=["a"])["allowed"])

    def test_verified_chain(self):
        result = mod.page_request_policy(3, verified_chain=["a", "b"])
        self.assertTrue(result["allowed"])
        self.assertEqual(result["cursor"], "b")

    def test_repeated_or_invalid_cursor_rejected(self):
        with self.assertRaises(ValueError):
            mod.page_request_policy(3, verified_chain=["a", "a"])
        with self.assertRaises(ValueError):
            mod.page_request_policy(2, verified_chain=["not a cursor"])

    def test_read_only_checkpoint(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "snapshot.sqlite"
            # sqlite3 connection context commits/rolls back but does not close.
            db = sqlite3.connect(path)
            try:
                db.execute("""CREATE TABLE accounts (
                    account_key TEXT PRIMARY KEY, latest_id TEXT,
                    backfill_cursor TEXT, catchup_cursor TEXT,
                    catchup_anchor TEXT, backfill_done INTEGER)""")
                db.execute("INSERT INTO accounts VALUES (?,?,?,?,?,?)",
                           ("KR_001", "post1", "after1", None, None, 0))
                db.commit()
            finally:
                db.close()
            result = mod.inspect_checkpoint(path, "KR_001")
            self.assertEqual(result["backfill_cursor"], "after1")
            db = sqlite3.connect(path)
            try:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0], 1)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
