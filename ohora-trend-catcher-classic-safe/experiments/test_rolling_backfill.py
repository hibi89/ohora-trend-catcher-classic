"""Offline tests for 90-minute, 5-post cursor backfill. No real Meta calls."""
from __future__ import annotations

import csv
from contextlib import closing
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, unquote

sys.path.insert(0, str(Path(__file__).resolve().parent))
import full_batch_collector as base
import rolling_backfill as mod


def source_294(path: Path):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=["account_key", "username", "country", "image_url"])
        writer.writeheader()
        for country, amount in base.EXPECTED_COUNTS.items():
            for i in range(1, amount + 1):
                writer.writerow({"account_key": f"{country}_{i:03d}",
                                 "username": f"test{country.lower()}{i:03d}",
                                 "country": country,
                                 "image_url": "https://example.invalid/thumb.jpg"})


def fake_result(post_number: int, media_count=80, n=5, after=None):
    data = [{"id": str(17900000000000000 + i), "timestamp": "2026-10-01T12:00:00+0000",
             "media_type": "IMAGE", "media_url": f"https://example.invalid/{i}.jpg",
             "like_count": i, "comments_count": 1}
            for i in range(post_number, post_number + n)]
    payload = {"business_discovery": {
        "id": "123", "username": "example", "followers_count": 1000,
        "media_count": media_count, "media": {"data": data}}}
    if after is not None:
        payload["business_discovery"]["media"]["paging"] = {
            "cursors": {"after": after}}
    return payload


def fake_meta(payload, usage=10):
    return (200, [{"code": 200,
                    "headers": [{"name": "X-App-Usage",
                                 "value": json.dumps({"call_count": 5, "total_time": usage,
                                                      "total_cputime": 0})}],
                    "body": json.dumps(payload)}],
            {}, 0.01)


class CursorBackfillTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.home = Path(t.name)
        self.source = self.home / "accounts.csv"
        source_294(self.source)
        self.config = self.home / "meta.env"
        self.config.write_text(
            "META_ACCESS_TOKEN=FAKE_LOCAL_TEST_TOKEN\n"
            "META_IG_USER_ID=1234567890\nMETA_GRAPH_VERSION=v26.0\n")
        self.output = self.home / "backfill_A"

    def args(self, cycle="cycle001", app="A", live=True, count=1):
        flags = [
            "--app", app, "--source", str(self.source),
            "--env-file", str(self.config), "--output-dir", str(self.output),
            "--batch-size", str(count), "--max-batches", "1",
            "--delay-seconds", "0", "--stop-usage", "70",
            "--cycle-id", cycle,
        ]
        if live:
            flags.append("--live")
        return flags

    def test_split_A_B_and_cursor_field_expression(self):
        self.assertEqual((1, 150), mod.RANGES["A"])
        self.assertEqual((151, 294), mod.RANGES["B"])
        accounts, _ = base.load_source(self.source)
        first = mod.cursor_operation(accounts[0], "123", None)
        f1 = parse_qs(first["relative_url"].split("?", 1)[1])["fields"][0]
        self.assertIn("media.limit(5){", f1)
        after = mod.cursor_operation(accounts[0], "123", "ABCD+/=09")
        f2 = parse_qs(after["relative_url"].split("?", 1)[1])["fields"][0]
        self.assertIn("media.limit(5).after(ABCD+/=09){", f2)
        self.assertNotIn("FAKE_LOCAL_TEST_TOKEN", first["relative_url"])

    def test_single_account_probe_can_advance_one_cursor_without_other_accounts(self):
        probes = []
        def responder(_ver, _token, ops, timeout=120):
            fields = parse_qs(ops[0]["relative_url"].split("?", 1)[1])["fields"][0]
            probes.append(fields)
            return fake_meta(fake_result(1 if len(probes)==1 else 6,
                                         after="NEXT111" if len(probes)==1 else "NEXT222"))
        with patch.object(base, "request_batch", side_effect=responder):
            self.assertEqual(0, mod.main(self.args(cycle="p001") + [
                "--probe-ordinal", "1"]))
            self.assertEqual(0, mod.main(self.args(cycle="p002") + [
                "--probe-ordinal", "1"]))
        self.assertEqual(2, len(probes))
        self.assertIn(".after(NEXT111)", probes[1])
        with closing(sqlite3.connect(self.output / "collection.sqlite")) as db:
            self.assertEqual(10, db.execute("SELECT COUNT(*) FROM posts").fetchone()[0])
            self.assertEqual(0, db.execute(
                "SELECT COUNT(*) FROM posts WHERE account_key<>'KR_001'").fetchone()[0])

    def test_dry_run_never_writes_or_calls_api(self):
        with patch.object(base, "request_batch") as unused:
            self.assertEqual(0, mod.main(self.args(live=False)))
            unused.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_unique_5_to_10_resume_and_same_cycle_noop(self):
        calls = []
        def responder(ver, token, ops, timeout=120):
            self.assertEqual(1, len(ops))
            fields = parse_qs(ops[0]["relative_url"].split("?", 1)[1])["fields"][0]
            calls.append(fields)
            return fake_meta(fake_result(1 if len(calls) == 1 else 6,
                                         after="CURSOR2" if len(calls) == 1 else "CURSOR3"))
        with patch.object(base, "request_batch", side_effect=responder):
            self.assertEqual(0, mod.main(self.args(cycle="cycle001")))
            self.assertEqual(0, mod.main(self.args(cycle="cycle001")))
            with closing(sqlite3.connect(self.output / "collection.sqlite")) as db:
                db.execute("UPDATE backfill_state SET blocked=1 WHERE account_key<>'KR_001'")
                db.commit()
            self.assertEqual(0, mod.main(self.args(cycle="cycle002")))
        self.assertEqual(2, len(calls))
        self.assertNotIn(".after(", calls[0])
        self.assertIn(".after(CURSOR2)", calls[1])
        with closing(sqlite3.connect(self.output / "collection.sqlite")) as db:
            self.assertEqual(10, db.execute("SELECT COUNT(*) FROM posts").fetchone()[0])
            self.assertEqual(10, db.execute("SELECT COUNT(*) FROM media").fetchone()[0])
            self.assertEqual(2, db.execute("SELECT pages_fetched FROM backfill_state "
                                           "WHERE account_key='KR_001'").fetchone()[0])
            self.assertEqual("partial", db.execute("SELECT status FROM accounts "
                                                   "WHERE account_key='KR_001'").fetchone()[0])
            self.assertEqual(2, db.execute("SELECT COUNT(*) FROM backfill_runs").fetchone()[0])
        for filename in self.output.glob("*.csv"):
            self.assertNotIn("FAKE_LOCAL_TEST_TOKEN",
                             filename.read_text(encoding="utf-8-sig"))

    def test_exactly_ten_cycles_to_reach_50_if_pages_have_5_unique(self):
        state = {"page": 0}
        def responder(_ver, _token, _ops, timeout=120):
            state["page"] += 1
            n = state["page"]
            return fake_meta(fake_result((n-1)*5 + 1, after=f"CURSOR{n}"))
        with patch.object(base, "request_batch", side_effect=responder):
            self.assertEqual(0, mod.main(self.args(cycle="round000")))
            with closing(sqlite3.connect(self.output / "collection.sqlite")) as db:
                db.execute("UPDATE backfill_state SET blocked=1 WHERE account_key<>'KR_001'")
                db.commit()
            for i in range(1, 10):
                self.assertEqual(0, mod.main(self.args(cycle=f"round{i:03}")))
            self.assertEqual(0, mod.main(self.args(cycle="round009")))  # duplicate trigger is a no-op
        self.assertEqual(10, state["page"])
        with closing(sqlite3.connect(self.output / "collection.sqlite")) as db:
            self.assertEqual(50, db.execute("SELECT COUNT(*) FROM posts").fetchone()[0])
            self.assertEqual(1, db.execute("SELECT exhausted FROM backfill_state "
                                           "WHERE account_key='KR_001'").fetchone()[0])
            self.assertEqual(50, db.execute("SELECT posts_collected FROM accounts "
                                            "WHERE account_key='KR_001'").fetchone()[0])

    def test_missing_cursor_on_full_page_is_blocked_no_repeated_head(self):
        with patch.object(base, "request_batch", return_value=fake_meta(fake_result(1, after=None))) as fn:
            self.assertEqual(0, mod.main(self.args(cycle="round001")))
            self.assertEqual(0, mod.main(self.args(cycle="round001")))
            self.assertEqual(1, fn.call_count)
        with closing(sqlite3.connect(self.output / "collection.sqlite")) as db:
            self.assertEqual(5, db.execute("SELECT COUNT(*) FROM posts").fetchone()[0])
            self.assertEqual(1, db.execute("SELECT blocked FROM backfill_state "
                                           "WHERE account_key='KR_001'").fetchone()[0])

    def test_short_page_is_exhausted_not_falsely_50_posts(self):
        with patch.object(base, "request_batch", return_value=fake_meta(
                fake_result(1, media_count=3, n=3, after=None))) as fn:
            self.assertEqual(0, mod.main(self.args(cycle="cycle001")))
            self.assertEqual(0, mod.main(self.args(cycle="cycle001")))
            self.assertEqual(1, fn.call_count)
        with closing(sqlite3.connect(self.output / "collection.sqlite")) as db:
            self.assertEqual(3, db.execute("SELECT COUNT(*) FROM posts").fetchone()[0])
            self.assertEqual(1, db.execute("SELECT exhausted FROM backfill_state "
                                           "WHERE account_key='KR_001'").fetchone()[0])

    def test_110_failure_blocks_bad_account_without_fabricating_posts(self):
        response = (200, [{"code":400, "headers": [],
                           "body": json.dumps({"error": {"code": 110, "message": "Invalid user id"}})}],
                    {}, 0.01)
        with patch.object(base, "request_batch", return_value=response) as fn:
            self.assertEqual(0, mod.main(self.args(cycle="cycle001")))
            self.assertEqual(0, mod.main(self.args(cycle="cycle001")))
        self.assertEqual(1, fn.call_count)
        with closing(sqlite3.connect(self.output / "collection.sqlite")) as db:
            self.assertEqual(0, db.execute("SELECT COUNT(*) FROM posts").fetchone()[0])
            self.assertEqual("110", db.execute("SELECT last_error_code FROM backfill_state "
                                              "WHERE account_key='KR_001'").fetchone()[0])

    def test_usage_70_halts_after_first_batch_not_before(self):
        state = {"n": 0}
        def responder(_ver, _token, _ops, timeout=120):
            state["n"] += 1
            return fake_meta(fake_result(1, after="NEXT999"), usage=75)
        with patch.object(base, "request_batch", side_effect=responder):
            self.assertEqual(0, mod.main(self.args(cycle="cycle001")))
        self.assertEqual(1, state["n"])

    def test_isolated_B_does_not_change_A_and_can_hold_144_accounts(self):
        first_db = self.output / "collection.sqlite"
        with patch.object(base, "request_batch", return_value=fake_meta(fake_result(1, after="CURSOR1"))):
            self.assertEqual(0, mod.main(self.args()))
        first_before = first_db.read_bytes()
        self.output = self.home / "backfill_B"
        with patch.object(base, "request_batch", return_value=fake_meta(fake_result(1, after="CURSOR2"))):
            self.assertEqual(0, mod.main(self.args(app="B")))
        self.assertEqual(first_before, first_db.read_bytes())
        with closing(sqlite3.connect(self.output / "collection.sqlite")) as db:
            row = db.execute("SELECT a.ordinal FROM accounts a JOIN backfill_state s "
                             "ON a.account_key=s.account_key WHERE s.pages_fetched=1").fetchone()
            self.assertEqual(151, row[0])


if __name__ == "__main__":
    unittest.main()
