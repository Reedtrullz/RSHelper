"""Pure, explicit identity migration boundary shared by close and merge work.

This module never creates host origins or reads/writes state. An operator's
persisted source manifest must be supplied; writer activation is a later step.
Identical unlabelled records from different sources cannot be disambiguated
without that source lineage, so origins must not be inferred from paths.
"""
import copy
from datetime import datetime, timezone
import hashlib
import json
import re
from uuid import UUID, uuid5

from rshelper.persistence import (validate_state, canonical_uuid,
                                 validate_record_identity as record_identity)

IMMUTABLE_FIELDS = {
    'positions': ('id', 'item_id', 'buy_price', 'direction', 'opened_at'),
    'trades': ('id', 'item_id', 'qty', 'buy_price', 'sell_price', 'tax_paid', 'profit', 'timestamp'),
    'alerts': ('id', 'ts', 'type', 'item_id'),
    'watchlist': ('item_id', 'added'),
}
MAX_MAPPINGS = 100_000


def new_manifest(origin_uuid):
    return {'schema_version': 1, 'origin_uuid': canonical_uuid(origin_uuid), 'mappings': {}}


def validate_manifest(manifest):
    if (not isinstance(manifest, dict)
            or set(manifest) != {'schema_version', 'origin_uuid', 'mappings'}
            or type(manifest['schema_version']) is not int or manifest['schema_version'] != 1):
        raise ValueError('unsupported identity manifest')
    origin = canonical_uuid(manifest['origin_uuid'])
    mappings = manifest['mappings']
    if not isinstance(mappings, dict) or len(mappings) > MAX_MAPPINGS:
        raise ValueError('identity manifest exceeds mapping limit')
    for key, value in mappings.items():
        if (type(key) is not str
                or not re.fullmatch(r'(positions|trades|alerts|watchlist):[0-9a-f]{64}', key)):
            raise ValueError('invalid identity mapping key')
        canonical_uuid(value)
        if value != str(uuid5(UUID(origin), key)):
            raise ValueError('identity manifest conflict')
    return manifest


def _migration_key(row, kind):
    body = {field: row.get(field) for field in IMMUTABLE_FIELDS[kind]}
    if kind != 'watchlist':
        body['id'] = row.get('legacy_id', row['id'])
    for field in ('opened_at', 'timestamp', 'added'):
        if field in body:
            instant = datetime.fromisoformat(body[field].replace('Z', '+00:00'))
            if instant.tzinfo is None:
                instant = instant.replace(tzinfo=timezone.utc)
            try:
                body[field] = instant.astimezone(timezone.utc).isoformat(timespec='microseconds')
            except (ValueError, OverflowError) as exc:
                raise ValueError('identity timestamp outside supported UTC range') from exc
    if 'ts' in body:
        body['ts'] = float(body['ts'])
    payload = json.dumps(body, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return kind + ':' + hashlib.sha256(payload).hexdigest()


def migrate_rows(rows, kind, manifest):
    """Return upgraded copies and a reusable manifest, preserving display IDs.

    Mutable quantity/read/note changes reuse identity. Different origins with
    colliding legacy IDs stay distinct. Ambiguous duplicates fail without
    changing either input; supplied stable UUIDs survive display renumbering.
    Caller owns backup, durable manifest publication and writer activation.
    """
    if kind not in ('positions', 'trades', 'alerts') or not isinstance(rows, list):
        raise ValueError('unsupported identity row kind')
    validate_manifest(manifest)
    validate_state({kind: rows}, kind, kind + '.json')
    upgraded = copy.deepcopy(rows)
    result = copy.deepcopy(manifest)
    origin = result['origin_uuid']
    seen_keys, seen_records = set(), set()
    for row in upgraded:
        identity = record_identity(row, kind)
        key = _migration_key(row, kind)
        lineage = (row.get('origin_uuid', origin), key)
        if identity is None:
            if lineage in seen_keys:
                raise ValueError('ambiguous legacy record identity')
            identity = str(uuid5(UUID(origin), key))
            result['mappings'][key] = identity
            row.update(record_uuid=identity, origin_uuid=origin, revision=0, tombstone=False,
                       legacy_id=row["id"])
            if kind == 'positions':
                row['lot_uid'] = identity
        elif row['origin_uuid'] == origin:
            if 'legacy_id' not in row or result['mappings'].get(key) != identity:
                raise ValueError('identity manifest conflict: original lineage does not match')
        if identity in seen_records:
            raise ValueError('ambiguous duplicate record identity')
        seen_keys.add(lineage)
        seen_records.add(identity)
    validate_manifest(result)
    return upgraded, result


def migrate_watchlist(store, manifest):
    """Explicitly bind each item/creation generation, retaining deleted watches.

    Never infer a host origin or reactivate a deletion. A re-add must carry a
    new creation instant before migration. Caller owns durable publication.
    """
    validate_manifest(manifest)
    validate_state(store, 'watchlist', 'watchlist.json')
    upgraded, result = copy.deepcopy(store), copy.deepcopy(manifest)
    origin = result['origin_uuid']
    for item_id, row in upgraded['items'].items():
        if record_identity(row, 'watchlist') is None:
            if 'item_id' in row and row['item_id'] != int(item_id):
                raise ValueError('watch item lineage conflicts with dictionary key')
            row['item_id'] = int(item_id)
    rows = list(upgraded['items'].values()) + list(upgraded.get('tombstones', {}).values())
    for row in rows:
        identity = record_identity(row, 'watchlist')
        key = _migration_key(row, 'watchlist')
        if identity is None:
            identity = str(uuid5(UUID(origin), key))
            result['mappings'][key] = identity
            row.update(record_uuid=identity, origin_uuid=origin, revision=0, tombstone=False)
        elif row['origin_uuid'] == origin and result['mappings'].get(key) != identity:
            raise ValueError('identity manifest conflict: original watch lineage does not match')
    validate_manifest(result)
    validate_state(upgraded, 'watchlist', 'watchlist.json')
    return upgraded, result
