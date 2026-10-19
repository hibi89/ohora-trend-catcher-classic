"""Offline acceptance tests for app-partitioned Instagram collection.

Run: python -m unittest discover -s experiments -p 'test_*collector.py' -v
     python -m unittest discover -s experiments -p test_two_app_runner.py -v
"""
from __future__ import annotations

from contextlib import closing
import csv
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import full_batch_collector as collector
import two_app_runner as duo
from test_full_batch_collector import make_source, fake_response


class TwoAppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "official.csv"
        make_source(self.source)
        self.accounts, self.digest = collector.load_source(self.source)
        self.env_a = self.root / "owner.local"
        self.env_b = self.root / "hongju.local"
        self.env_c = self.root / "third.local"
        self.env_a.write_text("META_ACCESS_TOKEN=TOKEN_OWNER\nMETA_IG_USER_ID=111\nMETA_APP_ID=1111\n")
        self.env_b.write_text("META_ACCESS_TOKEN=TOKEN_HONGJU\nMETA_IG_USER_ID=222\nMETA_APP_ID=2222\n")
        self.env_c.write_text("META_ACCESS_TOKEN=TOKEN_THIRD\nMETA_IG_USER_ID=333\nMETA_APP_ID=3333\n")
        self.out = self.root / "dual"

    def args(self, live=False):
        options = ["--source", str(self.source),
                   "--app", "owner=" + str(self.env_a),
                   "--app", "hongju=" + str(self.env_b),
                   "--output-dir", str(self.out), "--delay-seconds", "0"]
        return options + (["--live"] if live else [])

    def test_exact_294_split_150_144_and_no_overlap(self):
        plan = duo.plan_accounts(self.accounts, duo.parse_apps(
            ["owner=" + str(self.env_a), "hongju=" + str(self.env_b)]), 150)
        self.assertEqual([("owner", 1, 150, 150), ("hongju", 151, 300, 144)],
                         [(n, a, b, c) for n, _, a, b, c in plan])
        covered = [i for _, _, first, last, _ in plan
                   for i in range(first, min(last, len(self.accounts)) + 1)]
        self.assertEqual(list(range(1, 295)), covered)

    def test_future_300_works_and_301_requires_third_app(self):
        apps = duo.parse_apps(["owner=" + str(self.env_a), "hongju=" + str(self.env_b)])
        future = self.accounts + [dict(self.accounts[-1], account_key="JP_094",
                                       username="morejp94", ordinal=295)]
        plan = duo.plan_accounts(future, apps, 150)
        self.assertEqual(145, plan[1][-1])
        for i in range(296, 302):
            future.append(dict(self.accounts[-1], account_key=f"JP_{i:03d}",
                               username=f"extra{i}", ordinal=i))
        with self.assertRaisesRegex(ValueError, "Add another authorized"):
            duo.plan_accounts(future, apps, 150)
        third = duo.parse_apps(["owner=" + str(self.env_a),
                                "hongju=" + str(self.env_b), "third=" + str(self.env_c)])
        plan = duo.plan_accounts(future, third, 150)
        self.assertEqual((301, 450, 1), plan[2][2:])

    def test_duplicate_apps_or_paths_rejected(self):
        with self.assertRaisesRegex(ValueError, "unique"):
            duo.parse_apps(["owner=" + str(self.env_a), "owner=" + str(self.env_b)])
        with self.assertRaisesRegex(ValueError, "unique"):
            duo.parse_apps(["owner=" + str(self.env_a), "other=" + str(self.env_a)])

    def test_preview_is_offline_and_creates_no_files(self):
        with patch.object(collector, "request_batch") as unused:
            self.assertEqual(0, duo.run(self.args()))
            unused.assert_not_called()
        self.assertFalse(self.out.exists())

    def test_preflight_never_requests_if_second_file_absent(self):
        self.env_b.unlink()
        with patch.object(collector, "request_batch") as unused:
            self.assertEqual(2, duo.run(self.args(live=True)))
            unused.assert_not_called()
        self.assertFalse(self.out.exists())

    def test_preflight_never_requests_with_same_token(self):
        self.env_b.write_text("META_ACCESS_TOKEN=TOKEN_OWNER\nMETA_IG_USER_ID=222\nMETA_APP_ID=2222\n")
        with self.assertRaisesRegex(ValueError, "same Meta access token"):
            duo.preflight_credentials(duo.plan_accounts(
                self.accounts, duo.parse_apps([
                    "owner=" + str(self.env_a), "hongju=" + str(self.env_b)]), 150))
        with patch.object(collector, "request_batch") as unused:
            self.assertEqual(2, duo.run(self.args(live=True)))
            unused.assert_not_called()
        self.assertFalse(self.out.exists())

    def test_preflight_same_declared_app_id_refused(self):
        self.env_b.write_text("META_ACCESS_TOKEN=TOKEN_B\nMETA_IG_USER_ID=222\nMETA_APP_ID=1111\n")
        with self.assertRaisesRegex(ValueError, "same META_APP_ID"):
            duo.preflight_credentials(duo.plan_accounts(
                self.accounts, duo.parse_apps([
                    "owner=" + str(self.env_a), "hongju=" + str(self.env_b)]), 150))

    def test_one_batch_each_uses_own_token_and_ordinal_range(self):
        requests = []
        def stub(version, token, operations, timeout=120):
            from urllib.parse import parse_qs
            requests.append((token, operations))
            expected = "111" if token == "TOKEN_OWNER" else "222"
            self.assertTrue(all(x["relative_url"].startswith(expected + "?")
                                for x in operations))
            self.assertTrue(all("media.limit(10)" in
                    parse_qs(op["relative_url"].split("?", 1)[1])["fields"][0]
                    for op in operations))
            return 200, fake_response(operations, count=10), {}, 0.1
        with patch.object(collector, "request_batch", side_effect=stub):
            self.assertEqual(0, duo.run(self.args(live=True)
                 + ["--max-batches-per-app", "1"]))
        self.assertEqual(2, len(requests))
        self.assertEqual(["TOKEN_OWNER", "TOKEN_HONGJU"], [x[0] for x in requests])
        for name, first in (("owner", 1), ("hongju", 151)):
            with closing(sqlite3.connect(self.out / name / "collection.sqlite")) as db:
                self.assertEqual(10, db.execute("SELECT COUNT(*) FROM accounts "
                    "WHERE status='success'").fetchone()[0])
                self.assertEqual(100, db.execute("SELECT COUNT(*) FROM posts").fetchone()[0])
                self.assertEqual((first, first + 9), db.execute(
                    "SELECT min(ordinal),max(ordinal) FROM accounts "
                    "WHERE status='success'").fetchone())
                self.assertEqual(
                    ("10",), db.execute("SELECT value FROM manifest "
                    "WHERE key='posts_requested'").fetchone())
                self.assertEqual(name, db.execute("SELECT value FROM manifest "
                    "WHERE key='assigned_app'").fetchone()[0])

    def test_rerun_next_batch_is_resumable_and_no_double_calls(self):
        seen = []
        def stub(_version, token, ops, timeout=120):
            seen.append(token)
            # A different fixture post ID per batch avoids unrealistic duplicate
            # IDs across distinct account sets in the fake Meta responses.
            items = fake_response(ops, count=10)
            for entry in items:
                entry["body"] = entry["body"].replace("fake-", f"round{len(seen)}-")
            return 200, items, {}, 0.1
        with patch.object(collector, "request_batch", side_effect=stub):
            for i in range(2):
                self.assertEqual(0, duo.run(self.args(live=True)
                    + ["--max-batches-per-app", "1"]))
        self.assertEqual(4, len(seen))
        for name in ("owner", "hongju"):
            with closing(sqlite3.connect(self.out / name / "collection.sqlite")) as db:
                self.assertEqual(20, db.execute("SELECT COUNT(*) FROM accounts "
                    "WHERE status='success'").fetchone()[0])
                self.assertEqual(200, db.execute("SELECT COUNT(*) FROM posts").fetchone()[0])

    def test_only_hongju_app_runs_only_151_to_160(self):
        seen = []
        def stub(_version, token, ops, timeout=120):
            seen.append((token, len(ops)))
            return 200, fake_response(ops, count=10), {}, 0.1
        with patch.object(collector, "request_batch", side_effect=stub):
            self.assertEqual(0, duo.run(self.args(live=True) +
                ["--only-app", "hongju", "--max-batches-per-app", "1"]))
        self.assertEqual([("TOKEN_HONGJU", 10)], seen)
        self.assertFalse((self.out / "owner").exists())
        with closing(sqlite3.connect(self.out / "hongju" / "collection.sqlite")) as db:
            self.assertEqual((151, 160), db.execute(
                "SELECT min(ordinal),max(ordinal) FROM accounts "
                "WHERE status='success'").fetchone())

    def test_usage_cutoff_app_a_stops_before_app_b(self):
        seen = []
        def high_usage(_version, token, ops, timeout=120):
            seen.append(token)
            responses = fake_response(ops, count=10)
            for item in responses:
                item["headers"][0]["value"] = json.dumps(
                    {"call_count": 11, "total_time": 78, "total_cputime": 0})
            return 200, responses, {}, 0.1
        with patch.object(collector, "request_batch", side_effect=high_usage):
            self.assertEqual(5, duo.run(self.args(live=True)))
        self.assertEqual(["TOKEN_OWNER"], seen)
        self.assertFalse((self.out / "hongju").exists())

    def test_missing_meta_usage_header_stops_before_next_app(self):
        seen = []
        def no_usage(_version, token, ops, timeout=120):
            seen.append(token)
            items = fake_response(ops, count=10)
            for item in items:
                item["headers"] = []
            return 200, items, {}, 0.1
        with patch.object(collector, "request_batch", side_effect=no_usage):
            self.assertEqual(6, duo.run(self.args(live=True)))
        self.assertEqual(["TOKEN_OWNER"], seen)

    def test_append_only_accounts_preserves_success_data(self):
        out = self.root / "append.sqlite"
        with closing(collector.database(out, self.accounts, self.digest, 10, (151,300,"hongju"))) as db:
            with db:
                db.execute("UPDATE accounts SET status='success' WHERE ordinal=151")
        append = dict(self.accounts[-1], ordinal=295, account_key="JP_094",
                      username="new_nail_artist")
        rows = self.accounts + [append]
        new_digest = "different_sha_new_account"
        with closing(collector.database(out, rows, new_digest, 10, (151,300,"hongju"))) as db:
            self.assertEqual(295, db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0])
            self.assertEqual(("success",), db.execute(
                "SELECT status FROM accounts WHERE ordinal=151").fetchone())
            self.assertEqual(("pending",), db.execute(
                "SELECT status FROM accounts WHERE ordinal=295").fetchone())
        mutated = [dict(a) for a in rows]
        mutated[0]["username"] = "changed_old_account"
        with self.assertRaisesRegex(ValueError, "changed/reordered"):
            collector.database(out, mutated, "another_digest", 10, (151,300,"hongju"))

    def test_changes_to_partition_refused_on_resume(self):
        out = self.root / "partition.sqlite"
        with closing(collector.database(out, self.accounts, self.digest, 10, (1,150,"owner"))):
            pass
        with self.assertRaisesRegex(ValueError, "partition/schema/posts"):
            collector.database(out, self.accounts, self.digest, 10, (1,149,"owner"))
        with self.assertRaisesRegex(ValueError, "partition/schema/posts"):
            collector.database(out, self.accounts, self.digest, 5, (1,150,"owner"))


if __name__ == "__main__":
    unittest.main()
