"""Concurrent market publication and bounded event-consumer contracts."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import json
import http.client
import io
from pathlib import Path
import queue
import sys
import threading
import tracemalloc
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from rshelper.config import Config
from rshelper.dashboard import server
from rshelper.market_data import MarketDataResult, MarketList, market_payload
from rshelper.models import Item
from rshelper.dashboard.handlers import make_handler
from rshelper.scanner import FlipScanner
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class EventBudgetTest(unittest.TestCase):
    def test_maximum_queued_payload_memory_is_bounded(self):
        tracemalloc.start()
        try:
            hub = server.EventHub()
            consumers = [queue.Queue(maxsize=8) for _ in range(16)]
            for consumer in consumers:
                hub.subscribe(consumer)
                consumer.get_nowait()
            for revision in range(8):
                hub.broadcast('refresh', {'revision': revision, 'fixture': 'x' * 16000})
            _, peak = tracemalloc.get_traced_memory()
            self.assertLess(peak, 512 * 1024)
            self.assertTrue(all(consumer.qsize() == 8 for consumer in consumers))
            print('SSE fixture peak bytes:', peak)
            hub.close()
        finally:
            tracemalloc.stop()

    def test_http_capacity_reconnect_and_shutdown_release_subscribers(self):
        hub = server.EventHub()
        handler = make_handler(FlipScanner(), lambda: [], event_hub=hub,
                               owner_token='synthetic-owner')
        http_server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        worker = threading.Thread(target=http_server.serve_forever, daemon=True)
        worker.start()
        connections = []
        response = None
        try:
            for _ in range(16):
                connection = http.client.HTTPConnection('127.0.0.1', http_server.server_port, timeout=3)
                connections.append(connection)
                connection.request('GET', '/api/events', headers={'Authorization': 'Bearer synthetic-owner'})
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.readline(), b'event: refresh\n')
                self.assertIn(b'"revision": 0', response.readline())
                response.readline()
            extra = http.client.HTTPConnection('127.0.0.1', http_server.server_port, timeout=3)
            connections.append(extra)
            extra.request('GET', '/api/events', headers={'Authorization': 'Bearer synthetic-owner'})
            self.assertEqual(extra.getresponse().status, 503)
            hub.close()
            self.assertIsNotNone(response)
            assert response is not None
            self.assertEqual(response.readline(), b'event: shutdown\n')
            response.readline()
            response.readline()
            self.assertEqual(response.readline(), b'')
            self.assertEqual(hub._subscribers, [])
        finally:
            hub.close()
            for connection in connections:
                connection.close()
            http_server.shutdown()
            http_server.server_close()
            worker.join(timeout=3)
            self.assertFalse(worker.is_alive())

    def test_overflow_disconnects_with_current_revision_and_bounded_queue(self):
        hub = server.EventHub()
        consumer = queue.Queue(maxsize=8)
        self.assertTrue(hub.subscribe(consumer))
        for revision in range(1, 30):
            hub.broadcast('refresh', {'revision': revision})
        messages = []
        while not consumer.empty():
            messages.append(consumer.get_nowait())
        self.assertTrue(any('event: resync' in message for message in messages))
        self.assertLessEqual(len(messages), 8)
        self.assertEqual(len(hub._subscribers), 0)
        reconnect = queue.Queue(maxsize=8)
        self.assertTrue(hub.subscribe(reconnect))
        self.assertEqual(json.loads(reconnect.get_nowait().split('data: ')[1])['revision'], 29)

    def test_ceiling_unbounded_queue_and_shutdown(self):
        hub = server.EventHub()
        self.assertFalse(hub.subscribe(queue.Queue()))
        consumers = [queue.Queue(maxsize=8) for _ in range(16)]
        for consumer in consumers:
            self.assertTrue(hub.subscribe(consumer))
        self.assertFalse(hub.subscribe(queue.Queue(maxsize=8)))
        hub.close()
        self.assertEqual(len(hub._subscribers), 0)
        self.assertFalse(hub.subscribe(queue.Queue(maxsize=8)))
        for consumer in consumers:
            self.assertTrue(any('event: shutdown' in consumer.get_nowait()
                                for _ in range(consumer.qsize())))

    def test_prefilled_consumer_is_rejected_without_leaking_a_slot(self):
        hub = server.EventHub()
        consumer = queue.Queue(maxsize=1)
        consumer.put_nowait('existing')
        self.assertFalse(hub.subscribe(consumer))
        self.assertEqual(hub._subscribers, [])

    def test_disconnecting_clients_keep_capacity_until_handler_cleanup(self):
        hub = server.EventHub()
        consumers = [queue.Queue(maxsize=8) for _ in range(16)]
        for consumer in consumers:
            hub.subscribe(consumer)
        for revision in range(9):
            hub.broadcast('refresh', {'revision': revision})
        self.assertEqual(hub._subscribers, [])
        self.assertEqual(len(hub._closing), 16)
        self.assertFalse(hub.subscribe(queue.Queue(maxsize=8)))
        for consumer in consumers:
            hub.unsubscribe(consumer)
        self.assertEqual(hub._closing, [])
        self.assertTrue(hub.subscribe(queue.Queue(maxsize=8)))

    def test_oversized_event_disconnects_and_drops_its_payload(self):
        hub = server.EventHub()
        consumer = queue.Queue(maxsize=8)
        hub.subscribe(consumer)
        hub.broadcast('alert', {'message': 'x' * 20000})
        self.assertEqual(hub._subscribers, [])
        payload = consumer.get_nowait()
        self.assertIn('event-too-large', payload)
        self.assertLess(len(payload), hub.MAX_EVENT_BYTES)


class MarketGenerationTest(unittest.TestCase):
    def test_empty_scan_http_response_preserves_revision_and_provenance(self):
        items = MarketList()
        items.market_revision = 7
        items.snapshot_provenance = {'latest': {'source': 'ge-tracker', 'delivery': 'network'}}
        handler = make_handler(FlipScanner(), lambda: items, mode='public-demo')
        request = BaseHTTPRequestHandler.__new__(handler)
        request.path = '/api/scan'
        request.command = 'GET'
        request.headers = {}
        request.wfile = io.BytesIO()
        request.send_response = lambda *a: None
        request.send_header = lambda *a: None
        request.end_headers = lambda: None
        request.do_GET()
        body = json.loads(request.wfile.getvalue())
        self.assertEqual(body['market_revision'], 7)
        self.assertEqual(body['market_data'], items.snapshot_provenance)
        self.assertEqual(body['items'], [])

    def test_failed_refresh_retains_revision_and_inputs_cannot_mutate_publication(self):
        now = [1000.0]
        callbacks = {}
        source_items = [Item(1, 'Synthetic', False, 100, 0, 100, 120, volume=100)]
        class HttpServer:
            def __init__(self, *args):
                pass
            def serve_forever(inner):
                source_items[0].name = 'changed input'
                first = callbacks['scan_items']()
                self.assertEqual(first[0].name, 'Synthetic')
                first[0].name = 'changed output'
                now[0] = 1121.0
                second = callbacks['scan_items']()
                self.assertEqual(second[0].name, 'Synthetic')
                self.assertEqual(first.market_revision, second.market_revision)
                self.assertEqual(callbacks['meta_fn']()['last_fetch'], 1000.0)
                self.assertEqual(callbacks['meta_fn']()['market_revision'], first.market_revision)
                now[0] = 1242.0
                third = callbacks['scan_items']()
                self.assertEqual(third.market_revision, first.market_revision)
                self.assertEqual(third[0].name, 'Synthetic')
            def server_close(self):
                pass
        def handler(*args, **kwargs):
            callbacks['scan_items'] = args[1]
            callbacks.update(kwargs)
            return object
        with ExitStack() as stack:
            for target, name, value in ((server, 'load_config', lambda *a: Config()),
                    (server, '_fetch_bootstrap', mock.Mock(side_effect=[([], {}, {}, source_items), SystemExit(1), (None, {}, {}, [])])),
                    (server, 'ThreadingHTTPServer', HttpServer), (server, 'make_handler', handler),
                    (server, 'detect_signals', lambda *a, **k: []),
                    (server.time, 'time', lambda: now[0])):
                stack.enter_context(mock.patch.object(target, name, value))
            stack.enter_context(mock.patch('rshelper.tuning.record_if_changed'))
            stack.enter_context(mock.patch('rshelper.journal.list_trades', return_value=[]))
            stack.enter_context(mock.patch.object(server.watchlist, 'load', return_value={'items': {}}))
            stack.enter_context(mock.patch.object(server.alerts, 'push_alert'))
            stack.enter_context(mock.patch.object(server.alerts, 'unread_count', return_value=0))
            server.run(port=0, owner_token='a' * 64)

    def test_interleaved_signal_read_keeps_items_and_volume_from_one_generation(self):
        entered, release = threading.Event(), threading.Event()
        armed = [False]
        now = [1000.0]
        callbacks = {}
        observed = []
        class PausingItems(list[Item]):
            def __iter__(self):
                values = list(super().__iter__())
                if armed[0]:
                    entered.set()
                    if not release.wait(3):
                        raise AssertionError('owned reader did not resume')
                return iter(values)
        class HttpServer:
            def __init__(self, *args):
                pass
            def serve_forever(self):
                armed[0] = True
                with ThreadPoolExecutor(max_workers=1) as pool:
                    pending = pool.submit(callbacks['signal_detector'])
                    try:
                        if not entered.wait(3):
                            raise AssertionError('reader fixture did not enter')
                        now[0] = 1121.0
                        callbacks['scan_items']()
                    finally:
                        armed[0] = False
                        release.set()
                    pending.result(timeout=3)
            def server_close(self):
                pass
        def bootstrap(generation):
            items = [Item(generation, 'Synthetic', False, 100, 0, 100, 120, volume=100)]
            if generation == 1:
                items = PausingItems(items)
            volume = market_payload(MarketDataResult({'generation': generation}, 'wiki', 'network',
                now[0], now[0], now[0], False, 'executed-trades', {'wiki': 1}))
            return [], {}, volume, items
        def signals(items, volume, **kwargs):
            observed.append((items[0].id, volume['generation']))
            return []
        def handler(*args, **kwargs):
            callbacks['scan_items'] = args[1]
            callbacks.update(kwargs)
            return object
        with ExitStack() as stack:
            for target, name, value in ((server, 'load_config', lambda *a: Config()),
                    (server, '_fetch_bootstrap', mock.Mock(side_effect=[bootstrap(1), bootstrap(2)])),
                    (server, 'ThreadingHTTPServer', HttpServer),
                    (server, 'make_handler', handler), (server, 'detect_signals', signals),
                    (server.time, 'time', lambda: now[0])):
                stack.enter_context(mock.patch.object(target, name, value))
            stack.enter_context(mock.patch('rshelper.tuning.record_if_changed'))
            stack.enter_context(mock.patch.object(server.watchlist, 'load', return_value={'items': {}}))
            stack.enter_context(mock.patch.object(server, '_alert_to_dict', return_value={}))
            stack.enter_context(mock.patch.object(server.alerts, 'push_alert'))
            server.run(port=0, owner_token='a' * 64)
        self.assertEqual(observed, [(1, 1)], 'a read must never pair old items with new volume')


if __name__ == '__main__':
    unittest.main()
