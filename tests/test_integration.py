"""Integration test: hits the real OSRS Wiki API, builds items, runs scans."""

import unittest
import urllib.request
import urllib.error
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from rshelper.api import fetch_mapping, fetch_latest, fetch_5m
from rshelper.scanner import build_items_from_api, AlchScanner, FlipScanner


def _has_network():
    try:
        req = urllib.request.Request(
            "https://prices.runescape.wiki/api/v1/osrs/latest",
            headers={"User-Agent": "RSHelper-test/0.1"},
        )
        with urllib.request.urlopen(req, timeout=5):
            return True
    except Exception:
        return False


HAS_NETWORK = _has_network()


class TestIntegration(unittest.TestCase):

    @unittest.skipUnless(HAS_NETWORK, "no network")
    def test_fetch_latest_returns_data(self):
        data = fetch_latest()
        self.assertIsInstance(data, dict)
        self.assertGreater(len(data), 100)
        # Cannonball (id=2) should exist
        self.assertIn("2", data)
        cannonball = data["2"]
        self.assertIsInstance(cannonball, dict)
        self.assertIn("high", cannonball)
        self.assertIn("low", cannonball)
        self.assertGreater(cannonball["high"], 0)
        self.assertGreater(cannonball["low"], 0)

    @unittest.skipUnless(HAS_NETWORK, "no network")
    def test_fetch_mapping_returns_items(self):
        mapping = fetch_mapping()
        self.assertIsInstance(mapping, list)
        self.assertGreater(len(mapping), 100)
        entry = mapping[0]
        self.assertIn("id", entry)
        self.assertIn("name", entry)

    @unittest.skipUnless(HAS_NETWORK, "no network")
    def test_build_items_and_scan(self):
        mapping = fetch_mapping()
        latest = fetch_latest()
        volume_5m = fetch_5m() or {}
        items = build_items_from_api(mapping, latest, volume_5m)
        self.assertGreater(len(items), 50)

        # Run alch scanner
        scanner = AlchScanner(nature_rune_cost=147)
        results = scanner.scan(items, min_volume=100)
        self.assertGreater(len(results), 0)
        for item in results[:5]:
            self.assertGreater(item.profit, 0)
            self.assertGreaterEqual(item.gp_per_hour, 0)

        # Run flip scanner
        flip = FlipScanner(direction="traditional")
        flips = flip.scan(items, min_volume=100)
        self.assertIsInstance(flips, list)
        self.assertGreater(len(flips), 0)

    @unittest.skipUnless(HAS_NETWORK, "no network")
    def test_confidence_bounds_integration(self):
        from rshelper.api import fetch_timeseries
        ts = fetch_timeseries(2, "5m")  # Cannonball
        if ts and len(ts) >= 6:
            from rshelper.analysis import analyze_timeseries
            analysis = analyze_timeseries(2, ts, current_buy=200, current_sell=190)
            if analysis:
                self.assertGreaterEqual(analysis.confidence, 0.0)
                self.assertLessEqual(analysis.confidence, 1.0)


if __name__ == "__main__":
    unittest.main()
