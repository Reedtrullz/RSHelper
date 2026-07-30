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
        self.assertEqual(body["status"], "ok")

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
