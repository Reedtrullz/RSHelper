import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from rshelper import profile, readiness
from rshelper.market_data import MarketDataResult


class ReadinessTest(unittest.TestCase):
    def test_invalid_authority_and_future_cycle_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(profile, 'CONFIG_DIR', Path(folder)):
            root = Path(folder)
            source = MarketDataResult({}, 'wiki', 'network', 100, 100, 100,
                                      False, 'executed-trades', {})
            sources = {'latest': source, '5m': source}
            (root/'identity-activation.json').write_text('{"financial_authority":1}')
            with self.assertRaises(ValueError):
                readiness.status('default', sources=sources, now=110)
            (root/'identity-activation.json').write_text('{"financial_authority":true}')
            (root/'trader_state.json').write_text('{"last_success_iso":"2099-01-01T00:00:00Z"}')
            self.assertIn('cycle:trader', readiness.status('default', sources=sources, now=110)['reasons'])
    def test_private_http_readiness_and_public_health_are_separate(self):
        from http.server import ThreadingHTTPServer
        import http.client
        import threading
        from rshelper.dashboard.handlers import make_handler
        from rshelper.scanner import FlipScanner
        handler = make_handler(FlipScanner(), lambda: [], owner_token='a'*64,
            readiness_fn=lambda: {'ready': False, 'status': 'degraded', 'reasons': ['source:latest']})
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            for auth, expected in (({}, 401), ({'Authorization': 'Bearer '+'a'*64}, 200)):
                connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=2)
                connection.request('GET', '/api/readiness', headers=auth)
                response = connection.getresponse()
                self.assertEqual(response.status, expected)
                payload = json.loads(response.read())
                if expected == 200:
                    self.assertFalse(payload['ready'])
                connection.close()
            with mock.patch('rshelper.release.health_metadata', return_value={'status':'healthy', 'version':'synthetic'}):
                connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=2)
                connection.request('GET', '/api/health')
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read())['status'], 'healthy')
                connection.close()
        finally:
            server.shutdown(); server.server_close(); thread.join(2)
    def test_stalled_source_degrades_without_private_records(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(profile, 'CONFIG_DIR', Path(folder)):
            source = MarketDataResult({'private-holding': 123}, 'wiki', 'network', 100, 100, 100,
                                      False, 'executed-trades', {'wiki': 1})
            result = readiness.status('default', sources={'latest': source, '5m': source}, now=500)
            self.assertFalse(result['ready'])
            self.assertIn('source:latest', result['reasons'])
            self.assertNotIn('private-holding', json.dumps(result))
            self.assertEqual(result['sources']['latest']['last_success_at'], 100)

    def test_successful_cycle_and_exact_sync_then_stalled_or_failed(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(profile, 'CONFIG_DIR', Path(folder)):
            root = Path(folder)
            (root/'identity-activation.json').write_text(json.dumps({'financial_authority': True}))
            (root/'trader_state.json').write_text(json.dumps({'last_cycle_iso': '1970-01-01T00:01:40+00:00',
                'last_success_iso': '1970-01-01T00:01:40+00:00', 'last_result': {'holdings': 'secret'}, 'errors': 0}))
            readiness.record_sync('default', {'status': 'no_op', 'applied_revision': 4,
                                    'applied_hash': 'a'*64}, now=100)
            receipt = {'schema_version': 1,
                       'profile_uuid': '11111111-1111-4111-8111-111111111111',
                       'origin_uuid': '22222222-2222-4222-8222-222222222222',
                       'status': 'applied', 'requested_revision': 4, 'requested_hash': 'a'*64,
                       'applied_revision': 4, 'applied_hash': 'a'*64}
            metadata = {'schema_version': 1, 'outgoing': None,
                        'receipts': {receipt['origin_uuid']: receipt}}
            (root/'replication-state.json').write_text(json.dumps(metadata))
            source = MarketDataResult({}, 'wiki', 'fresh-cache', 100, 100, 100,
                                      False, 'executed-trades', {})
            sources = {'latest': source, '5m': source}
            result = readiness.status('default', sources=sources, now=110)
            self.assertTrue(result['ready'])
            self.assertEqual(result['sync']['status'], 'no_op')
            self.assertEqual(result['sync']['applied_revision'], 4)
            self.assertTrue(result['sync']['exact_revision'])
            self.assertNotIn('secret', json.dumps(result))
            self.assertFalse(readiness.status('default', sources=sources, now=2200)['ready'])
            receipt['applied_hash'] = 'b'*64
            (root/'replication-state.json').write_text(json.dumps(metadata))
            self.assertIn('sync:revision-mismatch', readiness.status('default', sources=sources, now=110)['reasons'])
            readiness.record_sync('default', {'status': 'conflict'}, now=115)
            self.assertIn('sync:conflict', readiness.status('default', sources=sources, now=120)['reasons'])


if __name__ == '__main__':
    unittest.main()
