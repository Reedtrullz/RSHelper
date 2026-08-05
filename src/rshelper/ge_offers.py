"""Grand Exchange offer simulation: fill progress, slots, collect."""

import time
from datetime import datetime, timezone

from rshelper.journal import log_trade
from rshelper.market import ge_tax, price_issue, safe_int
from rshelper.positions import close_positions, list_positions

MAX_GE_SLOTS = 8


def resolve_icon_url(item_name: str, detail: bool = True) -> str:
    """OSRS wiki sprite URL from an item name.
    detail=True -> <Name>_detail.png (GE slot sprite).
    detail=False -> <Name>.png (inventory sprite).
    """
    from urllib.parse import quote
    suffix = "_detail" if detail else ""
    # The wiki stores files with URL-encoded names (apostrophes, &, etc.).
    base = quote(item_name.replace(" ", "_"), safe="")
    return "https://oldschool.runescape.wiki/images/" + base + suffix + ".png"


def _elapsed_minutes(opened_at: str, now: float) -> float:
    """Minutes since opened_at (UTC ISO string), clamped to >= 0."""
    try:
        opened = datetime.fromisoformat(opened_at)
        if opened.tzinfo is None:
            opened = opened.replace(tzinfo=timezone.utc)
        now_dt = datetime.fromtimestamp(now, tz=timezone.utc)
        return max(0.0, (now_dt - opened).total_seconds() / 60.0)
    except (ValueError, TypeError):
        return 0.0


def compute_fill_pct(qty: int, volume_5m: int, opened_at: str,
                     now: float | None = None) -> float:
    """0.0-1.0 fill progress, ease-out curve.

    rate = volume_5m / 5 units per minute; raw = elapsed_min * rate / qty;
    fill = 1 - (1 - min(raw, 1))^2. Zero/unknown volume falls back to a
    slow default: min(1.0, elapsed_min * (1/qty)).
    """
    if qty <= 0:
        return 0.0
    elapsed = _elapsed_minutes(opened_at, now if now is not None else time.time())
    if volume_5m > 0:
        rate = volume_5m / 5.0
        raw = min(1.0, elapsed * rate / qty)
        return 1.0 - (1.0 - raw) ** 2
    return min(1.0, elapsed * (1.0 / qty))


def _current_leg(price: dict, direction: str) -> int:
    """Exit leg for a position: offer (high) for traditional, bid (low) for arbitrage."""
    if direction == "traditional":
        return safe_int(price.get("high", 0))
    return safe_int(price.get("low", 0))


def _item_volume_5m(entry) -> int:
    """Total 5m trade volume from a cache entry (int or wiki per-side dict)."""
    if isinstance(entry, dict):
        return (safe_int(entry.get("highPriceVolume"))
                + safe_int(entry.get("lowPriceVolume")))
    return safe_int(entry)


def build_ge_slots(profile=None, latest=None, vol_5m=None, now=None) -> dict:
    """All 8 GE slots from open positions.

    Returns {"slots": [...], "empty_count": int, "total_value": int}.
    Each slot dict:
    {"index", "offer_type": "buy"|"sell", "item_id", "name", "qty",
     "fill_pct", "status": "pending"|"partially_filled"|"filled",
     "price" (qty*buy_price), "price_each", "buy_price",
     "current_price"|None, "unrealized"|None, "unrealized_pct",
     "icon_url", "icon_url_detail", "position_id", "opened_at",
     "age_minutes", "can_collect": fill >= 1.0}

    latest/vol_5m are injected (dashboard cache dicts) so tests can pass
    fixtures. Direction "traditional" -> buy offer, "arbitrage" -> sell
    offer. Realized offer_type is the *open side* of the position.
    """
    now = now if now is not None else time.time()
    latest = latest or {}
    vol_5m = vol_5m or {}
    slots = []
    for index, p in enumerate(list_positions(profile)[:MAX_GE_SLOTS]):
        fill = compute_fill_pct(p.qty, _item_volume_5m(vol_5m.get(str(p.item_id))),
                                p.opened_at, now)
        if fill >= 1.0:
            status = "filled"
        elif fill <= 0.0:
            status = "pending"
        else:
            status = "partially_filled"
        offer_type = "buy" if p.direction == "traditional" else "sell"
        price = latest.get(str(p.item_id))
        issue = price_issue(price, now=now) if isinstance(price, dict) else "no data"
        current_price = None
        unrealized = None
        unrealized_pct = None
        if issue is None:
            current_price = _current_leg(price, p.direction)
            tax = ge_tax(current_price)
            unrealized = (current_price - p.buy_price) * p.qty - tax * p.qty
            unrealized_pct = (round(
                (current_price - p.buy_price - tax) / p.buy_price * 100, 2)
                if p.buy_price > 0 else 0.0)
        slots.append({
            "index": index,
            "offer_type": offer_type,
            "item_id": p.item_id,
            "name": p.name,
            "qty": p.qty,
            "fill_pct": round(fill, 4),
            "status": status,
            "price": p.qty * p.buy_price,
            "price_each": p.buy_price,
            "buy_price": p.buy_price,
            "current_price": current_price,
            "unrealized": unrealized,
            "unrealized_pct": unrealized_pct,
            "icon_url": resolve_icon_url(p.name, detail=False),
            "icon_url_detail": resolve_icon_url(p.name, detail=True),
            "position_id": p.id,
            "opened_at": p.opened_at,
            "age_minutes": round(_elapsed_minutes(p.opened_at, now), 1),
            "can_collect": fill >= 1.0,
            "auto": p.note == "auto",  # auto-trader closes these itself
            "entry_sell": p.entry_sell,
            "entry_offer": p.entry_offer,
            "spread_pct": (round((p.entry_offer - p.buy_price) / p.buy_price * 100, 2)
                           if p.entry_offer and p.buy_price > 0 else None),
            "exit_reason": "ge_fill" if (p.note == "auto" and fill >= 1.0) else None,
        })
    return {
        "slots": slots,
        "empty_count": max(0, MAX_GE_SLOTS - len(slots)),
        "total_value": sum(s["price"] for s in slots),
    }


def collect_offer(position_id: int, profile=None, latest=None) -> dict:
    """Close a filled position at the live price.

    Calls close_positions(position's item/qty, sell_price) then
    log_trade(..., note="paper", strategy="ge_collect"). Sell price is
    the current market "high" (offer) for traditional, "low" (bid) for
    arbitrage; fall back to buy_price when no usable price. Returns
    {"ok": True, "name", "qty", "sell_price", "profit"}. Raises
    ValueError when the position id is unknown.
    """
    position = next((p for p in list_positions(profile)
                     if p.id == position_id), None)
    if position is None:
        raise ValueError(f"unknown position id {position_id}")
    sell_price = close_market_price(position, latest)
    # Close the SPECIFIC lot (not FIFO): the GE Collect button maps to one
    # slot; with several lots of the same item open, FIFO would book the
    # oldest lot's cost basis instead of the clicked one.
    lots = close_positions(position.item_id, position.qty, sell_price,
                           profile, position_id=position.id)
    for lot in lots:
        log_trade(position.item_id, lot["name"], lot["qty"], lot["buy_price"],
                  sell_price, note="paper", profile=profile,
                  strategy="ge_collect", exit_reason="collect")
    return {
        "ok": True,
        "name": position.name,
        "qty": position.qty,
        "sell_price": sell_price,
        "profit": sum(lot["profit"] for lot in lots),
    }


def close_market_price(position, latest: dict | None) -> int:
    """Current market exit price for a position, else its entry price.

    The direction-aware exit leg (offer/high for traditional, bid/low for
    arbitrage) at a usable live quote; falls back to the entry buy_price
    when no usable price exists (the same fallback collect_offer uses).
    Shared by the dashboard's manual position close and GE collect.
    """
    latest = latest or {}
    sell_price = position.buy_price
    price = latest.get(str(position.item_id))
    if isinstance(price, dict) and price_issue(price) is None:
        leg = _current_leg(price, position.direction)
        if leg > 0:
            sell_price = leg
    return sell_price
