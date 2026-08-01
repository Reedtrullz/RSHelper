"""Tests for the tuning log module."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from rshelper import profile, tuning


class TestTuning(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._cfg = profile.CONFIG_DIR
        self._active = profile.ACTIVE_PROFILE_PATH
        profile.CONFIG_DIR = self.tmp
        profile.ACTIVE_PROFILE_PATH = self.tmp / "active_profile"

    def tearDown(self):
        profile.CONFIG_DIR = self._cfg
        profile.ACTIVE_PROFILE_PATH = self._active
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_params_shape(self):
        p = tuning.params()
        self.assertEqual(set(p), {"alch", "flip", "margin", "trader"})
        self.assertIn("min_volume", p["flip"])
        self.assertIn("direction", p["margin"])
        self.assertIn("spread_collapse_exit_minutes", p["trader"])

    def test_record_on_change(self):
        entry = tuning.record_if_changed()
        self.assertIsNotNone(entry)
        self.assertEqual(entry["note"], "auto")
        self.assertIn("params", entry)
        self.assertEqual(len(tuning.load_entries()), 1)

    def test_skip_when_unchanged(self):
        tuning.record_if_changed()
        self.assertIsNone(tuning.record_if_changed())
        self.assertEqual(len(tuning.load_entries()), 1)

    def test_profile_isolation(self):
        tuning.record_if_changed("main")
        self.assertTrue(tuning.log_path("main").exists())
        self.assertFalse(tuning.log_path().exists())
        self.assertEqual(len(tuning.load_entries("main")), 1)

    def test_config_at(self):
        entries = [
            {"ts": "2026-07-30T10:00:00Z", "params": {"v": 1}},
            {"ts": "2026-08-01T10:00:00Z", "params": {"v": 2}},
        ]
        self.assertEqual(tuning.config_at("2026-07-31", entries), {"v": 1})
        self.assertEqual(tuning.config_at("2026-08-02", entries), {"v": 2})
        self.assertIsNone(tuning.config_at("2026-01-01", entries))

    def test_unchanged_params_not_duplicated(self):
        tuning.record_if_changed()
        tuning.record_if_changed()
        self.assertEqual(len(tuning.load_entries()), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
