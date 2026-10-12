"""One-snapshot summaries and revision-bound Activity pages."""
from dataclasses import asdict
import json
import io
from pathlib import Path
import sys
import unittest
from unittest import mock
from time import perf_counter
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from rshelper import history, journal
from rshelper.dashboard.handlers import make_handler
from rshelper.scanner import FlipScanner
from rshelper.dashboard import server
from rshelper.config import Config
from contextlib import ExitStack


def trades(count):
    return [journal.Trade(i + 1, i % 10 + 1, 'Synthetic', 1, 100, 120, 2, 18,
                         '2026-10-12T00:00:00Z', note='paper',
                         strategy='auto' if i % 2 else 'manual') for i in range(count)]


class ActivityPagesTest(unittest.TestCase):
    def test_history_loads_one_journal_snapshot(self):
        raw = [asdict(trade) for trade in trades(10)]
        with mock.patch.object(journal, '_load', return_value=raw) as load, \
             mock.patch.object(history.tuning, 'load_entries', return_value=[]), \
             mock.patch.object(history.snapshot, 'list_snapshots', return_value=[]):
            result = history.build_history()
        self.assertEqual(result['summary']['total_profit'], 180)
        self.assertEqual(load.call_count, 1)

    def test_summary_preserves_legacy_equal_time_drawdown(self):
        rows = trades(12)
        for row in rows:
            row.profit = {2: -7, 3: 5, 10: -7}.get(row.id, 0)
        with mock.patch.object(journal, 'list_trades', return_value=rows):
            summary = journal.compute_pnl()
        self.assertEqual(summary.max_drawdown, 9)

    def test_large_snapshots_have_identical_economics_and_bounded_pages(self):
        for count in (1000, 25000, 100000):
            with self.subTest(count=count):
                rows = trades(count)
                started = perf_counter()
                old_bytes = len(json.dumps({'trades': [asdict(row) for row in rows], 'count': count}))
                before_seconds = perf_counter() - started
                started = perf_counter()
                summary = journal.summarize_trades(rows, {})
                page = journal.page_trades(rows, revision='revision1', limit=100)
                self.assertEqual(summary.total_profit, count * 18)
                self.assertEqual(summary.total_tax_paid, count * 2)
                self.assertEqual(summary.total_cost_basis, count * 100)
                self.assertEqual(page['filtered_count'], count)
                self.assertEqual(len(page['trades']), 100)
                self.assertLess(len(json.dumps(page)), 60000)
                print(json.dumps({'rows': count, 'full_trade_response_bytes': old_bytes,
                                  'page_bytes': len(json.dumps(page)), 'serialize_full_sec': before_seconds,
                                  'summary_and_page_sec': perf_counter() - started}))

    def test_equal_timestamps_have_no_page_duplicates_or_omissions(self):
        rows = trades(123)
        cursor = None
        seen = []
        while True:
            page = journal.page_trades(rows, revision='same', cursor=cursor, limit=17)
            seen.extend(row['id'] for row in page['trades'])
            cursor = page['next_cursor']
            if not cursor:
                break
        self.assertEqual(len(seen), 123)
        self.assertEqual(set(seen), set(range(1, 124)))
        self.assertEqual(len(set(seen)), len(seen))

    def test_changed_revision_and_filters_require_explicit_restart(self):
        rows = trades(12)
        first = journal.page_trades(rows, revision='old', limit=5)
        changed = journal.page_trades(rows, revision='new', cursor=first['next_cursor'], limit=5)
        self.assertTrue(changed['restart'])
        self.assertEqual(changed['trades'], [])
        filtered = journal.page_trades(rows, revision='old', cursor=first['next_cursor'],
                                       limit=5, filters={'strategy': 'auto'})
        self.assertTrue(filtered['restart'])

    def test_legacy_duplicate_keys_do_not_repeat_pages(self):
        rows = trades(7)
        for row in rows:
            row.id = 1
        cursor, seen = None, []
        for _ in range(4):
            page = journal.page_trades(rows, revision='same', cursor=cursor, limit=2)
            seen.extend(page['trades'])
            cursor = page['next_cursor']
        self.assertEqual(len(seen), 7)
        self.assertIsNone(cursor)

    def test_maximum_date_filter_is_valid(self):
        page = journal.page_trades(trades(1), revision='same',
                                  filters={'until': '9999-12-31'})
        self.assertEqual(page['filtered_count'], 1)

    def test_preloaded_summary_honors_its_filters(self):
        rows = trades(4)
        self.assertEqual(journal.compute_pnl(strategy='auto', trades=rows).trade_count, 2)
        self.assertEqual(sum(row.trade_count for row in journal.compute_pnl_by_item(
            strategy='manual', trades=rows)), 2)

    def test_http_disk_failure_returns_structured_error(self):
        handler = make_handler(FlipScanner(), lambda: [], owner_token='fixture',
                               activity_fn=mock.Mock(side_effect=OSError('fixture failure')))
        request = BaseHTTPRequestHandler.__new__(handler)
        request.path, request.command = '/api/activity', 'GET'
        request.headers = {'Authorization': 'Bearer fixture'}
        request.wfile = io.BytesIO()
        codes = []
        request.send_response = lambda code, *args: codes.append(code)
        request.send_header = lambda *args: None
        request.end_headers = lambda: None
        request.do_GET()
        self.assertEqual(codes, [500])
        self.assertEqual(json.loads(request.wfile.getvalue())['error'], 'Activity unavailable')

    def test_invalid_cursor_limits_and_filters_fail_safely(self):
        for kwargs in ({'cursor': 'not a cursor'}, {'limit': 101}, {'limit': True},
                       {'filters': {'strategy': 'unknown'}}, {'filters': {'since': 'bad-date'}},
                       {'filters': {'unknown': 'value'}}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                journal.page_trades(trades(2), revision='same', **kwargs)

    def test_dates_are_utc_and_end_date_is_inclusive(self):
        rows = trades(3)
        rows[0].timestamp = '2026-10-11T23:30:00-01:00'
        rows[1].timestamp = '2026-10-12T23:30:00+00:00'
        rows[2].timestamp = '2026-10-13T00:00:00Z'
        page = journal.page_trades(rows, revision='same',
                                  filters={'since': '2026-10-12', 'until': '2026-10-12'})
        self.assertEqual({row['id'] for row in page['trades']}, {1, 2})
        self.assertEqual(page['timezone'], 'UTC')
        self.assertTrue(all(row['timestamp'].endswith('+00:00') for row in page['trades']))

    def test_http_activity_is_private_and_rejects_invalid_limits(self):
        rows = trades(12)
        callback = lambda filters, cursor, limit: journal.page_trades(
            rows, revision='same', filters=filters, cursor=cursor, limit=limit)
        handler = make_handler(FlipScanner(), lambda: [], activity_fn=callback, owner_token='fixture')
        for path, token, expected in (('/api/activity', '', 401),
                                      ('/api/activity?limit=101', 'fixture', 400),
                                      ('/api/activity?limit=3', 'fixture', 200)):
            request = BaseHTTPRequestHandler.__new__(handler)
            request.path = path
            request.command = 'GET'
            request.headers = {'Authorization': 'Bearer ' + token}
            request.wfile = io.BytesIO()
            codes = []
            request.send_response = lambda code, *args: codes.append(code)
            request.send_header = lambda *args: None
            request.end_headers = lambda: None
            request.do_GET()
            self.assertEqual(codes, [expected])
            if expected == 200:
                self.assertEqual(len(json.loads(request.wfile.getvalue())['trades']), 3)

    def test_history_buckets_follow_utc_dates(self):
        rows = trades(1)
        rows[0].timestamp = '2026-10-11T23:30:00-01:00'
        with mock.patch.object(history.tuning, 'load_entries', return_value=[]), \
             mock.patch.object(history.snapshot, 'list_snapshots', return_value=[]):
            result = history.build_history(trades=rows)
        self.assertEqual(result['buckets'][0]['date'], '2026-10-12')

    def test_server_activity_summary_and_page_share_one_load(self):
        rows = trades(12)
        raw = [asdict(row) for row in rows]
        callbacks = {}
        load = mock.Mock(return_value=raw)
        testcase = self
        class HttpServer:
            def __init__(self, *args):
                pass
            def serve_forever(self):
                load.reset_mock()
                result = callbacks['activity_fn']({'strategy': 'auto'}, None, 3)
                testcase.assertEqual(load.call_count, 1)
                testcase.assertEqual(result['pnl']['trade_count'], 6)
                testcase.assertEqual(result['history']['summary']['trade_count'], 6)
                testcase.assertEqual(result['filtered_count'], 6)
                testcase.assertEqual(len(result['trades']), 3)
                testcase.assertTrue(result['next_cursor'])
            def server_close(self):
                pass
        def handler(*args, **kwargs):
            callbacks.update(kwargs)
            return object
        with ExitStack() as stack:
            for target, name, value in ((server, 'load_config', lambda *a: Config()),
                    (server, '_fetch_bootstrap', lambda *a: ([], {}, {}, [])),
                    (server, 'ThreadingHTTPServer', HttpServer), (server, 'make_handler', handler),
                    (server, 'detect_signals', lambda *a, **k: []),
                    (journal, '_load', load),
                    (server.watchlist, 'load', lambda *a: {'items': {}}),
                    (server.alerts, 'unread_count', lambda *a: 0),
                    (server.alerts, 'push_alert', mock.Mock()),
                    (history.tuning, 'record_if_changed', mock.Mock()),
                    (history.tuning, 'load_entries', lambda *a: []),
                    (history.snapshot, 'list_snapshots', lambda **k: [])):
                stack.enter_context(mock.patch.object(target, name, value))
            server.run(port=0, owner_token='a' * 64)


if __name__ == '__main__':
    unittest.main()
