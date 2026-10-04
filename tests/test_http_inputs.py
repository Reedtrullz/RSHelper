"""Exercise input boundaries over real loopback HTTP, never live state."""
import json
import errno
import http.client
from pathlib import Path
import socket
import sys
import threading
import time
import unittest
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from rshelper.dashboard.handlers import make_handler
from rshelper.scanner import FlipScanner


class HttpInputsTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        def callback(*args):
            self.calls.append(args)
            return {'ok': True}
        handler = make_handler(FlipScanner(), lambda: [], owner_token='a'*64,
            control=True, paper_trade_fn=callback, log_trade_fn=callback,
            watchlist_update_fn=callback, close_position_fn=callback,
            trader_control_fn=callback, monitor_control_fn=callback,
            ge_collect_fn=callback, alerts_read_fn=callback,
            delete_trade_fn=callback, price_lookup=callback, confidence_fn=callback,
            timeseries_fn=callback)
        handler.body_read_timeout = .3
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2)

    def request(self, path='/api/paper', body=b'', *, method='POST', framing=None,
                half_close=True, drip=False, authenticated=True):
        headers = ['Host: localhost', 'Connection: close']
        if authenticated: headers.append('Authorization: Bearer ' + 'a'*64)
        if method == 'POST':
            headers.extend([f'Content-Length: {len(body)}'] if framing is None else framing)
        with socket.create_connection(self.server.server_address, timeout=2) as client:
            client.settimeout(1.5)
            client.sendall((f'{method} {path} HTTP/1.1\r\n' + '\r\n'.join(headers) + '\r\n\r\n').encode('ascii'))
            if drip:
                stop = threading.Event()
                def send_slowly():
                    while not stop.wait(.05):
                        try: client.sendall(b' ')
                        except OSError: return
                sender = threading.Thread(target=send_slowly, daemon=True); sender.start()
            else:
                client.sendall(body)
            if half_close:
                try: client.shutdown(socket.SHUT_WR)
                except OSError as exc:
                    if exc.errno != errno.ENOTCONN: raise
            raw = b''
            try:
                while True:
                    part = client.recv(65536)
                    if not part: break
                    raw += part
                    # HTTP completion is Content-Length, not TCP EOF. A server
                    # closing a deadline-aborted request may reset the socket if
                    # the dripping sender has already written additional bytes.
                    if b'\r\n\r\n' in raw:
                        head, payload = raw.split(b'\r\n\r\n', 1)
                        response_headers = dict(line.lower().split(': ', 1) for line in
                            head.decode('ascii').split('\r\n')[1:])
                        if len(payload) >= int(response_headers['content-length']): break
            finally:
                if drip: stop.set(); sender.join(timeout=1)
        head, payload = raw.split(b'\r\n\r\n', 1)
        lines = head.decode('ascii').split('\r\n')
        headers = dict(line.lower().split(': ', 1) for line in lines[1:])
        self.assertIn('application/json', headers['content-type'])
        self.assertEqual(int(headers['content-length']), len(payload))
        return int(lines[0].split()[1]), json.loads(payload)

    def assert_error(self, status, payload, expected=None):
        self.assertGreaterEqual(status, 400)
        if expected: self.assertEqual(status, expected)
        self.assertIs(payload['ok'], False)
        self.assertTrue(payload['code']); self.assertTrue(payload['message'])

    def test_invalid_body_never_calls_mutator(self):
        valid = b'{"action":"open","item":"nature rune","qty":5}'
        cases = [(valid, []), (valid, ['Content-Length: -1']),
                 (valid, ['Content-Length: nope']),
                 (valid, ['Content-Length: 65537']),
                 (valid, [f'Content-Length: {len(valid)}', f'Content-Length: {len(valid)}']),
                 (valid, [f'Content-Length: {len(valid)}', 'Transfer-Encoding: chunked']),
                 (b'[]', None), (b'{', None),
                 (b'{"action":"open","item":"nature rune","qty":"5"}', None),
                 (b'{"action":"open","item":"nature rune","qty":true}', None),
                 (b'{"action":"open","item":"nature rune","qty":1.5}', None),
                 (b'{"action":"open","item":"nature rune","qty":NaN}', None),
                 (b'{"action":"open","action":"instant","item":"x","qty":1}', None),
                 (b'{"action":"open","item":"x","qty":1,"extra":' + b'['*70 + b'0' + b']'*70 + b'}', None)]
        for body, framing in cases:
            with self.subTest(body=body[:50], framing=framing):
                status, payload = self.request(body=body, framing=framing)
                self.assert_error(status, payload)
                self.assertEqual(self.calls, [])

    def test_valid_browser_payload_and_operation_types(self):
        status, payload = self.request(body=b'{"action":"open","item":"nature rune","qty":5}')
        self.assertEqual(status, 200); self.assertTrue(payload['ok'])
        self.assertEqual(self.calls, [('open', 'nature rune', 5)])
        self.calls.clear()
        invalid = [('/api/ge/collect', {'position_id': True}),
                   ('/api/trades/delete', {'trade_id': -1}),
                   ('/api/watchlist', {'action': 'add', 'item_id': '2'}),
                   ('/api/watchlist', {'action': 'alerts', 'item_id': 2, 'alert_above': -1}),
                   ('/api/positions', {'action': 'close', 'position_id': 1, 'qty': 0}),
                   ('/api/trader', {'action': []}),
                   ('/api/monitor', {'action': 'restart'}),
                   ('/api/alerts/read', {'all': 'false'}),
                   ('/api/alerts/read', {'ids': [1, 1]}),
                   ('/api/trades', {'item_id': 2, 'name': 'x', 'qty': True, 'buy_price': 5, 'sell_price': 6}),
                   ('/api/trades', {'item_id': 2, 'name': [], 'qty': 1, 'buy_price': 5, 'sell_price': 6})]
        for path, data in invalid:
            with self.subTest(path=path, data=data):
                self.assert_error(*self.request(path, json.dumps(data).encode()))
                self.assertEqual(self.calls, [])

    def test_keepalive_uses_each_requests_body(self):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=2)
        try:
            for qty in (5, 7):
                connection.request('POST', '/api/paper',
                    json.dumps({'action': 'open', 'item': 'nature rune', 'qty': qty}),
                    {'Authorization': 'Bearer '+'a'*64, 'Host': 'localhost'})
                response = connection.getresponse()
                self.assertEqual(response.status, 200); response.read()
            self.assertEqual(self.calls, [('open', 'nature rune', 5), ('open', 'nature rune', 7)])
        finally: connection.close()

    def test_query_batches_are_bounded_and_unambiguous(self):
        for query in ('ids=1,1', 'ids=0', 'ids=-1', 'ids=2,nope', 'ids=2&ids=3',
                      'ids=' + ','.join(map(str, range(1, 102))), 'ids=2&x=' + 'a'*4096):
            with self.subTest(query=query[:60]):
                self.assert_error(*self.request('/api/prices?' + query, method='GET'))
                self.assertEqual(self.calls, [])
        for query in ('id=0', 'id=2&points=0', 'id=2&points=1001', 'id=2&step=bad'):
            self.assert_error(*self.request('/api/timeseries?' + query, method='GET'))
            self.assertEqual(self.calls, [])

    def test_api_errors_are_json_including_auth_and_methods(self):
        for method, path, auth, expected in [('GET', '/api/missing', True, 404),
                ('GET', '/api/prices?ids=2', False, 401), ('PATCH', '/api/paper', True, 501)]:
            self.assert_error(*self.request(path, method=method, authenticated=auth), expected)

    def test_slow_and_dripping_bodies_have_absolute_deadline(self):
        for drip in (False, True):
            with self.subTest(drip=drip):
                start = time.monotonic()
                self.assert_error(*self.request(body=b'{', framing=['Content-Length: 100'],
                                                half_close=False, drip=drip), 408)
                self.assertLess(time.monotonic() - start, 1.2)
                self.assertEqual(self.calls, [])


if __name__ == '__main__': unittest.main()
