"""Offline tests for Meta cursor edge validation."""
import importlib.util
from pathlib import Path
import unittest

p = Path(__file__).resolve().parents[1] / "raw_v2" / "three_api_paging.py"
spec = importlib.util.spec_from_file_location("three_api_paging", p)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class PagingTests(unittest.TestCase):
    def test_valid_edge(self):
        result = mod.validate_page_edge(
            {"data": [{"id": "1"}], "paging": {
                "next": "https://graph.facebook.com/page",
                "cursors": {"after": "abc123"}}})
        self.assertEqual(result["next_cursor"], "abc123")
        self.assertFalse(result["terminal"])

    def test_terminal_page(self):
        result = mod.validate_page_edge({"data": [{"id": "2"}]})
        self.assertTrue(result["terminal"])
        self.assertIsNone(result["next_cursor"])

    def test_next_without_cursor_fails(self):
        with self.assertRaises(ValueError):
            mod.validate_page_edge({"data": [], "paging": {"next": "https://example.org"}})

    def test_cycle_fails(self):
        with self.assertRaises(ValueError):
            mod.validate_page_edge(
                {"data": [], "paging": {"next": "https://example.org",
                 "cursors": {"after": "abc"}}},
                requested_cursor="abc")

    def test_prior_cursor_reuse_fails(self):
        with self.assertRaises(ValueError):
            mod.validate_page_edge(
                {"data": [], "paging": {"next": "https://example.org",
                 "cursors": {"after": "abc"}}}, prior_cursors=("abc",))

    def test_invalid_response_fails(self):
        with self.assertRaises(ValueError):
            mod.validate_page_edge({"data": "bad"})


if __name__ == "__main__":
    unittest.main()
