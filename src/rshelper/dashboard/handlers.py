"""HTTP request handlers for the RSHelper dashboard."""

import json
import sys
import time
from http.server import BaseHTTPRequestHandler
from typing import Callable

from rshelper.dashboard.templates import INDEX_HTML


def _item_to_dict(item) -> dict:
    """Serialize an Item dataclass to a JSON-safe dict."""
    return {
        "id": item.id,
        "name": item.name,
        "members": item.members,
        "buy_limit": item.buy_limit,
        "alch_value": item.alch_value,
        "buy_price": item.buy_price,
        "sell_price": item.sell_price,
        "volume": item.volume,
        "profit": item.profit,
        "gp_per_hour": item.gp_per_hour,
        "rs_score": getattr(item, "rs_score", 0.0),
    }


def make_handler(scanner, scan_items: Callable[[], list],
                 signal_detector: Callable[[], list] | None = None,
                 scan_kwargs: dict | None = None) -> type:
    """Return a BaseHTTPRequestHandler subclass.

    scanner: FlipScanner instance
    scan_items: Callable that returns list[Item] (fresh fetch each call)
    signal_detector: Optional callable that returns list[Signal] for /api/signals
    scan_kwargs: Optional kwargs (members_only, min_volume, min_margin) for scanner.scan
    """

    class DashboardHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/":
                self._serve_html()
            elif path == "/api/scan":
                self._serve_scan()
            elif path == "/api/health":
                self._serve_health()
            elif path == "/api/monitor":
                self._serve_monitor()
            elif path == "/api/signals":
                self._serve_signals()
            elif path == "/api/trades":
                self._serve_trades()
            elif path == "/api/pnl":
                self._serve_pnl()
            elif path == "/api/history":
                self._serve_history()
            else:
                self.send_error(404)

        def do_POST(self):
            path = self.path.split("?", 1)[0]
            if path == "/api/trades":
                self._handle_log_trade()
            else:
                self.send_error(404)

        def _serve_html(self):
            body = INDEX_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)

        def _serve_scan(self):
            try:
                items = scan_items()
                results = scanner.scan(items, **(scan_kwargs or {}))
                data = {
                    "items": [_item_to_dict(r) for r in results],
                    "count": len(results),
                    "timestamp": time.time(),
                }
                self._serve_json(data)
            except Exception as e:
                print(f"[dashboard] scan error: {e}", file=sys.stderr)
                self.send_error(500, "Scan failed")

        def _serve_health(self):
            import os
            from rshelper import __version__
            version = os.environ.get("VERSION") or __version__
            self._serve_json({"status": "healthy", "version": version})

        def _serve_signals(self):
            if signal_detector is None:
                self._serve_json({"signals": [], "count": 0})
                return
            try:
                signals = signal_detector()
                data = {
                    "signals": [
                        {"type": s.type, "item_id": s.item_id, "name": s.name,
                         "severity": s.severity, "current_price": s.current_price,
                         "deviation": s.deviation, "message": s.message}
                        for s in signals
                    ],
                    "count": len(signals),
                }
                self._serve_json(data)
            except Exception as e:
                print(f"[dashboard] signals error: {e}", file=sys.stderr)
                self.send_error(500, "Signal detection failed")

        def _serve_monitor(self):
            from rshelper.monitor import monitor_status
            status = monitor_status()
            self._serve_json(status if status else {"running": False})

        def _serve_trades(self):
            from rshelper.journal import list_trades
            from dataclasses import asdict
            trades = list_trades()
            self._serve_json({"trades": [asdict(t) for t in trades], "count": len(trades)})

        def _serve_pnl(self):
            from rshelper.journal import compute_pnl
            pnl = compute_pnl()
            d = {"total_profit": pnl.total_profit, "total_tax_paid": pnl.total_tax_paid,
                 "total_cost_basis": pnl.total_cost_basis,
                 "roi_pct": round(pnl.roi_pct, 2),
                 "trade_count": pnl.trade_count, "winning_trades": pnl.winning_trades,
                 "losing_trades": pnl.losing_trades, "win_rate": round(pnl.win_rate, 1),
                 "active_gp_per_hour": pnl.active_gp_per_hour, "items_traded": pnl.items_traded}
            if pnl.best_trade:
                d["best_trade"] = pnl.best_trade.profit
            if pnl.worst_trade:
                d["worst_trade"] = pnl.worst_trade.profit
            self._serve_json(d)

        def _serve_history(self):
            from urllib.parse import parse_qs
            from rshelper.history import build_history
            qs = parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
            paper_only = qs.get("paper", ["1"])[0] != "0"
            try:
                self._serve_json(build_history(paper_only=paper_only))
            except Exception as e:
                print(f"[dashboard] history error: {e}", file=sys.stderr)
                self.send_error(500, "History failed")

        def _handle_log_trade(self):
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                data = json.loads(body)
            except Exception:
                self.send_error(400, "Invalid JSON")
                return
            try:
                from rshelper.journal import log_trade
                trade = log_trade(
                    data.get("item_id", 0), data.get("name", ""),
                    data.get("qty", 0), data.get("buy_price", 0),
                    data.get("sell_price", 0), data.get("note", "")
                )
                from dataclasses import asdict
                self._serve_json(asdict(trade))
            except Exception as e:
                print(f"[dashboard] trade log error: {e}", file=sys.stderr)
                self.send_error(500, "Trade logging failed")

        def _serve_json(self, data):
            body = json.dumps(data).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            print(f"[dashboard] {format % args}", file=sys.stderr)

    return DashboardHandler
