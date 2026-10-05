"""Pure identity/revision reconciliation, inactive until writer/merge cutover.

Both inputs require explicit migration lineage. Equal-revision disagreement,
financial edits and attempted resurrection refuse instead of choosing a host.
Tombstones remain in the result; caller owns durable quarantine and publication.
"""
import copy
from datetime import datetime, timezone
import json
from uuid import UUID, uuid5

from rshelper.persistence import canonical_uuid, validate_state, validate_record_identity, MAX_STATE_BYTES

MAX_ROWS = 100_000
IMMUTABLE = {
    'positions': ('record_uuid','origin_uuid','legacy_id','lot_uid','item_id','buy_price','direction','opened_at'),
    'trades': ('record_uuid','origin_uuid','legacy_id','item_id','qty','buy_price','sell_price',
               'tax_paid','profit','timestamp','operation_id','closed_lot_uid'),
    'alerts': ('record_uuid','origin_uuid','legacy_id','ts','type','item_id'),
    'watchlist': ('record_uuid','origin_uuid','item_id','added'),
}


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def canonical_record(row, kind):
    """Copy a schema-validated row using the shared UTC/time representation."""
    values = copy.deepcopy(row)
    for timestamp in {'positions':('opened_at',),'trades':('timestamp',),'alerts':(),
                      'watchlist':('added',)}[kind]:
        if timestamp in values:
            parsed=datetime.fromisoformat(values[timestamp].replace('Z','+00:00'))
            if parsed.tzinfo is None:parsed=parsed.replace(tzinfo=timezone.utc)
            try:values[timestamp]=parsed.astimezone(timezone.utc).isoformat(timespec='microseconds')
            except (ValueError,OverflowError) as exc:raise ValueError('merge timestamp outside supported UTC range') from exc
    if kind=='alerts':
        if values['ts']>=253402300800:raise ValueError('alert timestamp outside supported UTC range')
        numerator,denominator=values['ts'].as_integer_ratio()
        if denominator==1:values['ts']=numerator
    return values


def _immutable(row, kind):
    values = {field:row.get(field) for field in IMMUTABLE[kind]}
    if kind=='alerts':values['ts']=list(values['ts'].as_integer_ratio())
    return _json(values)


def _indexed(rows,kind):
    if not isinstance(rows,list) or len(rows)>MAX_ROWS:
        raise ValueError('identity merge row budget exceeded or invalid rows')
    validate_state({kind:rows},kind,'identity-merge.json')
    indexed={}
    for row in rows:
        identity=validate_record_identity(row,kind)
        if identity is None:raise ValueError('identity merge requires explicit legacy migration')
        if identity in indexed:raise ValueError('duplicate identity in peer state')
        if kind=='trades':
            fields=('operation_id','closed_lot_uid')
            present=[field in row for field in fields]
            if any(present) and not all(present):raise ValueError('partial realization linkage')
            for field in fields:
                if field in row:canonical_uuid(row[field])
            if all(present) and identity != str(uuid5(UUID(row['origin_uuid']), row['operation_id'])):
                raise ValueError('realization trade identity does not match operation')
        indexed[identity]=canonical_record(row,kind)
    return indexed


def _pick(left,right,kind):
    if _immutable(left,kind)!=_immutable(right,kind):
        raise ValueError('immutable identity or financial conflict')
    # Display aliases are neither identity nor revision evidence.
    left_payload={key:value for key,value in left.items() if key!='id'}
    right_payload={key:value for key,value in right.items() if key!='id'}
    if left['revision']==right['revision']:
        if _json(left_payload)!=_json(right_payload):raise ValueError('equal revision conflict')
        return left
    older,newer=(left,right) if left['revision']<right['revision'] else (right,left)
    if older['tombstone'] and not newer['tombstone']:
        raise ValueError('tombstoned identity cannot resurrect')
    if kind=='positions' and newer['qty']>older['qty']:
        raise ValueError('closed lot quantity cannot increase')
    if kind=='positions' and older['tombstone'] and newer['qty']!=older['qty']:
        raise ValueError('closed tombstone quantity is immutable')
    return newer


def merge_rows(left,right,kind):
    """Return deterministic deep copies, retaining deletes and every identity.

    Original legacy_id stays fixed; numeric id is a display alias regenerated
    in UUID order. No filesystem, host precedence, mtime or inferred origin.
    """
    if type(kind) is not str or kind not in ('positions','trades','alerts'):raise ValueError('unsupported identity merge kind')
    peers=[_indexed(rows,kind) for rows in (left,right)]
    identities=set(peers[0])|set(peers[1])
    if len(identities)>MAX_ROWS:raise ValueError('identity merge row budget exceeded')
    merged=[]
    operations={}
    for display_id,identity in enumerate(sorted(identities),1):
        a,b=(peer.get(identity) for peer in peers)
        selected=_pick(a,b,kind) if a is not None and b is not None else a if a is not None else b
        if kind=='trades' and 'operation_id' in selected:
            operation=selected['operation_id']
            if operation in operations and operations[operation]!=identity:
                raise ValueError('ambiguous duplicate realization operation')
            operations[operation]=identity
        # Canonical key order also makes a caller's ordinary JSON serialization
        # independent of which equal-revision peer supplied the winning copy.
        merged.append({**json.loads(_json(selected)),'id':display_id})
    validate_state({kind:merged},kind,'identity-merge-result.json')
    if len(_json({kind:merged}).encode('utf-8'))>MAX_STATE_BYTES:
        raise ValueError('identity merge exceeds byte budget')
    return merged


def merge_watchlists(left, right):
    """Retain deleted generations while reconciling the one active item slot.

    Different live generations for one item are an explicit conflict. A stale
    generation with a retained tombstone cannot replace a later re-add.
    Unknown root metadata must agree; this boundary never silently drops it.
    """
    peers, metadata = [], []
    for store in (left, right):
        validate_state(store, 'watchlist', 'watchlist.json')
        metadata.append({key: value for key, value in store.items()
                         if key not in ('items', 'tombstones', 'schema_version')})
        rows = list(store['items'].values()) + list(store.get('tombstones', {}).values())
        if len(rows) > MAX_ROWS:
            raise ValueError('watch identity merge row budget exceeded')
        indexed = {}
        for row in rows:
            identity = validate_record_identity(row, 'watchlist')
            if identity is None:
                raise ValueError('watch merge requires explicit legacy migration')
            indexed[identity] = canonical_record(row, 'watchlist')
        peers.append(indexed)
    if _json(metadata[0]) != _json(metadata[1]):
        raise ValueError('watch root metadata conflict')
    identities = set(peers[0]) | set(peers[1])
    if len(identities) > MAX_ROWS:
        raise ValueError('watch identity merge row budget exceeded')
    result = {**copy.deepcopy(metadata[0]), 'items': {}, 'tombstones': {}}
    for identity in sorted(identities):
        a, b = (peer.get(identity) for peer in peers)
        row = _pick(a, b, 'watchlist') if a is not None and b is not None else a if a is not None else b
        if row['tombstone']:
            result['tombstones'][identity] = row
        else:
            item = str(row['item_id'])
            if item in result['items']:
                raise ValueError('conflicting active watch generations for one item')
            result['items'][item] = row
    result = json.loads(_json(result))
    validate_state(result, 'watchlist', 'watchlist.json')
    if len(_json(result).encode('utf-8')) > MAX_STATE_BYTES:
        raise ValueError('watch identity merge exceeds byte budget')
    return result
