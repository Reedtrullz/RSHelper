"""Durable paper-close intents; inactive until coordinated writer cutover.

Every operation pins one identified lot and one journal row before either
financial file changes. Replay applies the same economics under ordered locks.
No CLI, dashboard or trader caller is activated by this module alone.
"""
from contextlib import ExitStack
import copy
from datetime import datetime, timezone
import os
import json
import secrets
import math
from pathlib import Path
from uuid import UUID, uuid5

from rshelper import journal, positions
from rshelper.market import ge_tax
from rshelper.persistence import read_state, locked_state, validate_state, canonical_uuid, MAX_STATE_BYTES
from rshelper.profile import resolve_config_path
from rshelper.state_identity import validate_manifest

MAX_OPERATIONS = 10_000
MAX_METADATA_BYTES = 16 * 1024


def _same_json(left, right):
    """Python equality aliases bool/int and int/float; persisted requests do not."""
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(right, sort_keys=True, allow_nan=False)


def _metadata(supplied):
    defaults = {'note': 'paper', 'strategy': 'manual', 'hold_minutes': None,
                'quote_sell': None, 'entry_spread_pct': None, 'fill_guard': False,
                'market_data': {}}
    if supplied is None:
        supplied = {}
    if not isinstance(supplied, dict) or set(supplied) - set(defaults):
        raise ValueError('invalid realization metadata fields')
    result = {**defaults, **copy.deepcopy(supplied)}
    for field, limit in (('note', 512), ('strategy', 64)):
        if type(result[field]) is not str or len(result[field]) > limit:
            raise ValueError('invalid realization metadata text')
    for field in ('hold_minutes', 'entry_spread_pct'):
        value = result[field]
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
            raise ValueError('invalid realization metadata number')
    if result['hold_minutes'] is not None and result['hold_minutes'] < 0:
        raise ValueError('invalid realization hold time')
    quote = result['quote_sell']
    if quote is not None and (type(quote) is not int or quote <= 0):
        raise ValueError('invalid realization quote')
    if type(result['fill_guard']) is not bool or not isinstance(result['market_data'], dict):
        raise ValueError('invalid realization fill/provenance metadata')
    validate_state(result, 'generic', 'realization-metadata.json')
    if len(json.dumps(result, allow_nan=False).encode('utf-8')) > MAX_METADATA_BYTES:
        raise ValueError('realization metadata exceeds byte budget')
    return result


def _intent_path(profile):
    return resolve_config_path('realizations.json', profile)


def _manifest_path(profile):
    return resolve_config_path('identity-manifest.json', profile)


def _checkpoint(step):
    """Fault-injection boundary immediately after a durable persistence step."""


def _payload(data):
    validate_state(data, 'generic', 'realization-state.json')
    payload = json.dumps(data, allow_nan=False).encode('utf-8')
    if len(payload) > MAX_STATE_BYTES:
        raise ValueError('realization state exceeds byte budget')
    return payload


def _persist(path, data):
    payload = _payload(data)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    directory = os.open(path.parent, flags)
    temporary = '.realization-' + secrets.token_hex(12)
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0),
                     0o600, dir_fd=directory)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path.name, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    finally:
        try:
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass
        finally:
            os.close(directory)


def _paths(profile):
    return (positions._positions_path(profile), journal._trades_path(profile),
            _intent_path(profile), _manifest_path(profile))


def _load_intents(path):
    store = read_state(path, 'generic')
    if not store:
        try:
            Path(path).lstat()
        except FileNotFoundError:
            store = {'schema_version': 1, 'operations': {}}
    if set(store) != {'schema_version', 'operations'} or not isinstance(store['operations'], dict):
        raise ValueError('invalid realization intent store')
    if len(store['operations']) > MAX_OPERATIONS:
        raise ValueError('realization operation budget exceeded')
    for operation, intent in store['operations'].items():
        canonical_uuid(operation)
        if not isinstance(intent, dict) or set(intent) != {'request', 'before', 'trade', 'receipt', 'done'}:
            raise ValueError('invalid realization intent')
        if any(not isinstance(intent[field], dict) for field in ('request', 'before', 'trade', 'receipt')):
            raise ValueError('invalid realization intent payload shape')
        request, before, trade, receipt = (intent[field] for field in ('request', 'before', 'trade', 'receipt'))
        if (type(intent['done']) is not bool
                or set(request) != {'lot_uid', 'qty', 'sell_price', 'operation_id', 'reason', 'metadata'}
                or request.get('operation_id') != operation):
            raise ValueError('invalid realization operation identity')
        canonical_uuid(request['lot_uid'])
        if (type(request['qty']) is not int or request['qty'] <= 0
                or type(request['sell_price']) is not int or request['sell_price'] <= 0
                or type(request['reason']) is not str or not request['reason'] or len(request['reason']) > 64):
            raise ValueError('invalid realization request')
        metadata = _metadata(request['metadata'])
        if metadata != request['metadata']:
            raise ValueError('realization metadata must be normalized')
        validate_state({'positions': [before]}, 'positions', path)
        validate_state({'trades': [trade]}, 'trades', path)
        canonical_uuid(trade.get('origin_uuid'))
        if (type(receipt.get('remaining_qty')) is not int
                or not isinstance(receipt.get('trade_ids'), list)
                or any(type(value) is not int for value in receipt['trade_ids'])):
            raise ValueError('invalid realization receipt types')
        quantity, sell = request['qty'], request['sell_price']
        tax = ge_tax(sell) * quantity
        if (before.get('record_uuid') != request['lot_uid'] or before['qty'] < quantity
                or before.get('tombstone') is not False
                or trade.get('revision') != 0 or trade.get('tombstone') is not False
                or trade['qty'] != quantity or trade['buy_price'] != before['buy_price']
                or trade['sell_price'] != sell or trade['tax_paid'] != tax
                or trade['profit'] != (sell - before['buy_price']) * quantity - tax
                or trade['item_id'] != before['item_id'] or trade['name'] != before['name']
                or trade.get('closed_lot_uid') != request['lot_uid']
                or trade.get('operation_id') != operation or trade.get('exit_reason') != request['reason']
                or not _same_json({field: trade.get(field) for field in metadata}, metadata)
                or trade.get('record_uuid') != str(uuid5(UUID(trade['origin_uuid']), operation))):
            raise ValueError('realization intent economics conflict')
        expected = {'operation_id': operation, 'trade_ids': [trade['id']], 'remaining_qty': before['qty'] - quantity}
        if receipt != expected:
            raise ValueError('realization intent receipt conflict')
    return store


def _validate_origin(paths, store):
    if store['operations']:
        manifest = validate_manifest(read_state(paths[3], 'generic'))
        if any(intent['trade']['origin_uuid'] != manifest['origin_uuid']
               for intent in store['operations'].values()):
            raise ValueError('realization origin manifest conflict')


def _marker(intent):
    request = intent['request']
    return {'lot_uid': request['lot_uid'], 'qty': request['qty'],
            'sell_price': request['sell_price'], 'remaining_qty': intent['receipt']['remaining_qty']}


def _remaining_lot(intent):
    if not intent['receipt']['remaining_qty']:
        return None
    return {**intent['before'], 'qty': intent['receipt']['remaining_qty'],
            'revision': intent['before']['revision'] + 1}


def _verify_applied_lot(position_store, store, lot_uid, chain=None):
    """The retained marker alone cannot prove that consumed units stayed closed."""
    applied = position_store['realizations']
    if chain is None:
        chain = [intent for operation, intent in store['operations'].items()
                 if operation in applied and intent['request']['lot_uid'] == lot_uid]
    chain.sort(key=lambda intent: intent['before']['revision'])
    expected = chain[0]['before']
    for intent in chain:
        marker = applied[intent['request']['operation_id']]
        target = _marker(intent)
        if (not _same_json(intent['before'], expected) or not isinstance(marker, dict)
                or set(marker) != set(target) or marker != target
                or any(type(marker[key]) is not type(value) for key, value in target.items())):
            raise ValueError('realization lot revision chain conflict')
        expected = _remaining_lot(intent)
    rows = [row for row in position_store['positions'] if row.get('record_uuid') == lot_uid]
    if not _same_json(rows, [] if expected is None else [expected]):
        raise ValueError('realization applied lot changed or resurrected')


def _apply(paths, store, operation, replayed):
    position_path, trade_path, intent_path, _ = paths
    intent = store['operations'][operation]
    request, before, trade = intent['request'], intent['before'], intent['trade']
    position_store = read_state(position_path, 'positions')
    applied = position_store.setdefault('realizations', {})
    if not isinstance(applied, dict):
        raise ValueError('invalid position realization ledger')
    marker = _marker(intent)
    if operation in applied:
        stored = applied[operation]
        if (not isinstance(stored, dict) or set(stored) != set(marker)
                or any(type(stored[field]) is not type(marker[field]) for field in marker)
                or stored != marker):
            raise ValueError('realization position receipt conflict')
        _verify_applied_lot(position_store, store, request['lot_uid'])
    else:
        if intent['done']:
            raise ValueError('completed realization position proof missing')
        matching = [row for row in position_store['positions'] if row.get('record_uuid') == request['lot_uid']]
        if len(matching) != 1 or not _same_json(matching[0], before):
            raise ValueError('realization position changed; recovery requires review')
    trade_store = read_state(trade_path, 'trades')
    matches = [row for row in trade_store['trades'] if row.get('record_uuid') == trade['record_uuid']]
    if matches:
        if len(matches) != 1 or not _same_json(matches[0], trade):
            raise ValueError('realization journal conflict')
    else:
        if intent['done']:
            raise ValueError('completed realization journal proof missing')
        if any(row['id'] == trade['id'] for row in trade_store['trades']):
            raise ValueError('realization journal display ID conflict')
        trade_store['trades'].append(copy.deepcopy(trade))
        validate_state(trade_store, 'trades', trade_path)
        _checkpoint('before_journal')
        _persist(trade_path, trade_store)
    if intent['done']:
        return {**intent['receipt'], 'replayed': True}
    _checkpoint('journal')
    if operation not in applied:
        replacement = []
        for row in position_store['positions']:
            if row.get('record_uuid') != request['lot_uid']:
                replacement.append(row)
            elif marker['remaining_qty']:
                replacement.append({**row, 'qty': marker['remaining_qty'], 'revision': row['revision'] + 1})
        position_store['positions'] = replacement
        applied[operation] = marker
        validate_state(position_store, 'positions', position_path)
        _checkpoint('before_positions')
        _persist(position_path, position_store)
    _checkpoint('positions')
    intent['done'] = True
    _checkpoint('before_receipt')
    _persist(intent_path, store)
    _checkpoint('receipt')
    return {**intent['receipt'], 'replayed': replayed}


def _recover(paths, store):
    # Audit completed evidence once before a restart or a new operation can
    # consume restored units. Reads are bounded; no per-operation file rewrite.
    positions_state = read_state(paths[0], 'positions')
    applied = positions_state.get('realizations', {})
    if not isinstance(applied, dict) or set(applied) - set(store['operations']):
        raise ValueError('invalid or unowned position realization ledger')
    trades = read_state(paths[1], 'trades')['trades']
    by_uuid = {}
    for row in trades:
        by_uuid.setdefault(row.get('record_uuid'), []).append(row)
    chains = {}
    for operation, intent in store['operations'].items():
        if intent['done'] and (operation not in applied
                or not _same_json(by_uuid.get(intent['trade']['record_uuid']), [intent['trade']])):
            raise ValueError('completed realization proof missing or conflicting')
        if operation in applied:
            chains.setdefault(intent['request']['lot_uid'], []).append(intent)
    for lot_uid, chain in chains.items():
        _verify_applied_lot(positions_state, store, lot_uid, chain)
    receipts = []
    for operation, intent in store['operations'].items():
        if not intent['done']:
            receipts.append(_apply(paths, store, operation, True))
    return receipts


def recover_pending(profile):
    paths = _paths(profile)
    with ExitStack() as locks:
        for path in sorted(paths, key=lambda value: str(Path(value).resolve())):
            locks.enter_context(locked_state(path))
        store = _load_intents(paths[2])
        _validate_origin(paths, store)
        return _recover(paths, store)


def close_and_realize(profile, lot_uid, qty, sell_price, operation_id, reason, *, metadata=None):
    """Close an exact identified lot once; reuse requires identical economics."""
    canonical_uuid(lot_uid)
    canonical_uuid(operation_id)
    if type(qty) is not int or qty <= 0 or type(sell_price) is not int or sell_price <= 0:
        raise ValueError('quantity and sell price must be positive integers')
    if type(reason) is not str or not reason or len(reason) > 64:
        raise ValueError('invalid realization reason')
    request = {'lot_uid': lot_uid, 'qty': qty, 'sell_price': sell_price,
               'operation_id': operation_id, 'reason': reason, 'metadata': _metadata(metadata)}
    paths = _paths(profile)
    with ExitStack() as locks:
        for path in sorted(paths, key=lambda value: str(Path(value).resolve())):
            locks.enter_context(locked_state(path))
        store = _load_intents(paths[2])
        _validate_origin(paths, store)
        if operation_id in store['operations']:
            if not _same_json(store['operations'][operation_id]['request'], request):
                raise ValueError('operation ID reused with different economics')
            return _apply(paths, store, operation_id, True)
        _recover(paths, store)
        if len(store['operations']) >= MAX_OPERATIONS:
            raise ValueError('realization operation budget exceeded; receipts retained')
        manifest = validate_manifest(read_state(paths[3], 'generic'))
        state = read_state(paths[0], 'positions')
        lots = [row for row in state['positions'] if row.get('record_uuid') == lot_uid]
        if len(lots) != 1 or lots[0].get('tombstone') is not False:
            raise ValueError('exact identified lot not open; migration or ownership review required')
        lot = lots[0]
        if qty > lot['qty'] or lot['revision'] >= 2**63 - 1:
            raise ValueError('insufficient open quantity or exhausted lot revision')
        trade_state = read_state(paths[1], 'trades')
        trades = trade_state['trades']
        tax = ge_tax(sell_price) * qty
        trade_id = max((row['id'] for row in trades), default=0) + 1
        trade = {'id': trade_id, 'item_id': lot['item_id'], 'name': lot['name'],
                 'qty': qty, 'buy_price': lot['buy_price'], 'sell_price': sell_price,
                 'tax_paid': tax, 'profit': (sell_price - lot['buy_price']) * qty - tax,
                 'timestamp': datetime.now(timezone.utc).isoformat(), **request['metadata'],
                 'exit_reason': reason,
                 'record_uuid': str(uuid5(UUID(manifest['origin_uuid']), operation_id)),
                 'origin_uuid': manifest['origin_uuid'], 'revision': 0, 'tombstone': False,
                 'operation_id': operation_id, 'closed_lot_uid': lot_uid}
        receipt = {'operation_id': operation_id, 'trade_ids': [trade_id],
                   'remaining_qty': lot['qty'] - qty}
        if any(row.get('record_uuid') == trade['record_uuid'] for row in trades):
            raise ValueError('unowned realization journal identity already exists')
        store['operations'][operation_id] = {'request': request, 'before': copy.deepcopy(lot),
                                            'trade': trade, 'receipt': receipt, 'done': False}
        # Do not publish an intent that predictable schema/size conflicts can
        # never apply. I/O failures after publication remain restart-recoverable.
        projected = store['operations'][operation_id]
        trade_state['trades'].append(trade)
        validate_state(trade_state, 'trades', paths[1])
        _payload(trade_state)
        state['positions'] = [row for row in state['positions'] if row.get('record_uuid') != lot_uid]
        remaining = _remaining_lot(projected)
        if remaining is not None:
            state['positions'].append(remaining)
        state.setdefault('realizations', {})[operation_id] = _marker(projected)
        validate_state(state, 'positions', paths[0])
        _payload(state)
        _checkpoint('before_intent')
        _persist(paths[2], store)
        _checkpoint('intent')
        return _apply(paths, store, operation_id, False)
