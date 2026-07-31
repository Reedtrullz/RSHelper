"""Trade journal: log trades, compute P&L."""
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from rshelper.profile import resolve_config_path

TRADES_PATH = Path.home() / ".config" / "rshelper" / "trades.json"


def _trades_path(profile: str | None = None) -> Path:
    if profile is None or profile == "default":
        return TRADES_PATH
    return resolve_config_path("trades.json", profile)


@dataclass
class Trade:
    id: int
    item_id: int
    name: str
    qty: int
    buy_price: int
    sell_price: int
    tax_paid: int
    profit: int
    timestamp: str
    note: str = ""


@dataclass
class PnLSummary:
    total_profit: int = 0
    total_tax_paid: int = 0
    total_cost_basis: int = 0
    roi_pct: float = 0.0
    trade_count: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    best_trade: Trade | None = None
    worst_trade: Trade | None = None
    active_gp_per_hour: float = 0.0
    items_traded: int = 0


def _load(profile: str | None = None) -> list[dict]:
    path = _trades_path(profile)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if path.exists():
            return json.loads(path.read_text()).get("trades", [])
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _save(trades: list[dict], profile: str | None = None) -> None:
    path = _trades_path(profile)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"trades": trades}))
    os.replace(tmp, path)


def _next_id(trades: list[dict]) -> int:
    if not trades:
        return 1
    return max(t["id"] for t in trades) + 1


def log_trade(item_id: int, name: str, qty: int, buy_price: int,
              sell_price: int, note: str = "", profile: str | None = None) -> Trade:
    """Log a completed trade. Returns the Trade object.

    Tax is per-item (OSRS GE tax is per item, capped at 5M per item).
    """
    if qty <= 0:
        raise ValueError(f"qty must be positive, got {qty}")
    if buy_price <= 0:
        raise ValueError(f"buy_price must be positive, got {buy_price}")
    if sell_price <= 0:
        raise ValueError(f"sell_price must be positive, got {sell_price}")
    trades = _load(profile)
    per_item_tax = min(5_000_000, max(1, int(sell_price * 0.02)))
    tax_paid = per_item_tax * qty
    profit = (sell_price - buy_price) * qty - tax_paid
    trade = {
        "id": _next_id(trades), "item_id": item_id, "name": name, "qty": qty,
        "buy_price": buy_price, "sell_price": sell_price,
        "tax_paid": tax_paid, "profit": profit,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "note": note,
    }
    trades.append(trade)
    _save(trades, profile)
    return Trade(**trade)


def delete_trade(trade_id: int, profile: str | None = None) -> bool:
    """Delete a trade by ID. Returns True if it existed."""
    trades = _load(profile)
    for i, t in enumerate(trades):
        if t["id"] == trade_id:
            trades.pop(i)
            _save(trades, profile)
            return True
    return False


def list_trades(item_name: str = "", since: str = "", top: int = 0,
                profile: str | None = None) -> list[Trade]:
    """List trades, optionally filtered by item name substring or date."""
    trades = _load(profile)
    result = [Trade(**t) for t in trades]
    if item_name:
        q = item_name.lower()
        result = [t for t in result if q in t.name.lower()]
    if since:
        result = [t for t in result if t.timestamp >= since]
    result.sort(key=lambda t: t.timestamp, reverse=True)
    if top > 0:
        result = result[:top]
    return result


def compute_pnl(since: str = "", profile: str | None = None) -> PnLSummary:
    """Compute profit and loss summary, optionally since a date."""
    trades_list = list_trades(since=since, profile=profile) if since else list_trades(profile=profile)
    if not trades_list:
        return PnLSummary()

    total_profit = sum(t.profit for t in trades_list)
    total_tax = sum(t.tax_paid for t in trades_list)
    total_cost = sum(t.buy_price * t.qty for t in trades_list)
    winners = [t for t in trades_list if t.profit > 0]
    losers = [t for t in trades_list if t.profit < 0]
    best = max(trades_list, key=lambda t: t.profit)
    worst = min(trades_list, key=lambda t: t.profit)
    unique_items = len(set(t.item_id for t in trades_list))

    timestamps = sorted(t.timestamp for t in trades_list)
    active_gp_per_hour = 0.0
    if len(timestamps) >= 2:
        try:
            first = datetime.fromisoformat(timestamps[0])
            last = datetime.fromisoformat(timestamps[-1])
            hours = (last - first).total_seconds() / 3600
            if hours > 0:
                active_gp_per_hour = total_profit / hours
        except (ValueError, TypeError):
            pass

    return PnLSummary(
        total_profit=total_profit, total_tax_paid=total_tax,
        total_cost_basis=total_cost,
        roi_pct=(total_profit / total_cost * 100) if total_cost > 0 else 0.0,
        trade_count=len(trades_list),
        winning_trades=len(winners), losing_trades=len(losers),
        win_rate=len(winners) / len(trades_list) * 100 if trades_list else 0,
        best_trade=best, worst_trade=worst,
        active_gp_per_hour=round(active_gp_per_hour),
        items_traded=unique_items,
    )


@dataclass
class ItemPnL:
    item_id: int
    name: str
    trade_count: int = 0
    qty: int = 0
    cost_basis: int = 0
    profit: int = 0
    roi_pct: float = 0.0
    win_rate: float = 0.0


def compute_pnl_by_item(since: str = "",
                        profile: str | None = None) -> list[ItemPnL]:
    """Per-item P&L breakdown, sorted by profit descending."""
    trades_list = list_trades(since=since, profile=profile) if since else list_trades(profile=profile)
    rows: dict[int, ItemPnL] = {}
    wins: dict[int, int] = {}
    for t in trades_list:
        row = rows.setdefault(t.item_id, ItemPnL(item_id=t.item_id, name=t.name))
        row.trade_count += 1
        row.qty += t.qty
        row.cost_basis += t.buy_price * t.qty
        row.profit += t.profit
        if t.profit > 0:
            wins[t.item_id] = wins.get(t.item_id, 0) + 1
    for row in rows.values():
        row.roi_pct = (row.profit / row.cost_basis * 100) if row.cost_basis > 0 else 0.0
        row.win_rate = (wins.get(row.item_id, 0) / row.trade_count * 100) if row.trade_count else 0.0
    return sorted(rows.values(), key=lambda r: r.profit, reverse=True)
