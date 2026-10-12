"""Bank holdings: aggregate open positions into an inventory view."""

import time

from rshelper.ge_offers import resolve_icon_url
from rshelper.market import ge_tax, price_issue, safe_int
from rshelper.positions import list_positions


def build_bank_items(profile=None,latest=None,now=None):
    from rshelper import state_transaction,paper_book,positions
    root=positions._positions_path(profile).parent
    now=time.time() if now is None else now
    with state_transaction.profile_transaction(profile or 'default',root):
        result=_build_bank_items(profile,latest,now)
        equity={'initialized':False,'available_cash':None,'reserved_cash':None,
                'realized_profit':None,'marked_equity':None,'equity_return_pct':None}
        if (root/'paper-offers.json').exists():
            state=paper_book.budget_snapshot(profile,now=now)
            budget=state['budget']
            complete=result['total_value'] is not None and not any('unreconciled' in reason for reason in budget['unknown'])
            net_mark=result['cost_basis']+result['marked_unrealized_pnl']
            total=budget['available_cash']-budget['cash_deficit']+budget['reserved_cash']+net_mark if complete else None
            baseline=budget['initial_bankroll']
            equity={'initialized':True,'available_cash':budget['available_cash'],
                    'reserved_cash':budget['reserved_cash'],'cash_deficit':budget['cash_deficit'],
                    'realized_profit':budget['realized_profit'],'marked_equity':total,
                    'equity_return_pct':(round((total-baseline)/baseline*100,2) if total is not None and baseline else None),
                    'basis':'since-explicit-paper-budget-initialization'}
            equity['book_revision']=state['revision']
        from datetime import datetime,timezone
        from rshelper.market_data import provenance
        equity.update(observed_at=datetime.fromtimestamp(now,timezone.utc).isoformat(),
                      scope='whole-profile',market_data={'latest':provenance(latest)},
                      mark_coverage=result['mark_coverage'])
        result['equity']=equity
        return result


def _build_bank_items(profile=None, latest=None, now=None) -> dict:
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
    latest = latest if latest is not None else {}
    groups: dict[int, dict] = {}
    for p in list_positions(profile):
        g = groups.setdefault(p.item_id, {
            "item_id": p.item_id, "name": p.name, "total_qty": 0,
            "cost_basis": 0, "position_count": 0,
            "qty_by_direction": {"traditional": 0, "arbitrage": 0},
        })
        g["total_qty"] += p.qty
        g["cost_basis"] += p.buy_price * p.qty
        g["position_count"] += 1
        g["qty_by_direction"][p.direction] = (
            g["qty_by_direction"].get(p.direction, 0) + p.qty)
    items = []
    for item_id, g in groups.items():
        total_qty = g["total_qty"]
        avg_buy = round(g["cost_basis"] / total_qty) if total_qty > 0 else 0
        price = latest.get(str(item_id))
        issue = price_issue(price, now=now) if isinstance(price, dict) else "no data"
        current_price = None
        total_value = None
        unrealized = None
        unrealized_pct = None
        if issue is None:
            # Mark each lot to its own exit leg: traditional sells at the
            # offer (high), arbitrage at the bid (low). A stack with mixed
            # directions is valued per-lot, not with the first lot's leg.
            offer = safe_int(price.get("high", 0))
            bid = safe_int(price.get("low", 0))
            trad_qty = g["qty_by_direction"].get("traditional", 0)
            arb_qty = g["qty_by_direction"].get("arbitrage", 0)
            current_price = offer if trad_qty >= arb_qty else bid
            total_value = offer * trad_qty + bid * arb_qty
            # Tax on the exit leg each lot sells at.
            tax = (ge_tax(offer) * trad_qty + ge_tax(bid) * arb_qty)
            unrealized = total_value - g["cost_basis"] - tax
            unrealized_pct = (round(
                (total_value - g["cost_basis"] - tax) / g["cost_basis"] * 100, 2)
                if g["cost_basis"] > 0 else 0.0)
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
    items.sort(key=lambda i: (i["total_value"] is not None,i["total_value"] or 0), reverse=True)
    marked=[item for item in items if item['total_value'] is not None]
    missing=[item for item in items if item['total_value'] is None]
    from rshelper.market_data import provenance
    return {"market_data":{"latest":provenance(latest)},
        "items": items,
        "total_value": None if missing else sum(i["total_value"] for i in marked),
        "unrealized_pnl": None if missing else sum(i["unrealized_pnl"] for i in marked),
        "marked_value":sum(i['total_value'] for i in marked),
        "marked_unrealized_pnl":sum(i['unrealized_pnl'] for i in marked),
        "mark_coverage":{'marked_cost_basis':sum(i['cost_basis'] for i in marked),
                         'missing_cost_basis':sum(i['cost_basis'] for i in missing),
                         'missing_item_ids':sorted(i['item_id'] for i in missing)},
        "cost_basis": sum(i["cost_basis"] for i in items),
        "slot_count": len(items),
    }
