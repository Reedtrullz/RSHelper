"""Bank holdings: aggregate open positions into an inventory view."""

import time

from rshelper.ge_offers import resolve_icon_url
from rshelper.market import ge_tax, price_issue
from rshelper.positions import list_positions


def build_bank_items(profile=None, latest=None, now=None) -> dict:
    """Group positions by item_id (weighted avg buy price).

    Returns {"items": [...], "total_value", "unrealized_pnl", "cost_basis",
    "slot_count"} sorted by total_value desc.
    Each item: {"item_id", "name", "total_qty", "avg_buy_price",
    "current_price"|None, "total_value", "cost_basis",
    "unrealized_pnl" (current - cost - ge_tax(current)*qty),
    "unrealized_pct", "position_count", "icon_url", "icon_url_detail"}

    Items mark to the exit leg of the oldest open lot for the item
    (offer/high for traditional, bid/low for arbitrage) — the same
    convention the CLI uses when closing.
    """
    now = now if now is not None else time.time()
    latest = latest or {}
    groups: dict[int, dict] = {}
    for p in list_positions(profile):
        g = groups.setdefault(p.item_id, {
            "item_id": p.item_id, "name": p.name, "total_qty": 0,
            "cost_basis": 0, "position_count": 0, "direction": p.direction,
        })
        g["total_qty"] += p.qty
        g["cost_basis"] += p.buy_price * p.qty
        g["position_count"] += 1
    items = []
    for item_id, g in groups.items():
        total_qty = g["total_qty"]
        avg_buy = round(g["cost_basis"] / total_qty) if total_qty > 0 else 0
        price = latest.get(str(item_id))
        issue = price_issue(price, now=now) if isinstance(price, dict) else "no data"
        current_price = None
        total_value = g["cost_basis"]
        unrealized = 0
        unrealized_pct = None
        if issue is None:
            current_price = (int(price.get("high", 0) or 0)
                             if g["direction"] == "traditional"
                             else int(price.get("low", 0) or 0))
            tax = ge_tax(current_price)
            total_value = current_price * total_qty
            unrealized = total_value - g["cost_basis"] - tax * total_qty
            unrealized_pct = (round(
                (current_price - avg_buy - tax) / avg_buy * 100, 2)
                if avg_buy > 0 else 0.0)
        items.append({
            "item_id": item_id,
            "name": g["name"],
            "total_qty": total_qty,
            "avg_buy_price": avg_buy,
            "current_price": current_price,
            "total_value": total_value,
            "cost_basis": g["cost_basis"],
            "unrealized_pnl": unrealized,
            "unrealized_pct": unrealized_pct,
            "position_count": g["position_count"],
            "icon_url": resolve_icon_url(g["name"], detail=False),
            "icon_url_detail": resolve_icon_url(g["name"], detail=True),
        })
    items.sort(key=lambda i: i["total_value"], reverse=True)
    return {
        "items": items,
        "total_value": sum(i["total_value"] for i in items),
        "unrealized_pnl": sum(i["unrealized_pnl"] for i in items),
        "cost_basis": sum(i["cost_basis"] for i in items),
        "slot_count": len(items),
    }
