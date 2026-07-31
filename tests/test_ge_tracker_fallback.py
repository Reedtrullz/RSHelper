"""Tests for the GE Tracker fallback source when the OSRS Wiki is blocked."""

import datetime
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, "src")

import rshelper.api as api
import rshelper.profile as pmod


def _fresh_ts() -> str:
    """Recent GE Tracker-style timestamp so fixture prices pass the staleness guard."""
    fresh = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5)
    return fresh.strftime("%Y-%m-%d %H:%M:%S")


DUMP = {"data": [
    {"itemId": 4151, "name": "Abyssal whip", "members": True, "buyLimit": 70,
     "highAlch": 72000, "lowAlch": 48000, "buying": 1500000, "selling": 1520000,
     "buyingQuantity": 300, "sellingQuantity": 250,
     "lastKnownBuyTime": _fresh_ts(), "lastKnownSellTime": _fresh_ts(),
     "updatedAt": "2026-07-31 16:40:36"},
    {"itemId": 2, "name": "Cannonball", "members": False, "buyLimit": 10000,
     "highAlch": 3, "lowAlch": 2, "buying": 200, "selling": 210,
     "buyingQuantity": 5000, "sellingQuantity": 4000,
     "lastKnownBuyTime": _fresh_ts(), "lastKnownSellTime": _fresh_ts(),
     "updatedAt": "2026-07-31 16:40:36"},
]}


class GeTrackerFallbackTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self.tmp.name) / "cache"
        self.cache.mkdir(parents=True)
        self.patchers = [
            mock.patch.object(pmod, "CACHE_DIR", self.cache),
            mock.patch.object(api, "CACHE_DIR", self.cache),
        ]
        for p in self.patchers:
            p.start()
        self.addCleanup(self.tmp.cleanup)

    def tearDown(self):
        for p in self.patchers:
            p.stop()

    def test_wiki_primary_skips_ge_tracker(self):
        with mock.patch.object(api, "_get", return_value=[{"id": 1, "name": "Rune"}]):
            with mock.patch.object(api, "_get_ge_tracker",
                                   side_effect=AssertionError("fallback must not run")):
                mapping = api.fetch_mapping("default")
        self.assertEqual(mapping, [{"id": 1, "name": "Rune"}])

    def test_mapping_fallback(self):
        with mock.patch.object(api, "_get", return_value=None):
            with mock.patch.object(api, "_get_ge_tracker", return_value=DUMP):
                mapping = api.fetch_mapping("default")
        by_id = {e["id"]: e for e in mapping}
        self.assertEqual(by_id[4151]["name"], "Abyssal whip")
        self.assertEqual(by_id[4151]["limit"], 70)
        self.assertEqual(by_id[4151]["highalch"], 72000)
        self.assertEqual(by_id[4151]["lowalch"], 48000)
        self.assertTrue(by_id[4151]["members"])

    def test_latest_fallback(self):
        with mock.patch.object(api, "_get", return_value=None):
            with mock.patch.object(api, "_get_ge_tracker", return_value=DUMP):
                latest = api.fetch_latest("default")
        entry = latest["4151"]
        self.assertEqual(entry["high"], 1500000)
        self.assertEqual(entry["low"], 1520000)
        self.assertEqual(entry["high_volume"], 300)
        self.assertEqual(entry["low_volume"], 250)
        self.assertIsInstance(entry["highTime"], int)
        self.assertIsInstance(entry["lowTime"], int)

    def test_parse_tracker_time(self):
        self.assertIsNone(api._parse_tracker_time(None))
        self.assertIsNone(api._parse_tracker_time("not a date"))
        parsed = api._parse_tracker_time("2026-07-31 16:40:36")
        self.assertEqual(parsed, 1785516036)

    def test_5m_fallback_volume_proxy(self):
        with mock.patch.object(api, "_get", return_value=None):
            with mock.patch.object(api, "_get_ge_tracker", return_value=DUMP):
                vol = api.fetch_5m("default")
        self.assertEqual(vol["4151"]["highPriceVolume"], 300)
        self.assertEqual(vol["4151"]["lowPriceVolume"], 250)

    def test_bootstrap_builds_items_from_fallback(self):
        from rshelper.scanner import build_items_from_api
        with mock.patch.object(api, "_get", return_value=None):
            with mock.patch.object(api, "_get_ge_tracker", return_value=DUMP):
                mapping = api.fetch_mapping("default")
                latest = api.fetch_latest("default")
                vol = api.fetch_5m("default")
        items = build_items_from_api(mapping, latest, vol)
        by_id = {i.id: i for i in items}
        self.assertEqual(by_id[4151].buy_price, 1500000)
        self.assertEqual(by_id[4151].sell_price, 1520000)
        self.assertEqual(by_id[4151].volume, 550)
        self.assertEqual(by_id[4151].buy_limit, 70)


if __name__ == "__main__":
    unittest.main()
