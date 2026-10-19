"""Network-free regression checks for STEP 4 collection safeguards."""

from __future__ import annotations

import csv
import json
import os
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, unquote, urlsplit

import collector


def cost_error() -> collector.CollectorError:
    return collector.CollectorError(
        "1", "Please reduce the amount of data you're asking for, then retry your request",
        error_type="OAuthException", http_status=500,
    )


def make_page(start: int, count: int = 10, after: str | None = "NEXT") -> dict:
    data = [
        {
            "id": f"post-{index}", "timestamp": "2026-10-01T00:00:00+0000",
            "media_type": "IMAGE", "media_url": f"https://cdn.invalid/{index}.jpg",
            "like_count": 0, "comments_count": 2,
        }
        for index in range(start, start + count)
    ]
    paging = {"cursors": {"after": after}} if after else {}
    return {
        "username": "fixture", "id": "ig-account", "followers_count": 100,
        "media_count": 100, "media": {"data": data, "paging": paging},
    }


class Step4SyntheticTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(os.environ, {"META_REQUEST_INTERVAL_SECONDS": "0"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.old_next = collector._next_request_at
        collector._next_request_at = 0.0
        self.addCleanup(setattr, collector, "_next_request_at", self.old_next)

    def test_20_cost_error_falls_back_to_two_pages_and_deduplicates(self) -> None:
        def page(_username, _version, _ig, _token, *, max_posts, after=None,
                 minimal_fields=False, **_kwargs):
            self.assertEqual(max_posts, 20 if after is None and not calls else 10)
            calls.append((max_posts, after, minimal_fields))
            if len(calls) == 1:
                raise cost_error()
            return make_page(0 if after is None else 10, after="CURSOR-2" if after is None else None)

        calls = []
        with patch.object(collector, "business_discovery", side_effect=page):
            result, strategy, coverage, deferred = collector.business_discovery_with_fallback(
                "fixture", "v26.0", "ig-id", "synthetic-token",
            )
        ids = [post["id"] for post in collector.media_posts(result)]
        self.assertEqual(len(ids), 20)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(coverage, "complete")
        self.assertIsNone(deferred)
        self.assertIn("full_10_fallback", strategy)
        self.assertEqual(calls, [(20, None, False), (10, None, False), (10, "CURSOR-2", False)])

    def test_10_cost_error_uses_minimal_fields_for_both_pages(self) -> None:
        calls = []

        def page(_username, _version, _ig, _token, *, max_posts, after=None,
                 minimal_fields=False, **_kwargs):
            calls.append((max_posts, after, minimal_fields))
            if (max_posts == 20 or (max_posts == 10 and not minimal_fields)
                    or (after and not minimal_fields)):
                raise cost_error()
            start = 0 if after is None else 10
            return make_page(start, after="CURSOR-2" if after is None else None)

        with patch.object(collector, "business_discovery", side_effect=page):
            result, strategy, coverage, deferred = collector.business_discovery_with_fallback(
                "fixture", "26.0", "ig-id", "synthetic-token",
            )
        self.assertEqual(len(collector.media_posts(result)), 20)
        self.assertEqual(coverage, "complete")
        self.assertIsNone(deferred)
        self.assertEqual(calls, [
            (20, None, False), (10, None, False), (10, None, True),
            (10, "CURSOR-2", False), (10, "CURSOR-2", True),
        ])
        self.assertIn("minimal_10", strategy)

    def test_page_two_auth_error_returns_first_page_for_partial_commit(self) -> None:
        calls = []

        def page(_username, _version, _ig, _token, *, max_posts, after=None,
                 minimal_fields=False, **_kwargs):
            calls.append((max_posts, after, minimal_fields))
            if not after:
                if max_posts == 20:
                    raise cost_error()
                return make_page(0)
            raise collector.CollectorError(
                "190", "Invalid OAuth access token", error_type="OAuthException", http_status=400,
            )

        with patch.object(collector, "business_discovery", side_effect=page):
            result, _strategy, coverage, deferred = collector.business_discovery_with_fallback(
                "fixture", "26.0", "ig-id", "synthetic-token",
            )
        self.assertEqual(len(collector.media_posts(result)), 10)
        self.assertEqual(coverage, "partial")
        self.assertIsNotNone(deferred)
        self.assertEqual(deferred.code, "190")
        self.assertTrue(collector.should_halt_meta(deferred))

    def test_url_builds_version_cursor_and_minimal_fields_without_children(self) -> None:
        captured = {}

        def fake_request(url, _headers, _secrets, **_kwargs):
            captured["url"] = url
            return {"business_discovery": make_page(0, count=0, after=None)}

        with patch.object(collector, "request_json", side_effect=fake_request):
            collector.business_discovery(
                "fixture", "v26.0", "17841438211608317", "synthetic-token",
                max_posts=10, after="CURSOR-123", minimal_fields=True,
            )
        parsed = urlsplit(captured["url"])
        fields = parse_qs(parsed.query)["fields"][0]
        self.assertEqual(parsed.netloc, "graph.facebook.com")
        self.assertEqual(parsed.path, "/v26.0/17841438211608317")
        self.assertIn('media.limit(10).after("CURSOR-123")', fields)
        self.assertNotIn("children", fields)
        self.assertIn("like_count", fields)

    def test_request_log_excludes_query_and_auth_and_keeps_only_usage_metrics(self) -> None:
        with tempfile.TemporaryDirectory(dir=collector.HERE) as tmp:
            log_path = Path(tmp) / "api_request_log.csv"
            response_headers = Message()
            response_headers["X-App-Usage"] = json.dumps({"call_count": 21, "total_time": 4})
            response_headers["X-Business-Use-Case-Usage"] = json.dumps({
                "BUSINESS_ID_SECRET": [{"call_count": 31, "total_cputime": 8}],
            })

            class FakeResponse:
                status = 200
                headers = response_headers

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

                def read(self):
                    return b'{"ok":true}'

            url = "https://graph.facebook.com/v26.0/123?access_token=TOKEN_SECRET&fields=id"
            with patch.object(collector, "REQUEST_LOG", log_path), \
                    patch.object(collector, "urlopen", return_value=FakeResponse()), \
                    patch.object(collector.time, "monotonic", return_value=10.0):
                payload = collector.request_json(
                    url, {"Authorization": "Bearer TOKEN_SECRET"}, ["TOKEN_SECRET"],
                )
            self.assertEqual(payload, {"ok": True})
            text = log_path.read_text(encoding="utf-8")
            self.assertNotIn("TOKEN_SECRET", text)
            self.assertNotIn("access_token", text)
            self.assertNotIn("BUSINESS_ID_SECRET", text)
            rows = list(csv.DictReader(text.splitlines()))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["host"], "graph.facebook.com")
            self.assertEqual(rows[0]["path"], "/v26.0/123")
            self.assertEqual(json.loads(rows[0]["app_usage_json"])["call_count"], 21)
            self.assertEqual(
                json.loads(rows[0]["business_use_case_usage_json"])["call_count"], 31,
            )

    def test_retry_after_is_parsed_and_recorded_for_scheduler(self) -> None:
        headers = Message()
        headers["Retry-After"] = "17"
        headers["X-App-Usage"] = '{"call_count": 2}'
        error_body = json.dumps({
            "error": {"message": "Throttled", "type": "OAuthException", "code": 17},
        }).encode()
        http_error = HTTPError(
            "https://graph.facebook.com/v26.0/123", 429, "too many", headers,
            __import__("io").BytesIO(error_body),
        )
        with tempfile.TemporaryDirectory(dir=collector.HERE) as tmp:
            with patch.object(collector, "REQUEST_LOG", Path(tmp) / "api_request_log.csv"), \
                    patch.object(collector, "urlopen", side_effect=http_error), \
                    patch.object(collector, "schedule_next_request") as schedule:
                with self.assertRaises(collector.CollectorError) as raised:
                    collector.request_json(
                        "https://graph.facebook.com/v26.0/123?fields=id",
                        {}, [], max_retries=0,
                    )
            self.assertEqual(raised.exception.http_status, 429)
            schedule.assert_called_once_with(17.0, pace=True)

    def test_110_is_account_scoped_but_auth_and_rate_signals_halt(self) -> None:
        self.assertFalse(collector.should_halt_meta(collector.CollectorError("110", "Invalid user id")))
        self.assertFalse(collector.should_halt_meta(cost_error()))
        self.assertTrue(collector.should_halt_meta(collector.CollectorError("190", "OAuth", http_status=400)))
        self.assertTrue(collector.should_halt_meta(collector.CollectorError("17", "throttle")))

    def test_25_second_default_and_wait_are_configurable_without_sleeping(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(collector.configured_request_interval(), 25.0)
        with patch.dict(os.environ, {"META_REQUEST_INTERVAL_SECONDS": "7.5"}):
            self.assertEqual(collector.configured_request_interval(), 7.5)
        collector._next_request_at = 20.0
        with patch.object(collector.time, "monotonic", return_value=10.0), \
                patch.object(collector.time, "sleep") as sleep:
            self.assertEqual(collector.wait_for_request_slot(), 10.0)
        sleep.assert_called_once_with(10.0)

    def test_resume_skips_old_success_and_failed_then_code_110_continues(self) -> None:
        rows = [
            {"account_key": key, "username": key.lower(), "country": "KR", "image_url": "fixture"}
            for key in ("KR_OK", "KR_OLD_FAIL", "KR_110", "KR_NEXT")
        ]
        with tempfile.TemporaryDirectory(dir=collector.HERE) as tmp:
            original = (collector.HERE, collector.MANIFEST, collector.SUMMARY)
            collector.HERE = Path(tmp)
            collector.MANIFEST = Path(tmp) / "manifest.json"
            collector.SUMMARY = Path(tmp) / "collection_summary.md"
            self.addCleanup(setattr, collector, "HERE", original[0])
            self.addCleanup(setattr, collector, "MANIFEST", original[1])
            self.addCleanup(setattr, collector, "SUMMARY", original[2])
            accounts, posts, media, statuses, tags = collector.ensure_outputs(rows, "fixture-hash")
            statuses["KR_OK"].update({"status": "success", "api_status": "success"})
            statuses["KR_OLD_FAIL"].update({
                "status": "failed", "error_code": "110", "error_message": "old failure",
            })
            collector.atomic_csv("collection_status.csv", list(statuses.values()))

            good = {
                "username": "kr_next", "id": "ig-next", "followers_count": 100,
                "media_count": 1, "media": {"data": [{
                    "id": "new-post", "timestamp": "2026-10-01T00:00:00+0000",
                    "media_type": "IMAGE", "media_url": "https://cdn.invalid/post.jpg",
                    "like_count": 1, "comments_count": 0,
                }]},
            }
            calls = []

            def fake_collect(username, *_args):
                calls.append(username)
                if username == "kr_110":
                    raise collector.CollectorError("110", "Invalid user id", error_type="OAuthException")
                return good, "full_20", "complete", None

            with patch.object(collector, "load_env_file"), \
                    patch.object(collector, "business_discovery_with_fallback", side_effect=fake_collect), \
                    patch.dict(os.environ, {
                        "META_ACCESS_TOKEN": "SYNTHETIC_ONLY",
                        "META_IG_USER_ID": "fixture-id", "META_GRAPH_VERSION": "v26.0",
                    }):
                code = collector.meta_stage(rows, "fixture-hash")
            saved = {row["account_key"]: row for row in collector.read_csv("collection_status.csv")}
            self.assertEqual(code, 1)  # Account-level error is recorded; later account still completes.
            self.assertEqual(calls, ["kr_110", "kr_next"])
            self.assertEqual(saved["KR_OK"]["status"], "success")
            self.assertEqual(saved["KR_OLD_FAIL"]["status"], "failed")
            self.assertEqual(saved["KR_110"]["status"], "failed")
            self.assertEqual(saved["KR_NEXT"]["status"], "success")
            self.assertEqual(saved["KR_NEXT"]["posts_collected"], "1")

            with patch.object(collector, "load_env_file"), \
                    patch.object(
                        collector, "business_discovery_with_fallback",
                        return_value=(good, "full_20", "complete", None),
                    ), \
                    patch.dict(os.environ, {
                        "META_ACCESS_TOKEN": "SYNTHETIC_ONLY",
                        "META_IG_USER_ID": "fixture-id", "META_GRAPH_VERSION": "v26.0",
                    }):
                retry_code = collector.meta_stage(rows, "fixture-hash", retry_account_keys=["KR_110"])
            retried = {
                row["account_key"]: row for row in collector.read_csv("collection_status.csv")
            }["KR_110"]
            self.assertEqual(retry_code, 0)
            self.assertEqual(retried["status"], "success")
            self.assertEqual(json.loads(retried["error_history_json"])[0]["error_code"], "110")


if __name__ == "__main__":
    unittest.main(verbosity=2)
