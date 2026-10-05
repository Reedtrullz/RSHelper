"""HTTP request handlers for the RSHelper dashboard."""

import json
import re
import socket
import sys
import time
from http.server import BaseHTTPRequestHandler
from typing import Callable
from urllib.parse import urlparse

from rshelper.market_data import market_snapshot
from rshelper.dashboard.templates import INDEX_HTML
from rshelper.dashboard.http_inputs import (
    HttpInputError, MAX_BODY_BYTES, decode_object, parse_query, validate_operation,
)


_GET_RESOURCES = {
    "/": "static",
    "/api/capabilities": "capabilities",
    "/api/health": "sanitized-health",
    "/api/scan": "public-market",
    "/api/prices": "public-market",
    "/api/timeseries": "public-market",
    "/api/process": "public-market",
    "/api/alch": "public-market",
    "/api/confidence": "public-market",
    "/api/monitor": "private-state",
    "/api/signals": "private-state",
    "/api/trades": "private-state",
    "/api/pnl": "private-state",
    "/api/history": "private-state",
    "/api/meta": "private-state",
    "/api/watchlist": "private-state",
    "/api/watchlist/check": "private-state",
    "/api/positions": "private-state",
    "/api/trader": "private-state",
    "/api/ge": "private-state",
    "/api/bank": "private-state",
    "/api/alerts": "private-state",
    "/api/events": "private-state",
}

_POST_RESOURCES = {
    "/api/trades": "private-state",
    "/api/watchlist": "private-state",
    "/api/paper": "private-state",
    "/api/ge/collect": "private-state",
    "/api/positions": "private-state",
    "/api/trader": "daemon-control",
    "/api/monitor": "daemon-control",
    "/api/alerts/read": "private-state",
    "/api/trades/delete": "private-state",
}


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
        "market_data": getattr(item, "market_data", {}),
    }


def make_handler(scanner, scan_items: Callable[[], list],
                 signal_detector: Callable[[], list] | None = None,
                 scan_kwargs: dict | None = None,
                 price_lookup: Callable[[list[int]], dict] | None = None,
                 meta_fn: Callable[[], dict] | None = None,
                 watchlist_fn: Callable[[], dict] | None = None,
                 watchlist_update_fn: Callable[..., dict] | None = None,
                 watchlist_check_fn: Callable[[], dict] | None = None,
                 timeseries_fn: Callable[[int, str, int], dict] | None = None,
                 positions_fn: Callable[[], dict] | None = None,
                 close_position_fn: Callable[[int, int | None], dict] | None = None,
                 paper_trade_fn: Callable[[str, str, int], dict] | None = None,
                 trader_fn: Callable[[], dict] | None = None,
                 trader_control_fn: Callable[[str], dict] | None = None,
                 monitor_fn: Callable[[], dict] | None = None,
                 monitor_control_fn: Callable[[str], dict] | None = None,
                 ge_fn: Callable[[], dict] | None = None,
                 ge_collect_fn: Callable[[int], dict] | None = None,
                 bank_fn: Callable[[], dict] | None = None,
                 process_fn: Callable[[], dict] | None = None,
                 alch_fn: Callable[[], dict] | None = None,
                 confidence_fn: Callable[[list[int]], dict] | None = None,
                 alerts_fn: Callable[[int], dict] | None = None,
                 alerts_read_fn: Callable[[list[int] | None, bool], dict] | None = None,
                 history_fn: Callable[[bool, str], dict] | None = None,
                 trades_fn: Callable[[str, str], dict] | None = None,
                 pnl_fn: Callable[[str, str], dict] | None = None,
                 delete_trade_fn: Callable[[int], dict] | None = None,
                 log_trade_fn: Callable[..., dict] | None = None,
                 event_hub=None,
                 allowed_hosts: list[str] | None = None,
                 mode: str = "owner", owner_token: str | None = None,
                 control: bool = False) -> type:
    """Return a BaseHTTPRequestHandler subclass.

    scanner: FlipScanner instance
    scan_items: Callable that returns list[Item] (fresh fetch each call)
    signal_detector: Optional callable that returns list[Signal] for /api/signals
    scan_kwargs: Optional kwargs (members_only, min_volume, min_margin) for scanner.scan
    price_lookup: Optional callable(list[item_id]) -> {id: {usable, buy, sell}}
    meta_fn: Optional callable() -> {source, items, signals, watchlist, last_fetch}
    watchlist_fn: Optional callable() -> {items: [...]}
    watchlist_update_fn: Optional callable(action, item_id, ...) -> {items: [...]}
    watchlist_check_fn: Optional callable() -> {triggered: [...]}
    timeseries_fn: Optional callable(item_id, step, points) -> {points: [...]}
    positions_fn: Optional callable() -> {positions, open_qty, unrealized}
    close_position_fn: Optional callable(position_id, qty) -> {ok, ...}
    paper_trade_fn: Optional callable(action, item, qty) -> {ok, ...}
    trader_fn: Optional callable() -> trader status dict
    trader_control_fn: Optional callable(action) -> {ok, ...} (403 without control)
    monitor_fn: Optional callable() -> monitor status dict
    monitor_control_fn: Optional callable(action) -> {ok, ...} (403 without control)
    ge_fn: Optional callable() -> GE slots dict for /api/ge
    ge_collect_fn: Optional callable(position_id) -> collect result for /api/ge/collect
    bank_fn: Optional callable() -> bank holdings dict for /api/bank
    process_fn: Optional callable() -> processing recipes dict for /api/process
    alch_fn: Optional callable() -> alch scan dict for /api/alch
    confidence_fn: Optional callable(ids) -> {id: {...}} for /api/confidence
    alerts_fn: Optional callable(limit) -> {alerts, unread} for /api/alerts
    alerts_read_fn: Optional callable(ids, all) -> {changed, unread}
    history_fn: Optional callable(paper_only, strategy) -> history dict
    trades_fn: Optional callable(note, strategy) -> {trades, count}
    pnl_fn: Optional callable(note, strategy) -> pnl dict
    delete_trade_fn: Optional callable(trade_id) -> {ok}
    log_trade_fn: Optional callable(item_id, name, qty, buy, sell, note) -> trade dict
    event_hub: Optional EventHub for SSE broadcasts
    """

    class DashboardHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        body_read_timeout = 5.0

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            resource = _GET_RESOURCES.get(path)
            if resource is not None and not self._authorize(resource, False):
                return
            try:
                self._query()
            except HttpInputError as exc:
                self.send_error(exc.status, str(exc))
                return
            if path == "/":
                self._serve_html()
            elif path == "/api/capabilities":
                self._serve_capabilities()
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
            elif path == "/api/watchlist/check":
                self._serve_watchlist_check()
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
            elif path == "/api/process":
                self._serve_process()
            elif path == "/api/alch":
                self._serve_alch()
            elif path == "/api/confidence":
                self._serve_confidence()
            elif path == "/api/alerts":
                self._serve_alerts()
            elif path == "/api/events":
                self._serve_events()
            else:
                self.send_error(404)

        def do_POST(self):
            # A handler serves multiple requests on an HTTP/1.1 connection.
            self.__dict__.pop('_json_body', None)
            path = self.path.split("?", 1)[0]
            resource = _POST_RESOURCES.get(path)
            if resource is not None:
                if not self._authorize(resource, True):
                    return
            if not self._origin_ok():
                self.send_error(403, "Origin check failed")
                return
            if resource == "daemon-control" and not control:
                self.send_error(403, "Daemon control is disabled")
                return
            if resource is not None:
                try:
                    self._query()
                    self._json_body = self._read_json_object()
                except HttpInputError as exc:
                    self.send_error(exc.status, str(exc))
                    return
            if path == "/api/trades":
                self._handle_log_trade()
            elif path == "/api/watchlist":
                self._handle_watchlist()
            elif path == "/api/paper":
                self._handle_paper_trade()
            elif path == "/api/ge/collect":
                self._handle_ge_collect()
            elif path == "/api/positions":
                self._handle_close_position()
            elif path == "/api/trader":
                self._handle_trader_control()
            elif path == "/api/monitor":
                self._handle_monitor_control()
            elif path == "/api/alerts/read":
                self._handle_alerts_read()
            elif path == "/api/trades/delete":
                self._handle_trade_delete()
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
                    "market_data": getattr(items[0],"market_data",{}) if items else market_snapshot(None, None, None),
                    "count": len(results),
                    "timestamp": time.time(),
                }
                self._serve_json(data)
            except Exception as e:
                print(f"[dashboard] scan error: {e}", file=sys.stderr)
                self.send_error(500, "Scan failed")

        def _serve_health(self):
            from rshelper.release import health_metadata, ReleaseMetadataError
            try:
                self._serve_json(health_metadata())
            except ReleaseMetadataError:
                self.send_error(500, 'Invalid image build metadata')

        def _serve_capabilities(self):
            features = ["market", "static", "health"]
            if mode == "owner":
                features.append("private-state")
                if control:
                    features.append("daemon-control")
            self._serve_json({"mode": mode, "features": features})

        def _authorize(self, resource: str, mutation: bool) -> bool:
            from rshelper.dashboard.access import authorize
            if authorize(mode, self.headers.get("Authorization"), owner_token,
                         resource, mutation):
                return True
            status = 401 if mode == "owner" else 403
            self.send_error(status, "Authorization required")
            return False

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
                         "deviation": s.deviation, "message": s.message,
                         "market_data":getattr(s,"market_data",{})}
                        for s in signals
                    ],
                    "count": len(signals),
                }
                self._serve_json(data)
            except Exception as e:
                print(f"[dashboard] signals error: {e}", file=sys.stderr)
                self.send_error(500, "Signal detection failed")

        def _serve_monitor(self):
            try:
                self._serve_json(monitor_fn() if monitor_fn else {"running": False})
            except Exception as e:
                print(f"[dashboard] monitor error: {e}", file=sys.stderr)
                self.send_error(500, "Monitor status failed")

        def _serve_trades(self):
            q = self._query()
            note = q.get("note", [""])[0]
            strategy = q.get("strategy", [""])[0]
            try:
                if trades_fn:
                    self._serve_json(trades_fn(note, strategy))
                    return
                from rshelper.journal import list_trades
                from dataclasses import asdict
                trades = list_trades(note=note, strategy=strategy)
                self._serve_json({"trades": [asdict(t) for t in trades], "count": len(trades)})
            except Exception as e:
                print(f"[dashboard] trades error: {e}", file=sys.stderr)
                self.send_error(500, "Trades failed")

        def _serve_pnl(self):
            q = self._query()
            note = q.get("note", [""])[0]
            strategy = q.get("strategy", [""])[0]
            if pnl_fn:
                self._serve_json(pnl_fn(note, strategy))
                return
            from rshelper.journal import compute_pnl
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
            qs = self._query()
            paper_only = qs.get("paper", ["1"])[0] != "0"
            strategy = qs.get("strategy", [""])[0]
            try:
                if history_fn:
                    self._serve_json(history_fn(paper_only, strategy))
                    return
                from rshelper.history import build_history
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
            try:
                self._serve_json({"prices": price_lookup(ids)})
            except Exception as e:
                print(f"[dashboard] prices error: {e}", file=sys.stderr)
                self.send_error(500, "Prices failed")

        def _serve_meta(self):
            self._serve_json(meta_fn() if meta_fn else {"source": "unknown"})

        def _serve_watchlist(self):
            self._serve_json(watchlist_fn() if watchlist_fn else {"items": []})

        def _serve_watchlist_check(self):
            try:
                self._serve_json(watchlist_check_fn() if watchlist_check_fn
                                 else {"triggered": [], "count": 0})
            except Exception as e:
                print(f"[dashboard] watchlist check error: {e}", file=sys.stderr)
                self.send_error(500, "Watchlist check failed")

        def _serve_timeseries(self):
            qs = self._query()
            raw = qs.get("id", [""])[0]
            if not raw.isdigit():
                self.send_error(400, "Invalid item id")
                return
            item_id = int(raw)
            step = qs.get("step", ["5m"])[0]
            if step not in ("5m", "1h", "6h", "24h"):
                step = "5m"
            points = 96
            if qs.get("points", [""])[0].isdigit():
                points = min(1000, int(qs["points"][0]))
            try:
                fn = timeseries_fn
                if fn is None:
                    self._serve_json({"points": []})
                else:
                    # Check arity by signature so a real TypeError raised
                    # INSIDE the function isn't mistaken for a wrong-arity
                    # call (which would double-fetch and mask the bug).
                    import inspect
                    try:
                        sig = inspect.signature(fn)
                        n_params = len([p for p in sig.parameters.values()
                                        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)])
                    except (TypeError, ValueError):
                        n_params = 3  # builtin without a signature: assume new arity
                    if n_params >= 3:
                        self._serve_json(fn(item_id, step, points))
                    else:
                        self._serve_json(fn(item_id))
            except Exception as e:
                print(f"[dashboard] timeseries error: {e}", file=sys.stderr)
                self.send_error(500, "Timeseries failed")

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

        def _serve_process(self):
            try:
                self._serve_json(process_fn() if process_fn else
                                 {"recipes": [], "count": 0})
            except Exception as e:
                print(f"[dashboard] process data error: {e}", file=sys.stderr)
                self.send_error(500, "Process data failed")

        def _serve_alch(self):
            try:
                self._serve_json(alch_fn() if alch_fn else {"items": [], "count": 0})
            except Exception as e:
                print(f"[dashboard] alch data error: {e}", file=sys.stderr)
                self.send_error(500, "Alch data failed")

        def _serve_confidence(self):
            if confidence_fn is None:
                self._serve_json({})
                return
            qs = self._query()
            raw = qs.get("ids", [""])[0]
            ids = [int(i) for i in raw.split(",") if i.strip().isdigit()]
            try:
                self._serve_json(confidence_fn(ids))
            except Exception as e:
                print(f"[dashboard] confidence error: {e}", file=sys.stderr)
                self.send_error(500, "Confidence failed")

        def _serve_alerts(self):
            qs = self._query()
            limit = 50
            if qs.get("limit", [""])[0].isdigit():
                limit = min(200, int(qs["limit"][0]))
            self._serve_json(alerts_fn(limit) if alerts_fn
                             else {"alerts": [], "count": 0, "unread": 0})

        def _serve_events(self):
            """Server-Sent Events: refresh + alert pushes, heartbeat comments.

            Long-lived: the stream stays open across events and only closes
            on a broken pipe, a bounded ?ttl= (for tests/curl), or when the
            handler is asked to stop. Browsers receive every push; the 0.2s
            drain-and-return behavior was removed because it dropped events
            broadcast just after a refresh.
            """
            import queue as _queue
            q: _queue.Queue = _queue.Queue()
            if event_hub is not None:
                event_hub.subscribe(q)
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                # Same-origin only: a wildcard ACAO would let any website read
                # the alert stream (item names/prices) via EventSource.
                self.end_headers()
                deadline = None
                raw_ttl = self._query().get("ttl", [""])[0]
                if raw_ttl.isdigit():
                    deadline = time.time() + min(int(raw_ttl), 60)
                last_heartbeat = time.time()
                while True:
                    # Honor the deadline BEFORE the blocking wait so a
                    # bounded consumer (?ttl=) terminates immediately instead
                    # of always eating a full 15s queue timeout.
                    if deadline is not None and time.time() >= deadline:
                        return
                    try:
                        item = q.get(timeout=min(15, max(0.1, (deadline - time.time())
                                                         if deadline else 15)))
                        self.wfile.write(item.encode("utf-8"))
                        self.wfile.flush()
                    except _queue.Empty:
                        if deadline is not None and time.time() >= deadline:
                            return
                        if time.time() - last_heartbeat >= 15:
                            self.wfile.write(b": heartbeat\n\n")
                            self.wfile.flush()
                            last_heartbeat = time.time()
                        continue
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        return
            finally:
                if event_hub is not None:
                    event_hub.unsubscribe(q)

        def _handle_ge_collect(self):
            try:
                body = self._read_json_object()
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
                body = self._read_json_object()
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
                body = self._read_json_object()
                action = body.get("action", "")
                item_id = int(body.get("item_id", 0))
                above = body.get("alert_above")
                below = body.get("alert_below")
                if above is not None:
                    above = int(above)
                if below is not None:
                    below = int(below)
            except Exception:
                self.send_error(400, "Invalid JSON")
                return
            if watchlist_update_fn is None:
                self.send_error(404)
                return
            try:
                if action == "alerts":
                    self._serve_json(watchlist_update_fn(action, item_id,
                                                         above, below))
                else:
                    self._serve_json(watchlist_update_fn(action, item_id))
            except (ValueError, TypeError) as e:
                print(f"[dashboard] watchlist error: {e}", file=sys.stderr)
                self.send_error(400, "Watchlist update failed")

        def _handle_close_position(self):
            try:
                body = self._read_json_object()
                action = body.get("action", "")
                position_id = int(body.get("position_id", 0))
                qty = body.get("qty")
                qty = int(qty) if qty not in (None, "") else None
            except Exception:
                self.send_error(400, "Invalid JSON")
                return
            if close_position_fn is None:
                self.send_error(404)
                return
            if action != "close":
                self.send_error(400, "Unknown action")
                return
            try:
                self._serve_json(close_position_fn(position_id, qty))
            except (ValueError, TypeError) as e:
                print(f"[dashboard] close position error: {e}", file=sys.stderr)
                self.send_error(400, str(e))

        def _handle_trader_control(self):
            try:
                body = self._read_json_object()
                action = body.get("action", "")
            except Exception:
                self.send_error(400, "Invalid JSON")
                return
            if trader_control_fn is None:
                self.send_error(404)
                return
            try:
                self._serve_json(trader_control_fn(action))
            except PermissionError as e:
                print(f"[dashboard] trader control denied: {e}", file=sys.stderr)
                self.send_error(403, str(e))
            except (ValueError, TypeError) as e:
                print(f"[dashboard] trader control error: {e}", file=sys.stderr)
                self.send_error(400, str(e))

        def _handle_monitor_control(self):
            try:
                body = self._read_json_object()
                action = body.get("action", "")
            except Exception:
                self.send_error(400, "Invalid JSON")
                return
            if monitor_control_fn is None:
                self.send_error(404)
                return
            try:
                self._serve_json(monitor_control_fn(action))
            except PermissionError as e:
                print(f"[dashboard] monitor control denied: {e}", file=sys.stderr)
                self.send_error(403, str(e))
            except (ValueError, TypeError) as e:
                print(f"[dashboard] monitor control error: {e}", file=sys.stderr)
                self.send_error(400, str(e))

        def _handle_alerts_read(self):
            try:
                body = self._read_json_object()
                ids = body.get("ids")
                # Strict bool: a JSON string "false" must not coerce to True.
                all_flag = body.get("all") is True
                ids = [int(i) for i in ids] if isinstance(ids, list) else None
            except Exception:
                self.send_error(400, "Invalid JSON")
                return
            if alerts_read_fn is None:
                self.send_error(404)
                return
            try:
                self._serve_json(alerts_read_fn(ids, all_flag))
            except (ValueError, TypeError) as e:
                print(f"[dashboard] alerts read error: {e}", file=sys.stderr)
                self.send_error(400, str(e))

        def _handle_trade_delete(self):
            try:
                body = self._read_json_object()
                trade_id = int(body.get("trade_id", 0))
            except Exception:
                self.send_error(400, "Invalid JSON")
                return
            if delete_trade_fn is None:
                self.send_error(404)
                return
            try:
                self._serve_json(delete_trade_fn(trade_id))
            except (ValueError, TypeError) as e:
                print(f"[dashboard] trade delete error: {e}", file=sys.stderr)
                self.send_error(400, str(e))

        def _handle_log_trade(self):
            try:
                data = self._read_json_object()
            except Exception:
                self.send_error(400, "Invalid JSON")
                return
            try:
                if log_trade_fn:
                    trade = log_trade_fn(
                        data.get("item_id", 0), data.get("name", ""),
                        data.get("qty", 0), data.get("buy_price", 0),
                        data.get("sell_price", 0), data.get("note", ""))
                    self._serve_json(trade)
                    return
                from rshelper.journal import log_trade
                trade = log_trade(
                    data.get("item_id", 0), data.get("name", ""),
                    data.get("qty", 0), data.get("buy_price", 0),
                    data.get("sell_price", 0), data.get("note", "")
                )
                from dataclasses import asdict
                self._serve_json(asdict(trade))
            except (ValueError, TypeError) as e:
                # User error (qty <= 0, non-positive price) is a 400, not a 500.
                print(f"[dashboard] trade log error: {e}", file=sys.stderr)
                self.send_error(400, str(e))
            except Exception as e:
                print(f"[dashboard] trade log error: {e}", file=sys.stderr)
                self.send_error(500, "Trade logging failed")

        def _read_json_object(self):
            if hasattr(self, '_json_body'):
                return self._json_body
            get_all = getattr(self.headers, 'get_all', None)
            lengths = get_all('Content-Length', []) if get_all else (
                [self.headers['Content-Length']] if 'Content-Length' in self.headers else [])
            if self.headers.get('Transfer-Encoding') is not None:
                raise HttpInputError('Transfer-Encoding is not supported')
            if not lengths:
                raise HttpInputError('Content-Length is required', 411, 'length_required')
            if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdecimal():
                raise HttpInputError('Invalid Content-Length')
            # Avoid converting a huge integer just to reject it.
            if len(lengths[0]) > 10:
                raise HttpInputError('Body exceeds 65536-byte limit', 413, 'body_too_large')
            length = int(lengths[0])
            if length > MAX_BODY_BYTES:
                raise HttpInputError('Body exceeds 65536-byte limit', 413, 'body_too_large')
            deadline = time.monotonic() + self.body_read_timeout
            connection = getattr(self, 'connection', None)
            old_timeout = connection.gettimeout() if connection is not None else None
            content = bytearray()
            try:
                while len(content) < length:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0: raise HttpInputError('Body read deadline exceeded', 408, 'body_timeout')
                    if connection is not None: connection.settimeout(remaining)
                    read = getattr(self.rfile, 'read1', self.rfile.read)
                    chunk = read(length-len(content))
                    if not chunk: raise HttpInputError('Incomplete request body')
                    content.extend(chunk)
            except (TimeoutError, socket.timeout) as exc:
                raise HttpInputError('Body read deadline exceeded', 408, 'body_timeout') from exc
            finally:
                if connection is not None: connection.settimeout(old_timeout)
            return validate_operation(self.path.partition('?')[0], decode_object(content))

        def _json_error(self, status, code, message):
            self.close_connection = True
            body = json.dumps({'ok': False, 'code': code, 'message': message,
                               'error': message}).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Connection', 'close')
            self.end_headers()
            if getattr(self, 'command', '') != 'HEAD': self.wfile.write(body)

        def send_error(self, code, message=None, explain=None):
            if getattr(self, 'path', '').partition('?')[0].startswith('/api/'):
                codes = {400: 'invalid_request', 401: 'unauthorized', 403: 'forbidden',
                         404: 'not_found', 408: 'body_timeout', 411: 'length_required',
                         413: 'body_too_large', 414: 'query_too_large',
                         500: 'internal_error', 501: 'unsupported_method'}
                self._json_error(code, codes.get(code, 'http_error'),
                                 message or self.responses.get(code, ('HTTP error',))[0])
            else:
                super().send_error(code, message, explain)

        def _serve_json(self, data):
            body = json.dumps(data).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)

        def _query(self):
            return parse_query(self.path)

        def _origin_ok(self) -> bool:
            """Reject state-mutating requests from foreign origins.

            The Origin netloc must match the Host, and the Host must be
            allowlisted (loopback, or the configured deployment host). The
            Host is validated against a fixed allowlist — NOT against the
            attacker-controlled Origin — so DNS rebinding cannot pass by
            setting both to a malicious host.
            """
            origin = self.headers.get("Origin")
            if not origin:
                return True
            host = self.headers.get("Host", "")
            if not host:
                return False
            netloc = host.split(":", 1)[0].lower()
            loopback = ("127.0.0.1", "localhost", "::1")
            allowed = loopback + tuple((h or "").lower() for h in (allowed_hosts or []))
            if netloc not in allowed:
                return False
            return urlparse(origin).netloc == host

        def log_message(self, format, *args):
            message = format % args
            message = re.sub(r"\?[^\s\"']*", "?[redacted]", message)
            message = re.sub(r"(?i)(authorization\s*[:=]\s*)[^\r\n]*",
                             r"\1[redacted]", message)
            print(f"[dashboard] {message}", file=sys.stderr)

    return DashboardHandler
