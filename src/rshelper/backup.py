"""App-owned private backup inspection and recoverable restoration."""
from contextlib import ExitStack, nullcontext
from datetime import datetime, timezone
import hashlib
from itertools import islice
import json
import os
from pathlib import Path
import stat
import tempfile
import tomllib
import zipfile

from rshelper import __version__
from rshelper.config import _config_from_toml, validate_config
from rshelper.persistence import MAX_STATE_BYTES, locked_state, validate_state, read_state, canonical_uuid
from rshelper.profile import resolve_config_path, resolve_profile

MAX_BUNDLE_BYTES = 256 * 1024 * 1024
FILES = frozenset({'config.toml', 'trades.json', 'positions.json', 'watchlist.json',
    'paper-offers.json',
    'alerts.json', 'tuning_log.json', 'volume_baseline.json', 'signal_cooldowns.json',
    'trader_state.json', 'recent_exits.json', 'monitor_state.json',
    'identity-manifest.json', 'identity-activation.json', 'identity-lineage.json',
    'realizations.json', 'realization-batches.json', 'replication-state.json',
    'peer-receipts.json', 'peer-information.json', 'backup-restores.json', 'migration-receipts.json'})
CORE_KINDS = {'trades.json': 'trades', 'positions.json': 'positions',
              'watchlist.json': 'watchlist', 'alerts.json': 'alerts'}


class BackupError(ValueError):
    pass


def _files(root):
    selected = {}
    excluded = []
    with os.scandir(root) as scan:
        entries = list(islice(scan, 4097))
    if len(entries) > 4096:
        raise BackupError('backup source exceeds directory entry budget')
    entries.sort(key=lambda entry: entry.name)
    for entry in entries:
        if entry.name in FILES:
            if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                raise BackupError('backup source must contain regular files')
            selected[entry.name] = Path(entry.path)
        elif entry.name == 'snapshots':
            if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                raise BackupError('snapshot directory must not be a symlink')
            with os.scandir(entry.path) as scan:
                snapshots = list(islice(scan, 4097))
            if len(snapshots) > 4096:
                raise BackupError('snapshot directory exceeds entry budget')
            snapshots.sort(key=lambda child: child.name)
            for snapshot in snapshots:
                if not snapshot.name.endswith('.json'):
                    excluded.append('snapshots/' + snapshot.name)
                    continue
                if snapshot.is_symlink() or not snapshot.is_file(follow_symlinks=False):
                    raise BackupError('snapshot source must be a regular file')
                selected['snapshots/' + snapshot.name] = Path(snapshot.path)
        elif not entry.name.endswith('.lock'):
            excluded.append(entry.name)
    if len(selected) > 512:
        raise BackupError('backup source exceeds selected file budget')
    return selected, excluded


def _read_file(path, max_bytes=MAX_STATE_BYTES):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        stream = os.fdopen(descriptor, 'rb')
    except BaseException:
        os.close(descriptor)
        raise
    with stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise BackupError('backup source is not a regular file')
        raw = stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise BackupError('backup source exceeds file budget')
    return raw


def _validate_file(name, raw):
    try:
        if name == 'config.toml':
            validate_config(_config_from_toml(tomllib.loads(raw.decode('utf-8'))))
        else:
            from rshelper.persistence import decode_json
            data = decode_json(raw)
            validate_state(data, 'paper-book' if name=='paper-offers.json' else CORE_KINDS.get(name, 'generic'), name)
            if name == 'tuning_log.json':
                entries = data.get('entries')
                if not isinstance(entries, list) or any(not isinstance(row, dict)
                        or not isinstance(row.get('params'), dict)
                        or not isinstance(row.get('ts'), str) for row in entries):
                    raise ValueError('invalid tuning log')
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise BackupError(f'{name}: backup validation failed; source preserved') from None


def export_profile(profile: str, destination: Path, policy: str = 'backup') -> dict:
    from rshelper.state_transaction import profile_transaction
    root = _profile_root(profile)
    with profile_transaction(profile, root):
        return _export_profile(profile, destination, policy)


def _profile_root(profile):
    name = resolve_profile(profile)
    from rshelper import profile as profile_module
    base = profile_module.CONFIG_DIR
    lexical_root = base if name == 'default' else base / 'profiles' / name
    if (base.is_symlink() or lexical_root.is_symlink() or
            name != 'default' and (base / 'profiles').is_symlink()):
        raise BackupError('backup profile root must not be a symlink')
    return resolve_config_path('', name)


def _export_profile(profile: str, destination: Path, policy: str = 'backup', *, allow_empty=False) -> dict:
    from rshelper.persistence import decode_json as _decode
    if policy not in ('backup', 'private', 'evidence'):
        raise BackupError('profile backups are private; public publication requires its own policy')
    name = resolve_profile(profile)
    root = _profile_root(name)
    destination = Path(destination).absolute()
    if destination.resolve().is_relative_to(root):
        raise BackupError('backup destination must be outside the selected state root')
    if destination.exists() or destination.is_symlink():
        raise FileExistsError('backup destination already exists')
    selected, excluded = _files(root)
    if not selected and not allow_empty:
        raise BackupError('profile has no supported files to back up')
    content = {}
    validation = {}
    total = 0
    with ExitStack() as locks:
        for path in sorted(selected.values(), key=str):
            locks.enter_context(locked_state(path))
        for filename, path in sorted(selected.items()):
            raw = _read_file(path)
            try:
                _validate_file(filename, raw)
                validation[filename] = 'validated'
            except BackupError:
                if policy != 'evidence':
                    raise
                validation[filename] = 'invalid'
            total += len(raw)
            if total > MAX_BUNDLE_BYTES:
                raise BackupError('backup exceeds total byte budget')
            content[filename] = raw
        current, _ = _files(root)
        if set(current) != set(selected) or any(_read_file(current[key]) != raw for key, raw in content.items()):
            raise BackupError('profile changed during backup; retry capture')
    activation = _decode(content['identity-activation.json']) if 'identity-activation.json' in content else {}
    if policy != 'evidence' and activation.get('paper_budget_origin') is not None and 'paper-offers.json' not in content:
        raise BackupError('acknowledged paper budget missing; recover before backup')
    files = {key: {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw),
                   'sensitivity': 'private', 'validation': validation[key]} for key, raw in content.items()}
    revision = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    manifest = {'schema_version': 1, 'app_version': __version__, 'profile': name,
        'created_at': datetime.now(timezone.utc).isoformat(), 'sensitivity': 'private',
        'policy': policy, 'validation': 'unvalidated-evidence' if policy == 'evidence' else 'validated',
        'source_revision': revision, 'files': files,
        'excluded': excluded, 'capture_consistency': 'shared-locks-and-byte-recheck'}
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=destination.parent, prefix='.rshelper-backup-')
    try:
        with os.fdopen(descriptor, 'w+b') as stream:
            with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
                for filename, raw in {**content, 'manifest.json': json.dumps(manifest, sort_keys=True).encode()}.items():
                    info = zipfile.ZipInfo(filename)
                    info.external_attr = 0o600 << 16
                    info.compress_type = zipfile.ZIP_DEFLATED
                    bundle.writestr(info, raw)
            stream.flush()
            os.fsync(stream.fileno())
        # Atomic exclusive publication; a concurrent target/symlink is never replaced.
        os.link(temporary, destination)
        directory = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return manifest


def _inspect(source):
    import io
    from rshelper.persistence import decode_json as _decode
    raw = _read_file(Path(source), MAX_BUNDLE_BYTES)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if (len(entries) > 513 or len(set(names)) != len(names)
                or sum(entry.file_size for entry in entries) > MAX_BUNDLE_BYTES
                or 'manifest.json' not in names):
            raise BackupError('invalid or excessive archive inventory')
        for entry in entries:
            name = entry.filename
            parts = Path(name).parts
            allowed = name in FILES or name == 'manifest.json' or (
                len(parts) == 2 and parts[0] == 'snapshots' and parts[1].endswith('.json'))
            if (not allowed or name != Path(name).as_posix() or '..' in parts
                    or entry.is_dir() or entry.flag_bits & 1
                    or stat.S_IFMT(entry.external_attr >> 16) not in (0, stat.S_IFREG)
                    or entry.file_size > MAX_STATE_BYTES):
                raise BackupError('archive contains unapproved or non-regular file')
        manifest = _decode(archive.read('manifest.json'))
        content = {name: archive.read(name) for name in names if name != 'manifest.json'}
    if (not isinstance(manifest, dict) or type(manifest.get('schema_version')) is not int
            or manifest['schema_version'] != 1 or manifest.get('validation') != 'validated'
            or manifest.get('sensitivity') != 'private' or manifest.get('policy') not in ('backup', 'private')
            or not isinstance(manifest.get('files'), dict) or set(manifest['files']) != set(content)):
        raise BackupError('unsupported, unvalidated or incomplete backup')
    if manifest.get('app_version') != __version__:
        raise BackupError('backup app version compatibility is unverified')
    for name, payload in content.items():
        record = manifest['files'][name]
        if (not isinstance(record, dict) or record.get('sensitivity') != 'private'
                or record.get('validation') != 'validated' or type(record.get('bytes')) is not int
                or record['bytes'] != len(payload)
                or record.get('sha256') != hashlib.sha256(payload).hexdigest()):
            raise BackupError('backup content hash mismatch')
        if name.endswith('.json'):
            _decode(payload)
        _validate_file(name, payload)
    revision = hashlib.sha256(json.dumps(manifest['files'], sort_keys=True).encode()).hexdigest()
    if revision != manifest.get('source_revision'):
        raise BackupError('backup source revision mismatch')
    activation = _decode(content['identity-activation.json']) if 'identity-activation.json' in content else {}
    profile_uuid = activation.get('profile_uuid')
    if activation.get('paper_budget_origin') is not None and 'paper-offers.json' not in content:
        raise BackupError('backup omits acknowledged paper budget')
    if profile_uuid is not None:
        canonical_uuid(profile_uuid)
        from rshelper import state_identity, realization
        canonical_uuid(activation.get('origin_uuid'))
        if activation.get('mode') != 'identified' or type(activation.get('financial_authority')) is not bool:
            raise BackupError('invalid backup activation')
        if 'identity-manifest.json' not in content:
            raise BackupError('backup activation lacks lineage manifest')
        identity = _decode(content['identity-manifest.json'])
        state_identity.validate_manifest(identity)
        if identity['origin_uuid'] != activation['origin_uuid']:
            raise BackupError('backup manifest origin differs from activation')
        from rshelper import identity_merge
        allowed_origins = activation.get('replication_origins', [activation['origin_uuid']])
        if not isinstance(allowed_origins, list) or activation['origin_uuid'] not in allowed_origins:
            raise BackupError('invalid declared replication origins')
        for origin in allowed_origins:
            canonical_uuid(origin)
        for name, kind in CORE_KINDS.items():
            if name not in content:
                continue
            data = _decode(content[name])
            if kind == 'watchlist':
                identity_merge.merge_watchlists(data, data)
                rows = list(data['items'].values()) + list(data.get('tombstones', {}).values())
            else:
                rows = identity_merge.merge_rows(data[kind], [], kind)
            if any(row['origin_uuid'] not in allowed_origins for row in rows):
                raise BackupError('backup contains undeclared foreign profile lineage')
        if 'realization-batches.json' in content:
            realization.validate_batches(_decode(content['realization-batches.json']))
        intents = _decode(content['realizations.json']) if 'realizations.json' in content else {'schema_version': 1, 'operations': {}}
        if not isinstance(intents, dict) or not isinstance(intents.get('operations'), dict):
            raise BackupError('invalid backup operation collection')
        operations = intents['operations']
        assert isinstance(operations, dict)
        realization.validate_intents(intents, 'realizations.json')
        consumed_by_lot = {}
        for operation in operations.values():
            lot = operation['request']['lot_uid']
            consumed_by_lot[lot] = consumed_by_lot.get(lot, 0) + operation['request']['qty']
        if any(not intent['done'] for intent in operations.values()):
            raise BackupError('recover pending financial operations before restoring backup')
        realization.verify_realization_snapshot(
            _decode(content['positions.json']) if 'positions.json' in content else {'positions': []},
            _decode(content['trades.json'])['trades'] if 'trades.json' in content else [], intents)
        if 'paper-offers.json' in content:
            from rshelper.paper_book import verify_book_financial
            book=_decode(content['paper-offers.json'])
            if activation.get('paper_budget_origin')!=book['origin_uuid']:
                raise BackupError('backup paper authority marker differs')
            verify_book_financial(book,_decode(content['positions.json']) if 'positions.json' in content else {'positions':[]},
                _decode(content['trades.json']) if 'trades.json' in content else {'trades':[]},intents,
                _decode(content['realization-batches.json']) if 'realization-batches.json' in content else {})
        lineage = _decode(content['identity-lineage.json']) if 'identity-lineage.json' in content else {'origins': {}}
        if not isinstance(lineage, dict) or not isinstance(lineage.get('origins'), dict):
            raise BackupError('invalid backup lineage collection')
        manifests = dict(lineage['origins'])
        for origin, attestation in manifests.items():
            state_identity.validate_manifest(attestation)
            if attestation['origin_uuid'] != origin:
                raise BackupError('foreign manifest origin mismatch')
        if identity['origin_uuid'] in manifests:
            prior = manifests[identity['origin_uuid']]
            for field in ('mappings', 'native'):
                for key, value in prior.get(field, {}).items():
                    if key not in identity.get(field, {}) or identity[field][key] != value:
                        raise BackupError('own lineage does not include its attested history')
        manifests[identity['origin_uuid']] = identity
        for name, kind in CORE_KINDS.items():
            if name not in content:
                continue
            store = _decode(content[name])
            rows = list(store['items'].values()) + list(store.get('tombstones', {}).values()) if kind == 'watchlist' else store[kind]
            groups = {}
            for row in rows:
                attestation = manifests.get(row['origin_uuid'])
                if attestation is None:
                    raise BackupError('backup record lacks attested lineage')
                intent = operations.get(row.get('operation_id')) if kind == 'trades' else None
                if intent is not None and intent['trade']['record_uuid'] == row['record_uuid']:
                    continue
                groups.setdefault(row['origin_uuid'], []).append(row)
                if kind == 'positions' and row['record_uuid'] in attestation.get('native', {}):
                    consumed = consumed_by_lot.get(row['record_uuid'], 0)
                    if consumed + (0 if row['tombstone'] else row['qty']) != attestation['native'][row['record_uuid']]['creation_qty']:
                        raise BackupError('native lot creation quantity conflicts with realized state')
            for origin, group in groups.items():
                if kind == 'watchlist':
                    state_identity.migrate_watchlist({'items': {str(row['item_id']): row for row in group if not row['tombstone']},
                        'tombstones': {row['record_uuid']: row for row in group if row['tombstone']}}, manifests[origin])
                else:
                    state_identity.migrate_rows(group, kind, manifests[origin])
    return {**manifest, 'profile_uuid': profile_uuid}, content


def inspect_backup(source: Path) -> dict:
    return _inspect(source)[0]


def restore_profile(profile: str, source: Path, *, expected_profile_uuid: str, operation_id: str | None,
                    expected_source_revision: str | None = None, dry_run=False,
                    pre_restore_backup: Path | None = None) -> dict:
    from rshelper import identity_merge, state_transaction
    from rshelper.persistence import decode_json as _decode
    from rshelper.identity_merge import _json
    canonical_uuid(expected_profile_uuid)
    if operation_id is not None or not dry_run:
        canonical_uuid(operation_id)
    manifest, content = _inspect(source)
    if expected_source_revision is not None and expected_source_revision != manifest['source_revision']:
        raise BackupError('backup source revision does not match explicit restore source')
    legacy = manifest['profile_uuid'] is None
    if legacy:
        if expected_source_revision is None:
            raise BackupError('legacy restore requires its explicit inspected source revision')
        if any(name.startswith('identity-') or name in ('realizations.json', 'realization-batches.json',
                'replication-state.json', 'migration-receipts.json') for name in content):
            raise BackupError('legacy restore source contains identity or operation metadata')
        from rshelper.persistence import validate_writable_state
        for name, kind in CORE_KINDS.items():
            if name in content:
                validate_writable_state(_decode(content[name]), kind, Path(name))
    elif manifest['profile_uuid'] != expected_profile_uuid:
        raise BackupError('backup profile UUID does not match explicit restore target')
    root = _profile_root(profile)
    with (nullcontext() if dry_run else state_transaction.profile_transaction(profile, root)) as txn:
        activation = read_state(root / 'identity-activation.json', 'generic')
        incoming_activation = _decode(content['identity-activation.json']) if not legacy else {}
        if legacy and activation:
            raise BackupError('legacy restore cannot replace an activated profile')
        if activation and (activation.get('profile_uuid') != expected_profile_uuid
                           or activation.get('origin_uuid') != incoming_activation.get('origin_uuid')
                           or activation.get('financial_authority') != incoming_activation.get('financial_authority')):
            raise BackupError('existing profile identity differs from restore target')
        operations = read_state(root / 'backup-restores.json', 'generic').get('operations', {})
        if operation_id in operations:
            prior = operations[operation_id]
            if (prior['source_revision'] != manifest['source_revision']
                    or prior['profile_uuid'] != expected_profile_uuid):
                raise BackupError('restore operation reused with another backup')
            if not dry_run:
                return prior
        if legacy and any((root / name).exists() or (root / name).is_symlink()
                          for name in FILES if name != 'backup-restores.json'):
            raise BackupError('legacy restore requires an empty inactive target')
        for name, kind in CORE_KINDS.items():
            local = read_state(root / name, kind)
            rows = local.get('items', {}) if kind == 'watchlist' else local[kind]
            if not rows and not local.get('tombstones') and not local.get('realizations'):
                continue
            if name not in content:
                raise BackupError('backup would discard acknowledged state')
            peer = _decode(content[name])
            if kind == 'watchlist':
                merged = identity_merge.merge_watchlists(local, peer)
                canonical = identity_merge.merge_watchlists(peer, peer)
            else:
                merged = identity_merge.merge_rows(local[kind], peer[kind], kind)
                canonical = identity_merge.merge_rows(peer[kind], peer[kind], kind)
            if _json(merged) != _json(canonical):
                raise BackupError('backup is older than acknowledged state; assessed disaster recovery required')
        for name, key in (('realizations.json', 'operations'), ('realization-batches.json', 'batches')):
            live = read_state(root / name, 'generic').get(key, {})
            incoming = _decode(content[name]).get(key, {}) if name in content else {}
            if any(operation not in incoming or _json(value) != _json(incoming[operation]) for operation, value in live.items()):
                raise BackupError('backup would discard acknowledged operation proof')
        if (root/'paper-offers.json').exists():
            from rshelper.paper_book import require_book_successor
            live_book=read_state(root/'paper-offers.json','paper-book')
            if 'paper-offers.json' not in content:
                raise BackupError('backup would discard acknowledged paper reservations')
            try:require_book_successor(live_book,_decode(content['paper-offers.json']))
            except ValueError as exc:raise BackupError('backup would rewind paper reservations: '+str(exc)) from None
        live_packets = read_state(root / 'replication-state.json', 'generic')
        old_packets = _decode(content['replication-state.json']) if 'replication-state.json' in content else {}
        for origin, receipt in live_packets.get('receipts', {}).items():
            saved = old_packets.get('receipts', {}).get(origin, {})
            if (saved.get('applied_revision', 0) < receipt['applied_revision']
                    or saved.get('applied_revision') == receipt['applied_revision']
                    and saved.get('applied_hash') != receipt['applied_hash']):
                raise BackupError('backup would roll back an acknowledged replication receipt')
        outgoing = live_packets.get('outgoing')
        saved_outgoing = old_packets.get('outgoing')
        if outgoing and (not saved_outgoing or saved_outgoing['source_revision'] < outgoing['source_revision']
                         or saved_outgoing['source_revision'] == outgoing['source_revision']
                         and saved_outgoing['packet_hash'] != outgoing['packet_hash']):
            raise BackupError('backup would roll back the publication cursor')
        if dry_run:
            changes = []
            for name, payload in sorted(content.items()):
                if name == 'backup-restores.json':
                    continue
                path = root/name
                if not path.exists() or _read_file(path) != payload:
                    changes.append({'file': name, 'action': 'replace' if path.exists() else 'create'})
            return {'status': 'preview', 'sensitivity': 'private', 'profile_uuid': expected_profile_uuid,
                    'source_revision': manifest['source_revision'], 'changes': changes,
                    'files': sorted(content)}
        prior_backup = None
        if pre_restore_backup is not None:
            prior_backup = _export_profile(profile, pre_restore_backup, allow_empty=True)
        result = {'schema_version': 1, 'operation_id': operation_id, 'status': 'restored',
                  'source_revision': manifest['source_revision'], 'profile_uuid': expected_profile_uuid,
                  'restored_files': sorted(content)}
        if prior_backup is not None:
            result['pre_apply_backup_revision'] = prior_backup['source_revision']
        assert operation_id is not None
        operations[operation_id] = result
        assert txn is not None
        for name, payload in content.items():
            if name != 'backup-restores.json':
                txn.stage_bytes(name, payload)
        txn.stage('backup-restores.json', {'schema_version': 1, 'operations': operations})
        txn.commit(operation_id)
        return result
