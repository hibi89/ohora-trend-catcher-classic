"""Offline regression tests; neither Meta nor image API requests are made."""
from __future__ import annotations

import csv
from email.message import Message
from io import BytesIO
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vision_runner as v


class VisionTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.root = Path(self.t.name)
        self.source = self.root / "collection"
        self.source.mkdir()
        self.out = self.root / "vision_results"
        self.cfg = self.root / ".env.local"
        self.cfg.write_text("VISION_API_KEY=DUMMY_NO_LIVE_TOKEN\n"
                            "VISION_BASE_URL=https://api.example.invalid/v1\n"
                            "VISION_MODEL=gemini-3.8-flash\n", encoding="utf-8")
        self.posts = [
            {"post_id": "P1", "account_key": "KR_001", "country": "KR",
             "username": "test", "timestamp": "2026-10-15T14:00:00Z", "caption": "pink nails",
             "like_count": "", "comments_count": "2", "permalink": "https://example.invalid/p/1", "media_type": "IMAGE"},
            {"post_id": "P2", "account_key": "US_001", "country": "US",
             "username": "testus", "timestamp": "2026-10-14T10:00:00Z", "caption": "carousel",
             "like_count": "1", "comments_count": "2", "media_type": "CAROUSEL_ALBUM"},
            {"post_id": "P3", "account_key": "JP_001", "country": "JP",
             "username": "testjp", "timestamp": "2026-10-13T11:00:00Z", "caption": "video",
             "like_count": "1", "comments_count": "2", "media_type": "VIDEO"},
            {"post_id": "P4", "account_key": "JP_002", "country": "JP",
             "username": "missing", "timestamp": "2026-10-12T10:00:00Z", "caption": "none",
             "like_count": "0", "comments_count": "0", "media_type": "VIDEO"}
        ]
        self.media = [{"media_id":"P1", "post_id":"P1", "media_type":"IMAGE", "media_role":"primary",
                       "media_url":"https://cdn.invalid/a.jpg?signature=one", "sort_order":"1"}]
        self.media += [{"media_id": "P2:container", "post_id": "P2", "media_type": "CAROUSEL_ALBUM",
                        "media_role": "carousel_container", "sort_order": "0"}]
        self.media += [{"media_id": f"C{i}", "post_id": "P2", "media_type": "IMAGE",
                        "media_role": "carousel_item", "media_url": f"https://cdn.invalid/{i}.jpg",
                        "sort_order": str(i)} for i in range(1,6)]
        self.media += [{"media_id": "P3", "post_id": "P3", "media_type": "VIDEO", "media_role": "primary",
                        "thumbnail_url": "https://cdn.invalid/vid.jpg", "sort_order": "1"},
                       {"media_id": "P4", "post_id": "P4", "media_type": "VIDEO", "media_role": "primary",
                        "sort_order": "1"}]
        def write(file, rows):
            with (self.source / file).open("w", encoding="utf-8-sig", newline="") as f:
                keys = sorted({key for row in rows for key in row})
                w = csv.DictWriter(f, keys)
                w.writeheader()
                w.writerows(rows)
        write("posts.csv", self.posts)
        write("media.csv", self.media)

    def run_live(self, *args):
        return v.main(["--source", str(self.source), "--output-dir", str(self.out),
                       "--env-file", str(self.cfg), "--delay-seconds", "0", "--live", *args])

    @staticmethod
    def good():
        return {"is_design_post": True, "visual_summary": "pink glossy nails",
                "color": ["Pink"], "technique": ["gradient"], "texture": ["glossy"],
                "motif": [], "season": [], "use": ["daily"], "confidence": .9}

    def test_urls(self):
        self.assertEqual("https://foo.invalid/v1/chat/completions", v.endpoint_url("https://foo.invalid/v1"))
        self.assertEqual("https://foo.invalid/v1/chat/completions", v.endpoint_url("https://foo.invalid"))
        self.assertEqual("https://foo.invalid/v1/chat/completions", v.endpoint_url("https://foo.invalid/v1/chat/completions"))
        with self.assertRaises(ValueError):
            v.endpoint_url("http://unsafe.invalid/v1")

    def test_no_secrets_logged_in_preview(self):
        with patch.object(v,"analyze") as mock:
            self.assertEqual(0, v.main(["--source",str(self.source),"--output-dir",str(self.out),
                                        "--env-file",str(self.cfg)]))
            mock.assert_not_called()
        self.assertFalse(self.out.exists())

    def test_media_selection_carousel(self):
        chosen = v.select_images([m for m in self.media if m["post_id"] == "P2"], 3)
        self.assertEqual(["C1","C3","C5"], [m["media_id"] for m in chosen])
        self.assertEqual(0,len([m for m in chosen if m["role"]=="carousel_container"]))
        self.assertEqual(["C1","C5"], [m["media_id"] for m in v.select_images(self.media[1:7], 2)])

    def test_video_thumbnail_only(self):
        chosen=v.select_images([m for m in self.media if m["post_id"]=="P3"],3)
        self.assertEqual("video_thumbnail", chosen[0]["basis"])
        self.assertEqual([],v.select_images([m for m in self.media if m["post_id"]=="P4"],3))

    def test_signed_image_url_rotation_does_not_reanalyze(self):
        image = v.select_images(self.media[:1], 3)
        first=v.fingerprint(self.posts[0],image,"flash",3)
        rotated = [dict(image[0],url="https://cdn.invalid/new.jpg?signature=two")]
        self.assertEqual(first,v.fingerprint(self.posts[0],rotated,"flash",3))
        self.assertNotEqual(first,v.fingerprint(dict(self.posts[0],caption="new"),image,"flash",3))

    def test_validate_model_output(self):
        data=v.parse_response(json.dumps(self.good()))
        self.assertEqual(["pink"],data["color"])
        self.assertTrue(data["is_design_post"])
        with self.assertRaises(v.ProviderError):
            v.parse_response('{"is_design_post":"yes"}')
        with self.assertRaises(v.ProviderError):
            v.parse_response('invalid json')

    def test_code_fenced_model_output_and_negative(self):
        obj=self.good();obj["is_design_post"]=False
        d=v.parse_response("```json\n"+json.dumps(obj)+"\n```")
        self.assertEqual([],d["color"])
        self.assertFalse(d["is_design_post"])

    def test_wrapped_json_and_second_json_rejected(self):
        wrapped = "Design analysis result:\n" + json.dumps(self.good()) + "\nCompleted."
        out = v.parse_response(wrapped)
        self.assertEqual(["pink"], out["color"])
        with self.assertRaises(v.ProviderError) as caught:
            v.parse_response(json.dumps(self.good()) + "\n" + json.dumps(self.good()))
        self.assertEqual("invalid_json", caught.exception.code)

    def test_broken_json_is_not_invented(self):
        with self.assertRaises(v.ProviderError) as caught:
            v.parse_response('Here is partial output: {"is_design_post":true, "color":')
        self.assertEqual("invalid_json", caught.exception.code)

    def test_format_error_retried_once_and_cached(self):
        with patch.object(v, "analyze",
                          side_effect=[v.ProviderError("invalid_json"), self.good()]) as fn:
            self.assertEqual(0, self.run_live("--limit", "1"))
            self.assertEqual(2, fn.call_count)
            self.assertEqual(2200, fn.call_args.kwargs.get("max_tokens"))
        with closing(sqlite3.connect(self.out / "vision.sqlite")) as db:
            self.assertEqual(1, db.execute(
                "SELECT COUNT(*) FROM post_analysis WHERE status='success'"
            ).fetchone()[0])
        # Re-run only the previously classified post. An untargeted
        # --limit 1 run would legitimately select a DIFFERENT uncached post;
        # the default MagicMock response is not a valid model JSON result.
        with patch.object(v, "analyze") as fn:
            self.assertEqual(0, self.run_live("--post-id", "P1", "--limit", "1"))
            fn.assert_not_called()

    def test_json_length_finish_reason_is_detected(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def read(self, limit):
                return json.dumps({"choices": [{"finish_reason": "length",
                     "message": {"content": json.dumps(VisionTests.good())}}]}).encode()
        provider = v.Provider("primary", "https://api.example.invalid/v1",
                              "FAKE_TEST_KEY", "fake-model")
        with patch.object(v, "urlopen", return_value=Response()):
            with self.assertRaises(v.ProviderError) as caught:
                v.analyze(self.posts[0], v.select_images(self.media[:1], 3), provider, 10)
        self.assertEqual("truncated_response", caught.exception.code)

    def test_read_sqlite_source(self):
        dbpath=self.source / "collection.sqlite"
        with closing(sqlite3.connect(dbpath)) as db:
            db.execute("CREATE TABLE posts (post_id TEXT PRIMARY KEY, country TEXT)")
            db.execute("CREATE TABLE media (media_id TEXT,post_id TEXT,media_type TEXT,media_url TEXT)")
            db.execute("INSERT INTO posts VALUES ('DB1','US')")
            db.execute("INSERT INTO media VALUES ('DB1','DB1','IMAGE','https://cdn.invalid/a.jpg')")
            db.commit()
        posts,media=v.read_inputs(self.source)
        self.assertEqual(["DB1"],[p["post_id"] for p in posts]);self.assertEqual(1,len(media))
        self.assertEqual(1,len(v.read_inputs(dbpath)[0]))

    def test_fail_on_duplicate_input_ids(self):
        p=self.posts+[dict(self.posts[0])]
        with (self.source / "posts.csv").open("w",encoding="utf-8-sig",newline="") as fp:
            w=csv.DictWriter(fp,p[0].keys(),extrasaction="ignore");w.writeheader();w.writerows(p)
        with self.assertRaises(ValueError):
            v.read_inputs(self.source)

    def test_persist_and_resume_no_duplicate_request(self):
        with patch.object(v,"analyze",return_value=self.good()) as fun:
            self.assertEqual(0,self.run_live("--limit","2"))
            self.assertEqual(2,fun.call_count)
        with closing(sqlite3.connect(self.out/"vision.sqlite")) as db:
            self.assertEqual(2,db.execute("SELECT COUNT(*) FROM post_analysis WHERE status='success'").fetchone()[0])
            self.assertIsNone(db.execute("SELECT engagement FROM post_analysis WHERE post_id='P1'").fetchone()[0])
            self.assertEqual(3,db.execute("SELECT COUNT(*) FROM selected_media WHERE post_id='P2'").fetchone()[0])
        with patch.object(v,"analyze",return_value=self.good()) as fun:
            self.assertEqual(0,self.run_live("--limit","1"))
            self.assertEqual(1,fun.call_count)
        with closing(sqlite3.connect(self.out/"vision.sqlite")) as db:
            self.assertEqual(3,db.execute("SELECT COUNT(*) FROM post_analysis WHERE status='success'").fetchone()[0])
        self.assertTrue((self.out/"post_analysis.csv").exists())
        self.assertTrue((self.out/"selected_media.csv").exists())
        self.assertTrue((self.out/"vision_summary.json").exists())

    def test_missing_image_marked_unavailable_no_network_call(self):
        with patch.object(v,"analyze",return_value=self.good()) as fn:
            self.assertEqual(0,self.run_live())
            self.assertEqual(3,fn.call_count)
        with closing(sqlite3.connect(self.out/"vision.sqlite")) as db:
            self.assertEqual(1,db.execute("SELECT COUNT(*) FROM post_analysis WHERE status='unavailable'").fetchone()[0])

    def test_provider_403_stop_no_retries(self):
        with patch.object(v,"analyze",side_effect=v.ProviderError("provider_http_403",403,True)) as fn:
            self.assertEqual(3,self.run_live())
            self.assertEqual(1,fn.call_count)
        with closing(sqlite3.connect(self.out/"vision.sqlite")) as db:
            self.assertEqual(1,db.execute("SELECT COUNT(*) FROM post_analysis WHERE status='failed'").fetchone()[0])

    def test_failed_skip_then_retry_explicit(self):
        with patch.object(v,"analyze",side_effect=v.ProviderError("invalid_json")):
            self.assertEqual(1,self.run_live("--limit","1"))
        with patch.object(v,"analyze",return_value=self.good()) as fun:
            self.assertEqual(0,self.run_live("--limit","1"))
            self.assertEqual(1,fun.call_count)
        with patch.object(v,"analyze",return_value=self.good()) as fun:
            self.assertEqual(0,self.run_live("--retry-failed","--limit","1"))
            self.assertEqual(1,fun.call_count)
        with closing(sqlite3.connect(self.out/"vision.sqlite")) as db:
            self.assertEqual(2,db.execute("SELECT attempts FROM post_analysis WHERE post_id='P1'").fetchone()[0])

    def test_targeted_failed_post_recovery_never_calls_other_post(self):
        # Initial artificial provider failure is persisted specifically for P1.
        with patch.object(v, "analyze", side_effect=v.ProviderError("invalid_json")) as fail:
            self.assertEqual(1, self.run_live("--post-id", "P1", "--limit", "1"))
            self.assertEqual(2, fail.call_count)
        with patch.object(v, "analyze", return_value=self.good()) as recovered:
            self.assertEqual(0, self.run_live("--post-id", "P1", "--retry-failed", "--limit", "1"))
            self.assertEqual(1, recovered.call_count)
            self.assertEqual("P1", recovered.call_args.args[0]["post_id"])
        with closing(sqlite3.connect(self.out / "vision.sqlite")) as db:
            actual = db.execute("SELECT post_id,status,attempts FROM post_analysis").fetchall()
            self.assertEqual([("P1", "success", 2)], actual)
        # Successful P1 is cached: an identical targeted rerun costs zero API calls.
        with patch.object(v, "analyze") as unused:
            self.assertEqual(0, self.run_live("--post-id", "P1", "--retry-failed"))
            unused.assert_not_called()

    def test_unknown_post_id_rejected_without_writing_results(self):
        with patch.object(v, "analyze") as unused:
            self.assertEqual(2, self.run_live("--post-id", "UNKNOWN_POST"))
            unused.assert_not_called()
        self.assertFalse(self.out.exists())

    def test_image_inline_converts_valid_jpeg_without_file(self):
        class Response:
            def __init__(self):
                self.headers = Message()
                self.headers["Content-Type"] = "image/jpeg"
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def read(self, limit): return b"\xff\xd8\xff\xe0testbytes"
        with patch.object(v,"urlopen",return_value=Response()) as fake:
            encoded=v.inline_image_url("https://cdn.invalid/signed.jpg")
        self.assertTrue(encoded.startswith("data:image/jpeg;base64,"))
        self.assertEqual(1,fake.call_count)

    def test_image_inline_rejects_html(self):
        class Response:
            headers = Message()
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def read(self, limit): return b"<html>invalid signed CDN image</html>"
        with patch.object(v,"urlopen",return_value=Response()):
            with self.assertRaises(v.ProviderError) as caught:
                v.inline_image_url("https://cdn.invalid/signed.jpg")
        self.assertEqual("image_invalid_format",caught.exception.code)

    def test_https_api_payload_and_auth_sanitized(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def read(self, limit):
                return json.dumps({"choices":[{"message":{"content":json.dumps(VisionTests.good())}}]}).encode()
        provider=v.Provider("primary","https://api.example.invalid/v1","NEVER_LOG_KEY","gemini-example")
        images=v.select_images(self.media[:1],3)
        with patch.object(v,"urlopen",return_value=Response()) as call:
            result=v.analyze(self.posts[0],images,provider,50)
        request=call.call_args.args[0]
        sent=json.loads(request.data.decode())
        self.assertEqual("gemini-example",sent["model"])
        self.assertEqual("https://cdn.invalid/a.jpg?signature=one",
                         sent["messages"][1]["content"][1]["image_url"]["url"])
        self.assertEqual("Bearer NEVER_LOG_KEY",request.headers["Authorization"])
        self.assertEqual(["pink"],result["color"])

    def test_two_consecutive_bad_outputs_halt(self):
        with patch.object(v,"analyze",side_effect=v.ProviderError("invalid_schema")) as mock:
            self.assertEqual(3,self.run_live())
            self.assertEqual(4,mock.call_count)  # 2 posts x 2 bounded format attempts
        with closing(sqlite3.connect(self.out/"vision.sqlite")) as db:
            self.assertEqual(2,db.execute("SELECT COUNT(*) FROM post_analysis WHERE status='failed'").fetchone()[0])

    def test_exclusive_lock(self):
        self.out.mkdir()
        with v.process_lock(self.out):
            with self.assertRaises(RuntimeError):
                with v.process_lock(self.out):
                    pass

    def test_bad_source_dest_fails_without_writes(self):
        self.assertEqual(2,v.main(["--source",str(self.source),"--output-dir",str(self.root)]))

    def test_live_requires_keys(self):
        env=self.root/"empty.env";env.write_text("",encoding="utf-8")
        with patch.dict("os.environ",{},clear=True):
            self.assertEqual(2,v.main(["--source",str(self.source),"--output-dir",str(self.out),
                                        "--env-file",str(env),"--live"]))
            self.assertFalse(self.out.exists())

    def test_selected_media_does_not_store_urls(self):
        with patch.object(v,"analyze",return_value=self.good()):
            self.run_live("--limit","1")
        with closing(sqlite3.connect(self.out/"vision.sqlite")) as db:
            media_json=db.execute("SELECT selected_media_json FROM post_analysis WHERE post_id='P1'").fetchone()[0]
            self.assertNotIn("signature",media_json)
            self.assertNotIn("DUMMY_NO_LIVE_TOKEN",media_json)

if __name__ == "__main__":
    unittest.main()
