"""Profile-wide recoverable state publication.

One profile transaction publishes validated profile state files under one
profile lock plus sorted per-file locks. A publishing marker makes any
interrupted publication fail closed, and a durable receipt names the exact
operation and per-file hashes that a publish made durable.
"""
import copy
import hashlib
import json
import os
import secrets
import stat
from contextlib import ExitStack, contextmanager
from pathlib import Path

from rshelper import persistence
from rshelper.persistence import locked_state

SCHEMA_VERSION = 1
STATE_FILES = {
    'observed-offers.json':'generic',
    'paper-offers.json': 'paper-book',
    'trading_mode.json': 'trading_mode',
    'positions.json': 'positions',
    'trades.json': 'trades',
    'alerts.json': 'alerts',
    'watchlist.json': 'watchlist',
    'replication-state.json': 'generic',
    'peer-receipts.json': 'generic',
    'peer-information.json': 'generic',
    'identity-lineage.json': 'generic',
    'realizations.json': 'generic',
    'realization-batches.json': 'generic',
    'identity-manifest.json': 'generic',
    'migration-receipts.json': 'generic',
    'identity-activation.json': 'generic',
    'backup-restores.json': 'generic',
    'tuning_log.json': 'generic', 'volume_baseline.json': 'generic',
    'signal_cooldowns.json': 'generic', 'trader_state.json': 'generic',
    'recent_exits.json': 'generic', 'monitor_state.json': 'generic',
    'config.toml': 'config',
    'trade-reviews.json':'generic',
}
MAX_PROFILE_BYTES = 64 * 1024 * 1024


def receipt_path(root: Path) -> Path:
    return Path(root) / 'realization-receipt.json'


def activation_path(root: Path) -> Path:
    return Path(root) / 'identity-activation.json'


def _marker_path(path: Path) -> Path:
    return path.with_name('.' + path.name + '.publishing')


def _durable_write(path: Path, payload: bytes, mode: int) -> None:
    path = Path(path)
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    temporary = path.name + '.' + secrets.token_hex(12) + '.tmp'
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
    dir_fd = os.open(directory, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) | getattr(os, 'O_NOFOLLOW', 0))
    try:
        fd = os.open(temporary, flags, mode, dir_fd=dir_fd)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path.name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        except BaseException:
            try:
                os.unlink(temporary, dir_fd=dir_fd)
            except FileNotFoundError:
                pass
            raise
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _publish_file(path: Path, payload: bytes) -> None:
    """Durable file replacement with a marker; crash leaves the marker."""
    path = Path(path)
    marker = _marker_path(path)
    _durable_write(marker, b'{"publishing": true}', 0o600)
    _checkpoint('data:' + path.name)
    _durable_write(path, payload, 0o600)
    marker.unlink()
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _publish_receipt(path: Path, receipt: dict) -> None:
    payload = json.dumps(receipt, sort_keys=True, separators=(',', ':'),
                         allow_nan=False).encode()
    _durable_write(Path(path), payload, 0o600)


def _validate_payload(path: Path, data: dict, kind: str) -> bytes:
    persistence.validate_state(data, kind, path)
    payload = json.dumps(data, indent=2, allow_nan=False).encode()
    if len(payload) > MAX_PROFILE_BYTES:
        raise ValueError(f'{path.name}: state exceeds transaction byte budget')
    return payload


def _kind(filename):
    if type(filename) is not str or filename != Path(filename).as_posix():
        raise ValueError('noncanonical profile filename')
    if filename in STATE_FILES:
        return STATE_FILES[filename]
    parts = Path(filename).parts
    if (len(parts) == 2 and parts[0] == 'snapshots'
            and parts[1].endswith('.json') and parts[1] not in ('.json', '..json')
            and len(parts[1]) <= 255):
        return 'generic'
    raise ValueError('unknown profile state file')


def _validate_bytes(filename, raw):
    kind = _kind(filename)
    if kind == 'config':
        import tomllib
        from rshelper.config import _config_from_toml, validate_config
        validate_config(_config_from_toml(tomllib.loads(raw.decode('utf-8'))))
    else:
        persistence.validate_state(persistence.decode_json(raw), kind, filename)
        if filename=='tuning_log.json':
            from rshelper.tuning import validate_log
            validate_log(persistence.decode_json(raw))
        if filename=='trade-reviews.json':
            from rshelper.trade_reviews import validate_store
            validate_store(persistence.decode_json(raw))
        if filename=='observed-offers.json':
            from rshelper.observed_offers import validate_store
            validate_store(persistence.decode_json(raw))
    if len(raw) > MAX_PROFILE_BYTES:
        raise ValueError('profile state file exceeds byte budget')


def _checkpoint(step: str) -> None:
    """Fault-injection boundary; tests may replace it."""


class _ProfileLock:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.lease = ExitStack()

    def __enter__(self):
        if self.root.is_symlink():
            raise ValueError('profile state root cannot be a symlink')
        self.root.mkdir(parents=True, exist_ok=True)
        self.lease.enter_context(persistence.locked_state(self.root / '.profile'))
        return self

    def __exit__(self, *exception):
        return self.lease.__exit__(*exception)


@contextmanager
def _ordered_locks(root: Path, paths):
    root = Path(root)
    with ExitStack() as stack:
        stack.enter_context(_ProfileLock(root))
        for path in sorted(paths, key=lambda value: str(value)):
            stack.enter_context(locked_state(path))
        yield


def read_profile_snapshot(profile: str, root: Path) -> dict:
    """Read all four profile files coherently under the profile lock."""
    root = Path(root)
    paths = [root / name for name in STATE_FILES]
    with _ordered_locks(root, paths):
        _recover_locked(root)
        return {kind: persistence.read_state(root / name, kind)
                for name, kind in STATE_FILES.items()
                if kind in ('positions', 'trades', 'alerts', 'watchlist')}


class StateTransaction:
    def __init__(self, profile: str, root: Path):
        self.profile = profile
        self.root = Path(root)
        self.staged = {}
        self._committed = False

    def stage(self, filename: str, data: dict) -> None:
        kind = _kind(filename)
        path = self.root / filename
        staged = copy.deepcopy(data)
        if kind in ('positions', 'trades', 'watchlist', 'alerts') and profile_is_active(self.root):
            staged['schema_version'] = 2
        self.stage_bytes(filename, _validate_payload(path, staged, kind))

    def stage_bytes(self, filename, raw):
        _validate_bytes(filename, raw)
        parent = (self.root / filename).parent
        if parent.is_symlink() or not parent.resolve().is_relative_to(self.root.resolve()):
            raise ValueError('profile filename escapes transaction root')
        self.staged[filename] = bytes(raw)

    def commit(self, operation_id: str) -> dict:
        if self._committed:
            raise ValueError('transaction already committed')
        persistence.canonical_uuid(operation_id)
        files = dict(self.staged)
        for name, raw in files.items():
            _validate_bytes(name, raw)
        hashes = {name: hashlib.sha256(files[name]).hexdigest() for name in files}
        receipt = {'schema_version': SCHEMA_VERSION, 'operation_id': operation_id,
                   'files': sorted(files), 'hashes': hashes}
        paths = [self.root / name for name in files]
        with _ordered_locks(self.root, paths):
            _recover_locked(self.root)
            pending = {'schema_version': SCHEMA_VERSION, 'receipt': receipt,
                       'files': {name: files[name].decode('utf-8') for name in files},
                       'before': {name: _file_hash(self.root / name) for name in files}}
            payload = json.dumps(pending, sort_keys=True, allow_nan=False).encode()
            if len(payload) > MAX_PROFILE_BYTES:
                raise ValueError('transaction redo intent exceeds byte budget')
            _durable_write(self.root / '.profile-pending.json', payload, 0o600)
            _checkpoint('intent')
            _recover_locked(self.root)
        self._committed = True
        return receipt


def _file_hash(path):
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    with os.fdopen(descriptor, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('transaction target is not a regular file')
        raw = stream.read(MAX_PROFILE_BYTES + 1)
    if len(raw) > MAX_PROFILE_BYTES:
        raise ValueError('transaction target exceeds byte budget')
    relative = 'snapshots/' + path.name if path.parent.name == 'snapshots' else path.name
    _validate_bytes(relative, raw)
    return hashlib.sha256(raw).hexdigest()


def _recover_locked(root):
    pending_path = root / '.profile-pending.json'
    pending = persistence.read_state(pending_path, 'generic', _publication_check=False)
    if not pending:
        if any(_marker_path(root / name).exists() for name in STATE_FILES):
            raise persistence.StateCorruptionError('publication marker lacks recoverable intent')
        return
    if (set(pending) != {'schema_version', 'receipt', 'files', 'before'}
            or type(pending['schema_version']) is not int
            or pending['schema_version'] != SCHEMA_VERSION
            or not isinstance(pending['files'], dict)
            or not isinstance(pending['before'], dict)):
        raise persistence.StateCorruptionError('invalid transaction redo intent')
    receipt = pending['receipt']
    if (not isinstance(receipt, dict)
            or set(receipt) != {'schema_version', 'operation_id', 'files', 'hashes'}
            or type(receipt['schema_version']) is not int or receipt['schema_version'] != SCHEMA_VERSION
            or receipt['files'] != sorted(pending['files'])
            or set(receipt['hashes']) != set(pending['files'])
            or set(pending['before']) != set(pending['files'])):
        raise persistence.StateCorruptionError('invalid transaction redo receipt')
    persistence.canonical_uuid(receipt['operation_id'])
    files = {}
    for name, text in pending['files'].items():
        if type(name) is not str or type(text) is not str:
            raise persistence.StateCorruptionError('invalid transaction redo filename')
        payload = text.encode('utf-8')
        _validate_bytes(name, payload)
        parent = (root / name).parent
        if parent.is_symlink() or not parent.resolve().is_relative_to(root.resolve()):
            raise ValueError('redo filename escapes transaction root')
        digest = hashlib.sha256(payload).hexdigest()
        if digest != receipt['hashes'][name]:
            raise persistence.StateCorruptionError('transaction redo hash mismatch')
        if _file_hash(root / name) not in (pending['before'][name], digest):
            raise persistence.StateCorruptionError('transaction target changed outside publication')
        files[name] = payload
    for name in sorted(files):
        _publish_file(root / name, files[name])
    _checkpoint('receipt')
    _publish_receipt(receipt_path(root), receipt)
    _checkpoint('receipt-published')
    pending_path.unlink()
    directory = os.open(root, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    _checkpoint('directory-fsync')


def _publish_marker_only(path: Path) -> None:
    _durable_write(_marker_path(path), b'{"publishing": true}', 0o600)


def activate_profile(root: Path, origin_uuid: str,
                     financial_authority: bool = True) -> dict:
    """Publish the activation manifest for a profile state root."""
    persistence.canonical_uuid(origin_uuid)
    manifest = {'schema_version': SCHEMA_VERSION, 'origin_uuid': origin_uuid,
                'mode': 'identified',
                'financial_authority': bool(financial_authority)}
    _publish_receipt(activation_path(root), manifest)
    return manifest


def profile_is_active(root: Path) -> bool:
    try:
        manifest = persistence.read_state(activation_path(root), 'generic')
    except (persistence.StateCorruptionError, OSError):
        return False
    return bool(manifest) and manifest.get('mode') == 'identified'


def recover_profile(root: Path) -> dict:
    """Refuse mixed snapshots and report the durable receipt when complete."""
    root = Path(root)
    paths = [root / name for name in STATE_FILES]
    with _ordered_locks(root, paths):
        _recover_locked(root)
        return persistence.read_state(receipt_path(root), 'generic')


@contextmanager
def profile_transaction(profile: str, root: Path):
    """Open one recoverable transaction for a profile state root."""
    root = Path(root)
    with _ProfileLock(root):
        _recover_locked(root)
        yield _TransactionHandle(profile, root)


class _TransactionHandle:
    def __init__(self, profile: str, root: Path):
        self.profile = profile
        self.root = root
        self._txn = None

    def stage(self, filename: str, data: dict) -> None:
        if self._txn is None:
            self._txn = StateTransaction(self.profile, self.root)
        self._txn.stage(filename, data)

    def stage_bytes(self, filename, raw):
        if self._txn is None:
            self._txn = StateTransaction(self.profile, self.root)
        self._txn.stage_bytes(filename, raw)

    def commit(self, operation_id: str) -> dict:
        if self._txn is None or self._committed():
            raise ValueError('nothing staged to commit')
        return self._txn.commit(operation_id)

    def _committed(self):
        return getattr(self._txn, '_committed', False)
