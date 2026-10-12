import copy
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from uuid import UUID, uuid5
import zipfile

from rshelper import identity_merge, persistence, state_identity, state_transaction
from rshelper.backup import _read_file, _files as _backup_files
from rshelper.profile import resolve_config_path
from rshelper.persistence import decode_json as _decode

MAX_FILES = 512
MAX_BYTES = 64 * 1024 * 1024
MAX_ROWS = 100_000
CORE = {'positions.json': 'positions', 'trades.json': 'trades',
        'alerts.json': 'alerts', 'watchlist.json': 'watchlist'}
FILES = {**CORE, 'identity-manifest.json': 'identity',
         'trading_mode.json':'trading_mode',
         'identity-lineage.json': 'lineage', 'realizations.json': 'realizations',
         'realization-batches.json': 'batches', 'replication-receipts.json': 'receipts',
         'information.json': 'information'}


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _hash(value):
    if type(value) is not str or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('invalid SHA256')
    return value


def _revision(value):
    if type(value) is not int or not 0 <= value < 2**63:
        raise ValueError('invalid source revision')
    return value


def packet_hash(manifest, files):
    digest = hashlib.sha256(_json({key: value for key, value in manifest.items()
                                  if key != 'packet_hash'}))
    for name in sorted(files):
        digest.update(files[name])
    return digest.hexdigest()


def _activation(root):
    data = state_identity.activation_manifest(root / 'identity-activation.json')
    if data is None:
        raise ValueError('private replication requires explicit identity activation and lineage')
    persistence.canonical_uuid(data.get('profile_uuid'))
    origins = data.get('replication_origins')
    if (not isinstance(origins, list) or not origins or len(origins) > MAX_FILES
            or any(type(origin) is not str for origin in origins)
            or len(set(origins)) != len(origins)):
        raise ValueError('explicit replication origins required')
    for origin in origins:
        persistence.canonical_uuid(origin)
    if data['origin_uuid'] not in origins:
        raise ValueError('local origin is missing from replication lineage')
    return data


def _metadata(root):
    data = persistence.read_state(root / 'replication-state.json', 'generic')
    if not data:
        return {'schema_version': 1, 'outgoing': None, 'receipts': {}}
    if (set(data) != {'schema_version', 'outgoing', 'receipts'}
            or not isinstance(data['receipts'], dict)
            or len(data['receipts']) > MAX_FILES):
        raise ValueError('invalid replication metadata')
    for origin, receipt in data['receipts'].items():
        persistence.canonical_uuid(origin)
        _validate_receipt(receipt)
        if receipt['origin_uuid'] != origin:
            raise ValueError('receipt origin mismatch')
    outgoing = data['outgoing']
    if outgoing is not None:
        if (not isinstance(outgoing, dict) or set(outgoing) != {
                'schema_version', 'profile_uuid', 'origin_uuid', 'source_revision',
                'parent_revision', 'parent_hash', 'packet_hash', 'files'}
                or type(outgoing['schema_version']) is not int or outgoing['schema_version'] != 2
                or not isinstance(outgoing['files'], list) or len(outgoing['files']) > MAX_FILES):
            raise ValueError('invalid outgoing cursor')
        persistence.canonical_uuid(outgoing['profile_uuid'])
        persistence.canonical_uuid(outgoing['origin_uuid'])
        if _revision(outgoing['source_revision']) != _revision(outgoing['parent_revision']) + 1:
            raise ValueError('invalid outgoing ancestry')
        _hash(outgoing['packet_hash'])
        if outgoing['parent_revision']:
            _hash(outgoing['parent_hash'])
        elif outgoing['parent_hash'] is not None:
            raise ValueError('invalid initial outgoing cursor')
    return data


def _validate_receipt(receipt):
    fields = {'schema_version', 'profile_uuid', 'origin_uuid', 'status',
              'requested_revision', 'requested_hash', 'applied_revision', 'applied_hash'}
    if (not isinstance(receipt, dict) or set(receipt) != fields
            or type(receipt['schema_version']) is not int or receipt['schema_version'] != 1
            or receipt['status'] not in ('applied', 'no_op', 'obsolete', 'conflict')):
        raise ValueError('invalid replication receipt')
    for field in ('profile_uuid', 'origin_uuid'):
        persistence.canonical_uuid(receipt[field])
    for field in ('requested_revision', 'applied_revision'):
        _revision(receipt[field])
    _hash(receipt['requested_hash'])
    if receipt['applied_revision']:
        _hash(receipt['applied_hash'])
    elif receipt['applied_hash'] is not None:
        raise ValueError('invalid initial receipt hash')
    return receipt


def _information(data):
    if (not isinstance(data, dict) or set(data) != {'schema_version', 'origin_uuid', 'files'}
            or type(data['schema_version']) is not int or data['schema_version'] != 1
            or not isinstance(data['files'], dict) or len(data['files']) > MAX_FILES):
        raise ValueError('invalid informational packet')
    persistence.canonical_uuid(data['origin_uuid'])
    count = 0
    for relative, value in data['files'].items():
        if relative != 'tuning_log.json' and not relative.startswith('snapshots/'):
            raise ValueError('unapproved informational source')
        state_transaction._kind(relative)
        persistence.validate_state(value, 'generic', relative)
        rows = value.get('entries' if relative == 'tuning_log.json' else 'items', [])
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError('invalid informational record collection')
        count += len(rows)
    if count > MAX_ROWS:
        raise ValueError('informational record budget exceeded')
    return count


def _validate_files(files):
    parsed = {}
    count = 0
    selected_files = len(files)
    if not set(CORE).issubset(files) or 'identity-manifest.json' not in files:
        raise ValueError('incomplete packet inventory')
    for name, raw in files.items():
        data = _decode(raw)
        if name in CORE:
            kind = CORE[name]
            persistence.validate_state(data, kind, name)
            if kind == 'watchlist':
                identity_merge.merge_watchlists(data, data)
                count += len(data['items']) + len(data.get('tombstones', {}))
            else:
                identity_merge.merge_rows(data[kind], [], kind)
                count += len(data[kind])
        elif name == 'trading_mode.json':
            persistence.validate_state(data,'trading_mode',name)
            count += 1
        elif name == 'identity-manifest.json':
            state_identity.validate_manifest(data)
            count += len(data['mappings']) + len(data.get('native', {}))
        elif name == 'identity-lineage.json':
            if set(data) != {'schema_version', 'origins'} or not isinstance(data['origins'], dict):
                raise ValueError('invalid foreign lineage')
            for origin, manifest in data['origins'].items():
                persistence.canonical_uuid(origin)
                state_identity.validate_manifest(manifest)
                if manifest['origin_uuid'] != origin:
                    raise ValueError('foreign lineage origin mismatch')
                count += len(manifest['mappings']) + len(manifest.get('native', {}))
        elif name == 'realizations.json':
            from rshelper.realization import validate_intents
            validate_intents(data, name)
            count += len(data['operations'])
            if any(not intent['done'] for intent in data['operations'].values()):
                raise ValueError('recover pending financial operations before replication')
        elif name == 'realization-batches.json':
            from rshelper.realization import validate_batches
            validate_batches(data)
            count += sum(len(batch['operations']) for batch in data['batches'].values())
        elif name == 'replication-receipts.json':
            if set(data) != {'schema_version', 'receipts'} or not isinstance(data['receipts'], dict):
                raise ValueError('invalid foreign receipts')
            if len(data['receipts']) > MAX_FILES:
                raise ValueError('foreign receipt budget exceeded')
            count += len(data['receipts'])
            for origin, receipt in data['receipts'].items():
                persistence.canonical_uuid(origin)
                _validate_receipt(receipt)
                if receipt['origin_uuid'] != origin:
                    raise ValueError('foreign receipt origin mismatch')
        elif name == 'information.json':
            count += _information(data)
            selected_files += len(data['files'])
        else:
            raise ValueError('unapproved packet file')
        parsed[name] = data
    if count > MAX_ROWS or selected_files > MAX_FILES:
        raise ValueError('packet exceeds record budget')
    from rshelper.realization import verify_realization_snapshot
    verify_realization_snapshot(parsed['positions.json'], parsed['trades.json']['trades'],
                                parsed.get('realizations.json', {'operations': {}}))
    manifests = dict(parsed.get('identity-lineage.json', {}).get('origins', {}))
    own = parsed['identity-manifest.json']
    if own['origin_uuid'] in manifests:
        own = _merge_manifest(manifests[own['origin_uuid']], own)
    manifests[own['origin_uuid']] = own
    operations = parsed.get('realizations.json', {}).get('operations', {})
    consumed_by_lot = {}
    for intent in operations.values():
        lot = intent['request']['lot_uid']
        consumed_by_lot[lot] = consumed_by_lot.get(lot, 0) + intent['request']['qty']
    for name, kind in CORE.items():
        store = parsed[name]
        rows = (list(store['items'].values()) + list(store.get('tombstones', {}).values())
                if kind == 'watchlist' else store[kind])
        groups = {}
        for row in rows:
            manifest = manifests.get(row['origin_uuid'])
            if manifest is None:
                raise ValueError('record origin lacks declared lineage')
            intent = operations.get(row.get('operation_id')) if kind == 'trades' else None
            if intent is not None and intent['trade']['record_uuid'] == row['record_uuid']:
                continue
            groups.setdefault(row['origin_uuid'], []).append(row)
            if kind == 'positions' and row['record_uuid'] in manifest.get('native', {}):
                created = manifest['native'][row['record_uuid']]['creation_qty']
                consumed = consumed_by_lot.get(row['record_uuid'], 0)
                if consumed + (0 if row['tombstone'] else row['qty']) != created:
                    raise ValueError('native lot creation and realized quantity conflict')
        for origin, source_rows in groups.items():
            manifest = manifests[origin]
            if kind == 'watchlist':
                state_identity.migrate_watchlist({
                    'items': {str(row['item_id']): row for row in source_rows if not row['tombstone']},
                    'tombstones': {row['record_uuid']: row for row in source_rows if row['tombstone']}}, manifest)
            else:
                state_identity.migrate_rows(source_rows, kind, manifest)
    return parsed


def capture_packet(profile, destination):
    root = resolve_config_path('', profile)
    destination = Path(destination).absolute()
    if destination.resolve().is_relative_to(root) or destination.exists() or destination.is_symlink():
        raise ValueError('packet output must be a new file outside the profile')
    with state_transaction.profile_transaction(profile, root) as txn:
        activation = _activation(root)
        state = _metadata(root)
        files = {}
        for name, kind in FILES.items():
            path = root / name
            if path.exists() or path.is_symlink():
                files[name] = _read_file(path)
            elif name in CORE:
                files[name] = _json(persistence.read_state(path, kind))
        files['replication-receipts.json'] = _json({'schema_version': 1, 'receipts': state['receipts']})
        selected, _ = _backup_files(root)
        information = {name: _decode(_read_file(path)) for name, path in selected.items()
                       if name == 'tuning_log.json' or name.startswith('snapshots/')}
        if information:
            files['information.json'] = _json({'schema_version': 1, 'origin_uuid': activation['origin_uuid'],
                                               'files': information})
        parsed = _validate_files(files)
        if 'trading_mode.json' in parsed:
            from rshelper.trading_mode import validate_authority
            validate_authority(parsed['trading_mode.json'],activation)
        if parsed['identity-manifest.json']['origin_uuid'] != activation['origin_uuid']:
            raise ValueError('source identity manifest mismatch')
        declared = {activation['origin_uuid'], *parsed.get('identity-lineage.json', {}).get('origins', {})}
        if not declared.issubset(activation['replication_origins']):
            raise ValueError('source contains undeclared foreign lineage')
        if len(files) > MAX_FILES or sum(map(len, files.values())) > MAX_BYTES:
            raise ValueError('packet exceeds transfer budget')
        entries = [{'path': name, 'kind': FILES[name],
                    'owner': 'informational' if name == 'information.json' else
                             'financial' if name in ('positions.json', 'trades.json', 'realizations.json', 'realization-batches.json', 'trading_mode.json') else 'shared',
                    'bytes': len(files[name]), 'sha256': hashlib.sha256(files[name]).hexdigest()}
                   for name in sorted(files)]
        previous = state['outgoing']
        if previous and (previous['profile_uuid'] != activation['profile_uuid']
                         or previous['origin_uuid'] != activation['origin_uuid']):
            raise ValueError('outgoing cursor identity mismatch')
        if previous and previous['files'] == entries:
            manifest = previous
        else:
            manifest = {'schema_version': 2, 'profile_uuid': activation['profile_uuid'],
                        'origin_uuid': activation['origin_uuid'],
                        'source_revision': previous['source_revision'] + 1 if previous else 1,
                        'parent_revision': previous['source_revision'] if previous else 0,
                        'parent_hash': previous['packet_hash'] if previous else None,
                        'files': entries}
            manifest['packet_hash'] = packet_hash(manifest, files)
        _revision(manifest['source_revision'])
        if manifest['packet_hash'] != packet_hash(manifest, files):
            raise ValueError('outgoing cursor does not match captured bytes')
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_STORED) as archive:
            archive.writestr('manifest.json', _json(manifest))
            for name, raw in files.items():
                archive.writestr(name, raw)
        if len(buffer.getvalue()) > MAX_BYTES:
            raise ValueError('encoded packet exceeds transfer budget')
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.state-packet-', dir=destination.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(buffer.getvalue())
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary, destination)
            directory = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            Path(temporary).unlink(missing_ok=True)
        state['outgoing'] = manifest
        txn.stage('replication-state.json', state)
        txn.commit(str(uuid5(UUID(activation['origin_uuid']), manifest['packet_hash'])))
        return manifest


def validate_profile(profile):
    root = resolve_config_path('', profile)
    with state_transaction.profile_transaction(profile, root):
        activation = _activation(root)
        files = {name: _read_file(root / name) for name in FILES
                 if name != 'information.json' and ((root / name).exists() or (root / name).is_symlink())}
        parsed = _validate_files(files)
        origin = parsed['identity-manifest.json']['origin_uuid']
        declared = {origin, *parsed.get('identity-lineage.json', {}).get('origins', {})}
        if origin != activation['origin_uuid'] or not declared.issubset(activation['replication_origins']):
            raise ValueError('initialized profile lineage mismatch')
        metadata = _metadata(root)
        if any(receipt['profile_uuid'] != activation['profile_uuid'] for receipt in metadata['receipts'].values()):
            raise ValueError('initialized profile receipt mismatch')
        return {'initialized': True, 'schema_version': 2,
                'profile_uuid': activation['profile_uuid'], 'origin_uuid': origin,
                'receipts': metadata['receipts']}


def _read_packet(source):
    raw = _read_file(Path(source))
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if (len(entries) > MAX_FILES + 1 or len(set(names)) != len(names)
                or set(names) - set(FILES) - {'manifest.json'}
                or 'manifest.json' not in names
                or sum(entry.file_size for entry in entries) > MAX_BYTES):
            raise ValueError('invalid or excessive packet inventory')
        for entry in entries:
            mode = entry.external_attr >> 16
            if (entry.flag_bits & 1 or entry.is_dir()
                    or stat.S_IFMT(mode) not in (0, stat.S_IFREG)
                    or entry.file_size > persistence.MAX_STATE_BYTES):
                raise ValueError('packet contains a non-regular or oversized entry')
        manifest = _decode(archive.read('manifest.json'))
        files = {name: archive.read(name) for name in names if name != 'manifest.json'}
    fields = {'schema_version', 'profile_uuid', 'origin_uuid', 'source_revision',
              'parent_revision', 'parent_hash', 'packet_hash', 'files'}
    if (not isinstance(manifest, dict) or set(manifest) != fields
            or type(manifest['schema_version']) is not int or manifest['schema_version'] != 2):
        raise ValueError('unsupported packet manifest')
    for field in ('profile_uuid', 'origin_uuid'):
        persistence.canonical_uuid(manifest[field])
    revision = _revision(manifest['source_revision'])
    parent = _revision(manifest['parent_revision'])
    if revision != parent + 1:
        raise ValueError('packet parent revision mismatch')
    if parent:
        _hash(manifest['parent_hash'])
    elif manifest['parent_hash'] is not None:
        raise ValueError('invalid initial parent hash')
    if not isinstance(manifest['files'], list) or len(manifest['files']) != len(files):
        raise ValueError('packet inventory mismatch')
    seen = set()
    for entry in manifest['files']:
        if not isinstance(entry, dict) or set(entry) != {'path', 'kind', 'owner', 'bytes', 'sha256'}:
            raise ValueError('invalid file descriptor')
        name = entry['path']
        if type(name) is not str or name not in files or name in seen:
            raise ValueError('duplicate or unapproved packet path')
        seen.add(name)
        expected_owner = 'informational' if name == 'information.json' else 'financial' if name in ('positions.json', 'trades.json', 'realizations.json', 'realization-batches.json', 'trading_mode.json') else 'shared'
        if (entry['kind'] != FILES[name] or entry['owner'] != expected_owner
                or type(entry['bytes']) is not int or entry['bytes'] != len(files[name])
                or entry['sha256'] != hashlib.sha256(files[name]).hexdigest()):
            raise ValueError('packet descriptor or content hash mismatch')
    if _hash(manifest['packet_hash']) != packet_hash(manifest, files):
        raise ValueError('packet hash mismatch')
    parsed = _validate_files(files)
    if parsed.get('information.json', {}).get('origin_uuid', manifest['origin_uuid']) != manifest['origin_uuid']:
        raise ValueError('informational source origin mismatch')
    return manifest, parsed, raw


def _union(left, right):
    result = copy.deepcopy(left)
    for key, value in right.items():
        if key in result and _json(result[key]) != _json(value):
            raise ValueError('immutable lineage or operation proof conflict')
        result[key] = copy.deepcopy(value)
    return result


def _merge_manifest(left, right):
    state_identity.validate_manifest(left)
    state_identity.validate_manifest(right)
    if left['origin_uuid'] != right['origin_uuid']:
        raise ValueError('identity manifest origin conflict')
    merged = {**right, 'mappings': _union(left['mappings'], right['mappings'])}
    if 'native' in left or 'native' in right:
        merged['native'] = _union(left.get('native', {}), right.get('native', {}))
    return state_identity.validate_manifest(merged)


def _merge(root, incoming):
    result = {}
    if 'trading_mode.json' in incoming:
        mode = incoming['trading_mode.json']
        current = persistence.read_state(root/'trading_mode.json','trading_mode')
        activation = _activation(root)
        owner = (activation['origin_uuid'] if activation['financial_authority'] else
                 current.get('authority_origin') or mode['authority_origin'])
        if mode['authority_origin'] != owner or owner is None:
            raise ValueError('trading stance authority differs')
        if not current or mode['revision'] > current['revision']:
            if incoming['identity-manifest.json']['origin_uuid'] != owner:
                raise ValueError('only the authority can advance trading stance')
            result['trading_mode.json'] = mode
        elif mode['revision'] == current['revision'] and _json(mode) != _json(current):
            raise ValueError('trading stance revision conflict')
    if 'information.json' in incoming:
        information = incoming['information.json']
        peers = persistence.read_state(root / 'peer-information.json', 'generic') or {'schema_version': 1, 'origins': {}}
        if (set(peers) != {'schema_version', 'origins'} or not isinstance(peers['origins'], dict)
                or len(peers['origins']) > MAX_FILES):
            raise ValueError('invalid peer informational store')
        for origin, value in peers['origins'].items():
            _information(value)
            if value['origin_uuid'] != origin:
                raise ValueError('peer informational origin mismatch')
        peers['origins'][information['origin_uuid']] = information
        result['peer-information.json'] = peers
    for name, kind in CORE.items():
        local = persistence.read_state(root / name, kind)
        peer = incoming[name]
        metadata_a = {key: value for key, value in local.items() if key not in (kind, 'items', 'tombstones', 'schema_version', 'realizations', 'watch_triggered')}
        metadata_b = {key: value for key, value in peer.items() if key not in (kind, 'items', 'tombstones', 'schema_version', 'realizations', 'watch_triggered')}
        if metadata_a and metadata_b and _json(metadata_a) != _json(metadata_b):
            raise ValueError('state root metadata conflict')
        if kind == 'watchlist':
            result[name] = identity_merge.merge_watchlists(local, peer)
        else:
            output = {**metadata_a, **metadata_b, kind: identity_merge.merge_rows(local[kind], peer[kind], kind)}
            if kind == 'positions':
                output['realizations'] = _union(local.get('realizations', {}), peer.get('realizations', {}))
            if kind == 'alerts':
                triggered = dict(local.get('watch_triggered', {}))
                for key, value in peer.get('watch_triggered', {}).items():
                    triggered[key] = max(value, triggered.get(key, value))
                output['watch_triggered'] = triggered
            result[name] = output
    local_lineage = persistence.read_state(root / 'identity-lineage.json', 'generic').get('origins', {})
    peer_lineage = incoming.get('identity-lineage.json', {}).get('origins', {})
    manifest = incoming['identity-manifest.json']
    lineage = dict(local_lineage)
    for declared, peer in peer_lineage.items():
        lineage[declared] = _merge_manifest(lineage[declared], peer) if declared in lineage else peer
    origin = manifest['origin_uuid']
    if origin in lineage:
        manifest = _merge_manifest(lineage[origin], manifest)
    lineage[origin] = manifest
    result['identity-lineage.json'] = {'schema_version': 1, 'origins': lineage}
    for name, key in (('realizations.json', 'operations'), ('realization-batches.json', 'batches')):
        local = persistence.read_state(root / name, 'generic').get(key, {})
        peer = incoming.get(name, {}).get(key, {})
        result[name] = {'schema_version': 1, key: _union(local, peer)}
    from rshelper.realization import validate_intents, verify_realization_snapshot
    validate_intents(result['realizations.json'], 'realizations.json')
    verify_realization_snapshot(result['positions.json'], result['trades.json']['trades'], result['realizations.json'])
    _validate_files({**{name: _json(value) for name, value in result.items() if name in FILES},
                     'identity-manifest.json': _json(persistence.read_state(root / 'identity-manifest.json', 'generic'))})
    return result


def apply_packet(profile, source):
    from rshelper.readiness import record_sync
    try:
        result = _apply_packet(resolve_config_path('', profile), profile, source)
    except (OSError, ValueError):
        record_sync(profile, {'status': 'failed'})
        raise
    record_sync(profile, result)
    return result


def _apply_packet(root, profile, source):
    manifest, incoming, raw = _read_packet(source)
    with state_transaction.profile_transaction(profile, root) as txn:
        activation = _activation(root)
        origin = manifest['origin_uuid']
        if (manifest['profile_uuid'] != activation['profile_uuid']
                or origin not in activation['replication_origins']
                or incoming['identity-manifest.json']['origin_uuid'] != origin):
            raise ValueError('packet profile or declared lineage mismatch')
        declared = {origin, *incoming.get('identity-lineage.json', {}).get('origins', {})}
        if not declared.issubset(activation['replication_origins']):
            raise ValueError('packet contains undeclared foreign lineage')
        state = _metadata(root)
        foreign_receipts = incoming.get('replication-receipts.json', {}).get('receipts', {})
        if (not set(foreign_receipts).issubset(activation['replication_origins'])
                or any(value['profile_uuid'] != manifest['profile_uuid'] for value in foreign_receipts.values())):
            raise ValueError('foreign receipt profile mismatch')
        if incoming.get('information.json', {}).get('origin_uuid', origin) != origin:
            raise ValueError('informational packet origin mismatch')
        last = state['receipts'].get(origin)
        revision = last['applied_revision'] if last else 0
        digest = last['applied_hash'] if last else None
        receipt = {'schema_version': 1, 'profile_uuid': manifest['profile_uuid'],
                   'origin_uuid': origin, 'status': 'applied',
                   'requested_revision': manifest['source_revision'], 'requested_hash': manifest['packet_hash'],
                   'applied_revision': revision, 'applied_hash': digest}
        if manifest['source_revision'] < revision:
            return {**receipt, 'status': 'obsolete'}
        if manifest['source_revision'] == revision and manifest['packet_hash'] == digest:
            return {**receipt, 'status': 'no_op'}
        try:
            if manifest['parent_revision'] != revision or manifest['parent_hash'] != digest:
                raise ValueError('packet parent or same-revision hash conflict')
            merged = _merge(root, incoming)
            proofs = persistence.read_state(root / 'peer-receipts.json', 'generic').get('sources', {})
            proofs[origin] = foreign_receipts
            merged['peer-receipts.json'] = {'schema_version': 1, 'sources': proofs}
        except ValueError:
            quarantine = root / 'replication-quarantine'
            if quarantine.is_symlink():
                raise ValueError('quarantine directory cannot be a symlink')
            quarantine.mkdir(mode=0o700, exist_ok=True)
            quarantine.chmod(0o700)
            state_transaction._durable_write(quarantine / (manifest['packet_hash'] + '.zip'), raw, 0o600)
            return {**receipt, 'status': 'conflict'}
        receipt.update(applied_revision=manifest['source_revision'], applied_hash=manifest['packet_hash'])
        state['receipts'][origin] = receipt
        for name, data in merged.items():
            txn.stage(name, data)
        txn.stage('replication-state.json', state)
        txn.commit(str(uuid5(UUID(origin), manifest['packet_hash'])))
        return receipt


def read_receipt(profile, origin_uuid):
    persistence.canonical_uuid(origin_uuid)
    root = resolve_config_path('', profile)
    with state_transaction.profile_transaction(profile, root):
        return copy.deepcopy(_metadata(root)['receipts'].get(origin_uuid, {}))
