"""Meta-shaped synthetic payload regression tests; no network access."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "raw_v2"))
from three_api_meta_normalizer import normalize_meta_page


class MetaNormalizerTests(unittest.TestCase):
    def test_nested_media_allowlist(self):
        payload = {"business_discovery": {"media": {"data": [
            {"id": "p1", "caption": "nail", "like_count": 4,
             "access_token": "DO_NOT_STORE", "extra": "DROP"}]}}}
        result = normalize_meta_page(payload)
        self.assertEqual(result, {"data": [
            {"id": "p1", "caption": "nail", "like_count": 4}]})

    def test_next_url_removed_but_cursor_kept(self):
        payload = {"data": [{"id": "p1"}], "paging": {
            "next": "https://graph.facebook.com/?access_token=SECRET",
            "cursors": {"after": "edge1"}}}
        result = normalize_meta_page(payload)
        self.assertEqual(result["paging"]["next"], "offline-next-page")
        self.assertNotIn("SECRET", str(result))
        self.assertEqual(result["paging"]["cursors"]["after"], "edge1")

    def test_meta_error_fails_closed(self):
        with self.assertRaises(ValueError):
            normalize_meta_page({"error": {"message": "quota"}})

    def test_missing_id_fails_closed(self):
        with self.assertRaises(ValueError):
            normalize_meta_page({"data": [{"caption": "no id"}]})

    def test_invalid_engagement_fails_closed(self):
        with self.assertRaises(ValueError):
            normalize_meta_page({"data": [{"id": "p", "like_count": -1}]})

    def test_next_without_cursor_fails_closed(self):
        with self.assertRaises(ValueError):
            normalize_meta_page({"data": [{"id": "p"}],
                                 "paging": {"next": "https://graph.facebook.com/next"}})

    def test_over_limit_fails_closed(self):
        with self.assertRaises(ValueError):
            normalize_meta_page({"data": [{"id": str(i)} for i in range(5)]})


if __name__ == "__main__":
    unittest.main()
