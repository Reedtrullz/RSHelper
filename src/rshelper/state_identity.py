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
from pathlib import Path
from uuid import UUID, uuid5

from rshelper.persistence import (validate_state, canonical_uuid, read_state,
                                 validate_record_identity as record_identity)

IMMUTABLE_FIELDS = {
    'positions': ('id', 'item_id', 'buy_price', 'direction', 'opened_at'),
    'trades': ('id', 'item_id', 'qty', 'buy_price', 'sell_price', 'tax_paid', 'profit', 'timestamp'),
    'alerts': ('id', 'ts', 'type', 'item_id'),
    'watchlist': ('item_id', 'added'),
}
MAX_MAPPINGS = 100_000

REPLICATION_OWNERSHIP = {
    # financial: Mac authority only; replicated as owned financial data.
    'positions.json': 'financial', 'trades.json': 'financial', 'paper-offers.json':'financial',
    'alerts.json': 'shared',
    'watchlist.json': 'shared',
    # informational: replicated for operator visibility only.
    'tuning_log.json': 'informational', 'snapshots/*.json': 'informational',
    # local-only: never leaves the owning host.
    'signal_cooldowns.json': 'local-only', 'volume_baseline.json': 'local-only',
    'active_profile': 'local-only',
    'trader_state.json': 'local-only', 'monitor_state.json': 'local-only',
    'config.toml': 'local-only', 'recent_exits.json': 'local-only',
}

_LOCAL_ONLY_SUFFIXES = ('.pid', '.lock', '.sock', '.socket')


def new_record_identity(origin_uuid: str, kind: str, operation_id: str) -> dict:
    """Deterministic identity for a natively created record (replay-safe)."""
    canonical_uuid(origin_uuid)
    canonical_uuid(operation_id)
    if kind not in ('positions', 'trades', 'alerts', 'watchlist'):
        raise ValueError('unsupported identity row kind')
    record = str(uuid5(UUID(origin_uuid), kind + ':native:' + operation_id))
    row = {'record_uuid': record, 'origin_uuid': origin_uuid,
           'revision': 0, 'tombstone': False}
    if kind == 'positions':
        row['lot_uid'] = record
    return row


def require_financial_authority(manifest) -> None:
    """Refuse financial writes unless the manifest grants authority."""
    if (not isinstance(manifest, dict) or manifest.get('mode') != 'identified'
            or manifest.get('financial_authority') is not True
            or 'origin_uuid' not in manifest):
        raise ValueError('financial writes require the profile financial authority; make this change on the source trader host')
    canonical_uuid(manifest['origin_uuid'])


def activation_manifest(path):
    """Read the activation manifest at path; None when legacy/unactivated."""
    path = Path(path)
    if not path.exists() and not path.is_symlink():
        return None
    try:
        data = read_state(path, 'generic')
    except (OSError, ValueError) as exc:
        raise ValueError(f'activation manifest is corrupt: {exc}') from None
    if (not isinstance(data, dict) or data.get('mode') != 'identified'
            or 'origin_uuid' not in data):
        raise ValueError('activation manifest is not an identified profile')
    canonical_uuid(data['origin_uuid'])
    return data


def validate_activated_store(store, kind, path):
    if activation_manifest(Path(path).with_name('identity-activation.json')) is not None:
        validate_state({**store, 'schema_version': 2}, kind, path)
    return store


def new_manifest(origin_uuid):
    return {'schema_version': 1, 'origin_uuid': canonical_uuid(origin_uuid), 'mappings': {}}


def validate_manifest(manifest):
    if (not isinstance(manifest, dict)
            or set(manifest) not in ({'schema_version', 'origin_uuid', 'mappings'},
                                    {'schema_version', 'origin_uuid', 'mappings', 'native'})
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
    native = manifest.get('native', {})
    if not isinstance(native, dict) or len(native) + len(mappings) > MAX_MAPPINGS:
        raise ValueError('identity manifest exceeds creation limit')
    for record, proof in native.items():
        if (not isinstance(proof, dict)
                or set(proof) != ({'kind', 'operation_id', 'request_hash', 'immutable_hash'} |
                                  ({'creation_qty'} if proof.get('kind') == 'positions' else set()))
                or proof['kind'] not in IMMUTABLE_FIELDS):
            raise ValueError('invalid native creation proof')
        if proof['kind'] == 'positions' and (type(proof['creation_qty']) is not int or proof['creation_qty'] <= 0):
            raise ValueError('invalid native lot creation quantity')
        expected = new_record_identity(origin, proof['kind'], proof['operation_id'])
        if record != expected['record_uuid']:
            raise ValueError('native creation UUID conflict')
        for field in ('request_hash', 'immutable_hash'):
            if not isinstance(proof[field], str) or not re.fullmatch('[0-9a-f]{64}', proof[field]):
                raise ValueError('invalid native creation hash')
    return manifest


def request_hash(request):
    return hashlib.sha256(json.dumps(request, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def attest_native(txn, root, kind, row, operation_id, request):
    manifest = read_state(Path(root) / 'identity-manifest.json', 'generic')
    if not manifest:
        manifest = new_manifest(row['origin_uuid'])
    validate_manifest(manifest)
    proof = {'kind': kind, 'operation_id': operation_id,
             'request_hash': request_hash(request), 'immutable_hash': _native_hash(row, kind)}
    if kind == 'positions':
        proof['creation_qty'] = row['qty']
    native = manifest.setdefault('native', {})
    existing = native.get(row['record_uuid'])
    if existing is not None and existing != proof:
        raise ValueError('native creation operation conflict')
    native[row['record_uuid']] = proof
    validate_manifest(manifest)
    txn.stage('identity-manifest.json', manifest)


def validate_native_retry(root, kind, row, request):
    manifest = validate_manifest(read_state(Path(root) / 'identity-manifest.json', 'generic'))
    proof = manifest.get('native', {}).get(row['record_uuid'])
    if (proof is None or proof['kind'] != kind
            or proof['request_hash'] != request_hash(request)
            or proof['immutable_hash'] != _native_hash(row, kind)):
        raise ValueError('native creation retry conflict')


def _native_hash(row, kind):
    normalized = _migration_key({**row, 'id': 0, 'legacy_id': 0}, kind)
    return request_hash({'lineage': normalized,
                         **({field: row.get(field) for field in ('entry_sell', 'entry_offer')}
                            if kind == 'positions' else {})})


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
            native = result.get('native', {}).get(identity)
            if native is not None:
                if native['kind'] != kind or native['immutable_hash'] != _native_hash(row, kind):
                    raise ValueError('native creation immutable conflict')
                if kind == 'positions' and row['qty'] > native['creation_qty']:
                    raise ValueError('native lot exceeds its attested creation quantity')
            elif 'legacy_id' not in row or result['mappings'].get(key) != identity:
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
        elif row['origin_uuid'] == origin:
            native = result.get('native', {}).get(identity)
            if native is not None:
                if native['kind'] != 'watchlist' or native['immutable_hash'] != _native_hash(row, 'watchlist'):
                    raise ValueError('native watch creation conflict')
            elif result['mappings'].get(key) != identity:
                raise ValueError('identity manifest conflict: original watch lineage does not match')
    validate_manifest(result)
    validate_state(upgraded, 'watchlist', 'watchlist.json')
    return upgraded, result
