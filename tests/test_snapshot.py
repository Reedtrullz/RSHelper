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

    def test_save_embeds_config_fingerprint(self):
        path = snapshot.save("flip", self._fake_results())
        data = json.loads(path.read_text())
        self.assertIn("config", data)
        self.assertIn("flip", data["config"])
        self.assertIn("min_volume", data["config"]["flip"])

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

    def test_diff_process_tracks_gp_per_hour(self):
        """Process diff uses profit AND carries gp_per_hour (the actionable
        'is it a good time now vs before' number)."""
        snapshot.save("process", [
            {"item_id": 569, "name": "Fire orb", "profit": 2000,
             "gp_per_hour": 3600000, "input_cost": 95, "sell_price": 2079},
            {"item_id": 2353, "name": "Steel bar", "profit": 195,
             "gp_per_hour": 234000, "input_cost": 371, "sell_price": 577},
        ])
        prev = {
            "scan_type": "process",
            "date": "2026-07-28",
            "saved_at": "2026-07-28T12:00:00Z",
            "count": 2,
            "items": [
                {"item_id": 569, "name": "Fire orb", "profit": 1500,
                 "gp_per_hour": 2700000, "input_cost": 95, "sell_price": 1600},
                {"item_id": 2353, "name": "Steel bar", "profit": 195,
                 "gp_per_hour": 234000, "input_cost": 371, "sell_price": 577},
            ],
        }
        (snapshot.SNAPSHOT_DIR / "process-2026-07-28.json").write_text(json.dumps(prev))

        diff = snapshot.diff_scan_type("process", "2026-07-28")
        self.assertIsNotNone(diff)
        # Fire orb improved (profit 1500→2000, gp/hr 2.7M→3.6M)
        self.assertEqual(len(diff["improved"]), 1)
        improved = diff["improved"][0]
        self.assertEqual(improved["item_id"], 569)
        self.assertEqual(improved["delta"], 500)
        self.assertEqual(improved["gp_per_hour"], 3600000)  # flows through
        # Steel bar unchanged
        self.assertEqual(diff["unchanged"], 1)

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
