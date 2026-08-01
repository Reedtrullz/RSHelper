"""Open paper-trading positions: buy-and-hold until closed.

Positions are the hold side of paper trading: `trade open` records a buy
at the live price, `trade close` sells matching units at the live price and
logs the realized trades into the journal. State lives in positions.json
(atomic writes, profile-aware) and syncs to the deployed site like the
journal.
"""

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from rshelper.market import ge_tax
from rshelper.profile import atomic_write_json, resolve_config_path

POSITIONS_PATH = Path.home() / ".config" / "rshelper" / "positions.json"
_LOCK = threading.Lock()


@dataclass
class Position:
    id: int
    item_id: int
    name: str
    qty: int
    buy_price: int
    direction: str  # "arbitrage" | "traditional"
    opened_at: str
    note: str = ""
    entry_sell: int | None = None  # sell quote (low) when the position opened


def _positions_path(profile: str | None = None) -> Path:
    if profile is None or profile == "default":
        return POSITIONS_PATH
    return resolve_config_path("positions.json", profile)


def _load(profile: str | None = None) -> list[dict]:
    path = _positions_path(profile)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if path.exists():
            return json.loads(path.read_text()).get("positions", [])
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _save(positions: list[dict], profile: str | None = None) -> None:
    atomic_write_json(_positions_path(profile), {"positions": positions}, indent=2)


def _next_id(positions: list[dict]) -> int:
    if not positions:
        return 1
    return max(p["id"] for p in positions) + 1


def open_position(item_id: int, name: str, qty: int, buy_price: int,
                  direction: str = "arbitrage", note: str = "",
                  entry_sell: int | None = None,
                  profile: str | None = None) -> Position:
    """Open a hold position at buy_price. Returns the Position."""
    if qty <= 0:
        raise ValueError(f"qty must be positive, got {qty}")
    if buy_price <= 0:
        raise ValueError(f"buy_price must be positive, got {buy_price}")
    if direction not in ("arbitrage", "traditional"):
        raise ValueError(f"direction must be 'arbitrage' or 'traditional', got '{direction}'")
    with _LOCK:
        positions = _load(profile)
        position = {
            "id": _next_id(positions), "item_id": item_id, "name": name,
            "qty": qty, "buy_price": buy_price, "direction": direction,
            "opened_at": datetime.now(timezone.utc).isoformat(), "note": note,
            "entry_sell": entry_sell,
        }
        positions.append(position)
        _save(positions, profile)
    return Position(**position)


def list_positions(profile: str | None = None) -> list[Position]:
    """Return open positions, oldest first."""
    positions = [Position(**p) for p in _load(profile)]
    positions.sort(key=lambda p: p.opened_at)
    return positions


def open_qty(item_id: int, profile: str | None = None) -> int:
    """Total units currently open for an item."""
    return sum(p.qty for p in list_positions(profile) if p.item_id == item_id)


def close_positions(item_id: int, qty: int, sell_price: int,
                    profile: str | None = None) -> list[dict]:
    """Close qty units of an item FIFO at sell_price.

    Returns realized lots: [{"position_id", "name", "qty", "buy_price",
    "sell_price", "tax_paid", "profit"}]. Raises ValueError when the item
    has fewer open units or inputs are invalid.
    """
    if qty <= 0:
        raise ValueError(f"qty must be positive, got {qty}")
    if sell_price <= 0:
        raise ValueError(f"sell_price must be positive, got {sell_price}")
    with _LOCK:
        positions = _load(profile)
        lots = []
        remaining = qty
        for p in sorted(positions, key=lambda x: x["id"]):
            if p["item_id"] != item_id or remaining <= 0:
                continue
            take = min(remaining, p["qty"])
            tax = ge_tax(sell_price)
            lots.append({
                "position_id": p["id"], "name": p["name"], "qty": take,
                "buy_price": p["buy_price"], "sell_price": sell_price,
                "tax_paid": tax * take,
                "profit": (sell_price - p["buy_price"]) * take - tax * take,
            })
            p["qty"] -= take
            remaining -= take
        if remaining > 0:
            raise ValueError(
                f"only {qty - remaining} of {qty} units open for item {item_id}")
        kept = [p for p in positions if p["qty"] > 0]
        _save(kept, profile)
    return lots
