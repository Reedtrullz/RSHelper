"""Tests for snapshot save/load/diff."""

import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from rshelper import snapshot


class TestSnapshot(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._orig_dir = snapshot.SNAPSHOT_DIR
        snapshot.SNAPSHOT_DIR = Path(self.tmp)

    def tearDown(self):
        snapshot.SNAPSHOT_DIR = self._orig_dir

    def _fake_results(self):
        return [
            {"item_id": 1, "name": "Item A", "profit": 100, "gp_per_hour": 1000},
            {"item_id": 2, "name": "Item B", "profit": 200, "gp_per_hour": 2000},
            {"item_id": 3, "name": "Item C", "profit": 50,  "gp_per_hour": 500},
        ]

    def test_save_creates_file(self):
        results = self._fake_results()
        path = snapshot.save("flip", results)
        self.assertTrue(path.exists())
        data = json.loads(path.read_text())
        self.assertEqual(data["scan_type"], "flip")
        self.assertEqual(data["count"], 3)
        self.assertEqual(data["date"], date.today().isoformat())

    def test_load_most_recent(self):
        results = self._fake_results()
        snapshot.save("flip", results)
        loaded = snapshot.load("flip")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["scan_type"], "flip")
        self.assertEqual(len(loaded["items"]), 3)

    def test_load_by_date(self):
        results = self._fake_results()
        snapshot.save("flip", results)
        today = date.today().isoformat()
        loaded = snapshot.load("flip", today)
        self.assertIsNotNone(loaded)

    def test_load_nonexistent_date(self):
        loaded = snapshot.load("flip", "2020-01-01")
        self.assertIsNone(loaded)

    def test_diff_alch_flip_uses_profit(self):
        # Save today's data
        today = [
            {"item_id": 1, "name": "Item A", "profit": 150, "gp_per_hour": 1500},
            {"item_id": 2, "name": "Item B", "profit": 250, "gp_per_hour": 2500},
        ]
        snapshot.save("alch", today)

        # Create a fake previous snapshot
        prev = {
            "scan_type": "alch",
            "date": "2026-07-28",
            "saved_at": "2026-07-28T12:00:00Z",
            "count": 3,
            "items": [
                {"item_id": 1, "name": "Item A", "profit": 100, "gp_per_hour": 1000},
                {"item_id": 2, "name": "Item B", "profit": 300, "gp_per_hour": 3000},
                {"item_id": 99, "name": "Old Item", "profit": 50, "gp_per_hour": 500},
            ],
        }
        prev_path = snapshot.SNAPSHOT_DIR / "alch-2026-07-28.json"
        prev_path.write_text(json.dumps(prev))

        diff = snapshot.diff_scan_type("alch", "2026-07-28")
        self.assertIsNotNone(diff)
        self.assertEqual(len(diff["improved"]), 1)  # Item A: 100→150
        self.assertEqual(len(diff["fell_off"]), 1)   # Item B: 300→250
        self.assertEqual(len(diff["removed"]), 1)    # Item 99: gone
        self.assertEqual(diff["unchanged"], 0)

    def test_diff_margin_uses_avg_margin(self):
        today = [
            {"item_id": 1, "name": "Item A", "avg_margin": 150, "confidence": 0.8},
            {"item_id": 2, "name": "Item B", "avg_margin": 50,  "confidence": 0.5},
        ]
        snapshot.save("margin", today)

        prev = {
            "scan_type": "margin",
            "date": "2026-07-28",
            "saved_at": "2026-07-28T12:00:00Z",
            "count": 1,
            "items": [
                {"item_id": 1, "name": "Item A", "avg_margin": 100, "confidence": 0.7},
            ],
        }
        prev_path = snapshot.SNAPSHOT_DIR / "margin-2026-07-28.json"
        prev_path.write_text(json.dumps(prev))

        diff = snapshot.diff_scan_type("margin", "2026-07-28")
        self.assertIsNotNone(diff)
        self.assertEqual(len(diff["improved"]), 1)  # Item A: 100→150
        self.assertEqual(len(diff["new"]), 1)       # Item B: new
        self.assertEqual(diff["unchanged"], 0)

    def test_diff_missing_today(self):
        result = snapshot.diff_scan_type("flip")
        self.assertIsNone(result)

    def test_list_snapshots(self):
        snapshot.save("alch", self._fake_results())
        snapshot.save("flip", self._fake_results())
        all_paths = snapshot.list_snapshots()
        self.assertGreaterEqual(len(all_paths), 2)

        alch_paths = snapshot.list_snapshots("alch")
        self.assertEqual(len(alch_paths), 1)


if __name__ == "__main__":
    unittest.main()
