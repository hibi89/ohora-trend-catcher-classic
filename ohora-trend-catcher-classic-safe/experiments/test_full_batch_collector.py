"""Network-free tests. Run: python -m unittest discover -s experiments -p test_full_batch_collector.py -v"""
from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from contextlib import closing
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import full_batch_collector as mod


def make_source(path: Path):
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, ["account_key", "username", "country", "image_url"])
        w.writeheader()
        for cc, count in mod.EXPECTED_COUNTS.items():
            for i in range(1, count + 1):
                w.writerow({"account_key": f"{cc}_{i:03d}", "username": f"test{cc.lower()}{i}",
                            "country": cc, "image_url": "https://example.invalid/thumb.png"})


def fake_success(key: str, count: int = 1) -> dict:
    posts = [{"id": f"{key}-post-{i}", "timestamp": "2026-10-15T00:00:00+0000",
              "media_type": "IMAGE", "media_url": "https://example.invalid/1.jpg",
              "like_count": None if i == 0 else 0, "comments_count": 2}
             for i in range(count)]
    return {"business_discovery": {"id": "12345", "username": key,
             "followers_count": 100, "media_count": count, "media": {"data": posts}}}


def fake_response(ops: list, count: int = 1) -> list:
    return [{"code": 200, "headers": [{"name": "X-App-Usage",
            "value": '{"call_count": 3,"total_time": 17,"total_cputime": 0}'}],
            "body": json.dumps(fake_success(f"fake-{i}", count))}
            for i in range(len(ops))]


class FullBatchUnitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "account_list.csv"
        make_source(self.source)
        self.accounts, self.hash = mod.load_source(self.source)

    def test_initial_five_posts_isolated_and_manifest_locked(self):
        cfg = self.base / "safe_env.local"
        cfg.write_text("META_ACCESS_TOKEN=SYNTHETIC_SECRET\nMETA_IG_USER_ID=123\n")
        output = self.base / "latest_5"
        calls = []

        def stub(_version, _token, operations, timeout=120):
            calls.append(len(operations))
            return 200, fake_response(operations, count=5), {}, 0.02

        arguments = [
            "--source", str(self.source), "--env-file", str(cfg),
            "--output-dir", str(output), "--posts", "5",
            "--batch-size", "10", "--max-batches", "1",
            "--delay-seconds", "0", "--stop-usage", "75", "--live",
        ]
        with patch.object(mod, "request_batch", side_effect=stub):
            self.assertEqual(1, mod.main(arguments))
        self.assertEqual([10], calls)
        with closing(sqlite3.connect(output / "collection.sqlite")) as conn:
            self.assertEqual(
                ("5",), conn.execute(
                    "SELECT value FROM manifest WHERE key='posts_requested'"
                ).fetchone()
            )
            self.assertEqual(10, conn.execute(
                "SELECT count(*) FROM accounts WHERE status='success'"
            ).fetchone()[0])
            self.assertEqual(50, conn.execute(
                "SELECT count(*) FROM posts"
            ).fetchone()[0])
        # Reusing a database with a different posts limit must be rejected.
        different = list(arguments)
        different[different.index("--posts") + 1] = "4"
        with patch.object(mod, "request_batch") as unused:
            self.assertEqual(2, mod.main(different))
            unused.assert_not_called()

    def test_source_constraints_and_order(self):
        self.assertEqual(294, len(self.accounts))
        self.assertEqual(("KR_001", "KR_100", "US_001", "JP_093"),
                         tuple(self.accounts[i]["account_key"] for i in (0, 99, 100, 293)))
        with self.source.open("a") as f:
            f.write("KR_001,duplicate,KR,x\n")
        with self.assertRaises(ValueError):
            mod.load_source(self.source)

    def test_operations_max_posts_and_carousel(self):
        ops = mod.operations_for(self.accounts[:2], "123", 20)
        self.assertEqual(2, len(ops))
        from urllib.parse import parse_qs
        field = parse_qs(ops[0]["relative_url"].split("?", 1)[1])["fields"][0]
        self.assertIn("media.limit(20)", field)
        self.assertIn("children.limit(50)", field)
        self.assertNotIn("access_token", ops[0]["relative_url"])

    def test_usage_is_cumulative_snapshot_not_sum(self):
        self.assertEqual({"total_time": 17., "call_count": 3.},
                         {k: v for k, v in mod.usage([{"name": "x-app-usage",
                         "value": '{"call_count":3,"total_time":17}'}]).items()})
        self.assertEqual({}, mod.usage({"unrelated": "no"}))

    def test_missing_like_remains_null(self):
        a, p, m = mod.decode_success(fake_success("A"), self.accounts[0])
        self.assertIsNone(p[0]["like_count"])
        self.assertIsNone(p[0]["engagement_count"])
        self.assertIsNone(p[0]["engagement_rate_pct"])
        self.assertEqual(2, p[0]["comments_count"])
        self.assertEqual(1, len(m))

    def test_carousel_and_video_child_rows(self):
        data = fake_success("A")
        posts = data["business_discovery"]["media"]["data"]
        posts[0].update({"media_type": "CAROUSEL_ALBUM", "children": {"data": [
            {"id": "child1", "media_type": "IMAGE", "media_url": "https://example.invalid/1.jpg"},
            {"id": "child2", "media_type": "VIDEO", "thumbnail_url": "https://example.invalid/a.jpg"}
        ]}})
        _, p, m = mod.decode_success(data, self.accounts[0])
        self.assertEqual(3, len(m))
        self.assertEqual(2, p[0]["media_count"])
        self.assertEqual(["carousel_container", "carousel_item", "carousel_item"],
                         [x["media_role"] for x in m])
        self.assertEqual("https://example.invalid/a.jpg", m[2]["thumbnail_url"])

    def make_db(self):
        path = self.base / "out"
        path.mkdir(exist_ok=True)
        return mod.database(path / "collection.sqlite", self.accounts, self.hash, 20), path

    def test_manifest_protection(self):
        conn, out = self.make_db()
        conn.close()
        with self.assertRaises(ValueError):
            mod.database(out / "collection.sqlite", self.accounts, "incorrect_hash", 20)

    def test_mixed_batch_rate_limit_stops_but_commits_success(self):
        conn, out = self.make_db()
        bid = mod.begin_batch(conn, self.accounts[:2], 20)
        response = [{"code": 200, "body": json.dumps(fake_success("good"))},
                    {"code": 429, "body": json.dumps({"error": {"code": 4,"message": "Limit"}})}]
        s, f, stopped, usage = mod.apply_batch(conn, bid, self.accounts[:2], 200, response, {}, 0.5, 20, "secret")
        self.assertEqual((1, 1, True), (s, f, stopped))
        state = dict(conn.execute("SELECT account_key,status FROM accounts LIMIT 2").fetchall())
        self.assertEqual("success", state["KR_001"])
        self.assertEqual("rate_limited", state["KR_002"])
        self.assertEqual(1, conn.execute("SELECT count(*) FROM posts").fetchone()[0])
        report = mod.export_all(conn, out)
        self.assertEqual(1, report["accounts"]["success"])
        self.assertEqual(1, report["accounts"]["rate_limited"])
        conn.close()

    def test_partial_when_fewer_than_20_posts_without_known_reason(self):
        conn, out = self.make_db()
        bid = mod.begin_batch(conn, self.accounts[:1], 20)
        p = fake_success("partial", count=10)
        p["business_discovery"]["media_count"] = 500
        s, f, stop, _ = mod.apply_batch(conn, bid, self.accounts[:1], 200,
            [{"code":200,"body":json.dumps(p)}], {}, 2, 20, "secret")
        self.assertEqual((1,0,False),(s,f,stop))
        row = conn.execute("SELECT status,coverage,posts_collected FROM accounts WHERE account_key='KR_001'").fetchone()
        self.assertEqual(("partial", "partial", 10), tuple(row))
        self.assertEqual(10, conn.execute("SELECT count(*) FROM posts").fetchone()[0])
        conn.close()

    def test_unexpected_batch_response_never_marks_success(self):
        conn, _ = self.make_db()
        bid = mod.begin_batch(conn, self.accounts[:2], 20)
        s, f, stopped, _ = mod.apply_batch(conn, bid, self.accounts[:2], 200,
                                          [{"code":200,"body":json.dumps(fake_success("x"))}], {}, 1, 20, "secret")
        self.assertEqual((0,0,True), (s,f,stopped))
        self.assertEqual(294, conn.execute("SELECT count(*) FROM accounts WHERE status='pending'").fetchone()[0])
        self.assertEqual(0, conn.execute("SELECT count(*) FROM posts").fetchone()[0])
        conn.close()

    def test_no_live_by_default_does_not_write_anything(self):
        output = self.base / "newdir"
        rc = mod.main(["--source",str(self.source),"--output-dir",str(output)])
        self.assertEqual(0, rc)
        self.assertFalse(output.exists())

    def test_small_full_run_and_resume_no_extra_api_calls(self):
        cfg = self.base / ".env.local"
        cfg.write_text("META_ACCESS_TOKEN=UNSAFE_TEST_SECRET\nMETA_IG_USER_ID=123\nMETA_GRAPH_VERSION=v26.0\n")
        out = self.base / "out"
        seen = []
        def fake_call(_version, _token, ops, timeout=120):
            seen.append(len(ops))
            return 200, [{**entry, "body": entry["body"].replace("fake-", f"run{len(seen)}-")} for entry in fake_response(ops)], {}, 0.02
        argv=["--source",str(self.source),"--env-file",str(cfg),"--output-dir",str(out),
              "--delay-seconds","0","--batch-size","10","--max-batches","2","--live"]
        with patch.object(mod,"request_batch",side_effect=fake_call):
            self.assertEqual(1, mod.main(argv))  # 20 success, 274 pending
            self.assertEqual([10, 10], seen)
            self.assertEqual(1, mod.main(argv))  # 20 MORE, not same twenty
            self.assertEqual([10,10,10,10], seen)
        with closing(sqlite3.connect(out / "collection.sqlite")) as db:
            self.assertEqual(40, db.execute("SELECT count(*) FROM accounts WHERE status='success'").fetchone()[0])
            self.assertEqual(40, db.execute("SELECT count(*) FROM posts").fetchone()[0])
        # Tests are designed not to print secrets or persist token
        for f in out.glob("*.csv"):
            self.assertNotIn("UNSAFE_TEST_SECRET", f.read_text(encoding="utf-8-sig"))

    def test_rate_limit_prevents_next_request_and_exports(self):
        cfg = self.base / ".env.local"
        cfg.write_text("META_ACCESS_TOKEN=TEST_SECRET\nMETA_IG_USER_ID=123\n")
        out = self.base / "out"
        calls = []
        def fake_call(_version,_token,ops,timeout=120):
            calls.append(1)
            r=fake_response(ops)
            r[1]={"code":400,"body":json.dumps({"error":{"code":4,"message":"token TEST_SECRET rate"}})}
            return 200,r,{},0.1
        with patch.object(mod,"request_batch",side_effect=fake_call):
            rc=mod.main(["--source",str(self.source),"--env-file",str(cfg),"--output-dir",str(out),
                         "--delay-seconds","0","--live"])
        self.assertEqual(4,rc)
        self.assertEqual([1],calls)
        with (out / "collection_status.csv").open(encoding="utf-8-sig",newline="") as f:
            status=list(csv.DictReader(f))
        self.assertEqual("success", status[0]["status"])
        self.assertEqual("rate_limited", status[1]["status"])
        self.assertEqual("pending", status[10]["status"])
        self.assertNotIn("TEST_SECRET", (out / "collection_status.csv").read_text(encoding="utf-8-sig"))

    def test_outer_rate_limit_is_logged_and_pending_preserved(self):
        conn, out = self.make_db()
        bid = mod.begin_batch(conn, self.accounts[:10], 20)
        s, f, stop, metrics = mod.apply_batch(conn, bid, self.accounts[:10], 400,
            {"error": {"code": 4, "message": "Rate-limited while batching TEST_SECRET"}},
            {}, 0.5, 20, "TEST_SECRET")
        self.assertEqual((0, 0, True), (s, f, stop))
        info = conn.execute("SELECT status,error FROM batches WHERE batch_id=?", (bid,)).fetchone()
        self.assertEqual("outer_error", info[0])
        self.assertIn("code=4", info[1])
        self.assertNotIn("TEST_SECRET", info[1])
        self.assertEqual(294, conn.execute("SELECT count(*) FROM accounts WHERE status='pending'").fetchone()[0])
        conn.close()

    def test_existing_collector_directory_is_protected(self):
        legacy = mod.ROOT / "kq3_294_collection"
        rc = mod.main(["--source",str(self.source),"--output-dir",str(legacy)])
        self.assertEqual(2, rc)

    def test_one_post_restricts_to_old_pending_without_touching_old_db(self):
        original = self.base / "latest_5"
        original.mkdir()
        original_db = original / "collection.sqlite"
        with closing(mod.database(original_db, self.accounts, self.hash, 5)) as db:
            with db:
                for a in self.accounts[:176]:
                    db.execute("UPDATE accounts SET status='success' WHERE account_key=?",
                               (a["account_key"],))
                for a in self.accounts[176:181]:
                    db.execute("UPDATE accounts SET status='failed',error_code='110' "
                               "WHERE account_key=?", (a["account_key"],))
        self.assertEqual(113, len(mod.eligible_from_snapshot(
            original_db, self.hash, self.accounts, self.base / "latest_1" / "collection.sqlite")))
        cfg = self.base / "env.local"
        cfg.write_text("META_ACCESS_TOKEN=TEST_KEY\nMETA_IG_USER_ID=123\n")
        output = self.base / "latest_1"
        seen = []
        def fake_call(_version, _token, ops, timeout=120):
            from urllib.parse import parse_qs
            for op in ops:
                fields = parse_qs(op["relative_url"].split("?", 1)[1])["fields"][0]
                self.assertIn("media.limit(1)", fields)
            seen.append(len(ops))
            return 200, fake_response(ops, count=1), {}, 0.1
        arguments = [
            "--source", str(self.source), "--env-file", str(cfg),
            "--posts", "1", "--batch-size", "10", "--max-batches", "1",
            "--stop-usage", "85", "--delay-seconds", "0",
            "--only-pending-from", str(original_db),
            "--output-dir", str(output), "--live",
        ]
        with patch.object(mod, "request_batch", side_effect=fake_call):
            self.assertEqual(1, mod.main(arguments))
        self.assertEqual([10], seen)
        with closing(sqlite3.connect(original_db)) as db:
            self.assertEqual(0, db.execute("SELECT COUNT(*) FROM posts").fetchone()[0])
            self.assertEqual(176, db.execute(
                "SELECT COUNT(*) FROM accounts WHERE status='success'").fetchone()[0])
        with closing(sqlite3.connect(output / "collection.sqlite")) as db:
            self.assertEqual(10, db.execute("SELECT COUNT(*) FROM posts").fetchone()[0])
            successful = {row[0] for row in db.execute(
                "SELECT account_key FROM accounts WHERE status='success'")}
            self.assertEqual({a["account_key"] for a in self.accounts[181:191]}, successful)
            self.assertTrue(all(a["account_key"] not in successful for a in self.accounts[:181]))

    def test_restrict_refuses_different_account_source(self):
        original = self.base / "old"
        original.mkdir()
        db_path = original / "collection.sqlite"
        with closing(mod.database(db_path, self.accounts, self.hash, 5)):
            pass
        changed = self.base / "alternative.csv"
        changed.write_bytes(self.source.read_bytes() + b"\n")
        env = self.base / "cfg.env"
        env.write_text("META_ACCESS_TOKEN=DUMMY\nMETA_IG_USER_ID=123\n")
        output = self.base / "new"
        with patch.object(mod, "request_batch") as unused:
            rc = mod.main(["--source", str(changed), "--env-file", str(env),
                 "--output-dir", str(output), "--only-pending-from", str(db_path),
                 "--posts", "1", "--live"])
            self.assertEqual(2, rc)
            unused.assert_not_called()
        self.assertFalse(output.exists())

    def test_restrict_refuses_destination_equal_original_sqlite(self):
        old = self.base / "result"
        old.mkdir()
        old_db = old / "collection.sqlite"
        with closing(mod.database(old_db, self.accounts, self.hash, 5)):
            pass
        with self.assertRaisesRegex(ValueError, "must differ"):
            mod.eligible_from_snapshot(old_db, self.hash, self.accounts, old_db)

    def setup_cross_skip_sources(self):
        primary_dir = self.base / "latest_5"
        secondary_dir = self.base / "latest_1_pending"
        primary_dir.mkdir()
        secondary_dir.mkdir()
        primary_db = primary_dir / "collection.sqlite"
        secondary_db = secondary_dir / "collection.sqlite"
        with closing(mod.database(primary_db, self.accounts, self.hash, 5)) as db:
            with db:
                for i, a in enumerate(self.accounts[:181], start=1):
                    status = ("failed" if i in {32, 61, 100, 113, 152}
                              else "success")
                    db.execute("UPDATE accounts SET status=? WHERE account_key=?",
                               (status, a["account_key"]))
        with closing(mod.database(secondary_db, self.accounts, self.hash, 1)) as db:
            with db:
                for a in self.accounts[181:196]:
                    db.execute("UPDATE accounts SET status='success' WHERE account_key=?",
                               (a["account_key"],))
        return primary_db, secondary_db

    def test_split_151_294_skips_both_snapshots_preview_with_no_writes(self):
        old, partial = self.setup_cross_skip_sources()
        out = self.base / "split_10"
        from contextlib import redirect_stdout
        from io import StringIO
        std = StringIO()
        argv = ["--source", str(self.source), "--posts", "10",
                "--batch-size", "10", "--start-ordinal", "151",
                "--end-ordinal", "294", "--assigned-app", "owner_slot2_probe",
                "--only-pending-from", str(old),
                "--skip-collected-from", str(partial),
                "--output-dir", str(out)]
        with redirect_stdout(std), patch.object(mod, "request_batch") as net:
            self.assertEqual(0, mod.main(argv))
            net.assert_not_called()
        printed = std.getvalue()
        self.assertIn("144/294 assigned accounts", printed)
        self.assertIn("98 eligible AFTER cross-DB skip", printed)
        self.assertIn("197, 198, 199, 200", printed)
        self.assertFalse(out.exists())

    def test_split_10_posts_live_resumes_and_preserves_other_dbs(self):
        old, partial = self.setup_cross_skip_sources()
        out = self.base / "split_10"
        env = self.base / "cfg.env"
        env.write_text("META_ACCESS_TOKEN=FAKE_TEST_TOKEN\nMETA_IG_USER_ID=123\n")
        before = [
            (p.stat().st_size, hashlib.sha256(p.read_bytes()).hexdigest())
            for p in (old, partial)
        ]
        batches = []
        def fake_call(_ver, _token, ops, timeout=120):
            from urllib.parse import parse_qs
            batch_ordinals = []
            for item in ops:
                fields = parse_qs(item["relative_url"].split("?", 1)[1])["fields"][0]
                self.assertIn("media.limit(10)", fields)
                name = fields.split("business_discovery.username(", 1)[1].split(")", 1)[0]
                batch_ordinals.append(int(name.rsplit("us", 1)[-1])
                                      if "testus" in name else
                                      int(name.rsplit("jp", 1)[-1]) + 101)
            batches.append(batch_ordinals)
            responses = fake_response(ops, count=10)
            for entry in responses:
                entry["body"] = entry["body"].replace("fake-", f"run{len(batches)}-")
            return 200, responses, {}, 0.02
        args = [
            "--source", str(self.source), "--env-file", str(env),
            "--posts", "10", "--batch-size", "10",
            "--max-batches", "1", "--stop-usage", "70",
            "--delay-seconds", "0",
            "--start-ordinal", "151", "--end-ordinal", "294",
            "--assigned-app", "owner_slot2_probe",
            "--only-pending-from", str(old),
            "--skip-collected-from", str(partial),
            "--output-dir", str(out), "--live",
        ]
        with patch.object(mod, "request_batch", side_effect=fake_call):
            self.assertEqual(1, mod.main(args))
            self.assertEqual(1, len(batches))
            self.assertEqual(10, len(batches[0]))
            self.assertEqual(1, mod.main(args))
            self.assertEqual(2, len(batches))
        after = [
            (p.stat().st_size, hashlib.sha256(p.read_bytes()).hexdigest())
            for p in (old, partial)
        ]
        self.assertEqual(before, after)
        with closing(sqlite3.connect(out / "collection.sqlite")) as db:
            self.assertEqual(20, db.execute(
                "SELECT count(*) FROM accounts WHERE status='success'").fetchone()[0])
            self.assertEqual(200, db.execute("SELECT count(*) FROM posts").fetchone()[0])
            seq = [r[0] for r in db.execute(
                "SELECT ordinal FROM accounts WHERE status='success' ORDER BY ordinal")]
            self.assertEqual(list(range(197, 217)), seq)
            manifest = dict(db.execute("SELECT key,value FROM manifest"))
            self.assertEqual("owner_slot2_probe", manifest["assigned_app"])
            self.assertEqual("10", manifest["posts_requested"])
        # New split directory may not change assigned range or depth on resume.
        other = list(args)
        other[other.index("--posts") + 1] = "5"
        with patch.object(mod, "request_batch") as no_api:
            self.assertEqual(2, mod.main(other))
            no_api.assert_not_called()

    def test_cross_skip_refuses_wrong_source_hash_or_same_destination(self):
        old, partial = self.setup_cross_skip_sources()
        out = self.base / "new"
        changed = self.base / "different.csv"
        changed.write_bytes(self.source.read_bytes() + b"\n")
        args = ["--source", str(changed), "--output-dir", str(out),
                "--skip-collected-from", str(partial)]
        with patch.object(mod, "request_batch") as no_api:
            self.assertEqual(2, mod.main(args + ["--live"]))
            no_api.assert_not_called()
        self.assertFalse(out.exists())
        with self.assertRaisesRegex(ValueError, "must differ"):
            mod.completed_from_snapshot(partial, self.hash, self.accounts, partial)

    def test_optional_usage_halt(self):
        cfg=self.base / ".env.local"
        cfg.write_text("META_ACCESS_TOKEN=TEST_SECRET\nMETA_IG_USER_ID=123\n")
        out=self.base / "out"
        with patch.object(mod,"request_batch",return_value=(200,fake_response([None]*10),{},1)):
            rc=mod.main(["--source",str(self.source),"--env-file",str(cfg),"--output-dir",str(out),
                         "--delay-seconds","0","--stop-usage","10","--live"])
        self.assertEqual(5,rc)


if __name__=="__main__":
    unittest.main()
