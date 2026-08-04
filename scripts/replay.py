#!/usr/bin/env python3
"""Replay the paper-trader entry/exit logic over real 5m candles.

Feeds historical 5m OHLC (avgHigh/avgLow/volumes) through the same
filters and decisions the live trader uses — select_candidates entry,
exit_reason exit, ge_fill auto-collect, tax, slippage — and reports
ROI / win rate / max drawdown / profit factor for a given config.

This is a *model* of the trader, not a perfect simulation: it assumes
the entry bid and exit legs fill at the candle's avgHigh/avgLow, and it
walks candle-by-candle with a 5m cadence. It is meant to compare configs
against each other on the same data, not to predict absolute returns.

Usage:
    PYTHONPATH=src .venv/bin/python scripts/replay.py [--items I1,I2,..]
        [--min-spread 4.0] [--dip-depth 2.0] [--max-dip 10.0]
        [--stop -1.5] [--tp 3.0] [--grace 10] [--time-exit 60]
        [--hold 180] [--json]

Data: reads /tmp/replay_ts.json (or fetches top items from the journal).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from rshelper.market import ge_tax, safe_int

REPLAY_DATA = os.environ.get("REPLAY_DATA", "/tmp/replay_ts.json")


@dataclass
class ReplayConfig:
    min_spread_pct: float = 4.0
    dip_depth_pct: float = 2.0
    max_dip_pct: float = 10.0
    min_volume: int = 800
    stop_loss_pct: float = -1.5
    take_profit_pct: float = 3.0
    stop_grace_minutes: int = 10
    time_exit_minutes: int = 60
    max_hold_minutes: int = 180
    stop_slippage: float = 0.97
    capital_frac: float = 0.25   # fraction of bankroll per position
    max_volume_frac: float = 0.10  # max position = this fraction of 5m volume
    trailing_tp_pct: float = 0.0  # exit when the offer pulls back this % from its peak (0 = fixed TP)


@dataclass
class Position:
    item_id: int
    qty: int
    buy: int
    opened_at_idx: int
    entry_offer: int
    candles: list  # the item's candle list (for avgLow reference)
    peak_offer: int = 0  # highest offer seen since entry (for trailing TP)


def _elapsed_minutes(opened_at_iso: str, now_iso: str) -> float:
    try:
        a = datetime.fromisoformat(opened_at_iso.replace("Z", "+00:00"))
        b = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
        return max(0.0, (b - a).total_seconds() / 60.0)
    except (ValueError, TypeError):
        return 0.0


def _candle_iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _entry_spread(candle: dict) -> float:
    """Spread % = (high - low) / low for a 5m candle (wiki legs)."""
    hi = safe_int(candle.get("avgHighPrice"))
    lo = safe_int(candle.get("avgLowPrice"))
    if lo <= 0:
        return 0.0
    return (hi - lo) / lo * 100


def _volume(candle: dict) -> int:
    return (safe_int(candle.get("highPriceVolume"))
            + safe_int(candle.get("lowPriceVolume")))


def _ge_fill_pct(pos: Position, candle: dict) -> float:
    """0-1 simulated GE buy-fill, same curve as the live trader: rate =
    volume/5 per minute, ease-out, capped at 1.0."""
    qty = pos.qty
    vol = _volume(candle)
    opened_idx = pos.opened_at_idx
    now_iso = _candle_iso(candle.get("timestamp", 0))
    opened_iso = _candle_iso(pos.candles[opened_idx].get("timestamp", 0))
    elapsed = _elapsed_minutes(opened_iso, now_iso)
    if qty <= 0:
        return 0.0
    if vol <= 0:
        return min(1.0, elapsed * (1.0 / qty))
    raw = min(1.0, elapsed * (vol / 5.0) / qty)
    return 1.0 - (1.0 - raw) ** 2


def simulate(timeseries: dict[int, list[dict]], cfg: ReplayConfig,
             capital: int = 1_000_000, max_positions: int = 3) -> dict:
    """Walk a global 5-min clock; open the top-edge candidates into the
    global slot budget (one position per item), exit on TP/SL/time/hold.

    This matches the live trader's run_cycle: at each step it (1) exits
    open positions, then (2) fills free slots with the highest-edge
    candidates not already held. capital caps total deployed gp.
    """
    # Group candles by item, each sorted by timestamp
    items = {}
    for iid, candles in timeseries.items():
        items[int(iid)] = sorted(candles, key=lambda c: c.get("timestamp", 0))
    if not items:
        return {"error": "no timeseries data"}

    # Align all items to a global step list: the union of their timestamps.
    # Each item advances its own candle index as the clock reaches it.
    all_ts = sorted({c.get("timestamp", 0) for cs in items.values() for c in cs})
    # Map each item's candle index for a given timestamp.
    idx_map = {}
    for iid, cs in items.items():
        idx_map[iid] = {c.get("timestamp", 0): i for i, c in enumerate(cs)}

    trades = []
    positions: list[Position] = []  # global open positions (max max_positions)
    open_items: set[int] = set()
    capital_used = 0

    def _exit_pos(pos: Position, reason: str, sell: int, now_iso: str,
                  idx: int, candle: dict) -> None:
        nonlocal capital_used
        tax = ge_tax(sell) * pos.qty
        profit = (sell - pos.buy) * pos.qty - tax
        trades.append({
            "item_id": pos.item_id, "qty": pos.qty, "buy": pos.buy,
            "sell": sell, "profit": profit, "reason": reason,
            "hold_minutes": round(_elapsed_minutes(
                _candle_iso(pos.candles[pos.opened_at_idx].get("timestamp", 0)),
                now_iso), 1),
            "spread_pct": round(_entry_spread(pos.candles[pos.opened_at_idx]), 2),
        })
        capital_used -= pos.buy * pos.qty

    for ts in all_ts:
        now_iso = _candle_iso(ts)
        # --- Exits first (evaluate each open position at its current candle) ---
        still_open = []
        for pos in positions:
            iid = pos.item_id
            idx = idx_map[iid].get(ts)
            if idx is None:
                still_open.append(pos)  # no candle this step; hold
                continue
            candle = items[iid][idx]
            hi = safe_int(candle.get("avgHighPrice"))
            lo = safe_int(candle.get("avgLowPrice"))
            if hi > pos.peak_offer:
                pos.peak_offer = hi
            age_min = _elapsed_minutes(
                _candle_iso(pos.candles[pos.opened_at_idx].get("timestamp", 0)),
                now_iso)
            reason = None
            sell = None
            if age_min >= cfg.max_hold_minutes:
                reason = "max_hold"
                sell = lo if lo > 0 else pos.buy
            elif hi > 0 and (hi - pos.buy - ge_tax(hi)) / pos.buy * 100 >= cfg.take_profit_pct:
                reason = "take_profit"
                sell = hi
            elif (cfg.trailing_tp_pct > 0 and pos.peak_offer > pos.buy
                    and (pos.peak_offer - hi) / pos.peak_offer * 100 >= cfg.trailing_tp_pct):
                reason = "take_profit"
                sell = hi
            elif hi > 0 and _ge_fill_pct(pos, candle) >= 1.0 \
                    and (hi - pos.buy - ge_tax(hi)) / pos.buy * 100 > 0:
                reason = "ge_fill"
                sell = hi
            elif lo > 0:
                move = (lo - pos.buy) / pos.buy * 100
                if move <= cfg.stop_loss_pct and age_min >= cfg.stop_grace_minutes:
                    reason = "stop_loss"
                    sell = int(lo * cfg.stop_slippage)
                elif age_min >= cfg.time_exit_minutes:
                    reason = "spread_collapse"
                    sell = hi if hi > lo else lo
            if reason and sell and sell > 0:
                _exit_pos(pos, reason, sell, now_iso, idx, candle)
                open_items.discard(iid)
            else:
                still_open.append(pos)
        positions = still_open

        # --- Entries: rank all candidates this step by edge, fill free slots ---
        if len(positions) < max_positions:
            candidates = []
            for iid, cs in items.items():
                if iid in open_items:
                    continue  # one position per item
                idx = idx_map[iid].get(ts)
                if idx is None:
                    continue
                candle = cs[idx]
                lo = safe_int(candle.get("avgLowPrice"))
                hi = safe_int(candle.get("avgHighPrice"))
                vol = _volume(candle)
                spread = _entry_spread(candle)
                window = cs[max(0, idx - 11):idx + 1]
                avg_low = sum(safe_int(c.get("avgLowPrice")) for c in window) / max(1, len(window))
                dip = (avg_low - lo) / avg_low * 100 if avg_low > 0 else 0
                if (lo >= 25 and vol >= cfg.min_volume
                        and cfg.min_spread_pct <= spread <= 5.0
                        and cfg.dip_depth_pct <= dip <= cfg.max_dip_pct):
                    # edge = dip * (spread - 2%) like the live trader
                    edge = dip * max(0.0, spread - 2.0)
                    qty = min(20000, int(capital * cfg.capital_frac) // lo,
                              int(vol * cfg.max_volume_frac))
                    if qty > 0 and capital_used + lo * qty <= capital:
                        candidates.append((edge, vol, iid, lo, hi, qty, idx))
            candidates.sort(key=lambda c: (c[0], c[1]), reverse=True)
            for edge, vol, iid, lo, hi, qty, idx in candidates:
                if len(positions) >= max_positions:
                    break
                if iid in open_items:
                    continue
                positions.append(Position(iid, qty, lo, idx, hi, items[iid],
                                          peak_offer=hi))
                open_items.add(iid)
                capital_used += lo * qty

    if not trades:
        return {"error": "no trades generated"}

    total_profit = sum(t["profit"] for t in trades)
    wins = [t for t in trades if t["profit"] > 0]
    losses = [t for t in trades if t["profit"] < 0]
    cost_basis = sum(t["buy"] * t["qty"] for t in trades)
    peak = 0
    cum = 0
    max_dd = 0
    for t in trades:
        cum += t["profit"]
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
    gross_profit = sum(t["profit"] for t in wins)
    gross_loss = abs(sum(t["profit"] for t in losses))
    return {
        "trades": len(trades),
        "trade_list": trades,
        "total_profit": total_profit,
        "roi_pct": round(total_profit / cost_basis * 100, 2) if cost_basis else 0,
        "win_rate": round(len(wins) / len(trades) * 100, 1),
        "avg_win": round(sum(t["profit"] for t in wins) / max(1, len(wins))),
        "avg_loss": round(sum(t["profit"] for t in losses) / max(1, len(losses))),
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss else float("inf"),
        "max_drawdown": max_dd,
        "by_reason": _by_reason(trades),
    }


def _by_reason(trades: list[dict]) -> dict:
    out = {}
    for t in trades:
        r = out.setdefault(t["reason"], {"n": 0, "profit": 0})
        r["n"] += 1
        r["profit"] += t["profit"]
    return out


def load_data() -> dict[int, list[dict]]:
    path = Path(REPLAY_DATA)
    if not path.exists():
        print(f"no data at {REPLAY_DATA}; run the fetch first", file=sys.stderr)
        return {}
    raw = json.loads(path.read_text())
    return {int(k): v for k, v in raw.items()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--items", help="comma-separated item ids (default: all)")
    ap.add_argument("--min-spread", type=float, default=4.0)
    ap.add_argument("--dip-depth", type=float, default=2.0)
    ap.add_argument("--max-dip", type=float, default=10.0)
    ap.add_argument("--stop", type=float, default=-1.5)
    ap.add_argument("--tp", type=float, default=3.0)
    ap.add_argument("--grace", type=int, default=10)
    ap.add_argument("--time-exit", type=int, default=60)
    ap.add_argument("--hold", type=int, default=180)
    ap.add_argument("--trailing-tp", type=float, default=0.0)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    data = load_data()
    if args.items:
        wanted = {int(x) for x in args.items.split(",")}
        data = {k: v for k, v in data.items() if k in wanted}
    if not data:
        print("no data loaded", file=sys.stderr)
        return 1

    cfg = ReplayConfig(
        min_spread_pct=args.min_spread, dip_depth_pct=args.dip_depth,
        max_dip_pct=args.max_dip, stop_loss_pct=args.stop,
        take_profit_pct=args.tp, stop_grace_minutes=args.grace,
        time_exit_minutes=args.time_exit, max_hold_minutes=args.hold,
        trailing_tp_pct=args.trailing_tp,
    )
    result = simulate(data, cfg)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"items={len(data)} config={args}")
        print(f"trades={result.get('trades')} roi={result.get('roi_pct')}% "
              f"win={result.get('win_rate')}% avg_win={result.get('avg_win')} "
              f"avg_loss={result.get('avg_loss')} pf={result.get('profit_factor')} "
              f"max_dd={result.get('max_drawdown')}")
        print("by_reason:", json.dumps(result.get("by_reason", {})))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
