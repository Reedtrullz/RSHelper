"""Dashboard server — launch a local HTTP server for the RSHelper dashboard."""

import errno
import sys
import time
from http.server import ThreadingHTTPServer

from rshelper.cli import _fetch_bootstrap
from rshelper.config import load_config
from rshelper.market import price_issue
from rshelper.scanner import FlipScanner
from rshelper.signals import detect_signals
from rshelper.dashboard.handlers import make_handler
from rshelper import watchlist


def run(bind: str = "127.0.0.1", port: int = 5555) -> None:
    """Start the dashboard HTTP server.

    Prints the dashboard URL to stdout. All status/log messages go to stderr.
    Blocks until interrupted. Handles KeyboardInterrupt for graceful shutdown.
    Data re-fetches from the API every 120 seconds (ponytail TTL cache).
    """
    cfg = load_config()
    scan_kwargs = {
        "members_only": cfg.flip.members_only,
        "min_volume": cfg.flip.min_volume,
        "min_margin": cfg.flip.min_margin,
    }

    # Initial fetch — seed the TTL cache. A failed live fetch must not kill
    # the dashboard: start with cached/empty data and retry on refresh.
    try:
        _mapping, _latest, _vol_5m, items = _fetch_bootstrap()
    except SystemExit:
        print("[dashboard] WARNING: initial OSRS Wiki fetch failed; starting with cached/empty data.",
              file=sys.stderr)
        _mapping = []
        items = []
        _latest = {}
        _vol_5m = {}

    from rshelper.tuning import record_if_changed
    record_if_changed()

    def _source(latest: dict) -> str:
        if not latest:
            return "none"
        sample = next(iter(latest.values()), {}) if latest else {}
        return "ge_tracker" if isinstance(sample, dict) and "high_volume" in sample else "wiki"

    # ponytail: closure-based TTL cache, re-fetch every 120s.
    # Add configurable --refresh N flag when needed.
    cache = {"mapping": _mapping, "items": items, "vol": _vol_5m, "latest": _latest,
             "source": _source(_latest), "last_fetch": time.time()}

    def refresh():
        now = time.time()
        if (now - cache["last_fetch"]) > 120:
            print("[dashboard] Re-fetching GE data...", file=sys.stderr)
            try:
                _m, _l, _v, fresh = _fetch_bootstrap()
                cache["mapping"] = _m
                cache["items"] = fresh
                cache["vol"] = _v
                cache["latest"] = _l
                cache["source"] = _source(_l)
            except SystemExit:
                print("[dashboard] Re-fetch failed; keeping previous data.", file=sys.stderr)
            cache["last_fetch"] = now

    def get_items():
        refresh()
        return list(cache["items"])

    scanner = FlipScanner(direction=cfg.flip.direction)

    sig_cache = {"list": [], "flips": 0, "ts": 0.0}

    def active_signals():
        now = time.time()
        if now - sig_cache["ts"] > 30:
            flips = scanner.scan(cache["items"], **scan_kwargs)
            sig_cache["list"] = detect_signals(flips, cache["vol"])
            sig_cache["flips"] = len(flips)
            sig_cache["ts"] = now
        return sig_cache["list"]

    def get_signals():
        refresh()
        return active_signals()

    def get_prices(item_ids: list[int]) -> dict:
        refresh()
        latest = cache["latest"] or {}
        out = {}
        for item_id in item_ids:
            price = latest.get(str(item_id))
            issue = price_issue(price) if isinstance(price, dict) else "no data"
            if issue:
                out[str(item_id)] = {"usable": False, "reason": issue}
            else:
                out[str(item_id)] = {"usable": True,
                                     "buy": int(price.get("high", 0)),
                                     "sell": int(price.get("low", 0))}
        return out

    def get_meta() -> dict:
        refresh()
        signals = active_signals()
        from rshelper.journal import list_trades
        return {
            "source": cache["source"],
            "items": len(cache["items"]),
            "flips": sig_cache["flips"],
            "signals": len(signals),
            "trades": len(list_trades()),
            "watchlist": len(watchlist.get_watched_ids()),
            "watch_ids": watchlist.get_watched_ids(),
            "last_fetch": cache["last_fetch"],
        }

    def get_watchlist() -> dict:
        refresh()
        latest = cache["latest"] or {}
        rows = []
        for id_str, entry in watchlist.load().get("items", {}).items():
            price = latest.get(id_str)
            issue = price_issue(price) if isinstance(price, dict) else "no data"
            row = {"id": int(id_str), "name": entry.get("name", id_str),
                   "added": entry.get("added", ""),
                   "alert_above": entry.get("alert_margin_above"),
                   "alert_below": entry.get("alert_margin_below"),
                   "usable": issue is None}
            if issue is None:
                row["buy"] = int(price.get("high", 0))
                row["sell"] = int(price.get("low", 0))
            else:
                row["reason"] = issue
            rows.append(row)
        rows.sort(key=lambda r: r["name"].lower())
        return {"items": rows}

    def update_watchlist(action: str, item_id: int) -> dict:
        if action == "add":
            item = next((i for i in cache["items"] if i.id == item_id), None)
            if item is None:
                raise ValueError(f"item {item_id} not in the current scan")
            watchlist.add(item_id, item.name)
        elif action == "remove":
            watchlist.remove(item_id)
        else:
            raise ValueError(f"unknown watchlist action '{action}'")
        return get_watchlist()

    def get_timeseries(item_id: int) -> dict:
        from rshelper.api import fetch_timeseries
        ts = fetch_timeseries(item_id, "5m")
        points = []
        for dp in (ts or [])[-96:]:
            high, low = dp.get("avgHighPrice"), dp.get("avgLowPrice")
            if high is None or low is None:
                continue
            h, l = int(high), int(low)
            if h <= 0 or l <= 0:
                continue
            points.append({"ts": dp.get("timestamp"), "avgHigh": h, "avgLow": l})
        return {"points": points}

    def get_positions() -> dict:
        refresh()
        from rshelper.market import ge_tax
        from rshelper.positions import list_positions
        latest = cache["latest"] or {}
        rows = []
        for p in list_positions():
            price = latest.get(str(p.item_id))
            issue = price_issue(price) if isinstance(price, dict) else "no data"
            row = {"id": p.id, "item_id": p.item_id, "name": p.name,
                   "qty": p.qty, "buy_price": p.buy_price,
                   "direction": p.direction, "opened_at": p.opened_at,
                   "usable": issue is None}
            if issue is None:
                sell = int(price.get("low", 0) or 0) if p.direction == "arbitrage" \
                    else int(price.get("high", 0) or 0)
                row["current"] = sell
                tax = ge_tax(sell)
                row["unrealized"] = (sell - p.buy_price) * p.qty - tax * p.qty
                row["unrealized_pct"] = round(
                    ((sell - p.buy_price - tax) / p.buy_price * 100), 2
                ) if p.buy_price > 0 else 0.0
            else:
                row["reason"] = issue
            rows.append(row)
        rows.sort(key=lambda r: r["opened_at"])
        return {"positions": rows,
                "open_qty": sum(r["qty"] for r in rows),
                "unrealized": sum(r.get("unrealized", 0) for r in rows)}

    def paper_trade(action: str, query: str, qty: int) -> dict:
        """Log a paper trade (instant round-trip) or open a hold position.

        Both use the current guarded prices from the TTL cache, so the
        dashboard can trade any mapped item without a CLI round trip.
        """
        refresh()
        mapping = cache["mapping"] or []
        q = query.strip().lower()
        entry = next((e for e in mapping
                      if (e.get("name") or "").lower() == q), None)
        if entry is None:
            matches = [e for e in mapping if q in (e.get("name") or "").lower()]
            if len(matches) == 1:
                entry = matches[0]
            elif len(matches) > 1:
                names = ", ".join(e.get("name", "?") for e in matches[:8])
                raise ValueError(f"multiple items match '{query}': {names}")
            else:
                raise ValueError(f"no item found matching '{query}'")
        price = (cache["latest"] or {}).get(str(entry["id"]))
        issue = price_issue(price) if isinstance(price, dict) else "no data"
        if issue:
            raise ValueError(f"no reliable live price for {entry.get('name')} ({issue})")
        high = int(price.get("high", 0) or 0)
        low = int(price.get("low", 0) or 0)
        if high <= 0 or low <= 0:
            raise ValueError(f"no live price data for {entry.get('name')}")
        from dataclasses import asdict
        from rshelper.positions import open_position
        from rshelper.journal import log_trade
        if action == "open":
            pos = open_position(entry["id"], entry["name"], qty, high,
                                direction="arbitrage")
            return {"ok": True, "position": asdict(pos)}
        if action == "instant":
            trade = log_trade(entry["id"], entry["name"], qty, high, low,
                              note="paper")
            return {"ok": True, "trade": asdict(trade)}
        raise ValueError(f"unknown action '{action}'")

    handler = make_handler(scanner, get_items, signal_detector=get_signals,
                           scan_kwargs=scan_kwargs, price_lookup=get_prices,
                           meta_fn=get_meta, watchlist_fn=get_watchlist,
                           watchlist_update_fn=update_watchlist,
                           timeseries_fn=get_timeseries,
                           positions_fn=get_positions,
                           paper_trade_fn=paper_trade)

    # Warn on non-loopback bind
    if bind not in ("127.0.0.1", "localhost", "::1"):
        print(f"[dashboard] WARNING: binding to {bind} exposes the dashboard on "
              f"all network interfaces with no authentication", file=sys.stderr)

    try:
        server = ThreadingHTTPServer((bind, port), handler)
    except OSError as e:
        if e.errno == errno.EADDRINUSE:
            print(f"[dashboard] Port {port} is already in use", file=sys.stderr)
        elif e.errno == errno.EACCES:
            print(f"[dashboard] Permission denied for port {port} "
                  f"(try a port >= 1024)", file=sys.stderr)
        else:
            print(f"[dashboard] Cannot bind to {bind}:{port}: {e}", file=sys.stderr)
        sys.exit(1)

    server.daemon_threads = True

    url = f"http://{bind}:{port}"
    print(url)
    print(f"[dashboard] Dashboard running at {url}", file=sys.stderr)
    print(f"[dashboard] Press Ctrl-C to stop", file=sys.stderr)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[dashboard] Shutting down...", file=sys.stderr)
    finally:
        server.server_close()
        print("[dashboard] Stopped", file=sys.stderr)
