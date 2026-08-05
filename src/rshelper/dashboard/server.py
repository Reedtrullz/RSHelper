"""Dashboard server — launch a local HTTP server for the RSHelper dashboard."""

import errno
import os
import subprocess
import sys
import time
from http.server import ThreadingHTTPServer

from rshelper.cli import _fetch_bootstrap
from rshelper.config import load_config
from rshelper.market import price_issue
from rshelper.scanner import FlipScanner
from rshelper.signals import detect_signals
from rshelper.dashboard.handlers import make_handler
from rshelper import alerts, watchlist


class EventHub:
    """Minimal pub/sub for server-push (SSE) refresh + alert events."""

    def __init__(self):
        self._subscribers: list = []
        self._lock = __import__("threading").Lock()

    def subscribe(self, queue) -> None:
        with self._lock:
            self._subscribers.append(queue)

    def unsubscribe(self, queue) -> None:
        with self._lock:
            if queue in self._subscribers:
                self._subscribers.remove(queue)

    def broadcast(self, event: str, data: dict | None = None) -> None:
        with self._lock:
            subs = list(self._subscribers)
        payload = f"event: {event}\ndata: {__import__('json').dumps(data or {})}\n\n"
        for queue in subs:
            try:
                queue.put_nowait(payload)
            except Exception:
                pass


def _spawn_daemon(kind: str, profile: str | None) -> dict:
    """Start auto-trade or monitor detached. Returns {ok, pid} or {ok: False, error}."""
    import rshelper
    pkg_dir = os.path.dirname(os.path.abspath(rshelper.__file__))
    src_dir = os.path.dirname(pkg_dir)  # repo/src — the parent the package lives in
    cmd = [sys.executable, "-m", "rshelper", kind]
    if profile and profile != "default":
        cmd += ["--profile", profile]
    log_dir = __import__("rshelper.profile", fromlist=["resolve_config_path"]).resolve_config_path("logs", profile)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{kind}.log"
    if log_path.exists() and log_path.stat().st_size > 5 * 1024 * 1024:
        log_path.unlink(missing_ok=True)  # ponytail: rotate at 5MB
    # The child runs `python -m rshelper`; when the dashboard's own
    # importability came from PYTHONPATH (or from cwd in a dev flow), the
    # child must inherit a path that resolves the package. Prepend src so a
    # cwd-based launch (PYTHONPATH unset) still works.
    env = dict(os.environ)
    env["PYTHONPATH"] = src_dir + os.pathsep + env.get("PYTHONPATH", "")
    try:
        with open(log_path, "ab") as logf:
            proc = subprocess.Popen(
                cmd, cwd=src_dir, stdout=logf, stderr=logf,
                start_new_session=True,  # survive dashboard shutdown
                env=env,
            )
    except OSError as exc:
        return {"ok": False, "error": f"could not start {kind}: {exc}"}
    return {"ok": True, "pid": proc.pid, "log": str(log_path)}


def _stop_daemon(kind: str, profile: str | None) -> dict:
    if kind == "auto-trade":
        from rshelper.trader import stop_trader
        stopped = stop_trader(profile)
    else:
        from rshelper.monitor import stop_monitor
        stopped = stop_monitor(profile)
    return {"ok": stopped, "stopped": stopped}


def run(bind: str = "127.0.0.1", port: int = 5555, control: bool = False,
        open_browser: bool = False, profile: str | None = None) -> None:
    """Start the dashboard HTTP server.

    Prints the dashboard URL to stdout. All status/log messages go to stderr.
    Blocks until interrupted. Handles KeyboardInterrupt for graceful shutdown.
    Data re-fetches from the API every 120 seconds (ponytail TTL cache).
    """
    cfg = load_config(profile)
    scan_kwargs = {
        "members_only": cfg.flip.members_only,
        "min_volume": cfg.flip.min_volume,
        "min_margin": cfg.flip.min_margin,
    }

    # Initial fetch — seed the TTL cache. A failed live fetch must not kill
    # the dashboard: start with cached/empty data and retry on refresh.
    try:
        _mapping, _latest, _vol_5m, items = _fetch_bootstrap(profile)
    except SystemExit:
        print("[dashboard] WARNING: initial OSRS Wiki fetch failed; starting with cached/empty data.",
              file=sys.stderr)
        _mapping = []
        items = []
        _latest = {}
        _vol_5m = {}
        try:
            alerts.push_alert("system", "WARN", None, "",
                              "Data source unavailable",
                              "Initial OSRS Wiki fetch failed; serving cached/empty data",
                              profile=profile)
        except Exception:
            pass

    from rshelper.tuning import record_if_changed
    record_if_changed(profile)

    hub = EventHub()

    def _source(latest: dict) -> str:
        if not latest:
            return "none"
        sample = next(iter(latest.values()), {}) if latest else {}
        return "ge_tracker" if isinstance(sample, dict) and "high_volume" in sample else "wiki"

    # ponytail: closure-based TTL cache, re-fetch every 120s.
    cache = {"mapping": _mapping, "items": items, "vol": _vol_5m, "latest": _latest,
             "source": _source(_latest), "last_fetch": time.time()}

    def _emit_signal_alerts(signals) -> None:
        """Persist newly-active signals as alerts unless a local monitor
        already delivers them (avoid double-push on the Mac)."""
        try:
            from rshelper.monitor import monitor_status
            local_monitor = monitor_status(profile) is not None
        except Exception:
            local_monitor = False
        if local_monitor:
            return
        for s in signals:
            try:
                alert = alerts.push_alert(
                    "signal", s.severity, s.item_id, s.name, s.type,
                    s.message, profile=profile,
                    data={"deviation": s.deviation,
                          "current_price": s.current_price})
                hub.broadcast("alert", {"alert": _alert_to_dict(alert)})
            except Exception:
                continue

    def _check_watch_alerts(latest: dict) -> None:
        """Persist watchlist threshold crossings (the VPS dashboard feed)."""
        try:
            wl = watchlist.load(profile)
            for id_str, entry in wl.get("items", {}).items():
                price = latest.get(id_str)
                if not isinstance(price, dict):
                    continue
                issue = price_issue(price)
                if issue:
                    continue
                buy = int(price.get("high", 0) or 0)
                sell = int(price.get("low", 0) or 0)
                if buy <= 0 or sell <= 0:
                    continue
                profit = (sell - buy) - __import__(
                    "rshelper.market", fromlist=["ge_tax"]).ge_tax(sell)
                item_id = int(id_str)
                above = entry.get("alert_margin_above")
                below = entry.get("alert_margin_below")
                hit = None
                if above is not None and profit > above:
                    hit = f"margin {profit:,} gp above {above:,}"
                elif below is not None and profit < below:
                    hit = f"margin {profit:,} gp below {below:,}"
                # Check-then-set must be atomic per item (this runs inside the
                # single-flight refresh lock, so no other thread can race it).
                if hit and not alerts.watch_triggered(item_id, profile):
                    alert = alerts.push_alert(
                        "watch", "HIGH", item_id, entry.get("name", str(item_id)),
                        "Watchlist alert", f"{entry.get('name', '')}: {hit}",
                        profile=profile)
                    alerts.set_watch_triggered(item_id, profile)
                    hub.broadcast("alert", {"alert": _alert_to_dict(alert)})
        except Exception as e:
            print(f"[dashboard] watch alert check failed: {e}", file=sys.stderr)

    refresh_lock = __import__("threading").Lock()

    def refresh():
        now = time.time()
        if (now - cache["last_fetch"]) > 120:
            # Single-flight: concurrent request threads must not double-fetch
            # or double-broadcast (the watch-alert check-then-set is only safe
            # when one thread performs it per refresh window).
            with refresh_lock:
                if (time.time() - cache["last_fetch"]) <= 120:
                    return
                print("[dashboard] Re-fetching GE data...", file=sys.stderr)
                old_source = cache["source"]
                try:
                    _m, _l, _v, fresh = _fetch_bootstrap(profile)
                    cache["mapping"] = _m
                    cache["items"] = fresh
                    cache["vol"] = _v
                    cache["latest"] = _l
                    cache["source"] = _source(_l)
                except SystemExit:
                    print("[dashboard] Re-fetch failed; keeping previous data.", file=sys.stderr)
                    try:
                        alerts.push_alert("system", "WARN", None, "",
                                          "Data source unavailable",
                                          "Re-fetch failed; keeping previous data",
                                          profile=profile)
                        hub.broadcast("alert", {"alert": {
                            "type": "system", "severity": "WARN",
                            "title": "Data source unavailable",
                            "message": "Re-fetch failed; keeping previous data"}})
                    except Exception:
                        pass
                cache["last_fetch"] = time.time()
                _check_watch_alerts(cache["latest"] or {})
                if cache["source"] != old_source:
                    alerts.push_alert(
                        "system", "INFO", None, "", "Data source changed",
                        f"Switched from {old_source} to {cache['source']}",
                        profile=profile)
                hub.broadcast("refresh")

    def get_items():
        refresh()
        return list(cache["items"])

    scanner = FlipScanner(direction=cfg.flip.direction)

    sig_cache = {"list": [], "flips": 0, "ts": 0.0, "active": set()}
    sig_lock = __import__("threading").Lock()

    def active_signals():
        now = time.time()
        with sig_lock:
            if now - sig_cache["ts"] > 30:
                # Snapshot items+vol together so a refresh mid-scan can't mix
                # old flips with new volume (spurious/missed signals).
                items_snap = list(cache["items"])
                vol_snap = dict(cache["vol"])
                flips = scanner.scan(items_snap, **scan_kwargs)
                # DUMP/CRASH/SURGE must see the full priced universe (mirror
                # the monitor); FLIP stays restricted to scan candidates.
                sig_cache["list"] = detect_signals(
                    items_snap, vol_snap, flip_ids={f.id for f in flips},
                    profile=profile)
                sig_cache["flips"] = len(flips)
                sig_cache["ts"] = now
                new = [s for s in sig_cache["list"]
                       if (s.item_id, s.type) not in sig_cache["active"]]
                sig_cache["active"] = {(s.item_id, s.type)
                                       for s in sig_cache["list"]}
                if new:
                    _emit_signal_alerts(new)
            return list(sig_cache["list"])

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
            "trades": len(list_trades(profile=profile)),
            "watchlist": len(watchlist.get_watched_ids(profile)),
            "watch_ids": watchlist.get_watched_ids(profile),
            "last_fetch": cache["last_fetch"],
            "control": control,
            "profile": profile or "default",
            "unread_alerts": alerts.unread_count(profile),
        }

    def get_watchlist() -> dict:
        refresh()
        latest = cache["latest"] or {}
        rows = []
        for id_str, entry in watchlist.load(profile).get("items", {}).items():
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

    def update_watchlist(action: str, item_id: int,
                         alert_above: int | None = None,
                         alert_below: int | None = None) -> dict:
        if action == "add":
            item = next((i for i in cache["items"] if i.id == item_id), None)
            if item is None:
                raise ValueError(f"item {item_id} not in the current scan")
            # Re-adding a watched item must preserve its alert thresholds
            # (un-star + re-star shouldn't wipe them).
            wl = watchlist.load(profile)
            existing = wl.get("items", {}).get(str(item_id))
            if existing:
                watchlist.add(item_id, item.name,
                              alert_margin_above=existing.get("alert_margin_above"),
                              alert_margin_below=existing.get("alert_margin_below"),
                              profile=profile)
            else:
                watchlist.add(item_id, item.name, profile=profile)
        elif action == "remove":
            watchlist.remove(item_id, profile=profile)
        elif action == "alerts":
            alerts.update_watch_alerts(item_id, alert_above, alert_below,
                                       profile)
        else:
            raise ValueError(f"unknown watchlist action '{action}'")
        return get_watchlist()

    def get_timeseries(item_id: int, step: str = "5m",
                       points: int = 96) -> dict:
        from rshelper.api import fetch_timeseries
        ts = fetch_timeseries(item_id, step, profile)
        points_out = []
        for dp in (ts or [])[-points:]:
            high, low = dp.get("avgHighPrice"), dp.get("avgLowPrice")
            if high is None or low is None:
                continue
            h, l = int(high), int(low)
            if h <= 0 or l <= 0:
                continue
            points_out.append({"ts": dp.get("timestamp"), "avgHigh": h, "avgLow": l})
        return {"points": points_out}

    def get_positions() -> dict:
        refresh()
        from rshelper.market import ge_tax
        from rshelper.positions import list_positions
        latest = cache["latest"] or {}
        rows = []
        for p in list_positions(profile):
            price = latest.get(str(p.item_id))
            issue = price_issue(price) if isinstance(price, dict) else "no data"
            row = {"id": p.id, "item_id": p.item_id, "name": p.name,
                   "qty": p.qty, "buy_price": p.buy_price,
                   "direction": p.direction, "opened_at": p.opened_at,
                   "note": p.note, "auto": p.note == "auto",
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

    def close_position(position_id: int, qty: int | None = None) -> dict:
        """Close a manual paper position at the market price.

        Auto-trader positions are refused (the trader owns those exits).
        Raises ValueError when the position is unknown/auto or the close
        cannot be priced.
        """
        refresh()
        from rshelper.ge_offers import close_market_price
        from rshelper.positions import close_positions, list_positions
        from rshelper.journal import log_trade
        position = next((p for p in list_positions(profile)
                         if p.id == position_id), None)
        if position is None:
            raise ValueError(f"unknown position id {position_id}")
        if position.note == "auto":
            raise ValueError("auto-trader positions close themselves")
        close_qty = qty if qty and qty > 0 else position.qty
        if close_qty > position.qty:
            raise ValueError(f"only {position.qty} units open for {position.name}")
        # Close at the direction-aware market leg when a usable price exists;
        # otherwise fall back to the entry buy_price (like collect_offer) so a
        # stale-data position is never stranded forever. The response flags
        # the fallback so the UI can surface the warning.
        price = (cache["latest"] or {}).get(str(position.item_id))
        usable = isinstance(price, dict) and price_issue(price) is None
        sell_price = close_market_price(position, cache["latest"])
        at_entry = not usable
        lots = close_positions(position.item_id, close_qty, sell_price, profile)
        for lot in lots:
            log_trade(position.item_id, lot["name"], lot["qty"],
                      lot["buy_price"], sell_price, note="paper",
                      profile=profile, strategy="manual",
                      exit_reason="manual")
        return {
            "ok": True,
            "name": position.name,
            "qty": close_qty,
            "sell_price": sell_price,
            "profit": sum(lot["profit"] for lot in lots),
            "closed_at_entry": at_entry,
        }

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
        # Honor the configured flip direction: the CLI's `trade open/paper`
        # respects --flip-direction, so the dashboard must too — booking a
        # traditional-config position as arbitrage buys the ask and sells
        # the bid, a structurally negative trade.
        direction = cfg.flip.direction
        if action == "open":
            if direction == "traditional":
                pos = open_position(entry["id"], entry["name"], qty, low,
                                    direction="traditional", note="paper",
                                    entry_sell=low, entry_offer=high,
                                    profile=profile)
            else:
                pos = open_position(entry["id"], entry["name"], qty, high,
                                    direction="arbitrage", note="paper",
                                    entry_sell=low, profile=profile)
            return {"ok": True, "position": asdict(pos)}
        if action == "instant":
            if direction == "traditional":
                trade = log_trade(entry["id"], entry["name"], qty, low, high,
                                  note="paper", strategy="manual",
                                  profile=profile)
            else:
                trade = log_trade(entry["id"], entry["name"], qty, high, low,
                                  note="paper", strategy="manual",
                                  profile=profile)
            return {"ok": True, "trade": asdict(trade)}
        raise ValueError(f"unknown action '{action}'")

    def get_trader_status() -> dict:
        from rshelper.trader import trader_status
        status = trader_status(profile)
        return status if status else {"running": False}

    def trader_control(action: str) -> dict:
        """Start or stop the auto-trader daemon. 403-guarded by control flag."""
        if not control:
            raise PermissionError("daemon control is disabled (run dashboard with --control)")
        if action == "start":
            from rshelper.trader import trader_status
            if trader_status(profile) and trader_status(profile).get("running"):
                raise ValueError("auto-trader is already running")
            return _spawn_daemon("auto-trade", profile)
        if action == "stop":
            return _stop_daemon("auto-trade", profile)
        raise ValueError(f"unknown trader action '{action}'")

    def monitor_control(action: str) -> dict:
        """Start or stop the monitor daemon. 403-guarded by control flag."""
        if not control:
            raise PermissionError("daemon control is disabled (run dashboard with --control)")
        if action == "start":
            from rshelper.monitor import monitor_status
            if monitor_status(profile) and monitor_status(profile).get("running"):
                raise ValueError("monitor is already running")
            return _spawn_daemon("monitor", profile)
        if action == "stop":
            return _stop_daemon("monitor", profile)
        raise ValueError(f"unknown monitor action '{action}'")

    def get_monitor_status() -> dict:
        from rshelper.monitor import monitor_status
        status = monitor_status(profile)
        return status if status else {"running": False}

    def get_ge():
        refresh()
        from rshelper.ge_offers import build_ge_slots
        return build_ge_slots(profile=profile, latest=cache["latest"],
                              vol_5m=cache["vol"])

    def collect_ge(position_id: int):
        from rshelper.ge_offers import collect_offer
        return collect_offer(position_id, profile=profile,
                             latest=cache["latest"])

    def get_bank():
        refresh()
        from rshelper.bank import build_bank_items
        return build_bank_items(profile=profile, latest=cache["latest"])

    def get_process():
        refresh()
        from rshelper.scanner import ProcessScanner
        from rshelper.recipes import RECIPES
        lookup = {i.id: i for i in cache["items"]}
        results = ProcessScanner().scan(cache["items"], capital=cfg.process.capital)
        out = []
        for r in results:
            recipe = RECIPES.get(r.id)
            inputs = []
            if recipe:
                for iid, qty in recipe.inputs.items():
                    it = lookup.get(iid)
                    inputs.append({
                        "name": it.name if it else str(iid),
                        "qty": qty,
                        "buy_price": it.buy_price if it else 0,
                    })
            out.append({
                "name": r.name, "item_id": r.id,
                "skill": recipe.skill if recipe else "",
                "input_cost": r.input_cost, "sell_price": r.sell_price,
                "profit": r.profit,
                "roi_pct": round(r.profit / r.input_cost * 100, 1) if r.input_cost else 0,
                "gp_per_hour": r.gp_per_hour,
                "volume": r.volume, "buy_limit": r.buy_limit,
                "inputs": inputs,
            })
        # Group by skill, then sort each skill's recipes by GP/hr desc.
        out.sort(key=lambda x: (x["skill"], -x["gp_per_hour"]))
        return {"recipes": out, "count": len(out)}

    def get_alch():
        refresh()
        from rshelper.scanner import AlchScanner
        from rshelper.api import fetch_latest
        nature = cfg.alch.nature_rune_cost
        if nature <= 0:
            price = (cache["latest"] or {}).get("561")
            if isinstance(price, dict) and price_issue(price) is None:
                nature = int(price.get("high", 0) or 0)
            if nature <= 0:
                nature = 147
        results = AlchScanner(nature_rune_cost=nature).scan(
            cache["items"], members_only=cfg.alch.members_only,
            min_volume=cfg.alch.min_volume)
        return {"items": [_item_dict(r) for r in results[:cfg.alch.top]],
                "count": len(results), "nature_rune_cost": nature}

    confidence_cache = {"ts": 0.0, "data": {}}
    conf_lock = __import__("threading").Lock()

    def get_confidence(item_ids: list[int]) -> dict:
        """Per-item margin confidence scores (MarginScanner), cached 10 min."""
        if not item_ids:
            return {}
        with conf_lock:
            now = time.time()
            if now - confidence_cache["ts"] > 600 or not confidence_cache["data"]:
                confidence_cache["data"] = {}
                confidence_cache["ts"] = now
            want = [i for i in item_ids
                    if str(i) not in confidence_cache["data"]][:30]
            if want:
                from rshelper.api import fetch_timeseries_batch
                from rshelper.scanner import MarginScanner
                lookup = {i.id: i for i in cache["items"]}
                ts_data = fetch_timeseries_batch(
                    want, timestep="5m", workers=2, profile=profile)
                results = MarginScanner().scan(
                    lookup, ts_data, direction=cfg.flip.direction)
                scored = {str(a.item_id) for a in results}
                for a in results:
                    confidence_cache["data"][str(a.item_id)] = {
                        "confidence": round(a.confidence, 4),
                        "reliability": round(a.reliability, 4),
                        "profitability_score": round(a.profitability_score, 4),
                        "avg_margin": round(a.avg_margin, 0),
                        "margin_volatility": round(a.margin_volatility, 4),
                        "avg_spread_pct": round(a.avg_spread_pct, 4),
                        "datapoints": a.datapoints,
                        "window_hours": round(a.window_hours, 1),
                    }
                # Cache negative results (no timeseries / too few windows) so
                # repeated polls don't re-fetch the same items every 10 min.
                for iid in want:
                    if str(iid) not in scored:
                        confidence_cache["data"][str(iid)] = None
            return {k: v for k, v in confidence_cache["data"].items()
                    if k in {str(i) for i in item_ids} and v is not None}

    def get_alerts_fn(limit: int = 50) -> dict:
        feed = alerts.list_alerts(limit=limit, profile=profile)
        return {
            "alerts": [
                {"id": a.id, "ts": a.ts, "type": a.type, "severity": a.severity,
                 "item_id": a.item_id, "item_name": a.item_name,
                 "title": a.title, "message": a.message, "read": a.read}
                for a in feed
            ],
            "count": len(feed),
            "unread": alerts.unread_count(profile),
        }

    def mark_alerts_read(ids: list[int] | None = None, all: bool = False) -> dict:
        changed = alerts.mark_read(ids=ids, all=all, profile=profile)
        return {"changed": changed,
                "unread": alerts.unread_count(profile)}

    def get_history(paper_only: bool = True, strategy: str = "") -> dict:
        from rshelper.history import build_history
        return build_history(profile=profile, paper_only=paper_only,
                             strategy=strategy)

    def get_trades(note: str = "", strategy: str = "") -> dict:
        from rshelper.journal import list_trades
        from dataclasses import asdict
        trades = list_trades(note=note, profile=profile, strategy=strategy)
        return {"trades": [asdict(t) for t in trades], "count": len(trades)}

    def get_pnl(note: str = "", strategy: str = "") -> dict:
        from rshelper.journal import compute_pnl
        pnl = compute_pnl(note=note, profile=profile, strategy=strategy)
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
        return d

    def delete_trade_fn(trade_id: int) -> dict:
        from rshelper.journal import delete_trade
        ok = delete_trade(trade_id, profile=profile)
        if not ok:
            raise ValueError(f"trade {trade_id} not found")
        return {"ok": True}

    def get_watch_check() -> dict:
        """Threshold crossings with the current margin, arbitrage convention."""
        refresh()  # "Check now" must use a fresh quote, not the TTL cache
        from rshelper.market import ge_tax
        latest = cache["latest"] or {}
        wl = watchlist.load(profile)
        triggered = []
        for id_str, entry in wl.get("items", {}).items():
            price = latest.get(id_str)
            if not isinstance(price, dict):
                continue
            issue = price_issue(price)
            if issue:
                continue
            buy = int(price.get("high", 0) or 0)
            sell = int(price.get("low", 0) or 0)
            if buy <= 0 or sell <= 0:
                continue
            profit = (sell - buy) - ge_tax(sell)
            item_id = int(id_str)
            above = entry.get("alert_margin_above")
            below = entry.get("alert_margin_below")
            if above is not None and profit > above:
                triggered.append({"item_id": item_id, "name": entry.get("name"),
                                  "reason": "above", "threshold": above,
                                  "current": profit})
            if below is not None and profit < below:
                triggered.append({"item_id": item_id, "name": entry.get("name"),
                                  "reason": "below", "threshold": below,
                                  "current": profit})
        return {"triggered": triggered, "count": len(triggered)}

    def log_trade_fn(item_id: int, name: str, qty: int, buy_price: int,
                     sell_price: int, note: str = "") -> dict:
        from rshelper.journal import log_trade
        from dataclasses import asdict
        trade = log_trade(item_id, name, qty, buy_price, sell_price,
                          note=note, profile=profile)
        return asdict(trade)

    handler = make_handler(scanner, get_items, signal_detector=get_signals,
                           scan_kwargs=scan_kwargs, price_lookup=get_prices,
                           meta_fn=get_meta, watchlist_fn=get_watchlist,
                           watchlist_update_fn=update_watchlist,
                           watchlist_check_fn=get_watch_check,
                           timeseries_fn=get_timeseries,
                           positions_fn=get_positions,
                           close_position_fn=close_position,
                           paper_trade_fn=paper_trade,
                           trader_fn=get_trader_status,
                           trader_control_fn=trader_control,
                           monitor_fn=get_monitor_status,
                           monitor_control_fn=monitor_control,
                           ge_fn=get_ge, ge_collect_fn=collect_ge,
                           bank_fn=get_bank, process_fn=get_process,
                           alch_fn=get_alch, confidence_fn=get_confidence,
                           alerts_fn=get_alerts_fn,
                           alerts_read_fn=mark_alerts_read,
                           history_fn=get_history, trades_fn=get_trades,
                           pnl_fn=get_pnl, delete_trade_fn=delete_trade_fn,
                           log_trade_fn=log_trade_fn, event_hub=hub)

    # Warn on non-loopback bind
    if bind not in ("127.0.0.1", "localhost", "::1"):
        print(f"[dashboard] WARNING: binding to {bind} exposes the dashboard on "
              f"all network interfaces with no authentication", file=sys.stderr)
    if control:
        print("[dashboard] NOTE: daemon control is ENABLED — the dashboard "
              "can start/stop the auto-trader and monitor.", file=sys.stderr)

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
    if open_browser:
        import webbrowser
        webbrowser.open(url)
        print(f"[dashboard] Opened {url} in your browser", file=sys.stderr)
    print(f"[dashboard] Press Ctrl-C to stop", file=sys.stderr)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[dashboard] Shutting down...", file=sys.stderr)
    finally:
        server.server_close()
        print("[dashboard] Stopped", file=sys.stderr)


def _alert_to_dict(alert) -> dict:
    """Serialize an Alert to its wire shape (matches /api/alerts entries)."""
    return {"id": alert.id, "ts": alert.ts, "type": alert.type,
            "severity": alert.severity, "item_id": alert.item_id,
            "item_name": alert.item_name, "title": alert.title,
            "message": alert.message, "read": alert.read}


def _item_dict(item) -> dict:
    """Serialize an Item dataclass to a JSON-safe dict (server-side copy)."""
    from rshelper.dashboard.handlers import _item_to_dict
    return _item_to_dict(item)
