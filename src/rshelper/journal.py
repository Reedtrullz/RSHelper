"""Trade journal: log trades, compute P&L."""
import threading
import base64
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from rshelper.market import ge_tax
from rshelper import state_identity, state_transaction
from rshelper.persistence import read_state, locked_writable_state, StateCorruptionError, validate_state
from rshelper.profile import atomic_write_json, filter_fields, resolve_config_path

TRADES_PATH = Path.home() / ".config" / "rshelper" / "trades.json"
_TRADE_LOCK = threading.Lock()


def _trades_path(profile: str | None = None) -> Path:
    if profile is None or profile == "default":
        return TRADES_PATH
    return resolve_config_path("trades.json", profile)


def _trade_lock(profile: str | None = None):
    return locked_writable_state(_trades_path(profile), "trades")


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
    strategy: str = ""          # "auto" (trader) | "manual" (hand paper trade)
    exit_reason: str = ""       # "take_profit" | "stop_loss" | "max_hold" | ""
    hold_minutes: float | None = None
    quote_sell: int | None = None  # raw low quote before stop-loss slippage
    entry_spread_pct: float | None = None  # (offer - bid) / bid at entry
    fill_guard: bool = False  # exit filled at the 5m avg, not a thin print
    record_uuid: str | None = None
    origin_uuid: str | None = None
    revision: int | None = None
    entry_config: dict | None = None
    exit_config: dict | None = None


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
    gross_profit: int = 0      # sum of winning trades
    gross_loss: int = 0        # absolute sum of losing trades
    profit_factor: float = 0.0 # gross_profit / gross_loss (inf when no losses)
    max_drawdown: int = 0      # worst peak-to-trough of cumulative P&L


def _load(profile: str | None = None):
    path = _trades_path(profile)
    return state_identity.validate_activated_store(read_state(path, 'trades'), 'trades', path)['trades']


def _save(trades: list[dict], profile: str | None = None) -> None:
    store = read_state(_trades_path(profile), "trades")
    store["trades"] = trades
    validate_state(store, "trades", _trades_path(profile))
    atomic_write_json(_trades_path(profile), store)


def _next_id(trades: list[dict]) -> int:
    if not trades:
        return 1
    return max(t["id"] for t in trades) + 1


def log_trade(item_id: int, name: str, qty: int, buy_price: int,
              sell_price: int, note: str = "", profile: str | None = None,
              strategy: str = "", exit_reason: str = "",
              hold_minutes: float | None = None,
              quote_sell: int | None = None,
              entry_spread_pct: float | None = None,
              fill_guard: bool = False,
              operation_id: str | None = None) -> Trade:
    """Log a completed trade. Returns the Trade object.

    Tax is per-item (OSRS GE tax is per item, capped at 5M per item).
    """
    if qty <= 0:
        raise ValueError(f"qty must be positive, got {qty}")
    if buy_price <= 0:
        raise ValueError(f"buy_price must be positive, got {buy_price}")
    if sell_price <= 0:
        raise ValueError(f"sell_price must be positive, got {sell_price}")
    per_item_tax = ge_tax(sell_price)
    tax_paid = per_item_tax * qty
    profit = (sell_price - buy_price) * qty - tax_paid
    path = _trades_path(profile)
    manifest = state_identity.activation_manifest(
        path.with_name('identity-activation.json'))
    if manifest is not None:
        state_identity.require_financial_authority(manifest)
        from uuid import uuid4
        operation_id = operation_id or str(uuid4())
        request = dict(item_id=item_id, name=name, qty=qty, buy_price=buy_price,
                       sell_price=sell_price, note=note, strategy=strategy,
                       exit_reason=exit_reason, hold_minutes=hold_minutes,
                       quote_sell=quote_sell, entry_spread_pct=entry_spread_pct,
                       fill_guard=fill_guard)
        identity = state_identity.new_record_identity(
            manifest['origin_uuid'], 'trades', operation_id)
        with state_transaction.profile_transaction(profile or 'default',
                                                   path.parent) as txn:
            store = read_state(path, 'trades')
            state_identity.validate_activated_store(store, 'trades', path)
            trades = store['trades']
            for row in trades:
                if row.get('record_uuid') == identity['record_uuid']:
                    state_identity.validate_native_retry(path.parent, 'trades', row, request)
                    return Trade(**filter_fields(Trade, row))
            trade = {
                "id": _next_id(trades), "item_id": item_id, "name": name,
                "qty": qty, "buy_price": buy_price, "sell_price": sell_price,
                "tax_paid": tax_paid, "profit": profit,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "note": note, "strategy": strategy, "exit_reason": exit_reason,
                "hold_minutes": hold_minutes, "quote_sell": quote_sell,
                "entry_spread_pct": entry_spread_pct, "fill_guard": fill_guard,
                **identity,
            }
            from rshelper.tuning import config_evidence
            trade['exit_config']=config_evidence(profile)
            trades.append(trade)
            state_identity.attest_native(txn, path.parent, 'trades', trade, operation_id, request)
            txn.stage('trades.json', store)
            txn.commit(operation_id=operation_id)
        return Trade(**filter_fields(Trade, trade))
    with _trade_lock(profile):
        trades = _load(profile)
        trade = {
            "id": _next_id(trades), "item_id": item_id, "name": name, "qty": qty,
            "buy_price": buy_price, "sell_price": sell_price,
            "tax_paid": tax_paid, "profit": profit,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "note": note,
            "strategy": strategy,
            "exit_reason": exit_reason,
            "hold_minutes": hold_minutes,
            "quote_sell": quote_sell,
            "entry_spread_pct": entry_spread_pct,
            "fill_guard": fill_guard,
        }
        from rshelper.tuning import config_evidence
        trade['exit_config']=config_evidence(profile)
        trades.append(trade)
        _save(trades, profile)
    return Trade(**trade)


def delete_trade(trade_id: int, profile: str | None = None) -> bool:
    """Delete a trade by ID. Returns True if it existed.

    Identified profiles retain a tombstone (revision +1) so deletions
    survive replication; legacy profiles drop the row entirely.
    """
    path = _trades_path(profile)
    if state_identity.activation_manifest(
            path.with_name('identity-activation.json')) is not None:
        with state_transaction.profile_transaction(profile or 'default',
                                                   path.parent) as txn:
            state_identity.require_financial_authority(state_identity.activation_manifest(
                path.with_name('identity-activation.json')))
            store = read_state(path, 'trades')
            trades = store['trades']
            for i, t in enumerate(trades):
                if t["id"] == trade_id:
                    if t.get('tombstone'):
                        return False
                    trades[i] = {**t, 'tombstone': True,
                                 'revision': t.get('revision', 0) + 1}
                    txn.stage('trades.json', store)
                    txn.commit(operation_id=t['record_uuid'])
                    return True
            return False
    with _trade_lock(profile):
        trades = _load(profile)
        for i, t in enumerate(trades):
            if t["id"] == trade_id:
                trades.pop(i)
                _save(trades, profile)
                return True
        return False


def list_trades(item_name: str = "", since: str = "", top: int = 0,
                profile: str | None = None, note: str = "",
                strategy: str = "") -> list[Trade]:
    """List trades, optionally filtered by item name, date, note, or strategy.

    strategy="auto" matches only trader closes; strategy="manual" also
    matches legacy trades that predate strategy tagging.
    """
    with _TRADE_LOCK:
        trades = _load(profile)
    result = [Trade(**filter_fields(Trade, t)) for t in trades if not t.get('tombstone', False)]
    if item_name:
        q = item_name.lower()
        result = [t for t in result if q in t.name.lower()]
    if since:
        result = [t for t in result if t.timestamp >= since]
    if note:
        result = [t for t in result if t.note == note]
    if strategy == "auto":
        result = [t for t in result if t.strategy == "auto"]
    elif strategy == "manual":
        result = [t for t in result if t.strategy != "auto"]
    result.sort(key=lambda t: t.timestamp, reverse=True)
    if top > 0:
        result = result[:top]
    return result


def compute_pnl(since: str = "", profile: str | None = None, note: str = "",
                strategy: str = "", *, trades=None) -> PnLSummary:
    """Compute profit and loss summary, optionally since a date."""
    if trades is None:
        trades = list_trades(since=since, profile=profile, note=note, strategy=strategy)
        return summarize_trades(trades, {})
    return summarize_trades(trades, {'since': since, 'note': note, 'strategy': strategy})


def summarize_trades(trades, filters=None) -> PnLSummary:
    """Compute the existing economics from one caller-owned snapshot."""
    trades_list = sorted(_filtered_trades(trades, filters),
                         key=lambda trade: _utc(trade.timestamp), reverse=True)
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
    gross_profit = sum(t.profit for t in winners)
    gross_loss = abs(sum(t.profit for t in losers))

    # Max drawdown: worst peak-to-trough of cumulative P&L over time.
    # list_trades returns newest-first, so walk reversed for chronological order.
    max_drawdown = 0
    peak = 0
    cumulative = 0
    for t in reversed(trades_list):
        cumulative += t.profit
        peak = max(peak, cumulative)
        max_drawdown = max(max_drawdown, peak - cumulative)

    timestamps = sorted(_utc(t.timestamp) for t in trades_list)
    active_gp_per_hour = 0.0
    if len(timestamps) >= 2:
        try:
            first = timestamps[0]
            last = timestamps[-1]
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
        gross_profit=gross_profit, gross_loss=gross_loss,
        profit_factor=(gross_profit / gross_loss if gross_loss > 0
                       else float("inf") if gross_profit > 0 else 0.0),
        max_drawdown=max_drawdown,
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
                        profile: str | None = None, note: str = "",
                        strategy: str = "", *, trades=None) -> list[ItemPnL]:
    """Per-item P&L breakdown, sorted by profit descending."""
    trades_list = (_filtered_trades(trades, {'since': since, 'note': note, 'strategy': strategy})
                   if trades is not None else list_trades(
                       since=since, profile=profile, note=note, strategy=strategy))
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


def read_trade_snapshot(profile=None):
    """One validated load; tombstones and all fields contribute to the revision."""
    with _TRADE_LOCK:
        raw = _load(profile)
    revision = hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(',', ':'),
                                         allow_nan=False).encode()).hexdigest()
    rows = tuple(Trade(**filter_fields(Trade, row)) for row in raw if not row.get('tombstone', False))
    return revision, rows


def _utc(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _trade_key(trade):
    return (_utc(trade.timestamp).isoformat(), trade.record_uuid or 'legacy:' + str(trade.id))


def _activity_filters(filters):
    filters = dict(filters or {})
    if set(filters) - {'since', 'until', 'strategy', 'note'}:
        raise ValueError('unknown Activity filter')
    if any(not isinstance(value, str) or len(value) > 256 for value in filters.values()):
        raise ValueError('invalid Activity filter value')
    if filters.get('strategy', '') not in ('', 'auto', 'manual'):
        raise ValueError('invalid strategy')
    for field in ('since', 'until'):
        if filters.get(field):
            _utc(filters[field])
    if filters.get('since') and filters.get('until'):
        start, end = _utc(filters['since']), _utc(filters['until'])
        if (start.date() > end.date() if len(filters['until']) == 10 else start > end):
            raise ValueError('since must not exceed until')
    return {key: value for key, value in filters.items() if value}


def _filtered_trades(trades, filters=None):
    filters = _activity_filters(filters)
    since = _utc(filters['since']) if filters.get('since') else None
    until = _utc(filters['until']) if filters.get('until') else None
    whole_day = bool(until and len(filters['until']) == 10)
    rows = []
    for trade in trades:
        timestamp = _utc(trade.timestamp)
        if since and timestamp < since or until and (
                timestamp.date() > until.date() if whole_day else timestamp >= until):
            continue
        if filters.get('note') and trade.note != filters['note']:
            continue
        strategy = filters.get('strategy')
        if strategy == 'auto' and trade.strategy != 'auto' or strategy == 'manual' and trade.strategy == 'auto':
            continue
        rows.append(trade)
    return rows


def page_trades(trades, *, revision, cursor=None, limit=50, filters=None):
    """Bound rows and bind continuation to journal content and filter identity."""
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('Activity limit must be 1..100')
    if not isinstance(revision, str) or not revision or len(revision) > 128:
        raise ValueError('invalid journal revision')
    filters = _activity_filters(filters)
    fingerprint = hashlib.sha256(json.dumps(filters, sort_keys=True).encode()).hexdigest()
    result = {'revision': revision, 'total_count': len(trades), 'filtered_count': 0,
              'trades': [], 'next_cursor': None, 'restart': False, 'timezone': 'UTC'}
    after, offset = None, 0
    if cursor:
        if not isinstance(cursor, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,2048}', cursor):
            raise ValueError('invalid Activity cursor')
        try:
            decoded = json.loads(base64.urlsafe_b64decode(cursor + '=' * (-len(cursor) % 4)))
        except (ValueError, UnicodeError) as error:
            raise ValueError('invalid Activity cursor') from error
        if (not isinstance(decoded, dict) or set(decoded) != {'v', 'revision', 'filters', 'after', 'offset'}
                or type(decoded['v']) is not int or decoded['v'] != 1
                or not isinstance(decoded['revision'], str) or not isinstance(decoded['filters'], str)
                or not isinstance(decoded['after'], list) or len(decoded['after']) != 2
                or any(not isinstance(value, str) for value in decoded['after'])
                or type(decoded['offset']) is not int or decoded['offset'] < 1):
            raise ValueError('invalid Activity cursor')
        if decoded['revision'] != revision or decoded['filters'] != fingerprint:
            return dict(result, restart=True, reason='journal-or-filters-changed')
        after = tuple(decoded['after'])
        offset = decoded['offset']
    rows = sorted(_filtered_trades(trades, filters), key=_trade_key, reverse=True)
    result['filtered_count'] = len(rows)
    if after is not None:
        if offset > len(rows) or _trade_key(rows[offset - 1]) != after:
            raise ValueError('cursor record is absent from this revision')
    page = rows[offset:offset + limit]
    result['trades'] = [dict(asdict(trade), timestamp=_utc(trade.timestamp).isoformat())
                        for trade in page]
    if offset + limit < len(rows):
        continuation = {'v': 1, 'revision': revision, 'filters': fingerprint,
                        'after': _trade_key(page[-1]), 'offset': offset + len(page)}
        result['next_cursor'] = base64.urlsafe_b64encode(
            json.dumps(continuation, separators=(',', ':')).encode()).decode().rstrip('=')
    return result
