"""Tests for watchlist state file management."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from rshelper import watchlist


class TestWatchlist(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._orig_path = watchlist.WATCHLIST_PATH
        watchlist.WATCHLIST_PATH = Path(self.tmp) / "watchlist.json"

    def tearDown(self):
        watchlist.WATCHLIST_PATH = self._orig_path

    def test_empty_list(self):
        self.assertEqual(watchlist.list_all(), [])

    def test_add_and_list(self):
        watchlist.add(561, "Nature rune")
        items = watchlist.list_all()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["name"], "Nature rune")

    def test_add_with_alerts(self):
        watchlist.add(561, "Nature rune", alert_margin_above=500, alert_margin_below=10)
        data = watchlist.load()
        entry = data["items"]["561"]
        self.assertEqual(entry["alert_margin_above"], 500)
        self.assertEqual(entry["alert_margin_below"], 10)

    def test_add_updates_existing(self):
        watchlist.add(561, "Nature rune")
        watchlist.add(561, "Nature rune", alert_margin_above=200)
        items = watchlist.list_all()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["alert_margin_above"], 200)

    def test_remove_existing(self):
        watchlist.add(561, "Nature rune")
        self.assertTrue(watchlist.remove(561))
        self.assertEqual(watchlist.list_all(), [])

    def test_remove_nonexistent(self):
        self.assertFalse(watchlist.remove(99999))

    def test_get_watched_ids(self):
        watchlist.add(561, "Nature rune")
        watchlist.add(2, "Cannonball")
        ids = watchlist.get_watched_ids()
        self.assertIn(561, ids)
        self.assertIn(2, ids)
        self.assertEqual(len(ids), 2)

    def test_corrupt_json_recovers(self):
        watchlist.WATCHLIST_PATH.write_text("not valid json {{{")
        data = watchlist.load()
        self.assertEqual(data, {"items": {}})

    def test_roundtrip(self):
        watchlist.add(1, "Item 1", alert_margin_above=100)
        watchlist.add(2, "Item 2")
        watchlist.add(3, "Item 3", alert_margin_below=50)
        ids = watchlist.get_watched_ids()
        self.assertEqual(len(ids), 3)

        watchlist.remove(2)
        ids = watchlist.get_watched_ids()
        self.assertEqual(len(ids), 2)
        self.assertNotIn(2, ids)


if __name__ == "__main__":
    unittest.main()
