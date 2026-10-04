"""Offline tests for source and freshness provenance at the API/cache boundary."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rshelper import api
from rshelper.market_data import MarketDataResult


class MarketDataResultTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cache = Path(self.temp.name)
        self.now = time.time()
        self.path_patch = mock.patch.object(api, "_cache_path",
                                           side_effect=lambda name, profile=None:
                                           self.cache / f"{name}.json")
        self.path_patch.start()
        self.cache_dir_patch = mock.patch.object(api, "CACHE_DIR", self.cache)
        self.cache_dir_patch.start()
        self.clock = mock.patch.object(api.time, "time", return_value=self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.addCleanup(self.cache_dir_patch.stop)
        self.addCleanup(self.path_patch.stop)
        self.addCleanup(self.temp.cleanup)

    def age_cache(self, name, at):
        for suffix in ('.json', '.provenance.json'):
            path=self.cache/(name+suffix)
            if path.exists(): os.utime(path,(at,at))

    def test_result_is_typed_and_exposes_all_provenance_fields(self):
        result = MarketDataResult({}, "unknown", "fresh-cache", None, None,
                                  None, False, "unknown", {"wiki": 2, "ge-tracker": 1})
        self.assertEqual(result.source, "unknown")
        self.assertEqual(result.volume_kind, "unknown")
        self.assertIsNone(result.fetched_at)
        self.assertEqual(result.coverage, {"wiki": 2, "ge-tracker": 1})

    def test_wiki_refresh_then_failed_refresh_preserves_last_success(self):
        payload = {"2": {"high": 100, "low": 90, "highTime": 1_000,
                          "lowTime": 1_000}}
        payload["2"]["highTime"] = payload["2"]["lowTime"] = self.now
        with mock.patch.object(api, "_get", return_value=payload), \
                mock.patch.object(api, "_get_ge_tracker", return_value=None):
            first = api.fetch_latest_result("default")
        self.assertEqual(first.source, "wiki")
        self.assertEqual(first.delivery, "network")
        self.assertEqual(first.fetched_at, self.now)
        self.age_cache("latest", self.now)
        with mock.patch.object(api, "_get", side_effect=AssertionError("fresh cache expected")):
            self.assertEqual(api.fetch_latest("default"), payload)

        self.cache.joinpath("latest.json").touch()
        self.age_cache("latest", self.now)
        with mock.patch.object(api, "CACHE_MAX_AGE", {**api.CACHE_MAX_AGE, "latest": 10}), \
                mock.patch.object(api.time, "time", return_value=self.now + 11.0), \
                mock.patch.object(api, "_get", return_value=None), \
                mock.patch.object(api, "_get_ge_tracker", return_value=None):
            stale = api.fetch_latest_result("default")
        self.assertEqual(stale.delivery, "stale-cache")
        self.assertTrue(stale.stale)
        self.assertEqual(stale.last_success_at, self.now)
        self.assertEqual(stale.last_attempt_at, self.now + 11.0)

    def test_legacy_payload_is_readable_with_unknown_provenance(self):
        data = {"2": {"high": 100, "low": 90, "highTime": 1_000,
                       "lowTime": 1_000}}
        data["2"]["highTime"] = data["2"]["lowTime"] = self.now
        (self.cache / "latest.json").write_text(json.dumps(data))
        self.age_cache("latest", self.now)
        result = api.fetch_latest_result("default")
        self.assertEqual(result.data, data)
        self.assertEqual(result.source, "unknown")
        self.assertEqual(result.delivery, "fresh-cache")
        self.assertIsNone(result.fetched_at)
        self.assertIsNone(result.last_success_at)

    def test_tracker_fallback_provenance_survives_fresh_cache(self):
        dump = {"data": [{"itemId": 2, "buying": 100, "selling": 90,
                          "buyingQuantity": 12, "sellingQuantity": 9}]}
        with mock.patch.object(api, "_get", return_value=None), \
                mock.patch.object(api, "_fetch_url", return_value=dump):
            first = api.fetch_latest_result("default")
        self.assertEqual(first.source, "ge-tracker")
        self.assertEqual(first.volume_kind, "standing-orders")
        self.age_cache("latest", self.now)
        cached = api.fetch_latest_result("default")
        self.assertEqual(cached.source, "ge-tracker")
        self.assertEqual(cached.delivery, "fresh-cache")
        self.assertEqual(cached.volume_kind, "standing-orders")

    def test_invalid_versioned_metadata_fails_closed(self):
        data = {"2": {"high": 100, "low": 90, "highTime": 1_000,
                       "lowTime": 1_000}}
        data["2"]["highTime"] = data["2"]["lowTime"] = self.now
        (self.cache / "latest.json").write_text(json.dumps(data))
        (self.cache / "latest.provenance.json").write_text(
            json.dumps({"schema_version": 900, "data": data,
                        "source": "made-up", "fetched_at": 1_000}))
        fresh = {"3": {"high": 200, "low": 190, "highTime": 1_000,
                        "lowTime": 1_000}}
        fresh["3"]["highTime"] = fresh["3"]["lowTime"] = self.now
        with mock.patch.object(api, "_get", return_value=fresh) as fetch:
            result = api.fetch_latest_result("default")
        fetch.assert_called_once()
        self.assertEqual(result.data, fresh)
        self.assertEqual(result.source, "wiki")

    def test_invalid_metadata_fields_are_quarantined(self):
        data = {"2": {"high": 100, "low": 90, "highTime": self.now,
                       "lowTime": self.now}}
        valid = {"schema_version": 1, "data": data, "source": "wiki",
                 "fetched_at": self.now, "last_attempt_at": self.now,
                 "last_success_at": self.now, "volume_kind": "unknown",
                 "coverage": {"wiki": 1}}
        invalid = ({"source": []}, {"coverage": {"untrusted": 1}},
                   {"last_attempt_at": True}, {"schema_version": True})
        for change in invalid:
            with self.subTest(change=change):
                (self.cache / "latest.json").write_text(json.dumps(data))
                (self.cache / "latest.provenance.json").write_text(
                    json.dumps({**valid, **change}))
                self.age_cache("latest", self.now)
                self.assertIsNone(api._load_cache("latest", "default"))

    def test_standing_order_quantities_do_not_claim_executed_volume(self):
        dump = {"data": [{"itemId": 2, "buying": 100, "selling": 90,
                          "buyingQuantity": 12, "sellingQuantity": 9}]}
        with mock.patch.object(api, "_get", return_value=None), \
                mock.patch.object(api, "_fetch_url", return_value=dump):
            result = api.fetch_5m_result("default")
        self.assertEqual(result.volume_kind, "standing-orders")
        self.assertEqual(result.source, "ge-tracker")

    def test_timeseries_result_and_data_only_wrapper(self):
        data = [{"timestamp": self.now, "avgHighPrice": 100,
                 "avgLowPrice": 90, "highPriceVolume": 4, "lowPriceVolume": 3}]
        with mock.patch.object(api, "_get", return_value={"data": data}):
            result = api.fetch_timeseries_result(2, "5m", "default")
        self.assertEqual(result.source, "wiki")
        self.assertEqual(result.volume_kind, "executed-trades")
        self.age_cache("ts_2_5m", self.now)
        with mock.patch.object(api, "_get", side_effect=AssertionError("fresh cache expected")):
            self.assertEqual(api.fetch_timeseries(2, "5m", "default"), data)

    def save_result(self, high=100, source='wiki', name='latest', at=None):
        at = self.now if at is None else at
        data = {'2': {'high': high, 'low': 90, 'highTime': at, 'lowTime': at}}
        api._save_cache_result(name, data, 'default', source=source, fetched_at=at,
            last_attempt_at=at, last_success_at=at,
            volume_kind='standing-orders' if source=='ge-tracker' else 'unknown',
            coverage={source:1})
        self.age_cache(name,at)
        return data

    def test_concurrent_refresh_cannot_attach_new_source_to_old_payload(self):
        old = self.save_result()
        original = api._load_cache
        def interleave(name, profile):
            result = original(name, profile)
            self.save_result(high=200, source='ge-tracker')
            return result
        with mock.patch.object(api, '_load_cache', side_effect=interleave):
            result = api._cache_result('latest', 'default', stale=False)
        self.assertEqual(result.data['2']['high'], 200)
        self.assertEqual(result.source, 'ge-tracker')

    def test_stale_attempt_cannot_overwrite_concurrent_success_metadata(self):
        old = self.save_result(at=self.now-api.CACHE_MAX_AGE['latest']-1)
        original = api._read_cache_record
        reads = 0
        def interleave(name, profile):
            nonlocal reads
            reads += 1
            result = original(name, profile)
            if reads == 2: self.save_result(high=200, source='ge-tracker')
            return result
        with mock.patch.object(api, '_read_cache_record', side_effect=interleave):
            api._cache_result('latest', 'default', stale=True, now=self.now)
        raw, metadata, _ = original('latest', 'default')
        self.assertEqual(raw['2']['high'], 200)
        self.assertEqual(metadata['source'], 'ge-tracker')
        self.assertEqual(metadata['last_success_at'], self.now)

    def test_provenance_cannot_claim_tracker_orders_are_executed_trades(self):
        self.save_result(source='ge-tracker')
        path = self.cache/'latest.provenance.json'
        metadata=json.loads(path.read_text());metadata['volume_kind']='executed-trades'
        path.write_text(json.dumps(metadata))
        with self.assertRaises(api.MarketDataError): api._cache_metadata('latest','default')

    def test_unattributed_fallback_does_not_invent_source_or_success_time(self):
        dump={'data':[{'itemId':2,'buying':100,'selling':90,
                      'buyingQuantity':12,'sellingQuantity':9}]}
        with mock.patch.object(api, '_get', return_value=None), \
             mock.patch.object(api, '_get_ge_tracker', return_value=dump):
            result=api.fetch_5m_result('default')
        self.assertEqual(result.source, 'unknown')
        self.assertEqual(result.volume_kind, 'unknown')
        self.assertIsNone(result.last_success_at)

    def test_tracker_stale_result_keeps_original_success_and_orders_semantics(self):
        dump={'data':[{'itemId':2,'buying':100,'selling':90,
                      'buyingQuantity':12,'sellingQuantity':9}]}
        with mock.patch.object(api, '_fetch_url', return_value=dump):
            api._get_ge_tracker('default')
        future = self.now + api.CACHE_MAX_AGE['ge_tracker'] + 1
        with mock.patch.object(api.time,'time',return_value=future), \
             mock.patch.object(api,'_fetch_url',return_value=None), \
             mock.patch.object(api,'_get',return_value=None):
            result=api.fetch_5m_result('default')
        self.assertEqual(result.delivery,'stale-cache')
        self.assertTrue(result.stale)
        self.assertEqual(result.last_success_at,self.now)
        self.assertEqual(result.last_attempt_at,future)
        self.assertEqual(result.volume_kind,'standing-orders')

    def test_invalid_second_snapshot_is_miss_instead_of_unknown_success(self):
        self.save_result()
        original=api._read_cache_record
        reads=0
        def interleave(name, profile):
            nonlocal reads
            reads+=1
            if reads==2: raise api.MarketDataError('changed provenance')
            return original(name, profile)
        with mock.patch.object(api,'_read_cache_record',side_effect=interleave):
            self.assertIsNone(api._cache_result('latest','default',stale=False))

    def test_concurrent_equal_payload_writers_keep_one_authoritative_provider(self):
        data={'2':{'avgHighPrice':100,'avgLowPrice':90,'highPriceVolume':12,'lowPriceVolume':9}}
        original=api._atomic_json
        interleaved=False
        def write(path, value):
            nonlocal interleaved
            original(path,value)
            if not interleaved:
                interleaved=True
                api._save_cache_result('5m',data,'default',source='ge-tracker',
                    fetched_at=self.now,last_attempt_at=self.now,last_success_at=self.now,
                    volume_kind='standing-orders',coverage={'ge-tracker':1})
        with mock.patch.object(api,'_atomic_json',side_effect=write):
            api._save_cache_result('5m',data,'default',source='wiki',
                fetched_at=self.now,last_attempt_at=self.now,last_success_at=self.now,
                volume_kind='executed-trades',coverage={'wiki':1})
        self.age_cache('5m',self.now)
        result=api._cache_result('5m','default',stale=False)
        self.assertEqual(result.source,'ge-tracker')
        self.assertEqual(result.volume_kind,'standing-orders')

    def test_concurrent_fresh_snapshot_is_not_labelled_stale(self):
        self.save_result(at=self.now-api.CACHE_MAX_AGE['latest']-1)
        original=api._load_stale_cache
        def interleave(name, profile):
            result=original(name,profile)
            self.save_result(high=200,source='ge-tracker')
            return result
        with mock.patch.object(api,'_load_stale_cache',side_effect=interleave):
            result=api._cache_result('latest','default',stale=True,now=self.now)
        self.assertEqual(result.data['2']['high'],200)
        self.assertEqual(result.delivery,'fresh-cache')
        self.assertFalse(result.stale)

    def test_legacy_tracker_cache_retains_unknown_source_fresh_and_stale(self):
        dump={'data':[{'itemId':2,'buying':100,'selling':90,
                      'buyingQuantity':12,'sellingQuantity':9}]}
        for stale in (False,True):
            with self.subTest(stale=stale):
                for path in self.cache.glob('*.json'): path.unlink()
                api._save_cache('ge_tracker',dump,'default')
                age=api.CACHE_MAX_AGE['ge_tracker']+1 if stale else 0
                self.age_cache('ge_tracker',self.now-age)
                with mock.patch.object(api,'_get',return_value=None), \
                     mock.patch.object(api,'_fetch_url',return_value=None):
                    result=api.fetch_5m_result('default')
                self.assertIsNotNone(result)
                self.assertEqual(result.source,'unknown')
                self.assertEqual(result.volume_kind,'unknown')
                self.assertIsNone(result.last_success_at)
                self.assertEqual(result.stale,stale)


if __name__ == "__main__":
    unittest.main()
