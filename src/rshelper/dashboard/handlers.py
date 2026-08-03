"""HTTP request handlers for the RSHelper dashboard."""

import json
import sys
import time
from http.server import BaseHTTPRequestHandler
from typing import Callable
from urllib.parse import parse_qs, urlparse

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
                 scan_kwargs: dict | None = None,
                 price_lookup: Callable[[list[int]], dict] | None = None,
                 meta_fn: Callable[[], dict] | None = None,
                 watchlist_fn: Callable[[], dict] | None = None,
                 watchlist_update_fn: Callable[[str, int], dict] | None = None,
                 timeseries_fn: Callable[[int], dict] | None = None,
                 positions_fn: Callable[[], dict] | None = None,
                 paper_trade_fn: Callable[[str, str, int], dict] | None = None,
                 trader_fn: Callable[[], dict] | None = None,
                 ge_fn: Callable[[], dict] | None = None,
                 ge_collect_fn: Callable[[int], dict] | None = None,
                 bank_fn: Callable[[], dict] | None = None) -> type:
    """Return a BaseHTTPRequestHandler subclass.

    scanner: FlipScanner instance
    scan_items: Callable that returns list[Item] (fresh fetch each call)
    signal_detector: Optional callable that returns list[Signal] for /api/signals
    scan_kwargs: Optional kwargs (members_only, min_volume, min_margin) for scanner.scan
    price_lookup: Optional callable(list[item_id]) -> {id: {usable, buy, sell}}
    meta_fn: Optional callable() -> {source, items, signals, watchlist, last_fetch}
    watchlist_fn: Optional callable() -> {items: [...]}
    watchlist_update_fn: Optional callable(action, item_id) -> {items: [...]}
    timeseries_fn: Optional callable(item_id) -> {points: [...]}
    positions_fn: Optional callable() -> {positions, open_qty, unrealized}
    paper_trade_fn: Optional callable(action, item, qty) -> {ok, ...}
    trader_fn: Optional callable() -> trader status dict
    ge_fn: Optional callable() -> GE slots dict for /api/ge
    ge_collect_fn: Optional callable(position_id) -> collect result for /api/ge/collect
    bank_fn: Optional callable() -> bank holdings dict for /api/bank
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
            elif path == "/api/prices":
                self._serve_prices()
            elif path == "/api/meta":
                self._serve_meta()
            elif path == "/api/watchlist":
                self._serve_watchlist()
            elif path == "/api/timeseries":
                self._serve_timeseries()
            elif path == "/api/positions":
                self._serve_positions()
            elif path == "/api/trader":
                self._serve_trader()
            elif path == "/api/ge":
                self._serve_ge()
            elif path == "/api/bank":
                self._serve_bank()
            else:
                self.send_error(404)

        def do_POST(self):
            path = self.path.split("?", 1)[0]
            if not self._origin_ok():
                self.send_error(403, "Origin check failed")
                return
            if path == "/api/trades":
                self._handle_log_trade()
            elif path == "/api/watchlist":
                self._handle_watchlist()
            elif path == "/api/paper":
                self._handle_paper_trade()
            elif path == "/api/ge/collect":
                self._handle_ge_collect()
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
            q = self._query()
            note = q.get("note", [""])[0]
            strategy = q.get("strategy", [""])[0]
            trades = list_trades(note=note, strategy=strategy)
            self._serve_json({"trades": [asdict(t) for t in trades], "count": len(trades)})

        def _serve_pnl(self):
            from rshelper.journal import compute_pnl
            q = self._query()
            note = q.get("note", [""])[0]
            strategy = q.get("strategy", [""])[0]
            pnl = compute_pnl(note=note, strategy=strategy)
            d = {"total_profit": pnl.total_profit, "total_tax_paid": pnl.total_tax_paid,
                 "total_cost_basis": pnl.total_cost_basis,
                 "roi_pct": round(pnl.roi_pct, 2),
                 "trade_count": pnl.trade_count, "winning_trades": pnl.winning_trades,
                 "losing_trades": pnl.losing_trades, "win_rate": round(pnl.win_rate, 1),
                 "active_gp_per_hour": pnl.active_gp_per_hour, "items_traded": pnl.items_traded,
                 "profit_factor": (round(pnl.profit_factor, 2)
                                   if pnl.profit_factor != float("inf") else None),
                 "max_drawdown": pnl.max_drawdown}
            if pnl.best_trade:
                d["best_trade"] = pnl.best_trade.profit
            if pnl.worst_trade:
                d["worst_trade"] = pnl.worst_trade.profit
            self._serve_json(d)

        def _serve_history(self):
            from rshelper.history import build_history
            qs = self._query()
            paper_only = qs.get("paper", ["1"])[0] != "0"
            strategy = qs.get("strategy", [""])[0]
            try:
                self._serve_json(build_history(paper_only=paper_only,
                                               strategy=strategy))
            except Exception as e:
                print(f"[dashboard] history error: {e}", file=sys.stderr)
                self.send_error(500, "History failed")

        def _serve_prices(self):
            if price_lookup is None:
                self._serve_json({"prices": {}})
                return
            qs = self._query()
            raw = qs.get("ids", [""])[0]
            ids = [int(i) for i in raw.split(",") if i.strip().isdigit()]
            self._serve_json({"prices": price_lookup(ids)})

        def _serve_meta(self):
            self._serve_json(meta_fn() if meta_fn else {"source": "unknown"})

        def _serve_watchlist(self):
            self._serve_json(watchlist_fn() if watchlist_fn else {"items": []})

        def _serve_timeseries(self):
            qs = self._query()
            raw = qs.get("id", [""])[0]
            if not raw.isdigit():
                self.send_error(400, "Invalid item id")
                return
            item_id = int(raw)
            self._serve_json(timeseries_fn(item_id) if timeseries_fn else {"points": []})

        def _serve_positions(self):
            self._serve_json(positions_fn() if positions_fn else
                             {"positions": [], "open_qty": 0, "unrealized": 0})

        def _serve_trader(self):
            self._serve_json(trader_fn() if trader_fn else {"running": False})

        def _serve_ge(self):
            try:
                self._serve_json(ge_fn() if ge_fn else
                                 {"slots": [], "empty_count": 8,
                                  "total_value": 0})
            except Exception as e:
                print(f"[dashboard] GE data error: {e}", file=sys.stderr)
                self.send_error(500, "GE data failed")

        def _serve_bank(self):
            try:
                self._serve_json(bank_fn() if bank_fn else
                                 {"items": [], "total_value": 0,
                                  "unrealized_pnl": 0, "cost_basis": 0,
                                  "slot_count": 0})
            except Exception as e:
                print(f"[dashboard] bank data error: {e}", file=sys.stderr)
                self.send_error(500, "Bank data failed")

        def _handle_ge_collect(self):
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length))
                position_id = int(body.get("position_id", 0))
            except Exception:
                self.send_error(400, "Invalid JSON")
                return
            if ge_collect_fn is None:
                self.send_error(404)
                return
            try:
                self._serve_json(ge_collect_fn(position_id))
            except (ValueError, TypeError) as e:
                print(f"[dashboard] GE collect error: {e}", file=sys.stderr)
                self.send_error(400, str(e))

        def _handle_paper_trade(self):
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length))
                action = body.get("action", "")
                item = body.get("item", "")
                qty = int(body.get("qty", 0))
            except Exception:
                self.send_error(400, "Invalid JSON")
                return
            if paper_trade_fn is None:
                self.send_error(404)
                return
            try:
                self._serve_json(paper_trade_fn(action, item, qty))
            except (ValueError, TypeError) as e:
                print(f"[dashboard] paper trade error: {e}", file=sys.stderr)
                self.send_error(400, str(e))

        def _handle_watchlist(self):
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length))
                action = body.get("action", "")
                item_id = int(body.get("item_id", 0))
            except Exception:
                self.send_error(400, "Invalid JSON")
                return
            if watchlist_update_fn is None:
                self.send_error(404)
                return
            try:
                self._serve_json(watchlist_update_fn(action, item_id))
            except (ValueError, TypeError) as e:
                print(f"[dashboard] watchlist error: {e}", file=sys.stderr)
                self.send_error(400, "Watchlist update failed")

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

        def _query(self):
            return parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}

        def _origin_ok(self) -> bool:
            """Reject state-mutating requests from foreign origins."""
            origin = self.headers.get("Origin")
            if not origin:
                return True
            host = self.headers.get("Host", "")
            return bool(host) and urlparse(origin).netloc == host

        def log_message(self, format, *args):
            print(f"[dashboard] {format % args}", file=sys.stderr)

    return DashboardHandler
