"""Untrusted provider/cache data cannot become usable market quotes."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from rshelper import api, market, profile


class TestMarketValidation(unittest.TestCase):
    def test_safe_int_nonfinite_exactness(self):
        for value in ('Infinity', '1e309', float('inf'), float('nan'), True, None):
            self.assertEqual(market.safe_int(value, -1), -1)
        number = 2 ** 60 + 1
        self.assertEqual(market.safe_int(number), number)
        self.assertEqual(market.safe_int(str(number)), number)
        self.assertEqual(market.safe_int(str(number) + '.0'), number)

    def test_future_quote_unusable(self):
        from rshelper import trader
        for key in ('highTime', 'lowTime'):
            quote = {'high': 100, 'low': 90, 'highTime': 1000, 'lowTime': 1000}
            quote[key] = 2000
            self.assertEqual(market.price_issue(quote, now=1000), 'future')
            self.assertFalse(trader._fresh(quote, max_age=300, now=1000))

    def test_latest_list_not_cached(self):
        with mock.patch.object(api, '_load_cache', return_value=None), \
                mock.patch.object(api, '_get', return_value={'data': [{'high': 100}]}), \
                mock.patch.object(api, '_get_ge_tracker', return_value=None) as fallback, \
                mock.patch.object(api, '_load_stale_cache', return_value=None), \
                mock.patch.object(api, '_save_cache') as save:
            self.assertIsNone(api.fetch_latest())
        fallback.assert_called_once()
        save.assert_not_called()

    def test_quarantine_closes_descriptor_if_wrapping_fails(self):
        import os
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'latest.json'
            path.write_bytes(b'broken')
            descriptor, scratch = tempfile.mkstemp(dir=tmp)
            try:
                with mock.patch.object(api.tempfile, 'mkstemp', return_value=(descriptor, scratch)), \
                        mock.patch.object(api.os, 'fdopen', side_effect=OSError('fixture')), \
                        mock.patch.object(api.os, 'close', wraps=os.close) as close:
                    api._quarantine_cache(path, 'latest')
                close.assert_called_once_with(descriptor)
            finally:
                try:
                    os.close(descriptor)
                except OSError:
                    pass

    def test_cache_disappearing_during_refresh_is_a_miss(self):
        with tempfile.TemporaryDirectory() as tmp:
            vanished = mock.MagicMock()
            vanished.parent = Path(tmp)
            vanished.exists.return_value = True
            vanished.stat.side_effect = FileNotFoundError('fixture')
            vanished.open.side_effect = FileNotFoundError('fixture')
            with mock.patch.object(api, '_cache_path', return_value=vanished):
                self.assertIsNone(api._load_cache('latest'))
                self.assertIsNone(api._load_stale_cache('latest'))

    def test_bad_cache_cannot_poison_refresh(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(profile, 'CACHE_DIR', Path(tmp)):
            cached = Path(tmp) / 'latest.json'
            cached.write_text('[{"high": 100}]')
            valid = {'2': {'high': 100, 'low': 90, 'highTime': 1000, 'lowTime': 1000}}
            with mock.patch.object(api, '_get', return_value={'data': valid}) as fetch:
                self.assertEqual(api.fetch_latest('default'), valid)
            fetch.assert_called_once()
            self.assertEqual(json.loads(cached.read_text()), valid)

    def test_validator_rejects_roots_and_quarantines_rows(self):
        from rshelper.market_validation import validate_payload, MarketDataError
        for payload in ([], None, True, 'text'):
            with self.assertRaises(MarketDataError):
                validate_payload('latest', payload, now=1000)
        good = {'high': 100, 'low': 90, 'highTime': 1000, 'lowTime': 1000}
        result = validate_payload('latest', {'data': {'2': good, '3': {'high': True},
                 '4': {**good, 'lowTime': 2000}, '5': {**good, 'high': 2**100}}}, now=1000)
        self.assertEqual(result['data'], {'2': good})
        self.assertEqual(result['rejected'], 3)

    def test_oversized_response_rejected_before_decode(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'x' * 17
        with mock.patch.object(api, 'MAX_RESPONSE_BYTES', 16), \
                mock.patch.object(api.urllib.request, 'urlopen', return_value=response), \
                mock.patch.object(api.json, 'loads') as decode:
            self.assertIsNone(api._fetch_url('https://fixture.invalid', retries=0))
        decode.assert_not_called()

    def test_overflowing_json_and_nonfinite_extensions_fail_closed(self):
        for raw in (b'{"n":' + b'9' * 5000 + b'}', b'{"extension":1e309}'):
            response = mock.MagicMock()
            response.__enter__.return_value.read.return_value = raw
            with mock.patch.object(api.urllib.request, 'urlopen', return_value=response):
                self.assertIsNone(api._fetch_url('https://fixture.invalid', retries=0))

    def test_untrusted_item_key_formats_rejected(self):
        from rshelper.market_validation import validate_payload
        quote = {'high': 100, 'low': 90}
        bad = ('../secret', '-1', '1.0', '2e0', '００２', '2' * 100, '02')
        payload = {'2': quote, **{key: quote for key in bad}}
        result = validate_payload('latest', payload, 1000)
        self.assertEqual(result, {'data': {'2': quote}, 'rejected': len(bad)})

    def test_endpoint_shapes_and_optional_nulls(self):
        from rshelper.market_validation import validate_payload, MarketDataError
        good_mapping = {'id': 2, 'name': 'Fixture', 'members': False, 'limit': None}
        good_volume = {'avgHighPrice': None, 'avgLowPrice': 100,
                       'highPriceVolume': 0, 'lowPriceVolume': 20}
        fixtures = {
            'mapping': ([good_mapping, {**good_mapping, 'id': True}], [good_mapping]),
            '5m': ({'2': good_volume, '3': {**good_volume, 'lowPriceVolume': float('nan')}}, {'2': good_volume}),
            'timeseries': ([{**good_volume, 'timestamp': 1000}, {**good_volume, 'timestamp': 2000}], [{**good_volume, 'timestamp': 1000}]),
            'ge_tracker': ([{'itemId': 2, 'buying': 100}, {'itemId': 3, 'selling': float('inf')}], [{'itemId': 2, 'buying': 100}]),
        }
        for endpoint, (raw, expected) in fixtures.items():
            with self.subTest(endpoint=endpoint):
                result = validate_payload(endpoint, raw, 1000)
                self.assertEqual(result, {'data': expected, 'rejected': 1})
                with self.assertRaises(MarketDataError):
                    validate_payload(endpoint, {} if isinstance(raw, list) else [], 1000)
        self.assertEqual(validate_payload('latest', {'2': {'high': None, 'low': None}}, 1000)['rejected'], 0)
        for key in ('highTime', 'lowTime'):
            row = {'high': 100, 'low': 90, 'highTime': 1000, 'lowTime': 1000}
            row[key] = 1060
            self.assertEqual(validate_payload('latest', {'2': row}, 1000)['rejected'], 0)
            row[key] = 1061
            self.assertEqual(validate_payload('latest', {'2': row}, 1000)['rejected'], 1)

    def test_rejected_primary_preserves_last_cache_and_fallback_order(self):
        import os
        from rshelper.market_validation import validate_payload
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(profile, 'CACHE_DIR', Path(tmp)):
            cached = Path(tmp) / 'latest.json'
            valid = {'2': {'high': 100, 'low': 90, 'highTime': 1000, 'lowTime': 1000}}
            cached.write_text(json.dumps(valid))
            original = cached.read_bytes()
            os.utime(cached, (1000, 1000))
            calls = []
            with mock.patch.object(api.time, 'time', return_value=1200), \
                    mock.patch.object(api, '_get', side_effect=lambda _: calls.append('primary') or []), \
                    mock.patch.object(api, '_get_ge_tracker', side_effect=lambda _: calls.append('fallback')):
                self.assertEqual(api.fetch_latest('default'), valid)
            self.assertEqual(calls, ['primary', 'fallback'])
            self.assertEqual(cached.read_bytes(), original)

    def test_bad_encoding_and_deep_json_fail_closed(self):
        for raw in (b'\xff\xfe\xff', b'[' * 2000 + b']' * 2000):
            response = mock.MagicMock()
            response.__enter__.return_value.read.return_value = raw
            with mock.patch.object(api.urllib.request, 'urlopen', return_value=response):
                self.assertIsNone(api._fetch_url('https://fixture.invalid', retries=0))


if __name__ == '__main__':
    unittest.main()
