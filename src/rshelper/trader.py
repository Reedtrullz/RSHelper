"""Autonomous paper trader: finds candidates and executes paper trades.

Paper-only by design — there is no live GE integration, so nothing here
touches real GP. A poll loop opens positions on liquid, sane-spread items
that are dipped below their 5-minute average and closes them at
take-profit / stop-loss / max-hold, logging realized trades into the
journal like any other paper trade. Only positions it opened (note="auto")
are managed.

Execution model is standard GE flipping ("traditional" convention): buy at
the bid (`low`), sell at the offer (`high`) on take-profit, sell at the bid
on stop/max-hold. Buying the ask and selling the bid is structurally
negative (verified by a 30-day backtest on real 5m candles: -4.9%/trade),
because every entry pays the spread and tax; flipping captures the spread
instead, which is why entries require spread > the 2% tax.
"""

import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from rshelper.market import ge_tax, price_issue
from rshelper.profile import atomic_write_json, resolve_config_path

TRADER_DIR = Path.home() / ".config" / "rshelper"
PID_PATH = TRADER_DIR / "trader.pid"
STATE_PATH = TRADER_DIR / "trader_state.json"

# A status snapshot older than 15 minutes is stale: the trader may have
# stopped, or the 15-minute state sync to the live site is behind.
STALE_AFTER_SEC = 900

# ponytail: price freshness windows. The wiki /latest endpoint publishes on
# a rolling ~2-3 minute cycle even for 100k-volume items (measured), so
# entries accept data up to 5 minutes old; exits are stricter.
ENTRY_MAX_AGE = 300
EXIT_MAX_AGE = 300
STOP_SLIPPAGE = 0.97  # model worse fills when stopping out
MAX_VOLUME_FRACTION = 0.10  # never size above 10% of the last 5m volume

# Recent exits persist to disk so a daemon restart cannot erase a cooldown;
# the in-memory map is just the fast path for the current process.
# Maps item_id -> (exit_ts, reason) so stop-losses get a longer cooldown.
_RECENT_EXITS: dict[int, tuple[float, str]] = {}
EXITS_PATH = TRADER_DIR / "recent_exits.json"
# Cooldowns are at most stop_reentry_minutes (90); entries older than 2h can
# never block a re-entry, so pruning them keeps the file bounded.
RECENT_EXIT_MAX_AGE = 2 * 3600


def _load_recent_exits() -> None:
    """Merge persisted exits into the in-memory map (survives restarts)."""
    try:
        data = json.loads(EXITS_PATH.read_text())
    except (OSError, json.JSONDecodeError, ValueError):
        return
    now = time.time()
    # Prune expired entries already held in memory (a long-running daemon
    # would otherwise keep them until restart).
    for iid in [iid for iid, (ts, _) in _RECENT_EXITS.items()
                if now - ts > RECENT_EXIT_MAX_AGE]:
        del _RECENT_EXITS[iid]
    for key, val in data.items():
        try:
            ts = float(val["ts"])
            if now - ts > RECENT_EXIT_MAX_AGE:
                continue  # stale exit: no longer blocks any re-entry
            _RECENT_EXITS[int(key)] = (ts, str(val["reason"]))
        except (KeyError, TypeError, ValueError):
            continue


def _persist_recent_exits() -> None:
    now = time.time()
    fresh = {iid: (ts, reason) for iid, (ts, reason) in _RECENT_EXITS.items()
             if now - ts <= RECENT_EXIT_MAX_AGE}
    atomic_write_json(EXITS_PATH, {
        str(iid): {"ts": ts, "reason": reason}
        for iid, (ts, reason) in fresh.items()
    })


def _pid_path(profile: str | None = None) -> Path:
    if profile is None or profile == "default":
        return PID_PATH
    return Path.home() / ".config" / "rshelper" / "profiles" / profile / "trader.pid"


def _state_path(profile: str | None = None) -> Path:
    if profile is None or profile == "default":
        return STATE_PATH
    return Path.home() / ".config" / "rshelper" / "profiles" / profile / "trader_state.json"


def _write_state(state: dict, profile: str | None = None) -> None:
    atomic_write_json(_state_path(profile), state)


def _read_state(profile: str | None = None) -> dict | None:
    path = _state_path(profile)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _fresh(price: dict, max_age: int, now: float) -> bool:
    for key in ("highTime", "lowTime"):
        ts = price.get(key)
        if not isinstance(ts, (int, float)):
            return False
        if now - ts > max_age:
            return False
    return True


def _opened_ts(position) -> float | None:
    """Epoch seconds of a position's open time, or None when unparseable."""
    try:
        return datetime.fromisoformat(
            position.opened_at.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError, AttributeError):
        return None


def _low_is_thin(vol: dict | None, cfg) -> bool:
    """True when the window's low-price volume cannot support a real fill.

    The wiki 5m window reports volume traded at the low and high prices. A
    dip or crash carried by a few units (a print) is not executable at
    depth: a real sell order walks to the window average instead. Missing
    volume data never blocks (fallback sources have no such field).
    """
    if not isinstance(vol, dict):
        return False
    low_vol = vol.get("lowPriceVolume")
    high_vol = vol.get("highPriceVolume")
    if not isinstance(low_vol, (int, float)) or not isinstance(high_vol, (int, float)):
        return False
    total = low_vol + high_vol
    return low_vol < max(cfg.artifact_min_low_vol,
                         cfg.artifact_low_vol_frac * total)


def _artifact_exit_fill(bid: int, vol: dict | None, entry_bid: int,
                        cfg) -> int | None:
    """Fill price when the exit bid is an unsupported outlier, else None.

    A stop that fires on a thin print far below the 5m window average
    cannot sell at that price; the realistic fill is the window average.
    Capped at the entry bid so a stop never books a paper profit. Real
    crashes carry volume at the low and keep the print fill.
    """
    if not _low_is_thin(vol, cfg):
        return None
    avg_low = vol.get("avgLowPrice") if isinstance(vol, dict) else None
    if not isinstance(avg_low, (int, float)) or avg_low <= 0:
        return None
    if bid >= avg_low * (1 - cfg.artifact_outlier_pct / 100):
        return None  # not an outlier: normal stop
    return max(1, min(int(avg_low), entry_bid))


def _last_cycle_age(state: dict, now: float | None = None) -> float | None:
    """Seconds since the last trader cycle, or None when unknown."""
    iso = state.get("last_cycle_iso")
    if not iso:
        return None
    try:
        last = datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None
    return max(0.0, (now if now is not None else time.time()) - last)


def _status_base(state: dict) -> dict:
    age = _last_cycle_age(state)
    return {
        "profile": state.get("profile", "default"),
        "started_iso": state.get("started_iso"),
        "last_cycle_iso": state.get("last_cycle_iso"),
        "last_cycle_age_sec": age,
        "stale": age is not None and age > STALE_AFTER_SEC,
        "last_result": state.get("last_result"),
        "realized_pnl": state.get("realized_pnl", 0),
        "cycles": state.get("cycles", 0),
        "errors": state.get("errors", 0),
        "exits_by_reason": state.get("exits_by_reason", {}),
    }


def select_candidates(items, latest: dict, vol_5m: dict, cfg,
                      now: float | None = None,
                      confidence: dict[int, float] | None = None) -> list:
    """Filter items to liquid, sane, freshly-dipped buy-the-bid candidates.

    confidence: optional {item_id: 0..1} map (e.g. from MarginAnalysis) used
    only to break ranking ties — the proven dip x net-spread `edge` stays
    the primary sort key so we never regress the mean-reversion edge.
    """
    now = now if now is not None else time.time()
    confidence = confidence or {}
    out = []
    ranked = []
    for item in items:
        if item.sell_price < cfg.min_price:
            # One 1gp tick is >= 4% at sub-25gp prices, so a 2% stop is
            # sub-tick: the first integer quote below it rounds the loss up
            # several ticks. Skip cheap items entirely.
            continue
        if item.volume < cfg.min_volume:
            continue
        lo, hi = min(item.buy_price, item.sell_price), max(item.buy_price, item.sell_price)
        if hi > cfg.max_spread_ratio * lo:
            continue
        spread_pct = (hi - lo) / lo * 100
        if spread_pct > cfg.max_entry_spread_pct:
            continue
        if spread_pct < cfg.min_spread_pct:
            # The 2% GE sell tax eats the flip unless the spread exceeds it.
            # Requiring spread > tax + buffer keeps the edge on the spread
            # itself, not on a hoped-for rally.
            continue
        price = latest.get(str(item.id))
        if not isinstance(price, dict) or not _fresh(price, ENTRY_MAX_AGE, now):
            continue
        avg_low = (vol_5m.get(str(item.id)) or {}).get("avgLowPrice")
        if not avg_low or avg_low <= 0:
            continue  # no dip baseline (e.g. fallback data)
        if _low_is_thin(vol_5m.get(str(item.id)), cfg):
            # The dip is a few low-price trades, not an executable bid:
            # entering at the print would be free lunch no real buyer gets.
            continue
        dip_pct = (avg_low - item.sell_price) / avg_low * 100
        if dip_pct < cfg.dip_depth_pct:
            continue  # not dipped enough below the 5m average
        if dip_pct > cfg.max_dip_pct:
            continue  # falling too hard; not a dip, a freefall
        last_ts, last_reason = _RECENT_EXITS.get(item.id, (0, ""))
        cooldown = (cfg.stop_reentry_minutes if last_reason == "stop_loss"
                    else cfg.reentry_minutes) * 60
        if now - last_ts < cooldown:
            continue
        # Rank by expected edge, not raw volume: dip depth (mean-reversion
        # room) times net spread capture (spread minus the 2% sell tax — the
        # profit if the offer simply holds). Volume stays as the tiebreaker;
        # fill risk is already capped by MAX_VOLUME_FRACTION. When a caller
        # supplies a confidence model (reliability x profitability), it
        # breaks ties between equal edges instead of raw volume.
        net_capture = spread_pct - 2.0
        edge = dip_pct * max(0.0, net_capture)
        conf = confidence.get(item.id, 0.0)
        ranked.append((edge, conf, item.volume, item))
    ranked.sort(key=lambda r: (r[0], r[1], r[2]), reverse=True)
    out = [r[3] for r in ranked]
    return out


def unrealized_pct(buy: int, sell: int, qty: int) -> float:
    """Unrealized P&L % of the position, net of 2% sell tax."""
    if buy <= 0 or qty <= 0:
        return 0.0
    tax = ge_tax(sell)
    unreal = (sell - buy) * qty - tax * qty
    return unreal / (buy * qty) * 100


def _stop_mark(entry_bid: int, avg_low: float | None, cfg) -> float:
    """Reference price for the stop-loss, blended between entry bid and avg.

    A dip entry can sit up to max_dip_pct below the 5m avgLowPrice, so a
    stop measured purely from the entry bid can fire on the very dip the
    strategy was designed to buy. stop_mark_blend in [0,1] moves the
    reference toward the window average: 0.0 = legacy (entry bid), 1.0 =
    the full avg_low at entry. When avg_low is unknown, fall back to the
    entry bid so behavior is unchanged for fallback data.
    """
    if not avg_low or avg_low <= 0:
        return float(entry_bid)
    blend = max(0.0, min(1.0, float(getattr(cfg, "stop_mark_blend", 0.0))))
    return entry_bid + blend * (avg_low - entry_bid)


def exit_reason(position, latest: dict, cfg, now: float | None = None,
                avg_low: float | None = None):
    """Return 'take_profit' | 'stop_loss' | 'spread_collapse' | 'max_hold' | None.

    Positions are opened at the bid (low). Take-profit sells at the offer
    (high) when it nets the target after tax; the stop sells at the bid
    (low) when the bid falls below the entry bid by the stop distance.
    After spread_collapse_exit_minutes, a position whose net spread (after
    tax) has collapsed below min_exit_spread_pct exits at the bid: the
    spread-capture edge it was opened for is gone, so holding only waits for
    a rally that may never come. A simulated GE fill completion is NOT
    returned here — run_cycle checks it separately so a filled offer closes
    at the offer (ge_fill) only when no TP/SL/collapse/max-hold fires first.
    """
    now = now if now is not None else time.time()
    opened = _opened_ts(position)
    age_min = (now - opened) / 60 if opened is not None else None
    # max_hold first: it must fire even when no fresh price is available,
    # otherwise a position on a dead item could sit open forever.
    if age_min is not None and age_min >= cfg.max_hold_minutes:
        return "max_hold"
    price = latest.get(str(position.item_id))
    if not isinstance(price, dict) or price_issue(price) or not _fresh(price, EXIT_MAX_AGE, now):
        return None  # no usable price this cycle; hold
    offer = int(price.get("high", 0) or 0)
    bid = int(price.get("low", 0) or 0)
    if position.direction == "traditional":
        if offer > 0 and unrealized_pct(position.buy_price, offer,
                                        position.qty) >= cfg.take_profit_pct:
            return "take_profit"
        if bid > 0:
            mark = _stop_mark(position.buy_price, avg_low, cfg)
            move_pct = (bid - mark) / mark * 100
            if move_pct <= cfg.stop_loss_pct:
                return "stop_loss"
            if (age_min is not None
                    and age_min >= cfg.spread_collapse_exit_minutes
                    and offer > 0):
                net_spread_pct = (offer - bid - ge_tax(offer)) / bid * 100
                if net_spread_pct < cfg.min_exit_spread_pct:
                    return "spread_collapse"
    else:
        # Legacy arbitrage positions (bought at the ask): TP/SL on the bid.
        if bid <= 0:
            return None
        if unrealized_pct(position.buy_price, bid,
                          position.qty) >= cfg.take_profit_pct:
            return "take_profit"
        mark = position.entry_sell if position.entry_sell is not None else position.buy_price
        move_pct = (bid - mark) / mark * 100
        if move_pct <= cfg.stop_loss_pct:
            return "stop_loss"
    return None


def size_position(cfg, capital_used: int, entry) -> int:
    """Units to open, capped by budget, bankroll, GE limit, and market share."""
    per_trade = int(cfg.capital * cfg.trade_capital_frac)
    budget = min(per_trade, max(0, cfg.capital - capital_used))
    bid = entry.sell_price  # flips enter at the bid
    if bid <= 0:
        return 0
    by_market = int(entry.volume * MAX_VOLUME_FRACTION)
    return min(entry.buy_limit, by_market, budget // bid)


def _ge_fill_pct(position, vol_5m: dict, now: float) -> float:
    """0.0-1.0 simulated GE buy-fill progress for a position.

    Reuses the dashboard's fill curve (ge_offers.compute_fill_pct) so the
    auto-trader closes a position at the offer the moment the dashboard
    would show it as "filled" — no manual Collect click for auto trades.
    """
    from rshelper.ge_offers import compute_fill_pct, _item_volume_5m
    return compute_fill_pct(position.qty,
                            _item_volume_5m(vol_5m.get(str(position.item_id))),
                            position.opened_at, now)


def _ge_fill_confirmed(position, vol_5m: dict, now: float) -> bool:
    """True when the GE buy-fill is complete AND backed by real volume data.

    The no-volume slow-default fill (elapsed * 1/qty) is not evidence of an
    actual fill — only a 5m volume figure confirms the buy side traded, so
    a spread-collapse exit of an "unconfirmed" offer still uses the bid.
    """
    entry = vol_5m.get(str(position.item_id))
    from rshelper.ge_offers import _item_volume_5m
    if _item_volume_5m(entry) <= 0:
        return False
    return _ge_fill_pct(position, vol_5m, now) >= 1.0


def run_cycle(cfg, profile: str | None = None) -> dict:
    """One poll cycle: manage auto positions (exits) then open new ones."""
    from rshelper.cli import _fetch_bootstrap
    from rshelper.positions import close_positions, list_positions, open_position
    from rshelper.journal import log_trade

    _load_recent_exits()
    _mapping, latest, vol_5m, items = _fetch_bootstrap(profile)
    candidates = select_candidates(items, latest, vol_5m, cfg)

    closed = []
    auto_open = set()
    now = time.time()
    for p in list_positions(profile):
        if p.note != "auto":
            continue
        auto_open.add(p.item_id)
        vol = vol_5m.get(str(p.item_id))
        avg_low = vol.get("avgLowPrice") if isinstance(vol, dict) else None
        reason = exit_reason(p, latest, cfg, now=now, avg_low=avg_low)
        if reason is None:
            # No TP/SL/collapse/hold exit this cycle: if the simulated GE
            # buy-fill has completed, close at the offer (the spread-capture
            # take-profit) exactly like the dashboard's Collect would. Only
            # when the offer still nets a profit AFTER the 2% sell tax — if
            # the spread has collapsed below tax, the spread-collapse/stop
            # logic owns it and a "filled" close at the offer would lock in
            # a net loss.
            if _ge_fill_pct(p, vol_5m, now) >= 1.0:
                price_now = latest.get(str(p.item_id))
                if isinstance(price_now, dict):
                    offer_now = int(price_now.get("high", 0) or 0)
                    if (offer_now > 0 and p.buy_price > 0
                            and unrealized_pct(p.buy_price, offer_now,
                                               p.qty) > 0):
                        reason = "ge_fill"
        if reason is None:
            continue
        price = latest.get(str(p.item_id))
        valid = isinstance(price, dict) and price_issue(price) is None
        fresh = valid and _fresh(price, EXIT_MAX_AGE, now)
        quote_sell = None
        guarded_fill = None
        if reason == "max_hold":
            if valid:
                # Mark to market at the last known bid (fresh or stale): a
                # flat close at the entry price would ignore real moves and
                # guarantee the 2% sale tax. Only with no price data at all
                # do we close flat at the entry.
                quote_sell = int(price.get("low", 0) or 0)
                sell = quote_sell if quote_sell > 0 else p.buy_price
                if quote_sell > 0:
                    guarded_fill = _artifact_exit_fill(
                        quote_sell, vol_5m.get(str(p.item_id)), p.buy_price, cfg)
                    if guarded_fill is not None:
                        sell = guarded_fill
            else:
                sell = p.buy_price  # expired; close flat without any quote
        elif fresh:
            if p.direction == "traditional" and reason in ("take_profit", "ge_fill"):
                quote_sell = int(price.get("high", 0) or 0)  # sell at the offer
                sell = quote_sell
            elif reason == "spread_collapse" and _ge_fill_confirmed(p, vol_5m, now):
                # A volume-confirmed GE buy-offer exits at the offer (that's
                # the spread-capture model: bought at the bid, sold at the
                # offer). Exiting at the bid would book the spread as a
                # loss even though the buy side already filled. Only when
                # there is real 5m volume data — the no-volume slow-default
                # fill is not evidence of an actual fill.
                quote_sell = int(price.get("high", 0) or 0)
                sell = quote_sell
            else:
                quote_sell = int(price.get("low", 0) or 0)  # sell at the bid
                sell = quote_sell
                if reason == "stop_loss":
                    guarded_fill = _artifact_exit_fill(
                        sell, vol_5m.get(str(p.item_id)), p.buy_price, cfg)
                    if guarded_fill is not None:
                        sell = guarded_fill  # print exit: fill at window avg
                    else:
                        sell = int(sell * cfg.stop_slippage)  # model worse fills
        else:
            # Unreachable today: exit_reason returns None for TP/SL/collapse
            # without a fresh price (only max_hold can arrive here with a
            # stale/absent quote, handled above). If exit_reason is ever
            # relaxed, hold rather than mis-price.
            continue
        if sell <= 0:
            continue
        opened = _opened_ts(p)
        if opened is None:
            print(f"[trader] warning: could not parse opened_at "
                  f"{p.opened_at!r} for position {p.id}", file=sys.stderr)
            hold_minutes = None
        else:
            hold_minutes = round((now - opened) / 60, 1)
        lots = close_positions(p.item_id, p.qty, sell, profile)
        entry_spread_pct = None
        if p.entry_offer and p.buy_price > 0:
            entry_spread_pct = round(
                (p.entry_offer - p.buy_price) / p.buy_price * 100, 2)
        for lot in lots:
            log_trade(p.item_id, lot["name"], lot["qty"], lot["buy_price"],
                      sell, note="paper", profile=profile, strategy="auto",
                      exit_reason=reason, hold_minutes=hold_minutes,
                      quote_sell=quote_sell, entry_spread_pct=entry_spread_pct,
                      fill_guard=guarded_fill is not None)
        closed.append({"item_id": p.item_id, "name": p.name, "qty": p.qty,
                       "reason": reason, "sell_price": sell,
                       "quote_sell": quote_sell, "hold_minutes": hold_minutes,
                       "profit": sum(l["profit"] for l in lots),
                       "fill_guard": guarded_fill is not None})
        _RECENT_EXITS[p.item_id] = (now, reason)
        _persist_recent_exits()

    remaining = [p for p in list_positions(profile) if p.note == "auto"]
    slots = max(0, cfg.max_positions - len(remaining))
    capital_used = sum(p.buy_price * p.qty for p in remaining)
    opened = []
    # One position per item, auto OR manual: stacking an auto position on
    # top of a hand-managed position splits the GE slot and the bank stack
    # into two rows for the same item, and the auto leg could close under
    # the manual one. Skip any candidate that already has any open position.
    all_open_items = set(p.item_id for p in list_positions(profile))
    for cand in candidates:
        if slots <= 0:
            break
        if cand.id in auto_open or cand.id in all_open_items:
            continue  # one position per item at a time (auto or manual)
        qty = size_position(cfg, capital_used, cand)
        if qty <= 0:
            print(f"[trader] skipped {cand.name}: size 0 "
                  f"(limit/by-market/budget constraint)", file=sys.stderr)
            continue
        open_position(cand.id, cand.name, qty, cand.sell_price,
                      direction="traditional", note="auto", profile=profile,
                      entry_sell=cand.sell_price, entry_offer=cand.buy_price)
        capital_used += qty * cand.sell_price
        slots -= 1
        opened.append({"item_id": cand.id, "name": cand.name,
                       "qty": qty, "buy_price": cand.sell_price})
    return {"candidates": len(candidates), "opened": opened, "closed": closed,
            "closed_pnl": sum(c["profit"] for c in closed)}


def run_trader(cfg, interval: int | None = None, profile: str | None = None,
               once: bool = False) -> dict | None:
    """Poll loop: manage and open paper positions. Blocks until stopped."""
    def _sigterm(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, _sigterm)
    if cfg.capital <= 0:
        raise ValueError("trader capital must be > 0")
    if not (0 < cfg.trade_capital_frac <= 1):
        raise ValueError("trade_capital_frac must be in (0, 1]")
    if cfg.max_positions <= 0:
        raise ValueError("max_positions must be > 0")
    if cfg.min_price < 10:
        raise ValueError("min_price must be >= 10")
    if cfg.take_profit_pct <= 0:
        raise ValueError("take_profit_pct must be > 0")
    if cfg.stop_loss_pct >= 0:
        raise ValueError("stop_loss_pct must be < 0")
    if cfg.max_hold_minutes <= 0:
        raise ValueError("max_hold_minutes must be > 0")
    if cfg.spread_collapse_exit_minutes < 0:
        raise ValueError("spread_collapse_exit_minutes must be >= 0")
    if cfg.min_exit_spread_pct < 0:
        raise ValueError("min_exit_spread_pct must be >= 0")
    if cfg.artifact_min_low_vol < 0:
        raise ValueError("artifact_min_low_vol must be >= 0")
    if not (0 < cfg.artifact_low_vol_frac <= 1):
        raise ValueError("artifact_low_vol_frac must be in (0, 1]")
    if cfg.artifact_outlier_pct < 0:
        raise ValueError("artifact_outlier_pct must be >= 0")
    if not (0 < cfg.stop_slippage <= 1):
        raise ValueError("stop_slippage must be in (0, 1]")
    if not (0 <= cfg.stop_mark_blend <= 1):
        raise ValueError("stop_mark_blend must be in [0, 1]")
    interval = interval or cfg.interval_sec
    prof_name = profile if profile else "default"
    pid = os.getpid()
    p_path = _pid_path(profile)
    # Claim the pid file with O_EXCL so two racing starts cannot both pass
    # the liveness check; a stale file from a dead process is replaced.
    for _ in range(2):
        try:
            fd = os.open(p_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(str(pid))
            break
        except FileExistsError:
            try:
                old_pid = int(p_path.read_text().strip())
                os.kill(old_pid, 0)
            except (ValueError, OSError):
                p_path.unlink(missing_ok=True)  # stale pid; retry the claim
                continue
            print(f"[trader] Already running (PID {old_pid}); use --stop first.",
                  file=sys.stderr)
            sys.exit(1)
    state = {"pid": pid, "started_iso": datetime.now(timezone.utc).isoformat(),
             "last_cycle_iso": None, "last_result": None,
             "realized_pnl": 0, "profile": prof_name, "running": True,
             "cycles": 0, "errors": 0, "exits_by_reason": {}}
    _write_state(state, profile)
    print(f"[trader] Paper trader started (PID {pid}, interval {interval}s, "
          f"capital {cfg.capital:,} gp)", file=sys.stderr)
    try:
        while True:
            cycle_started = time.time()
            result = {}
            try:
                result = run_cycle(cfg, profile)
            except SystemExit:
                result = {"error": "data sources unavailable"}
            except Exception as e:
                result = {"error": str(e)}
            print(f"[trader] cycle: {json.dumps(result)}", file=sys.stderr)
            state["cycles"] = state.get("cycles", 0) + 1
            if result.get("closed_pnl") is not None:
                state["realized_pnl"] = state.get("realized_pnl", 0) + result["closed_pnl"]
            for c in result.get("closed", []):
                reason = c.get("reason", "unknown")
                exits = state.setdefault("exits_by_reason", {})
                row = exits.setdefault(reason, {"count": 0, "profit": 0})
                row["count"] += 1
                row["profit"] += c.get("profit", 0)
            if result.get("error"):
                state["errors"] = state.get("errors", 0) + 1
            state["last_cycle_iso"] = datetime.now(timezone.utc).isoformat()
            state["last_result"] = result
            _write_state(state, profile)
            if once:
                break
            elapsed = time.time() - cycle_started
            time.sleep(max(1, interval - elapsed))
    except KeyboardInterrupt:
        print("\n[trader] Stopping...", file=sys.stderr)
    finally:
        try:
            # Only remove our own pid file; a later instance may have taken over.
            if _pid_path(profile).read_text().strip() == str(pid):
                _pid_path(profile).unlink(missing_ok=True)
        except (ValueError, OSError):
            pass
        state["running"] = False
        _write_state(state, profile)
    return state.get("last_result")


def stop_trader(profile: str | None = None) -> bool:
    p_path = _pid_path(profile)
    if not p_path.exists():
        return False
    try:
        pid = int(p_path.read_text().strip())
    except (ValueError, OSError):
        p_path.unlink(missing_ok=True)
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        p_path.unlink(missing_ok=True)
        return False
    os.kill(pid, signal.SIGTERM)
    deadline = time.time() + 3
    exited = False
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            exited = True
            break
        time.sleep(0.1)
    if not exited:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    try:
        if p_path.read_text().strip() == str(pid):
            p_path.unlink(missing_ok=True)
    except (ValueError, OSError):
        pass
    return True


def trader_status(profile: str | None = None) -> dict | None:
    """Live status when the pid file is present, else synced-state snapshot."""
    p_path = _pid_path(profile)
    state = _read_state(profile)
    if state is None:
        return None
    # The journal is the authoritative P&L ledger; the state counter resets
    # on every daemon start, so expose the all-time auto P&L alongside it.
    journal_pnl = None
    journal_trades = None
    try:
        from rshelper.journal import list_trades
        auto_trades = list_trades(profile=profile, strategy="auto")
        journal_pnl = sum(t.profit for t in auto_trades)
        journal_trades = len(auto_trades)
    except Exception:
        pass
    local_pid = None
    pid_file_present = False
    try:
        pid_file_present = p_path.exists()
        local_pid = int(p_path.read_text().strip())
        os.kill(local_pid, 0)
    except (OSError, ValueError, AttributeError):
        local_pid = None
    if pid_file_present and local_pid is None:
        # A pid file exists here but the process is dead (SIGKILL/reboot):
        # report truthfully as stopped and drop the stale pid file.
        try:
            p_path.unlink(missing_ok=True)
        except OSError:
            pass
        base = _status_base(state)
        base["journal_realized_pnl"] = journal_pnl
        base["journal_auto_trades"] = journal_trades
        return {"running": False, "local": True, "pid": None, **base}
    if local_pid is None:
        # No live process here: report the synced snapshot truthfully.
        base = _status_base(state)
        base["journal_realized_pnl"] = journal_pnl
        base["journal_auto_trades"] = journal_trades
        return {"running": bool(state.get("running")),
                "local": False, "pid": None, **base}
    base = _status_base(state)
    base["journal_realized_pnl"] = journal_pnl
    base["journal_auto_trades"] = journal_trades
    return {"running": True, "local": True, "pid": local_pid, **base}
