import io
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from rshelper import api


class SlowHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/headers':
            time.sleep(.8)
        self.send_response(200)
        self.send_header('Content-Length', '1000')
        self.end_headers()
        try:
            for _ in range(100):
                self.wfile.write(b' '); self.wfile.flush(); time.sleep(.03)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, format, *args):
        pass


class DeadlineTest(unittest.TestCase):
    def test_fallback_shares_overall_budget_and_preserves_stale_cache(self):
        import json
        import os
        server = ThreadingHTTPServer(('127.0.0.1', 0), SlowHandler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            with tempfile.TemporaryDirectory() as folder, \
                 mock.patch.object(api, 'CACHE_DIR', Path(folder)), \
                 mock.patch.object(api, '_cache_path', side_effect=lambda name, profile=None: Path(folder)/(name+'.json')), \
                 mock.patch.object(api, 'PROVIDER_TIMEOUT', .2), \
                 mock.patch.object(api, 'ACQUISITION_TIMEOUT', .32), \
                 mock.patch.object(api, 'REQUEST_INTERVAL', .01):
                now = time.time()
                data = {'2': {'high':100, 'low':90, 'highTime':now, 'lowTime':now}}
                api._save_cache_result('latest', data, 'default', source='wiki',
                    fetched_at=now-130, last_attempt_at=now-130, last_success_at=now-130,
                    volume_kind='unknown', coverage={'wiki':1})
                cache = Path(folder)/'latest.json'
                os.utime(cache, (now-130, now-130))
                os.utime(api._provenance_path('latest', 'default'), (now-130, now-130))
                before = cache.read_bytes()
                url = f'http://127.0.0.1:{server.server_port}'
                with mock.patch.object(api, '_get', side_effect=lambda path: api._fetch_url(url+'/headers', retries=0)), \
                     mock.patch.object(api, '_get_ge_tracker', side_effect=lambda profile: api._fetch_url(url+'/body', retries=0)):
                    started = time.monotonic()
                    result = api.fetch_latest_result('default')
                    self.assertLess(time.monotonic()-started, .6)
                self.assertTrue(result.stale)
                self.assertEqual(result.source, 'wiki')
                self.assertEqual(result.last_success_at, now-130)
                self.assertEqual(cache.read_bytes(), before)
                self.assertEqual(json.loads(cache.read_bytes()), data)
                time.sleep(.4)
        finally:
            server.shutdown(); server.server_close(); thread.join(2)

    def test_slow_stream_and_headers_bound_caller(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), SlowHandler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            for path in ('/body', '/headers'):
                with self.subTest(path=path), tempfile.TemporaryDirectory() as folder, \
                     mock.patch.object(api, 'CACHE_DIR', Path(folder)), \
                     mock.patch.object(api, 'PROVIDER_TIMEOUT', .2, create=True), \
                     mock.patch.object(api, 'REQUEST_INTERVAL', .01), \
                     mock.patch('sys.stderr', new_callable=io.StringIO) as errors, \
                     mock.patch('sys.stdout', new_callable=io.StringIO) as output:
                    started = time.monotonic()
                    self.assertIsNone(api._fetch_url(f'http://127.0.0.1:{server.server_port}{path}', retries=0))
                    self.assertLess(time.monotonic() - started, .6)
                    self.assertIn('deadline', errors.getvalue())
                    self.assertEqual(output.getvalue(), '')
                    time.sleep(.3)
            time.sleep(.9)
        finally:
            server.shutdown(); server.server_close(); thread.join(2)

    def test_shared_lock_wait_is_bounded(self):
        with tempfile.TemporaryDirectory() as folder, \
             mock.patch.object(api, 'CACHE_DIR', Path(folder)), \
             mock.patch.object(api, 'PROVIDER_TIMEOUT', .15), \
             mock.patch.object(api.urllib.request, 'urlopen') as fetch:
            with api._locked_request_budget():
                started = time.monotonic()
                self.assertIsNone(api._fetch_url('http://localhost/unused'))
                self.assertLess(time.monotonic() - started, .5)
            fetch.assert_not_called()

    def test_retry_after_does_not_dispatch_past_deadline(self):
        from urllib.error import HTTPError
        from email.message import Message
        from types import SimpleNamespace
        headers = Message(); headers['Retry-After'] = '60'
        clock=[100.0]
        def sleep(delay):clock[0]+=delay
        virtual=SimpleNamespace(monotonic=lambda:clock[0],time=time.time,sleep=sleep)
        with tempfile.TemporaryDirectory() as folder, \
             mock.patch.object(api, 'CACHE_DIR', Path(folder)), \
             mock.patch.object(api,'time',virtual), \
             mock.patch.object(api,'_ACQUISITION',SimpleNamespace(end=100.15,context={},cache_dir=Path(folder))), \
             mock.patch.object(api.urllib.request, 'urlopen', side_effect=
                 HTTPError('http://localhost', 503, 'fixture', headers, None)) as fetch:
            # Retry policy uses virtual time; slow fsync must not consume its first dispatch.
            with self.assertRaises(api.ProviderDeadline):api._fetch_url_attempts('http://localhost/unused',3)
            self.assertAlmostEqual(clock[0],100.15)
            self.assertEqual(fetch.call_count, 1)
            state = __import__('json').loads((Path(folder)/'.throttle').read_text())
            self.assertGreater(state['blocked_until'], time.time()+50)


if __name__ == '__main__':
    unittest.main()
