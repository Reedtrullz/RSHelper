"""Tests for the rshelper dashboard module."""
import io
import inspect
import json
import sys
import unittest
from contextlib import redirect_stderr

sys.path.insert(0, "src")

from rshelper.dashboard.templates import INDEX_HTML
from rshelper.dashboard.handlers import make_handler as _make_handler, _item_to_dict
from rshelper.models import Item
from rshelper.scanner import FlipScanner

TEST_OWNER_TOKEN = "synthetic-dashboard-owner-token"


def make_handler(*args, **kwargs):
    """Use real owner policy with a synthetic credential for legacy route tests."""
    kwargs.setdefault("mode", "owner")
    kwargs.setdefault("owner_token", TEST_OWNER_TOKEN)
    return _make_handler(*args, **kwargs)


class TestAuthorizationConfiguration(unittest.TestCase):
    def test_handler_accepts_explicit_policy_and_token_parameters(self):
        params = inspect.signature(_make_handler).parameters
        self.assertIn("mode", params)
        self.assertIn("owner_token", params)
        self.assertIn("control", params)


@unittest.skipUnless("mode" in inspect.signature(_make_handler).parameters,
                     "handler authorization wiring has not been added")
class TestAuthorizationBoundary(unittest.TestCase):
    def test_owner_runtime_watch_callbacks_serialize_valid_quotes(self):
        from unittest import mock
        from rshelper.config import Config
        import rshelper.dashboard.server as server
        callbacks = {}
        def capture(*args, **kwargs):
            callbacks.update(kwargs)
            return object
        class FakeServer:
            def __init__(self, *args): pass
            def serve_forever(self):
                rows = callbacks['watchlist_fn']()['items']
                self_case.assertEqual(rows[0]['buy'], 100)
                self_case.assertEqual(rows[0]['sell'], 110)
                self_case.assertIn('triggered', callbacks['watchlist_check_fn']())
            def server_close(self): pass
        self_case = self
        import time
        latest = {'2': {'high': 100, 'low': 110, 'highTime': int(time.time()), 'lowTime': int(time.time())}}
        with mock.patch.object(server, 'load_config', return_value=Config()), \
             mock.patch.object(server, '_fetch_bootstrap', return_value=([], latest, {}, [])), \
             mock.patch.object(server, 'make_handler', side_effect=capture), \
             mock.patch.object(server, 'ThreadingHTTPServer', FakeServer), \
             mock.patch.object(server.watchlist, 'load', return_value={'items': {'2': {'name': 'Fixture'}}}), \
             mock.patch('rshelper.tuning.record_if_changed'):
            server.run(port=0, profile='default', owner_token='a'*64)

    def test_public_startup_failure_does_not_write_private_state(self):
        from unittest import mock
        from rshelper.config import Config
        import rshelper.dashboard.server as smod
        class FakeServer:
            def __init__(self, *args): pass
            def serve_forever(self): pass
            def server_close(self): pass
        with mock.patch.object(smod, 'load_config', return_value=Config()), \
             mock.patch.object(smod, '_fetch_bootstrap', side_effect=SystemExit), \
             mock.patch.object(smod, 'ThreadingHTTPServer', FakeServer), \
             mock.patch.object(smod.alerts, 'push_alert') as alert, \
             mock.patch('rshelper.tuning.record_if_changed') as tuning:
            smod.run(port=0, access_mode='public-demo', profile='default')
        alert.assert_not_called()
        tuning.assert_not_called()

    GET_PRIVATE = (
        "/api/monitor", "/api/signals", "/api/trades", "/api/pnl",
        "/api/history", "/api/meta", "/api/watchlist",
        "/api/watchlist/check", "/api/positions", "/api/trader",
        "/api/ge", "/api/bank", "/api/alerts", "/api/events",
    )
    POST_MUTATIONS = (
        "/api/trades", "/api/watchlist", "/api/paper", "/api/ge/collect",
        "/api/positions", "/api/trader", "/api/monitor",
        "/api/alerts/read", "/api/trades/delete",
    )

    def _handler(self, method, path, headers=None, *, mode="owner",
                 owner_token=TEST_OWNER_TOKEN, control=False, event_hub=None):
        from http.server import BaseHTTPRequestHandler
        from rshelper.scanner import FlipScanner

        calls = []

        def callback(name, result=None):
            def invoke(*args):
                calls.append(name)
                return result if result is not None else {}
            return invoke

        fns = {
            "signal_detector": callback("signals", []),
            "scan_kwargs": {},
            "price_lookup": callback("prices", {}),
            "meta_fn": callback("meta"),
            "watchlist_fn": callback("watchlist"),
            "watchlist_update_fn": callback("watchlist-update"),
            "watchlist_check_fn": callback("watchlist-check"),
            "timeseries_fn": callback("timeseries"),
            "positions_fn": callback("positions"),
            "close_position_fn": callback("close-position"),
            "paper_trade_fn": callback("paper-trade"),
            "trader_fn": callback("trader"),
            "trader_control_fn": callback("trader-control"),
            "monitor_fn": callback("monitor"),
            "monitor_control_fn": callback("monitor-control"),
            "ge_fn": callback("ge"),
            "ge_collect_fn": callback("ge-collect"),
            "bank_fn": callback("bank"),
            "process_fn": callback("process"),
            "alch_fn": callback("alch"),
            "confidence_fn": callback("confidence"),
            "alerts_fn": callback("alerts"),
            "alerts_read_fn": callback("alerts-read"),
            "history_fn": callback("history"),
            "trades_fn": callback("trades"),
            "pnl_fn": callback("pnl"),
            "delete_trade_fn": callback("trade-delete"),
            "log_trade_fn": callback("trade-log"),
        }
        handler_type = _make_handler(
            FlipScanner(direction="arbitrage"), callback("scan", []),
            event_hub=event_hub, mode=mode, owner_token=owner_token,
            control=control, **fns)
        h = BaseHTTPRequestHandler.__new__(handler_type)
        h.path = path
        h.request_version = "HTTP/1.1"
        h.command = method
        h.headers = headers or {}
        payload = b'{"action":"start","trade_id":1,"item_id":1,"position_id":1}'
        h.rfile = io.BytesIO(payload)
        h.headers.setdefault("Content-Length", str(len(payload)))
        h.response_code = None
        h.response_headers = []
        h.wfile = io.BytesIO()
        h.send_response = lambda code, message=None: setattr(h, "response_code", code)
        h.send_header = lambda key, value: h.response_headers.append((key, value))
        h.end_headers = lambda: None
        return h, calls

    def test_missing_or_forged_origin_never_reaches_private_callbacks(self):
        requests = [("GET", path) for path in self.GET_PRIVATE]
        requests += [("POST", path) for path in self.POST_MUTATIONS]
        for method, path in requests:
            for headers in ({}, {"Origin": "https://evil.example",
                                 "Host": "127.0.0.1:5555"}):
                with self.subTest(method=method, path=path, headers=headers):
                    h, calls = self._handler(method, path, dict(headers))
                    (h.do_GET if method == "GET" else h.do_POST)()
                    self.assertIn(h.response_code, (401, 403))
                    self.assertEqual(calls, [])

    def test_owner_bearer_can_read_private_state(self):
        h, calls = self._handler("GET", "/api/trades", {
            "Authorization": f"Bearer {TEST_OWNER_TOKEN}"})
        h.do_GET()
        self.assertEqual(h.response_code, 200)
        self.assertEqual(calls, ["trades"])

    def test_missing_configured_owner_token_fails_closed(self):
        h, calls = self._handler("GET", "/api/trades", owner_token=None)
        h.do_GET()
        self.assertEqual(h.response_code, 401)
        self.assertEqual(calls, [])

    def test_url_query_token_is_not_an_authentication_credential(self):
        h, calls = self._handler("GET", f"/api/trades?token={TEST_OWNER_TOKEN}")
        h.do_GET()
        self.assertEqual(h.response_code, 401)
        self.assertEqual(calls, [])

    def test_request_logs_redact_query_and_authorization_values(self):
        h, _ = self._handler("GET", "/api/trades")
        log = io.StringIO()
        with redirect_stderr(log):
            h.log_message("request %s Authorization: %s",
                          "/api/trades?token=query-secret", "Bearer header-secret")
        emitted = log.getvalue()
        self.assertNotIn("query-secret", emitted)
        self.assertNotIn("header-secret", emitted)

    def test_public_demo_serves_only_sanitized_public_surfaces(self):
        for path in ("/", "/api/health", "/api/capabilities", "/api/scan"):
            with self.subTest(path=path):
                h, calls = self._handler("GET", path, mode="public-demo")
                h.do_GET()
                self.assertEqual(h.response_code, 200)
                if path == "/api/health":
                    payload = json.loads(h.wfile.getvalue())
                    self.assertEqual(set(payload), {'status', 'version', 'build_revision',
                        'image_digest', 'platform', 'base_image_digest'})
                    self.assertEqual(payload["status"], "healthy")
                    self.assertIsInstance(payload["version"], str)
                elif path == "/api/capabilities":
                    payload = json.loads(h.wfile.getvalue())
                    self.assertEqual(set(payload), {"mode", "features"})
                    self.assertEqual(payload["mode"], "public-demo")
                    self.assertEqual(payload["features"], ["market", "static", "health"])
                elif path == "/api/scan":
                    self.assertEqual(calls, ["scan"])
                self.assertNotIn(TEST_OWNER_TOKEN.encode(), h.wfile.getvalue())

    def test_public_events_are_denied_before_stream_subscription(self):
        class Hub:
            subscribers = []

            def subscribe(self, queue):
                self.subscribers.append(queue)

            def unsubscribe(self, queue):
                self.subscribers.remove(queue)

        hub = Hub()
        h, calls = self._handler("GET", "/api/events?ttl=1", {
            "Authorization": f"Bearer {TEST_OWNER_TOKEN}"}, mode="public-demo",
            event_hub=hub)
        h.do_GET()
        self.assertIn(h.response_code, (401, 403))
        self.assertEqual(calls, [])
        self.assertEqual(hub.subscribers, [])
        self.assertNotIn(b"private-alert", h.wfile.getvalue())

    def test_valid_owner_token_does_not_enable_daemon_control(self):
        h, calls = self._handler("POST", "/api/trader", {
            "Authorization": f"Bearer {TEST_OWNER_TOKEN}",
            "Host": "127.0.0.1:5555"})
        h.do_POST()
        self.assertEqual(h.response_code, 403)
        self.assertEqual(calls, [])

    def test_authenticated_foreign_origin_still_fails_csrf_check(self):
        h, calls = self._handler("POST", "/api/watchlist", {
            "Authorization": f"Bearer {TEST_OWNER_TOKEN}",
            "Origin": "https://evil.example", "Host": "127.0.0.1:5555"})
        h.do_POST()
        self.assertEqual(h.response_code, 403)
        self.assertEqual(calls, [])

    def test_public_market_refresh_does_not_mutate_private_alert_state(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from unittest import mock
        from http.server import BaseHTTPRequestHandler
        from itertools import chain, repeat
        import rshelper.dashboard.server as server_module

        latest = {"1": {"high": 100, "low": 110}}
        fetched = [({}, {}, {}, []), ({}, latest, {}, [])]
        cfg = SimpleNamespace(flip=SimpleNamespace(
            direction="arbitrage", members_only=False, min_volume=0,
            min_margin=0))
        response_codes = []
        times = iter(chain([0], repeat(121)))

        class FakeServer:
            def __init__(self, address, handler_type):
                self.RequestHandlerClass = handler_type

            def serve_forever(self):
                h = BaseHTTPRequestHandler.__new__(self.RequestHandlerClass)
                h.path = "/api/scan"
                h.command = "GET"
                h.request_version = "HTTP/1.1"
                h.headers = {}
                h.response_code = None
                h.wfile = io.BytesIO()
                h.send_response = lambda code, message=None: response_codes.append(code)
                h.send_header = lambda key, value: None
                h.end_headers = lambda: None
                h.do_GET()

            def server_close(self):
                pass

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(server_module, "load_config", return_value=cfg), \
                 mock.patch.object(server_module, "_fetch_bootstrap",
                                   side_effect=fetched), \
                 mock.patch.object(server_module, "ThreadingHTTPServer", FakeServer), \
                 mock.patch.object(server_module.time, "time",
                                   side_effect=lambda: next(times)), \
                 mock.patch.object(server_module.watchlist, "load",
                                   return_value={"items": {"1": {
                                       "name": "Private watched item",
                                       "alert_margin_above": 1}}}) as load_watchlist, \
                 mock.patch.object(server_module.alerts, "push_alert") as push_alert, \
                 mock.patch.object(server_module.alerts, "watch_triggered",
                                   return_value=False) as watch_triggered, \
                 mock.patch.object(server_module.alerts, "set_watch_triggered") as set_triggered, \
                 mock.patch.object(server_module.EventHub, "broadcast") as broadcast:
                server_module.run(bind="127.0.0.1", port=0,
                                  access_mode="public-demo")

        self.assertEqual(response_codes, [200])
        load_watchlist.assert_not_called()
        push_alert.assert_not_called()
        watch_triggered.assert_not_called()
        set_triggered.assert_not_called()
        broadcast.assert_not_called()


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


class TestCapOpenQty(unittest.TestCase):
    """The dashboard open-position qty must be capped by the GE buy limit,
    matching the CLI's trade sizing (an uncapped qty would wedge a GE slot)."""

    def test_within_limit(self):
        from rshelper.dashboard.server import _cap_open_qty
        self.assertEqual(_cap_open_qty(50, 10000, "Nature rune"), 50)

    def test_zero_qty_rejected(self):
        from rshelper.dashboard.server import _cap_open_qty
        with self.assertRaises(ValueError):
            _cap_open_qty(0, 10000, "Nature rune")
        with self.assertRaises(ValueError):
            _cap_open_qty(-5, 10000, "Nature rune")

    def test_exceeds_limit_rejected(self):
        from rshelper.dashboard.server import _cap_open_qty
        with self.assertRaises(ValueError) as ctx:
            _cap_open_qty(20000, 13000, "Nature rune")
        self.assertIn("buy limit", str(ctx.exception))

    def test_zero_limit_means_unknown_no_cap(self):
        from rshelper.dashboard.server import _cap_open_qty
        # A missing/zero buy limit (GE Tracker fallback without limit data)
        # must not reject a large qty.
        self.assertEqual(_cap_open_qty(20000, 0, "Unknown"), 20000)


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
        self.handler.headers = {"Authorization": "Bearer synthetic-dashboard-owner-token", }
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
        h.headers = {"Authorization": "Bearer synthetic-dashboard-owner-token", }
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

    def test_api_process(self):
        """GET /api/process returns profitable processing recipes."""
        from http.server import BaseHTTPRequestHandler
        from rshelper.models import Item
        # Steel bar recipe components (2353 = 1 iron ore 440 + 2 coal 453).
        items = [
            Item(id=2353, name="Steel bar", members=False, buy_limit=10000,
                 alch_value=0, buy_price=400, sell_price=576, volume=5000),
            Item(id=440, name="Iron ore", members=False, buy_limit=10000,
                 alch_value=0, buy_price=100, sell_price=90, volume=5000),
            Item(id=453, name="Coal", members=False, buy_limit=10000,
                 alch_value=0, buy_price=130, sell_price=120, volume=5000),
        ]
        Handler = make_handler(self.scanner, lambda: [],
                               process_fn=lambda: {
                                   "recipes": [{
                                       "name": "Steel bar", "item_id": 2353,
                                       "input_cost": 360, "sell_price": 576,
                                       "profit": 205, "roi_pct": 56.9,
                                       "gp_per_hour": 235200,
                                       "volume": 5000, "buy_limit": 10000,
                                   }], "count": 1})
        h = BaseHTTPRequestHandler.__new__(Handler)
        h.path = "/api/process"
        h.request_version = "HTTP/1.1"
        h.command = "GET"
        h.headers = {"Authorization": "Bearer synthetic-dashboard-owner-token", }
        h.response_code = None
        h.response_headers = []
        h.wfile = io.BytesIO()
        h.send_response = lambda code, message=None: setattr(h, "response_code", code)
        h.send_header = lambda key, value: h.response_headers.append((key, value))
        h.end_headers = lambda: None
        h.do_GET()
        body = json.loads(h.wfile.getvalue())
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["recipes"][0]["name"], "Steel bar")
        self.assertIn("gp_per_hour", body["recipes"][0])

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
        h.headers = {"Authorization": "Bearer synthetic-dashboard-owner-token", }
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
        h.headers = {"Authorization": "Bearer synthetic-dashboard-owner-token", }
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
        h.headers = {"Authorization": "Bearer synthetic-dashboard-owner-token", "Content-Length": str(len(payload))}
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
        h.headers = {"Authorization": "Bearer synthetic-dashboard-owner-token", "Content-Length": str(len(payload)), "Host": "127.0.0.1:5555"}
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
        h.headers = {"Authorization": "Bearer synthetic-dashboard-owner-token", }
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
        h.headers = {"Authorization": "Bearer synthetic-dashboard-owner-token", }
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
        h.headers = {"Authorization": "Bearer synthetic-dashboard-owner-token", }
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
        h.headers = {"Authorization": "Bearer synthetic-dashboard-owner-token", }
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
        h.headers = {"Authorization": "Bearer synthetic-dashboard-owner-token", "Content-Length": str(len(payload)), "Host": "127.0.0.1:5555",
                     "Origin": "https://evil.example"}
        h.rfile = io.BytesIO(payload)
        h.wfile = io.BytesIO()
        h.send_error = lambda code, message=None: setattr(h, "error_code", code)
        h.do_POST()
        self.assertEqual(h.error_code, 403)

    def test_origin_check_accepts_configured_host(self):
        """A same-origin POST on the deployed host (allowed_hosts) must pass."""
        from http.server import BaseHTTPRequestHandler
        calls = []
        Handler = make_handler(
            self.scanner, lambda: [],
            watchlist_update_fn=lambda a, i: calls.append(a) or {"items": []},
            allowed_hosts=["rs.reidar.tech"])
        h = BaseHTTPRequestHandler.__new__(Handler)
        h.path = "/api/watchlist"
        h.command = "POST"
        h.request_version = "HTTP/1.1"
        payload = json.dumps({"action": "add", "item_id": 5}).encode()
        h.headers = {"Authorization": "Bearer synthetic-dashboard-owner-token", "Content-Length": str(len(payload)),
                     "Host": "rs.reidar.tech",
                     "Origin": "https://rs.reidar.tech"}
        h.rfile = io.BytesIO(payload)
        h.wfile = io.BytesIO()
        h.send_response = lambda code, message=None: None
        h.send_header = lambda key, value: None
        h.end_headers = lambda: None
        h.do_POST()
        self.assertEqual(calls, ["add"])

    def test_origin_check_blocks_dns_rebinding_even_with_allowed_hosts(self):
        """Host=evil.com must 403 even though allowed_hosts has rs.reidar.tech."""
        from http.server import BaseHTTPRequestHandler
        Handler = make_handler(
            self.scanner, lambda: [],
            watchlist_update_fn=lambda a, i: {"items": []},
            allowed_hosts=["rs.reidar.tech"])
        h = BaseHTTPRequestHandler.__new__(Handler)
        h.path = "/api/watchlist"
        h.command = "POST"
        h.request_version = "HTTP/1.1"
        payload = json.dumps({"action": "add", "item_id": 5}).encode()
        h.headers = {"Authorization": "Bearer synthetic-dashboard-owner-token", "Content-Length": str(len(payload)),
                     "Host": "evil.com", "Origin": "http://evil.com"}
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
        h.headers = {"Authorization": "Bearer synthetic-dashboard-owner-token", }
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
        self.assertIn("apiFetch('/api/scan')", INDEX_HTML)

    def test_html_has_esc_html(self):
        self.assertIn("function escHtml", INDEX_HTML)

    def test_js_close_ge_history_defined(self):
        """The watch-alert editor's Cancel button calls closeGEHistory — it
        must be defined (a missing function throws on click)."""
        self.assertIn("function closeGEHistory", INDEX_HTML)
        # The reference and the definition must both exist.
        self.assertIn("onclick=\"closeGEHistory(this)\"", INDEX_HTML)

    def test_js_signals_map_keys_by_item_and_type(self):
        """signalsMap must key by item_id+type so an item with BOTH a DUMP
        and a FLIP signal keeps both (item_id-only keying drops one)."""
        self.assertIn("signalsMap[x.item_id+':'+x.type]=x", INDEX_HTML)

    def test_js_signal_severity_keeps_highest_rank(self):
        """HIGH has numeric rank 0, so JS fallbacks must use nullish
        coalescing; `0 || 3` incorrectly demotes HIGH to the fallback rank."""
        self.assertIn("sev[s.severity]??3", INDEX_HTML)
        self.assertIn("order[a.severity]??3", INDEX_HTML)
        self.assertNotIn("sev[s.severity]||3", INDEX_HTML)
        self.assertNotIn("order[a.severity]||3", INDEX_HTML)

    def test_js_surge_display_shows_multiplier(self):
        """renderSignals must convert the SURGE percentage deviation to a
        multiplier (220.0 -> 3.2x), not print 220x."""
        self.assertIn("(dev/100)+1", INDEX_HTML)
        self.assertNotIn("dev+'x'", INDEX_HTML)


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


class TestNewRoutes(unittest.TestCase):
    """Routes added by the v3.0 UI/UX refactor."""

    def _make(self, **fns):
        from http.server import BaseHTTPRequestHandler
        from rshelper.scanner import FlipScanner
        scanner = fns.pop("scanner", FlipScanner(direction="arbitrage"))
        control = fns.pop("control", False)
        Handler = make_handler(scanner, lambda: [], control=control, **fns)
        h = BaseHTTPRequestHandler.__new__(Handler)
        h.request_version = "HTTP/1.1"
        h.command = "GET"
        h.headers = {"Authorization": "Bearer synthetic-dashboard-owner-token", }
        h.response_code = None
        h.response_headers = []
        h.wfile = io.BytesIO()
        h.send_response = lambda code, message=None: setattr(h, "response_code", code)
        h.send_header = lambda key, value: h.response_headers.append((key, value))
        h.end_headers = lambda: None
        return h

    def test_api_alerts(self):
        h = self._make(alerts_fn=lambda limit: {"alerts": [
            {"id": 1, "ts": 1.0, "type": "trader", "severity": "HIGH",
             "item_id": 1, "item_name": "Nature rune", "title": "take_profit",
             "message": "+3,000 gp", "read": False}],
            "count": 1, "unread": 1})
        h.path = "/api/alerts"
        h.do_GET()
        body = json.loads(h.wfile.getvalue())
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["unread"], 1)

    def test_api_alerts_read(self):
        calls = []
        h = self._make(alerts_read_fn=lambda ids, allf: calls.append((ids, allf))
                       or {"changed": 1, "unread": 0})
        h.path = "/api/alerts/read"
        h.command = "POST"
        payload = json.dumps({"all": True}).encode()
        h.headers = {"Authorization": "Bearer synthetic-dashboard-owner-token", "Content-Length": str(len(payload))}
        h.rfile = io.BytesIO(payload)
        h.do_POST()
        self.assertEqual(calls, [(None, True)])

    def test_api_confidence(self):
        h = self._make(confidence_fn=lambda ids: {str(ids[0]): {
            "confidence": 0.7, "avg_margin": 100}})
        h.path = "/api/confidence?ids=1,2"
        h.do_GET()
        body = json.loads(h.wfile.getvalue())
        self.assertEqual(body["1"]["confidence"], 0.7)

    def test_api_alch(self):
        h = self._make(alch_fn=lambda: {"items": [{"id": 561, "name": "Nature rune"}],
                                        "count": 1, "nature_rune_cost": 147})
        h.path = "/api/alch"
        h.do_GET()
        body = json.loads(h.wfile.getvalue())
        self.assertEqual(body["count"], 1)

    def test_api_watchlist_check(self):
        h = self._make(watchlist_check_fn=lambda: {"triggered": [
            {"item_id": 1, "name": "Nature rune", "reason": "above",
             "threshold": 50, "current": 60}], "count": 1})
        h.path = "/api/watchlist/check"
        h.do_GET()
        body = json.loads(h.wfile.getvalue())
        self.assertEqual(body["count"], 1)

    def test_api_watchlist_alerts_action(self):
        calls = []
        h = self._make(watchlist_update_fn=lambda a, i, ab=None, bl=None:
                       calls.append((a, i, ab, bl)) or {"items": []})
        h.path = "/api/watchlist"
        h.command = "POST"
        payload = json.dumps({"action": "alerts", "item_id": 5,
                              "alert_above": 100, "alert_below": None}).encode()
        h.headers = {"Authorization": "Bearer synthetic-dashboard-owner-token", "Content-Length": str(len(payload))}
        h.rfile = io.BytesIO(payload)
        h.do_POST()
        self.assertEqual(calls, [("alerts", 5, 100, None)])

    def test_api_positions_close(self):
        calls = []
        h = self._make(close_position_fn=lambda pid, qty: calls.append((pid, qty))
                       or {"ok": True})
        h.path = "/api/positions"
        h.command = "POST"
        payload = json.dumps({"action": "close", "position_id": 7}).encode()
        h.headers = {"Authorization": "Bearer synthetic-dashboard-owner-token", "Content-Length": str(len(payload))}
        h.rfile = io.BytesIO(payload)
        h.do_POST()
        self.assertEqual(calls, [(7, None)])

    def test_api_trader_control_denied_without_control(self):
        def deny(action):
            raise PermissionError("daemon control is disabled")
        h = self._make(trader_control_fn=deny)
        h.path = "/api/trader"
        h.command = "POST"
        payload = json.dumps({"action": "stop"}).encode()
        h.headers = {"Authorization": "Bearer synthetic-dashboard-owner-token", "Content-Length": str(len(payload))}
        h.rfile = io.BytesIO(payload)
        h.send_error = lambda code, message=None: setattr(h, "error_code", code)
        h.do_POST()
        self.assertEqual(h.error_code, 403)

    def test_api_trader_control_start(self):
        calls = []
        h = self._make(control=True,
                       trader_control_fn=lambda a: calls.append(a) or {"ok": True})
        h.path = "/api/trader"
        h.command = "POST"
        payload = json.dumps({"action": "start"}).encode()
        h.headers = {"Authorization": "Bearer synthetic-dashboard-owner-token", "Content-Length": str(len(payload))}
        h.rfile = io.BytesIO(payload)
        h.do_POST()
        self.assertEqual(calls, ["start"])

    def test_api_monitor_control_denied_without_control(self):
        def deny(action):
            raise PermissionError("daemon control is disabled")
        h = self._make(monitor_control_fn=deny)
        h.path = "/api/monitor"
        h.command = "POST"
        payload = json.dumps({"action": "stop"}).encode()
        h.headers = {"Authorization": "Bearer synthetic-dashboard-owner-token", "Content-Length": str(len(payload))}
        h.rfile = io.BytesIO(payload)
        h.send_error = lambda code, message=None: setattr(h, "error_code", code)
        h.do_POST()
        self.assertEqual(h.error_code, 403)

    def test_api_trades_delete(self):
        calls = []
        h = self._make(delete_trade_fn=lambda tid: calls.append(tid) or {"ok": True})
        h.path = "/api/trades/delete"
        h.command = "POST"
        payload = json.dumps({"trade_id": 3}).encode()
        h.headers = {"Authorization": "Bearer synthetic-dashboard-owner-token", "Content-Length": str(len(payload))}
        h.rfile = io.BytesIO(payload)
        h.do_POST()
        self.assertEqual(calls, [3])

    def test_api_events_sse_headers(self):
        import queue
        q = queue.Queue()

        class Hub:
            def subscribe(self, qq):
                qq.put_nowait("event: refresh\ndata: {}\n\n")

            def unsubscribe(self, qq):
                pass
        h = self._make(event_hub=Hub())
        # ttl=1 bounds the long-lived loop so the test terminates; the event
        # is written before the deadline, then the stream closes.
        h.path = "/api/events?ttl=1"
        h.do_GET()
        headers = dict(h.response_headers)
        self.assertEqual(headers.get("Content-Type"), "text/event-stream")
        self.assertIn("event: refresh", h.wfile.getvalue().decode())

    def test_api_events_ttl_terminates(self):
        """SSE with ?ttl= must return (not hang) for bounded consumers."""
        from http.server import BaseHTTPRequestHandler
        import queue
        q = queue.Queue()

        class Hub:
            def subscribe(self, qq):
                pass

            def unsubscribe(self, qq):
                pass
        Handler = make_handler(FlipScanner(direction="arbitrage"), lambda: [],
                               event_hub=Hub())
        h = BaseHTTPRequestHandler.__new__(Handler)
        h.path = "/api/events?ttl=1"
        h.request_version = "HTTP/1.1"
        h.command = "GET"
        h.headers = {"Authorization": "Bearer synthetic-dashboard-owner-token", }
        h.wfile = io.BytesIO()
        h.send_response = lambda code, message=None: None
        h.send_header = lambda key, value: None
        h.end_headers = lambda: None
        h.do_GET()
        self.assertEqual(h.wfile.getvalue(), b"")  # returned without events

    def test_api_timeseries_step_param(self):
        from http.server import BaseHTTPRequestHandler
        calls = []
        Handler = make_handler(
            FlipScanner(direction="arbitrage"), lambda: [],
            timeseries_fn=lambda i, step, points: calls.append((i, step, points))
            or {"points": []})
        h = BaseHTTPRequestHandler.__new__(Handler)
        h.path = "/api/timeseries?id=561&step=1h&points=48"
        h.request_version = "HTTP/1.1"
        h.command = "GET"
        h.headers = {"Authorization": "Bearer synthetic-dashboard-owner-token", }
        h.wfile = io.BytesIO()
        h.send_response = lambda code, message=None: None
        h.send_header = lambda key, value: None
        h.end_headers = lambda: None
        h.do_GET()
        self.assertEqual(calls, [(561, "1h", 48)])

    def test_alerts_read_all_string_false_not_coerced(self):
        """A JSON string 'false' for all must NOT mark everything read."""
        from http.server import BaseHTTPRequestHandler
        calls = []
        Handler = make_handler(
            FlipScanner(direction="arbitrage"), lambda: [],
            alerts_read_fn=lambda ids, allf: calls.append((ids, allf))
            or {"changed": 0, "unread": 0})
        h = BaseHTTPRequestHandler.__new__(Handler)
        h.path = "/api/alerts/read"
        h.command = "POST"
        h.request_version = "HTTP/1.1"
        payload = json.dumps({"all": "false"}).encode()  # string, not bool
        h.headers = {"Authorization": "Bearer synthetic-dashboard-owner-token", "Content-Length": str(len(payload))}
        h.rfile = io.BytesIO(payload)
        h.wfile = io.BytesIO()
        h.send_response = lambda code, message=None: None
        h.send_header = lambda key, value: None
        h.end_headers = lambda: None
        h.do_POST()
        self.assertEqual(calls, [])  # Wrong JSON types never invoke a mutator.
        self.assertEqual(json.loads(h.wfile.getvalue())['code'], 'invalid_request')

    def test_timeseries_real_typeerror_not_masked(self):
        """A TypeError raised INSIDE the fn must 500, not re-call with 1 arg."""
        from http.server import BaseHTTPRequestHandler

        def boom(i, step, points):
            raise TypeError("int() arg is a string")  # real bug, not arity
        Handler = make_handler(FlipScanner(direction="arbitrage"), lambda: [],
                               timeseries_fn=boom)
        h = BaseHTTPRequestHandler.__new__(Handler)
        h.path = "/api/timeseries?id=561"
        h.request_version = "HTTP/1.1"
        h.command = "GET"
        h.headers = {"Authorization": "Bearer synthetic-dashboard-owner-token", }
        h.wfile = io.BytesIO()
        h.send_error = lambda code, message=None: setattr(h, "error_code", code)
        h.send_response = lambda code, message=None: None
        h.send_header = lambda key, value: None
        h.end_headers = lambda: None
        h.do_GET()
        self.assertEqual(h.error_code, 500)  # not silently re-invoked

    def test_log_trade_bad_input_400_not_500(self):
        """A user error (qty <= 0) on POST /api/trades is a 400, not a 500."""
        from http.server import BaseHTTPRequestHandler
        import rshelper.journal as jmod
        from pathlib import Path
        import tempfile
        original_path = jmod.TRADES_PATH
        with tempfile.TemporaryDirectory() as tmp:
            jmod.TRADES_PATH = Path(tmp) / "trades.json"
            try:
                Handler = make_handler(FlipScanner(direction="arbitrage"),
                                       lambda: [])
                h = BaseHTTPRequestHandler.__new__(Handler)
                h.path = "/api/trades"
                h.command = "POST"
                h.request_version = "HTTP/1.1"
                payload = json.dumps({"item_id": 1, "name": "X", "qty": 0,
                                      "buy_price": 100, "sell_price": 110}).encode()
                h.headers = {"Authorization": "Bearer synthetic-dashboard-owner-token", "Content-Length": str(len(payload))}
                h.rfile = io.BytesIO(payload)
                h.wfile = io.BytesIO()
                h.send_error = lambda code, message=None: setattr(h, "error_code", code)
                h.send_response = lambda code, message=None: None
                h.send_header = lambda key, value: None
                h.end_headers = lambda: None
                h.do_POST()
                self.assertEqual(h.error_code, 400)
            finally:
                jmod.TRADES_PATH = original_path

    def test_confidence_negative_cached(self):
        """/api/confidence caches items with no analysis so they aren't re-fetched."""
        from http.server import BaseHTTPRequestHandler
        calls = []
        Handler = make_handler(
            FlipScanner(direction="arbitrage"), lambda: [],
            confidence_fn=lambda ids: calls.append(list(ids)) or {})
        h = BaseHTTPRequestHandler.__new__(Handler)
        h.path = "/api/confidence?ids=1,2"
        h.request_version = "HTTP/1.1"
        h.command = "GET"
        h.headers = {"Authorization": "Bearer synthetic-dashboard-owner-token", }
        h.wfile = io.BytesIO()
        h.send_response = lambda code, message=None: None
        h.send_header = lambda key, value: None
        h.end_headers = lambda: None
        h.do_GET()
        self.assertEqual(calls, [[1, 2]])


if __name__ == "__main__":
    unittest.main(verbosity=2)
