"""Network-free tests for Friday OHORA Hongju CSV/ZIP handoff."""
from __future__ import annotations

import csv
from contextlib import closing
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_hongju_bundle as b


def write_csv(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def zip_csv(z, name):
    content = z.read(name).decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(content)))


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.output = self.root / "handoff"
        self.accounts = [
            {"account_key": "KR_001", "username": "krnails", "country": "KR",
             "status": "success", "followers_count": "1000"},
            {"account_key": "US_001", "username": "usnails", "country": "US",
             "status": "success", "followers_count": "500"},
            {"account_key": "JP_001", "username": "jpnails", "country": "JP",
             "status": "rate_limited"},
        ]
        self.posts = [
            {"post_id": f"1234567890123456{i:03}", "account_key": "KR_001",
             "username": "krnails", "country": "KR",
             "timestamp": f"2026-10-{i + 1:02}T12:00:00+0000",
             "caption": f"post-{i}", "like_count": str(i * 10),
             "comments_count": "2"} for i in range(6)
        ]
        self.posts.append({
            "post_id": "9876543210123456789", "account_key": "US_001",
            "username": "usnails", "country": "US",
            "timestamp": "2026-10-15T12:00:00+0000", "caption": "pink",
            "like_count": "", "comments_count": "",
        })
        self.media = [
            {"media_id": p["post_id"], "post_id": p["post_id"],
             "media_type": "IMAGE", "media_url": "https://cdn.example.invalid/nail.jpg",
             "country": p["country"], "account_key": p["account_key"]}
            for p in self.posts
        ]
        self.write_fixtures()

    def write_fixtures(self):
        write_csv(self.source / "accounts.csv",
                  ["account_key", "username", "country", "status", "followers_count"],
                  self.accounts)
        write_csv(self.source / "posts.csv",
                  ["post_id", "account_key", "username", "country",
                   "timestamp", "caption", "like_count", "comments_count"],
                  self.posts)
        write_csv(self.source / "media.csv",
                  ["media_id", "post_id", "media_type", "media_url", "country", "account_key"],
                  self.media)

    def test_partial_source_handoff_is_truthful_and_preserves_ids(self):
        archive, manifest = b.build_bundle(self.source, self.output)
        self.assertEqual(3, manifest["source_accounts"])
        self.assertEqual(2, manifest["accounts_with_posts"])
        self.assertEqual(7, manifest["source_posts"])
        self.assertEqual(6, manifest["latest_post_rows"])
        self.assertEqual({"KR": 5, "US": 1}, manifest["latest_posts_by_country"])
        self.assertEqual(1, manifest["missing_like_count_source_posts"])
        with ZipFile(archive) as z:
            self.assertEqual(8, len(z.namelist()))
            latest = zip_csv(z, "posts_latest5_per_account.csv")
            self.assertEqual(6, len(latest))
            self.assertNotIn("1234567890123456000", [p["post_id"] for p in latest])
            self.assertIn("9876543210123456789", [p["post_id"] for p in latest])
            self.assertEqual(6, len(zip_csv(z, "media_latest5_per_account.csv")))
            self.assertEqual(7, len(zip_csv(z, "posts_all_available.csv")))
            coverage = zip_csv(z, "account_coverage.csv")
            jp = next(row for row in coverage if row["account_key"] == "JP_001")
            self.assertEqual("0", jp["latest5_in_source"])
            self.assertEqual("rate_limited", jp["status"])
            self.assertIn("계정별", z.read("README_데이터안내.txt").decode("utf-8-sig"))

    def test_no_secret_files_are_packaged_and_source_unchanged(self):
        secret = self.source / ".env.local"
        secret.write_text("TOKEN=PRIVATE_SHOULD_NOT_SHARE", encoding="utf-8")
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in self.source.iterdir()}
        archive, _ = b.build_bundle(self.source, self.output)
        after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in self.source.iterdir()}
        self.assertEqual(before, after)
        with ZipFile(archive) as z:
            self.assertNotIn(".env.local", z.namelist())
            for name in z.namelist():
                self.assertNotIn(b"PRIVATE_SHOULD_NOT_SHARE", z.read(name))

    def test_bad_relationship_blocks_bundle_without_writes(self):
        self.media[0]["post_id"] = "missing"
        self.write_fixtures()
        with self.assertRaisesRegex(ValueError, "missing post"):
            b.build_bundle(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_duplicate_post_id_blocks_bundle(self):
        self.posts.append(dict(self.posts[0]))
        self.write_fixtures()
        with self.assertRaisesRegex(ValueError, "duplicate ID"):
            b.build_bundle(self.source, self.output)

    def test_works_with_experiment_sqlite_source(self):
        db = self.root / "experiment.sqlite"
        with closing(sqlite3.connect(db)) as conn:
            conn.executescript("""
            CREATE TABLE accounts (account_key TEXT,username TEXT,country TEXT,status TEXT);
            CREATE TABLE posts (post_id TEXT,account_key TEXT,timestamp TEXT,country TEXT);
            CREATE TABLE media (media_id TEXT,post_id TEXT,media_type TEXT,media_url TEXT);
            INSERT INTO accounts VALUES ('KR_001','kr','KR','success');
            INSERT INTO posts VALUES ('179900000001','KR_001','2026-10-15T00:00:00Z','KR');
            INSERT INTO media VALUES ('179900000001','179900000001','IMAGE','https://example.invalid/p.jpg');
            """)
        archive, manifest = b.build_bundle(db, self.output)
        self.assertEqual("sqlite", manifest["source_format"])
        self.assertEqual(1, manifest["latest_post_rows"])
        with ZipFile(archive) as z:
            self.assertEqual("179900000001",
                             zip_csv(z, "posts_latest5_per_account.csv")[0]["post_id"])

    def test_output_inside_source_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "inside the source"):
            b.build_bundle(self.source, self.source / "nested")

    def test_empty_latest_source_is_not_exported(self):
        self.posts = []
        self.media = []
        self.write_fixtures()
        with self.assertRaisesRegex(ValueError, "No collected posts"):
            b.build_bundle(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_spreadsheet_formula_from_caption_is_safely_escaped(self):
        self.posts[0]["caption"] = "=HYPERLINK(\"https://fake.invalid\")"
        self.write_fixtures()
        archive, _ = b.build_bundle(self.source, self.output)
        with ZipFile(archive) as z:
            posts = zip_csv(z, "posts_all_available.csv")
            target = next(p for p in posts if p["post_id"] == self.posts[0]["post_id"])
            self.assertTrue(target["caption"].startswith("'=HYPERLINK("))
        # Source still contains original unmodified caption
        source = b.read_csv(self.source / "posts.csv")
        self.assertEqual("=HYPERLINK(\"https://fake.invalid\")", source[0]["caption"])

    def supplement(self):
        folder = self.root / "supplement"
        folder.mkdir(exist_ok=True)
        accounts = [
            dict(a, status=("success" if a["account_key"] == "JP_001" else "pending"))
            for a in self.accounts
        ]
        posts = [{"post_id": "9999999999999999999", "account_key": "JP_001",
                  "username": "jpnails", "country": "JP",
                  "timestamp": "2026-10-16T01:00:00Z",
                  "caption": "new", "like_count": "4", "comments_count": "1"}]
        media = [{"media_id": "9999999999999999999",
                  "post_id": "9999999999999999999",
                  "account_key": "JP_001", "country": "JP",
                  "media_type": "IMAGE", "media_url": "https://example.invalid/jp.jpg"}]
        write_csv(folder / "accounts.csv",
                  ["account_key", "username", "country", "status", "followers_count"],
                  accounts)
        write_csv(folder / "posts.csv",
                  ["post_id", "account_key", "username", "country", "timestamp",
                   "caption", "like_count", "comments_count"], posts)
        write_csv(folder / "media.csv",
                  ["media_id", "post_id", "account_key", "country",
                   "media_type", "media_url"], media)
        return folder

    def test_merge_two_sources_covers_new_account_without_losing_old(self):
        extra = self.supplement()
        archive, info = b.build_bundle(self.source, self.output, supplement=extra)
        self.assertEqual(3, info["source_accounts"])
        self.assertEqual(3, info["accounts_with_posts"])
        self.assertEqual(8, info["source_posts"])
        self.assertEqual(7, info["latest_post_rows"])
        self.assertEqual({"primary": 7, "supplement_in_source": 1,
                          "supplement_included": 1},
                         info["posts_by_collection_source"])
        self.assertEqual({"KR": 5, "US": 1, "JP": 1}, info["latest_posts_by_country"])
        with ZipFile(archive) as z:
            all_posts = zip_csv(z, "posts_all_available.csv")
            self.assertEqual(8, len(all_posts))
            self.assertIn("9999999999999999999", {p["post_id"] for p in all_posts})
            jp_post = next(p for p in all_posts if p["account_key"] == "JP_001")
            self.assertEqual("supplement", jp_post["collection_source"])
            coverage = zip_csv(z, "account_coverage.csv")
            jp = next(a for a in coverage if a["account_key"] == "JP_001")
            self.assertEqual("success", jp["status"])
            self.assertEqual("1", jp["latest5_in_source"])
            self.assertIn("병합", z.read("README_데이터안내.txt").decode("utf-8-sig"))

    def test_merge_primary_five_post_wins_over_previous_one_post(self):
        # Simulates a new 5-post run that caught up with a prior 1-post
        # result for JP_001. Both copies of the post must not be delivered.
        self.accounts[2]["status"] = "success"
        self.posts.append({
            "post_id": "9999999999999999999", "account_key": "JP_001",
            "username": "jpnails", "country": "JP",
            "timestamp": "2026-10-16T01:00:00Z",
            "caption": "primary has the richer/newer record",
            "like_count": "7", "comments_count": "3",
        })
        self.media.append({
            "media_id": "9999999999999999999",
            "post_id": "9999999999999999999",
            "account_key": "JP_001", "country": "JP",
            "media_type": "IMAGE", "media_url": "https://cdn.example.invalid/better.jpg",
        })
        self.write_fixtures()
        extra = self.supplement()
        archive, info = b.build_bundle(self.source, self.output, supplement=extra)
        self.assertEqual(3, info["accounts_with_posts"])
        self.assertEqual(8, info["source_posts"])
        self.assertEqual(1, info["supplement_accounts_overlapped"])
        self.assertEqual(0, info["supplement_post_rows_included"])
        self.assertEqual(1, info["supplement_post_rows_ignored_overlap"])
        with ZipFile(archive) as z:
            posts = zip_csv(z, "posts_all_available.csv")
            matches = [p for p in posts if p["post_id"] == "9999999999999999999"]
            self.assertEqual(1, len(matches))
            self.assertEqual("primary has the richer/newer record", matches[0]["caption"])
            self.assertEqual("primary", matches[0]["collection_source"])

    def test_merge_mixed_overlap_and_new_supplement_account(self):
        # Supplemental KR_001 is already in primary, but JP_001 is new.
        # Keep KR primary rows and add the JP supplement, total 8 posts.
        extra = self.supplement()
        accounts = b.read_csv(extra / "accounts.csv")
        accounts[0]["status"] = "success"
        write_csv(extra / "accounts.csv", list(accounts[0]), accounts)
        sp = b.read_csv(extra / "posts.csv")
        sp.append(dict(self.posts[0]))
        write_csv(extra / "posts.csv", list(sp[0]), sp)
        sm = b.read_csv(extra / "media.csv")
        sm.append(dict(self.media[0]))
        write_csv(extra / "media.csv", list(sm[0]), sm)
        archive, info = b.build_bundle(self.source, self.output, supplement=extra)
        self.assertEqual(8, info["source_posts"])
        self.assertEqual(1, info["supplement_accounts_overlapped"])
        self.assertEqual(1, info["supplement_accounts_added"])
        self.assertEqual(1, info["supplement_post_rows_ignored_overlap"])
        self.assertEqual(1, info["supplement_post_rows_included"])
        with ZipFile(archive) as z:
            post_ids = [p["post_id"] for p in zip_csv(z, "posts_all_available.csv")]
            self.assertEqual(len(post_ids), len(set(post_ids)))

    def test_merge_falls_back_to_one_post_when_five_post_retry_failed(self):
        self.accounts[2]["status"] = "failed"
        self.accounts[2]["error_code"] = "110"
        self.write_fixtures()
        extra = self.supplement()
        archive, info = b.build_bundle(self.source, self.output, supplement=extra)
        self.assertEqual(3, info["accounts_with_posts"])
        self.assertEqual(1, info["supplement_accounts_restored_after_primary_failure"])
        self.assertEqual(8, info["source_posts"])
        with ZipFile(archive) as z:
            accounts = zip_csv(z, "accounts.csv")
            jp = next(a for a in accounts if a["account_key"] == "JP_001")
            self.assertEqual("success", jp["status"])
            self.assertEqual("failed", jp["primary_latest5_status"])
            self.assertEqual("110", jp["primary_latest5_error_code"])
            self.assertEqual("supplement", jp["collection_source"])

    def test_merge_rejects_different_country_username(self):
        extra = self.supplement()
        rows = b.read_csv(extra / "accounts.csv")
        rows[2]["username"] = "not_jpnails"
        write_csv(extra / "accounts.csv", list(rows[0]), rows)
        with self.assertRaisesRegex(ValueError, "mismatch"):
            b.build_bundle(self.source, self.output, supplement=extra)
        self.assertFalse(self.output.exists())

    def test_merge_preserves_both_sources_untouched(self):
        extra = self.supplement()
        source_before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in self.source.iterdir()}
        extra_before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in extra.iterdir()}
        b.build_bundle(self.source, self.output, supplement=extra)
        self.assertEqual(source_before, {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in self.source.iterdir()})
        self.assertEqual(extra_before, {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in extra.iterdir()})

    def test_cli_preview_creates_zip_without_credentials(self):
        self.assertEqual(0, b.main([
            "--source", str(self.source), "--output-dir", str(self.output)]))
        self.assertEqual(1, len(list(self.output.glob("OHORA_Hongju_handoff_*.zip"))))


if __name__ == "__main__":
    unittest.main()
