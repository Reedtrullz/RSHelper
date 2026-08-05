"""Open paper-trading positions: buy-and-hold until closed.

Positions are the hold side of paper trading: `trade open` records a buy
at the live price, `trade close` sells matching units at the live price and
logs the realized trades into the journal. State lives in positions.json
(atomic writes, profile-aware) and syncs to the deployed site like the
journal.
"""

import contextlib
import fcntl
import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from rshelper.market import ge_tax
from rshelper.profile import atomic_write_json, filter_fields, resolve_config_path

POSITIONS_PATH = Path.home() / ".config" / "rshelper" / "positions.json"
_LOCK = threading.Lock()


def _positions_lock(profile: str | None = None):
    """Cross-process advisory lock for positions.json (flock sidecar).

    The trader daemon, dashboard, and CLI are separate processes that all
    open/close positions; a process-local lock cannot serialize them.
    """
    path = _positions_path(profile).with_suffix(".json.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        return _LOCK

    @contextlib.contextmanager
    def _locked():
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
        except OSError:
            pass
        try:
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(fd)
    return _locked()


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
    entry_offer: int | None = None  # offer quote (high) when the position opened


def _positions_path(profile: str | None = None) -> Path:
    if profile is None or profile == "default":
        return POSITIONS_PATH
    return resolve_config_path("positions.json", profile)


def _load(profile: str | None = None) -> list[dict]:
    path = _positions_path(profile)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if path.exists():
            rows = json.loads(path.read_text()).get("positions", [])
            return [filter_fields(Position, r) for r in rows
                    if isinstance(r, dict)]
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
                  entry_offer: int | None = None,
                  profile: str | None = None) -> Position:
    """Open a hold position at buy_price. Returns the Position."""
    if qty <= 0:
        raise ValueError(f"qty must be positive, got {qty}")
    if buy_price <= 0:
        raise ValueError(f"buy_price must be positive, got {buy_price}")
    if direction not in ("arbitrage", "traditional"):
        raise ValueError(f"direction must be 'arbitrage' or 'traditional', got '{direction}'")
    with _positions_lock(profile):
        positions = _load(profile)
        position = {
            "id": _next_id(positions), "item_id": item_id, "name": name,
            "qty": qty, "buy_price": buy_price, "direction": direction,
            "opened_at": datetime.now(timezone.utc).isoformat(), "note": note,
            "entry_sell": entry_sell, "entry_offer": entry_offer,
        }
        positions.append(position)
        _save(positions, profile)
    return Position(**position)


def list_positions(profile: str | None = None) -> list[Position]:
    """Return open positions, oldest first."""
    with _LOCK:
        positions = [Position(**p) for p in _load(profile)]
    positions.sort(key=lambda p: p.opened_at)
    return positions


def open_qty(item_id: int, profile: str | None = None) -> int:
    """Total units currently open for an item."""
    # list_positions acquires _LOCK itself; nesting the lock here would
    # deadlock (threading.Lock is not reentrant).
    return sum(p.qty for p in list_positions(profile) if p.item_id == item_id)


def close_positions(item_id: int, qty: int, sell_price: int,
                    profile: str | None = None,
                    position_id: int | None = None) -> list[dict]:
    """Close qty units of an item FIFO at sell_price.

    When position_id is given, only that specific lot is closed (partial
    closes reduce it). Otherwise FIFO across lots of the item (oldest first).
    Returns realized lots: [{"position_id", "name", "qty", "buy_price",
    "sell_price", "tax_paid", "profit"}]. Raises ValueError when the item
    has fewer open units or inputs are invalid.
    """
    if qty <= 0:
        raise ValueError(f"qty must be positive, got {qty}")
    if sell_price <= 0:
        raise ValueError(f"sell_price must be positive, got {sell_price}")
    with _positions_lock(profile):
        positions = _load(profile)
        lots = []
        remaining = qty
        kept = []
        for p in sorted(positions, key=lambda x: x["id"]):
            if p["item_id"] != item_id or remaining <= 0:
                kept.append(p)
                continue
            if position_id is not None and p["id"] != position_id:
                kept.append(p)
                continue
            take = min(remaining, p["qty"])
            tax = ge_tax(sell_price)
            lots.append({
                "position_id": p["id"], "name": p["name"], "qty": take,
                "buy_price": p["buy_price"], "sell_price": sell_price,
                "tax_paid": tax * take,
                "profit": (sell_price - p["buy_price"]) * take - tax * take,
            })
            remaining -= take
            if p["qty"] - take > 0:
                # Copy, never mutate the loaded dict: if _save raises, the
                # caller's in-memory state must stay untouched.
                kept.append({**p, "qty": p["qty"] - take})
        if remaining > 0:
            raise ValueError(
                f"only {qty - remaining} of {qty} units open for item {item_id}")
        _save(kept, profile)
    return lots
