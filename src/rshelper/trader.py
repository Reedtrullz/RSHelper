"""Autonomous paper trader: finds candidates and executes paper trades.

Paper-only by design — there is no live GE integration, so nothing here
touches real GP. A poll loop opens positions on liquid, sane-spread,
upward-momentum items and closes them at take-profit / stop-loss /
max-hold, logging realized trades into the journal like any other paper
trade. Only positions it opened (note="auto") are managed.
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

# ponytail: price freshness windows. The wiki /latest endpoint publishes on
# a rolling ~2-3 minute cycle even for 100k-volume items (measured), so
# entries accept data up to 5 minutes old; exits are stricter.
ENTRY_MAX_AGE = 300
EXIT_MAX_AGE = 300
STOP_SLIPPAGE = 0.97  # model worse fills when stopping out
MAX_VOLUME_FRACTION = 0.25  # never size above 25% of the last 5m volume

# ponytail: in-memory only; a daemon restart forgets recent exits, which is
# fine (worst case one early re-entry per restart).
_RECENT_EXITS: dict[int, float] = {}


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


def select_candidates(items, latest: dict, vol_5m: dict, cfg,
                      now: float | None = None) -> list:
    """Filter items to liquid, sane, freshly-dipped buy-the-dip candidates."""
    now = now if now is not None else time.time()
    out = []
    for item in items:
        if item.buy_price < 10:
            continue
        if item.volume < cfg.min_volume:
            continue
        lo, hi = min(item.buy_price, item.sell_price), max(item.buy_price, item.sell_price)
        if hi > cfg.max_spread_ratio * lo:
            continue
        spread_pct = (item.buy_price - item.sell_price) / item.sell_price * 100
        if abs(spread_pct) > cfg.max_entry_spread_pct:
            continue
        price = latest.get(str(item.id))
        if not isinstance(price, dict) or not _fresh(price, ENTRY_MAX_AGE, now):
            continue
        avg_low = (vol_5m.get(str(item.id)) or {}).get("avgLowPrice")
        if not avg_low or avg_low <= 0:
            continue  # no dip baseline (e.g. fallback data)
        dip_pct = (avg_low - item.sell_price) / avg_low * 100
        if dip_pct < cfg.dip_depth_pct:
            continue  # not dipped enough below the 5m average
        if dip_pct > cfg.max_dip_pct:
            continue  # falling too hard; not a dip, a freefall
        if now - _RECENT_EXITS.get(item.id, 0) < cfg.reentry_minutes * 60:
            continue
        out.append(item)
    out.sort(key=lambda i: i.volume, reverse=True)
    return out


def unrealized_pct(buy: int, sell: int, qty: int) -> float:
    """Unrealized P&L % of the position, net of 2% sell tax."""
    if buy <= 0 or qty <= 0:
        return 0.0
    tax = ge_tax(sell)
    unreal = (sell - buy) * qty - tax * qty
    return unreal / (buy * qty) * 100


def exit_reason(position, latest: dict, cfg, now: float | None = None):
    """Return 'take_profit' | 'stop_loss' | 'max_hold' | None."""
    now = now if now is not None else time.time()
    # max_hold first: it must fire even when no fresh price is available,
    # otherwise a position on a dead item could sit open forever.
    try:
        opened = datetime.fromisoformat(position.opened_at.replace("Z", "+00:00")).timestamp()
        age_min = (now - opened) / 60
        if age_min >= cfg.max_hold_minutes:
            return "max_hold"
    except (ValueError, TypeError):
        pass
    price = latest.get(str(position.item_id))
    if not isinstance(price, dict) or price_issue(price) or not _fresh(price, EXIT_MAX_AGE, now):
        return None  # no usable price this cycle; hold
    sell = int(price.get("low", 0) or 0)
    if sell <= 0:
        return None
    pct = unrealized_pct(position.buy_price, sell, position.qty)
    if pct >= cfg.take_profit_pct:
        return "take_profit"
    if pct <= cfg.stop_loss_pct:
        return "stop_loss"
    return None


def size_position(cfg, capital_used: int, entry) -> int:
    """Units to open, capped by budget, bankroll, GE limit, and market share."""
    per_trade = int(cfg.capital * cfg.trade_capital_frac)
    budget = min(per_trade, max(0, cfg.capital - capital_used))
    if entry.buy_price <= 0:
        return 0
    by_market = int(entry.volume * MAX_VOLUME_FRACTION)
    return min(entry.buy_limit, by_market, budget // entry.buy_price)


def run_cycle(cfg, profile: str | None = None) -> dict:
    """One poll cycle: manage auto positions (exits) then open new ones."""
    from rshelper.cli import _fetch_bootstrap
    from rshelper.positions import close_positions, list_positions, open_position
    from rshelper.journal import log_trade

    _mapping, latest, vol_5m, items = _fetch_bootstrap(profile)
    candidates = select_candidates(items, latest, vol_5m, cfg)

    closed = []
    auto_open = set()
    for p in list_positions(profile):
        if p.note != "auto":
            continue
        auto_open.add(p.item_id)
        reason = exit_reason(p, latest, cfg)
        if reason is None:
            continue
        price = latest.get(str(p.item_id))
        usable = isinstance(price, dict) and price_issue(price) is None \
            and _fresh(price, EXIT_MAX_AGE, time.time())
        if reason == "max_hold" and not usable:
            sell = p.buy_price  # expired; close flat without a fresh quote
        elif usable:
            sell = int(price.get("low", 0) or 0)
            if reason == "stop_loss":
                sell = int(sell * STOP_SLIPPAGE)  # model worse fills on stops
        else:
            continue
        if sell <= 0:
            continue
        lots = close_positions(p.item_id, p.qty, sell, profile)
        for lot in lots:
            log_trade(p.item_id, lot["name"], lot["qty"], lot["buy_price"],
                      sell, note="paper", profile=profile)
        closed.append({"item_id": p.item_id, "name": p.name, "qty": p.qty,
                       "reason": reason, "sell_price": sell,
                       "profit": sum(l["profit"] for l in lots)})
        _RECENT_EXITS[p.item_id] = time.time()

    remaining = [p for p in list_positions(profile) if p.note == "auto"]
    slots = max(0, cfg.max_positions - len(remaining))
    capital_used = sum(p.buy_price * p.qty for p in remaining)
    opened = []
    for cand in candidates:
        if slots <= 0:
            break
        if cand.id in auto_open:
            continue  # one auto position per item at a time
        qty = size_position(cfg, capital_used, cand)
        if qty <= 0:
            continue
        open_position(cand.id, cand.name, qty, cand.buy_price,
                      direction="arbitrage", note="auto", profile=profile)
        capital_used += qty * cand.buy_price
        slots -= 1
        opened.append({"item_id": cand.id, "name": cand.name,
                       "qty": qty, "buy_price": cand.buy_price})
    return {"candidates": len(candidates), "opened": opened, "closed": closed,
            "closed_pnl": sum(c["profit"] for c in closed)}


def run_trader(cfg, interval: int | None = None, profile: str | None = None,
               once: bool = False) -> dict | None:
    """Poll loop: manage and open paper positions. Blocks until stopped."""
    if cfg.capital <= 0:
        raise ValueError("trader capital must be > 0")
    if not (0 < cfg.trade_capital_frac <= 1):
        raise ValueError("trade_capital_frac must be in (0, 1]")
    if cfg.max_positions <= 0:
        raise ValueError("max_positions must be > 0")
    if cfg.take_profit_pct <= 0:
        raise ValueError("take_profit_pct must be > 0")
    if cfg.stop_loss_pct >= 0:
        raise ValueError("stop_loss_pct must be < 0")
    if cfg.max_hold_minutes <= 0:
        raise ValueError("max_hold_minutes must be > 0")
    interval = interval or cfg.interval_sec
    prof_name = profile if profile else "default"
    pid = os.getpid()
    p_path = _pid_path(profile)
    try:
        old_pid = int(p_path.read_text().strip())
        os.kill(old_pid, 0)
        print(f"[trader] Already running (PID {old_pid}); use --stop first.",
              file=sys.stderr)
        sys.exit(1)
    except (ValueError, OSError):
        pass  # no live previous instance
    from rshelper.profile import atomic_write_text
    atomic_write_text(p_path, str(pid))
    state = {"pid": pid, "started_iso": datetime.now(timezone.utc).isoformat(),
             "last_cycle_iso": None, "last_result": None,
             "realized_pnl": 0, "profile": prof_name}
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
            if result.get("closed_pnl"):
                state["realized_pnl"] = state.get("realized_pnl", 0) + result["closed_pnl"]
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
    p_path = _pid_path(profile)
    state = _read_state(profile)
    if not p_path.exists() or state is None:
        return None
    try:
        pid = int(p_path.read_text().strip())
        os.kill(pid, 0)
    except (OSError, ValueError):
        return None
    return {"running": True, "pid": pid, "profile": state.get("profile", "default"),
            "started_iso": state.get("started_iso"),
            "last_cycle_iso": state.get("last_cycle_iso"),
            "last_result": state.get("last_result")}
