"""Open paper-trading positions: buy-and-hold until closed.

Positions are the hold side of paper trading: `trade open` records a buy
at the live price, `trade close` sells matching units at the live price and
logs the realized trades into the journal. State lives in positions.json
(atomic writes, profile-aware) and syncs to the deployed site like the
journal.
"""

import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from rshelper.market import ge_tax
from rshelper import state_identity, state_transaction
from rshelper.persistence import read_state, locked_writable_state, StateCorruptionError, validate_state
from rshelper.profile import atomic_write_json, filter_fields, resolve_config_path

POSITIONS_PATH = Path.home() / ".config" / "rshelper" / "positions.json"
_LOCK = threading.Lock()


def _positions_lock(profile: str | None = None):
    return locked_writable_state(_positions_path(profile), "positions")


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
    lot_uid: str | None = None  # identified lot UUID on migrated profiles
    record_uuid: str | None = None
    origin_uuid: str | None = None
    revision: int | None = None
    entry_config: dict | None = None


def _positions_path(profile: str | None = None) -> Path:
    if profile is None or profile == "default":
        return POSITIONS_PATH
    return resolve_config_path("positions.json", profile)


def _load(profile: str | None = None):
    path = _positions_path(profile)
    return state_identity.validate_activated_store(read_state(path, 'positions'), 'positions', path)['positions']


def _save(positions: list[dict], profile: str | None = None) -> None:
    path = _positions_path(profile)
    store = read_state(path, "positions")
    store["positions"] = positions
    validate_state(store, "positions", path)
    atomic_write_json(path, store, indent=2)


def _next_id(positions: list[dict]) -> int:
    if not positions:
        return 1
    return max(p["id"] for p in positions) + 1


def _stage_open_position(txn, profile, request, operation_id, *, opened_at=None,entry_config=...):
    path = _positions_path(profile)
    if path.parent != txn.root:
        raise ValueError('position and transaction profiles differ')
    manifest = state_identity.activation_manifest(path.with_name('identity-activation.json'))
    state_identity.require_financial_authority(manifest)
    identity = state_identity.new_record_identity(manifest['origin_uuid'],'positions',operation_id)
    store = read_state(path,'positions')
    state_identity.validate_activated_store(store,'positions',path)
    rows = store['positions']
    for row in rows:
        if row.get('record_uuid')==identity['record_uuid']:
            state_identity.validate_native_retry(path.parent,'positions',row,request)
            return Position(**filter_fields(Position,row)),False
    from rshelper.tuning import config_evidence,validate_config_evidence
    if entry_config is ...:entry_config=config_evidence(profile)
    validate_config_evidence(entry_config)
    row = {'id':_next_id(rows),**request,'entry_config':entry_config,
           'opened_at':opened_at or datetime.now(timezone.utc).isoformat(),**identity}
    rows.append(row)
    state_identity.attest_native(txn,path.parent,'positions',row,operation_id,request)
    txn.stage('positions.json',store)
    return Position(**filter_fields(Position,row)),True


def open_position(item_id: int, name: str, qty: int, buy_price: int,
                  direction: str = "arbitrage", note: str = "",
                  entry_sell: int | None = None,
                  entry_offer: int | None = None,
                  profile: str | None = None,
                  operation_id: str | None = None) -> Position:
    """Open a hold position at buy_price. Returns the Position."""
    from rshelper.trading_mode import require_entries_running
    if qty <= 0:
        raise ValueError(f"qty must be positive, got {qty}")
    if buy_price <= 0:
        raise ValueError(f"buy_price must be positive, got {buy_price}")
    if direction not in ("arbitrage", "traditional"):
        raise ValueError(f"direction must be 'arbitrage' or 'traditional', got '{direction}'")
    path = _positions_path(profile)
    manifest = state_identity.activation_manifest(
        path.with_name('identity-activation.json'))
    if manifest is not None:
        state_identity.require_financial_authority(manifest)
        operation_id = operation_id or str(uuid4())
        request = dict(item_id=item_id, name=name, qty=qty, buy_price=buy_price,
                       direction=direction, note=note, entry_sell=entry_sell,
                       entry_offer=entry_offer)
        with state_transaction.profile_transaction(profile or 'default',
                                                   path.parent) as txn:
            position,created = _stage_open_position(txn,profile,request,operation_id)
            if created:
                require_entries_running(path.parent)
                txn.commit(operation_id=operation_id)
        return position
    with _positions_lock(profile):
        from rshelper.tuning import config_evidence
        require_entries_running(path.parent)
        positions = _load(profile)
        position = {
            "id": _next_id(positions), "item_id": item_id, "name": name,
            "qty": qty, "buy_price": buy_price, "direction": direction,
            "opened_at": datetime.now(timezone.utc).isoformat(), "note": note,
            "entry_sell": entry_sell, "entry_offer": entry_offer,
            "entry_config":config_evidence(profile),
        }
        positions.append(position)
        _save(positions, profile)
    return Position(**position)


def list_positions(profile: str | None = None) -> list[Position]:
    """Return open positions, oldest first."""
    with _LOCK:
        positions = [Position(**filter_fields(Position, p)) for p in _load(profile)
                     if not p.get('tombstone', False)]
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
