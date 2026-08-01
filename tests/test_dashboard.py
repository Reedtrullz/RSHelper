"""Tests for the rshelper dashboard module."""
import io
import json
import sys
import unittest

sys.path.insert(0, "src")

from rshelper.dashboard.templates import INDEX_HTML
from rshelper.dashboard.handlers import make_handler, _item_to_dict
from rshelper.models import Item
from rshelper.scanner import FlipScanner


class TestItemToDict(unittest.TestCase):
    def test_full_item(self):
        item = Item(id=4151, name="Abyssal whip", members=True, buy_limit=70,
                     alch_value=72000, buy_price=1500000, sell_price=1520000,
                     volume=200, profit=19600, gp_per_hour=240000)
        d = _item_to_dict(item)
        self.assertEqual(d["id"], 4151)
        self.assertEqual(d["name"], "Abyssal whip")
        self.assertEqual(d["members"], True)
        self.assertEqual(d["profit"], 19600)

    def test_zero_values(self):
        item = Item(id=1, name="Toolkit", members=False, buy_limit=0,
                     alch_value=0, buy_price=0, sell_price=0, volume=0)
        d = _item_to_dict(item)
        self.assertEqual(d["profit"], 0)
        self.assertEqual(d["gp_per_hour"], 0)


class TestHandlerRouting(unittest.TestCase):
    def setUp(self):
        self.scanner = FlipScanner(direction="arbitrage")
        self.test_item = Item(id=2, name="Cannonball", members=False,
                               buy_limit=10000, alch_value=3, buy_price=200,
                               sell_price=210, volume=5000, profit=8,
                               gp_per_hour=96000)
        self.items = [self.test_item]
        Handler = make_handler(self.scanner, lambda: list(self.items))

        # Bypass BaseHTTPRequestHandler.__init__ (which tries to parse a real
        # socket) by constructing the base object directly and setting
        # attributes manually.
        from http.server import BaseHTTPRequestHandler
        self.handler = BaseHTTPRequestHandler.__new__(Handler)
        self.handler.path = "/"
        self.handler.request_version = "HTTP/1.1"
        self.handler.command = "GET"
        self.handler.headers = {}
        self.handler.response_code = None
        self.handler.response_headers = []

        # Capture writes
        self.out = io.BytesIO()
        self.handler.wfile = self.out

        # Override send_response etc. to record state without socket I/O
        def send_response(code, message=None):
            self.handler.response_code = code
        self.handler.send_response = send_response

        def send_header(key, value):
            self.handler.response_headers.append((key, value))
        self.handler.send_header = send_header

        def end_headers():
            pass
        self.handler.end_headers = end_headers

    def _get_body(self):
        return self.out.getvalue()

    def test_root_serves_html(self):
        self.handler.path = "/"
        self.handler.do_GET()
        self.assertEqual(self.handler.response_code, 200)
        body = self._get_body().decode()
        self.assertIn("<!DOCTYPE html>", body)
        self.assertIn("RSHelper", body)

    def test_api_health(self):
        self.handler.path = "/api/health"
        self.handler.do_GET()
        self.assertEqual(self.handler.response_code, 200)
        body = json.loads(self._get_body())
        self.assertEqual(body["status"], "healthy")
        self.assertIn("version", body)

    def test_api_pnl_includes_roi(self):
        import tempfile
        from pathlib import Path
        sys.path.insert(0, "src")
        import rshelper.journal as jmod
        original_path = jmod.TRADES_PATH
        with tempfile.TemporaryDirectory() as tmp:
            jmod.TRADES_PATH = Path(tmp) / "trades.json"
            try:
                jmod.log_trade(1, "Nature rune", 1000, 100, 110)
                self.handler.path = "/api/pnl"
                self.handler.do_GET()
                body = json.loads(self._get_body())
            finally:
                jmod.TRADES_PATH = original_path
        self.assertIn("roi_pct", body)
        self.assertIn("total_cost_basis", body)
        self.assertGreater(body["total_cost_basis"], 0)

    def test_api_pnl_note_filter(self):
        import tempfile
        from pathlib import Path
        sys.path.insert(0, "src")
        import rshelper.journal as jmod
        original_path = jmod.TRADES_PATH
        with tempfile.TemporaryDirectory() as tmp:
            jmod.TRADES_PATH = Path(tmp) / "trades.json"
            try:
                jmod.log_trade(1, "Paper", 1, 100, 200, note="paper")
                jmod.log_trade(2, "Live", 1, 100, 200, note="live")
                self.handler.path = "/api/pnl?note=paper"
                self.handler.do_GET()
                body = json.loads(self._get_body())
            finally:
                jmod.TRADES_PATH = original_path
        self.assertEqual(body["trade_count"], 1)
        self.assertEqual(body["total_profit"], 96)  # (200-100) - ge_tax(200)=4

    def test_api_trades_note_filter(self):
        import tempfile
        from pathlib import Path
        sys.path.insert(0, "src")
        import rshelper.journal as jmod
        original_path = jmod.TRADES_PATH
        with tempfile.TemporaryDirectory() as tmp:
            jmod.TRADES_PATH = Path(tmp) / "trades.json"
            try:
                jmod.log_trade(1, "Paper", 1, 100, 200, note="paper")
                jmod.log_trade(2, "Live", 1, 100, 200, note="live")
                self.handler.path = "/api/trades?note=paper"
                self.handler.do_GET()
                body = json.loads(self._get_body())
            finally:
                jmod.TRADES_PATH = original_path
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["trades"][0]["name"], "Paper")

    def test_api_trades_strategy_filter(self):
        import tempfile
        from pathlib import Path
        sys.path.insert(0, "src")
        import rshelper.journal as jmod
        original_path = jmod.TRADES_PATH
        with tempfile.TemporaryDirectory() as tmp:
            jmod.TRADES_PATH = Path(tmp) / "trades.json"
            try:
                jmod.log_trade(1, "Auto", 1, 100, 200, note="paper",
                               strategy="auto")
                jmod.log_trade(2, "Manual", 1, 100, 200, note="paper",
                               strategy="manual")
                self.handler.path = "/api/trades?note=paper&strategy=auto"
                self.handler.do_GET()
                body = json.loads(self._get_body())
            finally:
                jmod.TRADES_PATH = original_path
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["trades"][0]["name"], "Auto")
        self.assertEqual(body["trades"][0]["strategy"], "auto")

    def test_api_pnl_strategy_filter(self):
        import tempfile
        from pathlib import Path
        sys.path.insert(0, "src")
        import rshelper.journal as jmod
        original_path = jmod.TRADES_PATH
        with tempfile.TemporaryDirectory() as tmp:
            jmod.TRADES_PATH = Path(tmp) / "trades.json"
            try:
                jmod.log_trade(1, "Auto", 1, 100, 200, note="paper",
                               strategy="auto")
                jmod.log_trade(2, "Manual", 1, 100, 200, note="paper",
                               strategy="manual")
                self.handler.path = "/api/pnl?note=paper&strategy=auto"
                self.handler.do_GET()
                body = json.loads(self._get_body())
            finally:
                jmod.TRADES_PATH = original_path
        self.assertEqual(body["trade_count"], 1)
        self.assertEqual(body["total_profit"], 96)

    def test_api_prices(self):
        from http.server import BaseHTTPRequestHandler
        Handler = make_handler(
            self.scanner, lambda: [],
            price_lookup=lambda ids: {str(i): {"usable": True, "buy": 100, "sell": 110}
                                      for i in ids})
        h = BaseHTTPRequestHandler.__new__(Handler)
        h.path = "/api/prices?ids=561,2"
        h.request_version = "HTTP/1.1"
        h.command = "GET"
        h.headers = {}
        h.response_code = None
        h.response_headers = []
        h.wfile = io.BytesIO()
        h.send_response = lambda code, message=None: setattr(h, "response_code", code)
        h.send_header = lambda key, value: h.response_headers.append((key, value))
        h.end_headers = lambda: None
        h.do_GET()
        body = json.loads(h.wfile.getvalue())
        self.assertEqual(body["prices"]["561"]["buy"], 100)
        self.assertEqual(body["prices"]["2"]["sell"], 110)

    def test_api_meta(self):
        from http.server import BaseHTTPRequestHandler
        Handler = make_handler(
            self.scanner, lambda: [],
            meta_fn=lambda: {"source": "wiki", "items": 5, "flips": 3, "signals": 2,
                             "trades": 3, "watchlist": 1, "watch_ids": [1, 2]})
        h = BaseHTTPRequestHandler.__new__(Handler)
        h.path = "/api/meta"
        h.request_version = "HTTP/1.1"
        h.command = "GET"
        h.headers = {}
        h.wfile = io.BytesIO()
        h.send_response = lambda code, message=None: None
        h.send_header = lambda key, value: None
        h.end_headers = lambda: None
        h.do_GET()
        body = json.loads(h.wfile.getvalue())
        self.assertEqual(body["source"], "wiki")
        self.assertEqual(body["watch_ids"], [1, 2])
        self.assertIsInstance(body["flips"], int)

    def test_api_watchlist_get(self):
        from http.server import BaseHTTPRequestHandler
        Handler = make_handler(
            self.scanner, lambda: [],
            watchlist_fn=lambda: {"items": [{"id": 1, "name": "Nature rune",
                                             "usable": True, "buy": 100, "sell": 110}]})
        h = BaseHTTPRequestHandler.__new__(Handler)
        h.path = "/api/watchlist"
        h.request_version = "HTTP/1.1"
        h.command = "GET"
        h.headers = {}
        h.wfile = io.BytesIO()
        h.send_response = lambda code, message=None: None
        h.send_header = lambda key, value: None
        h.end_headers = lambda: None
        h.do_GET()
        body = json.loads(h.wfile.getvalue())
        self.assertEqual(body["items"][0]["name"], "Nature rune")

    def test_api_watchlist_post(self):
        from http.server import BaseHTTPRequestHandler
        calls = []
        Handler = make_handler(
            self.scanner, lambda: [],
            watchlist_update_fn=lambda a, i: calls.append((a, i)) or {"items": []})
        h = BaseHTTPRequestHandler.__new__(Handler)
        h.path = "/api/watchlist"
        h.command = "POST"
        h.request_version = "HTTP/1.1"
        payload = json.dumps({"action": "add", "item_id": 5}).encode()
        h.headers = {"Content-Length": str(len(payload))}
        h.rfile = io.BytesIO(payload)
        h.wfile = io.BytesIO()
        h.send_response = lambda code, message=None: None
        h.send_header = lambda key, value: None
        h.end_headers = lambda: None
        h.do_POST()
        self.assertEqual(calls, [("add", 5)])

    def test_api_paper_trade(self):
        from http.server import BaseHTTPRequestHandler
        calls = []
        Handler = make_handler(
            self.scanner, lambda: [],
            paper_trade_fn=lambda a, i, q: calls.append((a, i, q)) or {"ok": True})
        h = BaseHTTPRequestHandler.__new__(Handler)
        h.path = "/api/paper"
        h.command = "POST"
        h.request_version = "HTTP/1.1"
        payload = json.dumps({"action": "open", "item": "nature rune", "qty": 5}).encode()
        h.headers = {"Content-Length": str(len(payload)), "Host": "127.0.0.1:5555"}
        h.rfile = io.BytesIO(payload)
        h.wfile = io.BytesIO()
        h.send_response = lambda code, message=None: None
        h.send_header = lambda key, value: None
        h.end_headers = lambda: None
        h.do_POST()
        self.assertEqual(calls, [("open", "nature rune", 5)])

    def test_api_trader_status(self):
        from http.server import BaseHTTPRequestHandler
        Handler = make_handler(
            self.scanner, lambda: [],
            trader_fn=lambda: {"running": True, "pid": 42,
                               "last_result": {"opened": [], "closed": []}})
        h = BaseHTTPRequestHandler.__new__(Handler)
        h.path = "/api/trader"
        h.request_version = "HTTP/1.1"
        h.command = "GET"
        h.headers = {}
        h.wfile = io.BytesIO()
        h.send_response = lambda code, message=None: None
        h.send_header = lambda key, value: None
        h.end_headers = lambda: None
        h.do_GET()
        body = json.loads(h.wfile.getvalue())
        self.assertTrue(body["running"])
        self.assertEqual(body["pid"], 42)

    def test_api_timeseries(self):
        from http.server import BaseHTTPRequestHandler
        Handler = make_handler(
            self.scanner, lambda: [],
            timeseries_fn=lambda i: {"points": [{"ts": 1, "avgHigh": 100, "avgLow": 90}]})
        h = BaseHTTPRequestHandler.__new__(Handler)
        h.path = "/api/timeseries?id=561"
        h.request_version = "HTTP/1.1"
        h.command = "GET"
        h.headers = {}
        h.wfile = io.BytesIO()
        h.send_response = lambda code, message=None: None
        h.send_header = lambda key, value: None
        h.end_headers = lambda: None
        h.do_GET()
        body = json.loads(h.wfile.getvalue())
        self.assertEqual(body["points"][0]["avgHigh"], 100)

    def test_api_timeseries_bad_id_rejected(self):
        from http.server import BaseHTTPRequestHandler
        called = []
        Handler = make_handler(
            self.scanner, lambda: [],
            timeseries_fn=lambda i: called.append(i) or {"points": []})
        h = BaseHTTPRequestHandler.__new__(Handler)
        h.path = "/api/timeseries?id=abc"
        h.request_version = "HTTP/1.1"
        h.command = "GET"
        h.headers = {}
        h.wfile = io.BytesIO()
        h.send_error = lambda code, message=None: setattr(h, "error_code", code)
        h.do_GET()
        self.assertEqual(h.error_code, 400)
        self.assertEqual(called, [])

    def test_api_positions(self):
        from http.server import BaseHTTPRequestHandler
        Handler = make_handler(
            self.scanner, lambda: [],
            positions_fn=lambda: {"positions": [
                {"id": 1, "name": "Nature rune", "qty": 10, "buy_price": 100,
                 "current": 120, "unrealized": 180,
                 "opened_at": "2026-07-31T00:00:00Z"}],
                "open_qty": 10, "unrealized": 180})
        h = BaseHTTPRequestHandler.__new__(Handler)
        h.path = "/api/positions"
        h.request_version = "HTTP/1.1"
        h.command = "GET"
        h.headers = {}
        h.wfile = io.BytesIO()
        h.send_response = lambda code, message=None: None
        h.send_header = lambda key, value: None
        h.end_headers = lambda: None
        h.do_GET()
        body = json.loads(h.wfile.getvalue())
        self.assertEqual(body["open_qty"], 10)
        self.assertEqual(body["positions"][0]["unrealized"], 180)

    def test_api_watchlist_post_foreign_origin_rejected(self):
        from http.server import BaseHTTPRequestHandler
        Handler = make_handler(
            self.scanner, lambda: [],
            watchlist_update_fn=lambda a, i: {"items": []})
        h = BaseHTTPRequestHandler.__new__(Handler)
        h.path = "/api/watchlist"
        h.command = "POST"
        h.request_version = "HTTP/1.1"
        payload = json.dumps({"action": "add", "item_id": 5}).encode()
        h.headers = {"Content-Length": str(len(payload)), "Host": "127.0.0.1:5555",
                     "Origin": "https://evil.example"}
        h.rfile = io.BytesIO(payload)
        h.wfile = io.BytesIO()
        h.send_error = lambda code, message=None: setattr(h, "error_code", code)
        h.do_POST()
        self.assertEqual(h.error_code, 403)

    def test_dashboard_boot_survives_total_fetch_failure(self):
        """A total source failure must not crash the dashboard at startup."""
        import tempfile
        from pathlib import Path
        from unittest import mock
        sys.path.insert(0, "src")
        import rshelper.profile as pmod
        import rshelper.dashboard.server as smod
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(pmod, "CONFIG_DIR", Path(tmp) / "config"), \
                 mock.patch.object(pmod, "CACHE_DIR", Path(tmp) / "cache"), \
                 mock.patch.object(smod, "_fetch_bootstrap", side_effect=SystemExit), \
                 mock.patch.object(smod.ThreadingHTTPServer, "serve_forever",
                                   side_effect=KeyboardInterrupt):
                smod.run(bind="127.0.0.1", port=0)

    def test_scan_kwargs_passed_to_scanner(self):
        calls = []

        class StubScanner:
            def scan(self, items, **kw):
                calls.append(kw)
                return []

        Handler = make_handler(StubScanner(), lambda: [],
                               scan_kwargs={"min_volume": 10})
        from http.server import BaseHTTPRequestHandler
        h = BaseHTTPRequestHandler.__new__(Handler)
        h.path = "/api/scan"
        h.request_version = "HTTP/1.1"
        h.command = "GET"
        h.headers = {}
        h.response_code = None
        h.response_headers = []
        h.wfile = io.BytesIO()
        h.send_response = lambda code, message=None: setattr(h, "response_code", code)
        h.send_header = lambda key, value: h.response_headers.append((key, value))
        h.end_headers = lambda: None
        h.do_GET()
        self.assertEqual(calls, [{"min_volume": 10}])
        self.assertEqual(h.response_code, 200)

    def test_api_history_route(self):
        import tempfile
        from pathlib import Path
        sys.path.insert(0, "src")
        import rshelper.profile as pmod
        import rshelper.snapshot as smod
        import rshelper.journal as jmod
        old = (jmod.TRADES_PATH, smod.SNAPSHOT_DIR, pmod.CONFIG_DIR,
               pmod.ACTIVE_PROFILE_PATH)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            jmod.TRADES_PATH = tmp / "trades.json"
            smod.SNAPSHOT_DIR = tmp / "snapshots"
            pmod.CONFIG_DIR = tmp
            pmod.ACTIVE_PROFILE_PATH = tmp / "active_profile"
            try:
                self.handler.path = "/api/history?paper=1"
                self.handler.do_GET()
                body = json.loads(self._get_body())
            finally:
                (jmod.TRADES_PATH, smod.SNAPSHOT_DIR, pmod.CONFIG_DIR,
                 pmod.ACTIVE_PROFILE_PATH) = old
        self.assertEqual(self.handler.response_code, 200)
        for key in ("summary", "buckets", "eras", "items"):
            self.assertIn(key, body)

    def test_api_history_paper_default_on(self):
        import tempfile
        from pathlib import Path
        sys.path.insert(0, "src")
        import rshelper.profile as pmod
        import rshelper.snapshot as smod
        import rshelper.journal as jmod
        old = (jmod.TRADES_PATH, smod.SNAPSHOT_DIR, pmod.CONFIG_DIR,
               pmod.ACTIVE_PROFILE_PATH)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            jmod.TRADES_PATH = tmp / "trades.json"
            smod.SNAPSHOT_DIR = tmp / "snapshots"
            pmod.CONFIG_DIR = tmp
            pmod.ACTIVE_PROFILE_PATH = tmp / "active_profile"
            try:
                jmod.log_trade(1, "Paper item", 1, 100, 200, "paper")
                jmod.log_trade(2, "Manual item", 1, 100, 200, "")
                self.handler.path = "/api/history"
                self.handler.do_GET()
                body = json.loads(self._get_body())
                self.assertEqual(body["summary"]["trade_count"], 1)
                self.out = io.BytesIO()
                self.handler.wfile = self.out
                self.handler.response_code = None
                self.handler.response_headers = []
                self.handler.path = "/api/history?paper=0"
                self.handler.do_GET()
                body_all = json.loads(self._get_body())
                self.assertEqual(body_all["summary"]["trade_count"], 2)
            finally:
                (jmod.TRADES_PATH, smod.SNAPSHOT_DIR, pmod.CONFIG_DIR,
                 pmod.ACTIVE_PROFILE_PATH) = old

    def test_navigation_markup_present(self):
        self.assertIn("Market", INDEX_HTML)
        self.assertIn("Paper Trading", INDEX_HTML)
        self.assertIn("Signals", INDEX_HTML)
        self.assertIn("Watchlist", INDEX_HTML)
        self.assertIn("/api/history", INDEX_HTML)

    def test_api_scan_returns_json(self):
        self.handler.path = "/api/scan"
        self.handler.do_GET()
        self.assertEqual(self.handler.response_code, 200)
        body = json.loads(self._get_body())
        self.assertIn("items", body)
        self.assertIn("count", body)
        self.assertIn("timestamp", body)
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["items"][0]["name"], "Cannonball")

    def test_api_scan_with_query_params(self):
        self.handler.path = "/api/scan?top=10&sort=margin"
        self.handler.do_GET()
        self.assertEqual(self.handler.response_code, 200)
        body = json.loads(self._get_body())
        self.assertEqual(body["count"], 1)

    def test_unknown_path_404(self):
        self.handler.path = "/nonexistent"
        self.handler.do_GET()
        self.assertEqual(self.handler.response_code, 404)

    def test_content_type_html(self):
        self.handler.path = "/"
        self.handler.do_GET()
        headers = dict(self.handler.response_headers)
        self.assertIn("text/html", headers.get("Content-Type", ""))

    def test_content_type_json(self):
        self.handler.path = "/api/health"
        self.handler.do_GET()
        headers = dict(self.handler.response_headers)
        self.assertIn("application/json", headers.get("Content-Type", ""))

    def test_no_cache_on_api(self):
        self.handler.path = "/api/scan"
        self.handler.do_GET()
        headers = dict(self.handler.response_headers)
        self.assertEqual(headers.get("Cache-Control"), "no-cache")

    def test_no_cache_on_html(self):
        self.handler.path = "/"
        self.handler.do_GET()
        headers = dict(self.handler.response_headers)
        self.assertEqual(headers.get("Cache-Control"), "no-cache")

    def test_protocol_version_is_http11(self):
        self.assertEqual(self.handler.protocol_version, "HTTP/1.1")


class TestTemplate(unittest.TestCase):
    def test_html_is_nonempty(self):
        self.assertGreater(len(INDEX_HTML), 1000)

    def test_html_has_doctype(self):
        self.assertIn("<!DOCTYPE html>", INDEX_HTML)

    def test_html_closes_correctly(self):
        self.assertIn("</html>", INDEX_HTML)

    def test_html_has_close_body(self):
        self.assertIn("</body>", INDEX_HTML)

    def test_html_has_fetch_api(self):
        self.assertIn("fetch('/api/scan')", INDEX_HTML)

    def test_html_has_esc_html(self):
        self.assertIn("function escHtml", INDEX_HTML)


class TestCLIDashboardSubcommand(unittest.TestCase):
    def setUp(self):
        import argparse
        parser = argparse.ArgumentParser(prog="rshelper")
        sub = parser.add_subparsers(dest="command")
        dashboard = sub.add_parser("dashboard", help="Launch local web dashboard")
        dashboard.add_argument("--port", type=int, default=5555)
        dashboard.add_argument("--bind", type=str, default="127.0.0.1")
        self.parser = parser

    def test_dashboard_defaults(self):
        args = self.parser.parse_args(["dashboard"])
        self.assertEqual(args.command, "dashboard")
        self.assertEqual(args.port, 5555)
        self.assertEqual(args.bind, "127.0.0.1")

    def test_dashboard_custom_port(self):
        args = self.parser.parse_args(["dashboard", "--port", "9999"])
        self.assertEqual(args.port, 9999)

    def test_dashboard_custom_bind(self):
        args = self.parser.parse_args(["dashboard", "--bind", "0.0.0.0"])
        self.assertEqual(args.bind, "0.0.0.0")

    def test_dashboard_help(self):
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["dashboard", "--help"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
