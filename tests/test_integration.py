"""Integration test: hits the real OSRS Wiki API, builds items, runs scans."""

import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from rshelper.api import fetch_mapping_result, fetch_latest_result, fetch_5m_result, fetch_timeseries_result
from rshelper.scanner import build_items_from_api, AlchScanner, FlipScanner
from rshelper.market_data import MarketDataResult

PROVIDER_EVIDENCE = []


class TestProviderEvidence(unittest.TestCase):
    def test_cached_or_unidentified_results_cannot_certify_live_provider(self):
        for delivery, source, stale in [('fresh-cache', 'wiki', False),
                                        ('stale-cache', 'wiki', True),
                                        ('network', 'unknown', False)]:
            result = MarketDataResult({}, source, delivery, 1, 1, 1, stale,
                                      'unknown', {})
            with self.subTest(delivery=delivery, source=source):
                with self.assertRaises(AssertionError):
                    require_network_result(result)
        with self.assertRaises(AssertionError):
            require_network_result(None)

    def test_network_result_records_source_without_exposing_rows(self):
        import contextlib
        import io
        result = MarketDataResult({'private': 'row'}, 'ge-tracker', 'network',
                                  1, 1, 1, False, 'standing-orders', {'ge-tracker': 1})
        evidence_count = len(PROVIDER_EVIDENCE)
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            self.assertIs(require_network_result(result), result.data)
        self.assertIn('ge-tracker', output.getvalue())
        self.assertNotIn('private', output.getvalue())
        del PROVIDER_EVIDENCE[evidence_count:]


def require_network_result(result):
    assert result is not None, 'provider acquisition failed'
    assert result.delivery == 'network' and not result.stale, 'cached data is not a live provider check'
    assert result.source in ('wiki', 'ge-tracker'), 'provider source is unidentified'
    assert result.fetched_at is not None and result.last_success_at is not None, 'missing source timestamps'
    print(f'provider source={result.source} delivery={result.delivery} '
          f'volume={result.volume_kind} coverage={result.coverage}', file=sys.stderr)
    PROVIDER_EVIDENCE.append({key: getattr(result, key) for key in
        ('source', 'delivery', 'fetched_at', 'last_attempt_at', 'last_success_at', 'stale', 'volume_kind', 'coverage')})
    return result.data


PROVIDER_CHECK = os.environ.get("RSHELPER_PROVIDER_CHECK") == "1"


def fresh_result(fetcher, *args):
    # Separate owned caches make each test prove acquisition, including fallback.
    import uuid
    return fetcher(*args, profile='provider-' + uuid.uuid4().hex[:23])


class TestIntegration(unittest.TestCase):

    def test_build_items_offline(self):
        import time
        now = int(time.time())
        mapping = [{"id": 2, "name": "Cannonball", "members": True,
                    "limit": 11000, "highalch": 6}]
        latest = {"2": {"high": 200, "low": 190,
                        "highTime": now, "lowTime": now}}
        volumes = {"2": {"highPriceVolume": 500, "lowPriceVolume": 500}}
        items = build_items_from_api(mapping, latest, volumes)
        self.assertEqual(len(items), 1)
        self.assertEqual((items[0].buy_price, items[0].sell_price), (200, 190))

    @unittest.skipUnless(PROVIDER_CHECK, "provider checks explicitly disabled in offline mode")
    def test_fetch_latest_returns_data(self):
        data = require_network_result(fresh_result(fetch_latest_result))
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

    @unittest.skipUnless(PROVIDER_CHECK, "provider checks explicitly disabled in offline mode")
    def test_fetch_mapping_returns_items(self):
        mapping = require_network_result(fresh_result(fetch_mapping_result))
        self.assertIsInstance(mapping, list)
        self.assertGreater(len(mapping), 100)
        entry = mapping[0]
        self.assertIn("id", entry)
        self.assertIn("name", entry)

    @unittest.skipUnless(PROVIDER_CHECK, "provider checks explicitly disabled in offline mode")
    def test_build_items_and_scan(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=3) as pool:
            mapping, latest, volume_5m = [require_network_result(result) for result in
                pool.map(fresh_result, (fetch_mapping_result, fetch_latest_result, fetch_5m_result))]
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

    @unittest.skipUnless(PROVIDER_CHECK, "provider checks explicitly disabled in offline mode")
    def test_confidence_bounds_integration(self):
        result = fresh_result(fetch_timeseries_result, 2, '5m')
        if result is None:
            latest = fresh_result(fetch_latest_result)
            require_network_result(latest)
            if latest.source == 'ge-tracker':
                self.skipTest('Wiki history unavailable; GE Tracker has no historical candle capability')
        ts = require_network_result(result)
        self.assertGreaterEqual(len(ts), 6, 'insufficient live history for confidence check')
        from rshelper.analysis import analyze_timeseries
        analysis = analyze_timeseries(2, ts, current_buy=200, current_sell=190)
        self.assertIsNotNone(analysis)
        self.assertGreaterEqual(analysis.confidence, 0.0)
        self.assertLessEqual(analysis.confidence, 1.0)


if __name__ == "__main__":
    unittest.main()
