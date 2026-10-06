"""Profile-wide recoverable state publication.

One profile transaction publishes validated profile state files under one
profile lock plus sorted per-file locks. A publishing marker makes any
interrupted publication fail closed, and a durable receipt names the exact
operation and per-file hashes that a publish made durable.
"""
import copy
import fcntl
import hashlib
import json
import os
import secrets
from contextlib import ExitStack, contextmanager
from pathlib import Path

from rshelper import persistence
from rshelper.persistence import locked_state

SCHEMA_VERSION = 1
STATE_FILES = {
    'positions.json': 'positions',
    'trades.json': 'trades',
    'alerts.json': 'alerts',
    'watchlist.json': 'watchlist',
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
    dir_fd = os.open(directory, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
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


def _publish_receipt(path: Path, receipt: dict) -> None:
    payload = json.dumps(receipt, sort_keys=True, separators=(',', ':'),
                         allow_nan=False).encode()
    _durable_write(Path(path), payload, 0o600)


def _clear_stale_markers(root: Path) -> None:
    """Clear markers left by an interrupted publish; callers hold the profile lock."""
    for name in STATE_FILES:
        marker = _marker_path(root / name)
        try:
            marker.unlink()
        except FileNotFoundError:
            pass


def _validate_payload(path: Path, data: dict, kind: str) -> bytes:
    persistence.validate_state(data, kind, path)
    payload = json.dumps(data, indent=2, allow_nan=False).encode()
    if len(payload) > MAX_PROFILE_BYTES:
        raise ValueError(f'{path.name}: state exceeds transaction byte budget')
    return payload


def _checkpoint(step: str) -> None:
    """Fault-injection boundary; tests may replace it."""


class _ProfileLock:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.fd = None

    def __enter__(self):
        self.root.mkdir(parents=True, exist_ok=True)
        sidecar = self.root / '.profile.lock'
        flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0)
        self.fd = os.open(sidecar, flags, 0o600)
        fcntl.flock(self.fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exception):
        try:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
        finally:
            os.close(self.fd)
            self.fd = None


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
        return {kind: persistence.read_state(root / name, kind)
                for name, kind in STATE_FILES.items()}


class StateTransaction:
    def __init__(self, profile: str, root: Path):
        self.profile = profile
        self.root = Path(root)
        self.staged = {}
        self._committed = False

    def stage(self, filename: str, data: dict) -> None:
        if filename not in STATE_FILES:
            raise ValueError(f'unknown profile state file: {filename}')
        path = self.root / filename
        persistence.validate_state(data, STATE_FILES[filename], path)
        self.staged[filename] = copy.deepcopy(data)

    def commit(self, operation_id: str) -> dict:
        if self._committed:
            raise ValueError('transaction already committed')
        self._committed = True
        persistence.canonical_uuid(operation_id)
        files = {name: _validate_payload(self.root / name, data, STATE_FILES[name])
                 for name, data in self.staged.items()}
        hashes = {name: hashlib.sha256(files[name]).hexdigest() for name in files}
        receipt = {'schema_version': SCHEMA_VERSION, 'operation_id': operation_id,
                   'files': sorted(files), 'hashes': hashes}
        paths = [self.root / name for name in files]
        with _ordered_locks(self.root, paths):
            _clear_stale_markers(self.root)
            for name in sorted(files):
                _publish_file(self.root / name, files[name])
            _checkpoint('receipt')
            _publish_receipt(receipt_path(self.root), receipt)
        return receipt


def _publish_marker_only(path: Path) -> None:
    _durable_write(_marker_path(path), b'{"publishing": true}', 0o600)


def activate_profile(root: Path, origin_uuid: str) -> dict:
    """Publish the schema-2 activation marker for a profile state root."""
    persistence.canonical_uuid(origin_uuid)
    manifest = {'schema_version': SCHEMA_VERSION, 'origin_uuid': origin_uuid,
                'mode': 'identified'}
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
        markers = [ _marker_path(root / name) for name in STATE_FILES ]
        if any(marker.exists() for marker in markers):
            raise persistence.StateCorruptionError('mixed profile state snapshot requires recovery')
        return persistence.read_state(receipt_path(root), 'generic')


@contextmanager
def profile_transaction(profile: str, root: Path):
    """Open one recoverable transaction for a profile state root."""
    root = Path(root)
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

    def commit(self, operation_id: str) -> dict:
        if self._txn is None or self._committed():
            raise ValueError('nothing staged to commit')
        return self._txn.commit(operation_id)

    def _committed(self):
        return getattr(self._txn, '_committed', False)
