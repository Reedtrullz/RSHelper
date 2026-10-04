"""App-owned private backups; staged restore is a separate acceptance slice."""
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import tomllib
import zipfile

from rshelper import __version__
from rshelper.config import _config_from_toml, validate_config
from rshelper.persistence import MAX_STATE_BYTES, locked_state, validate_state
from rshelper.profile import resolve_config_path, resolve_profile

MAX_BUNDLE_BYTES = 256 * 1024 * 1024
FILES = frozenset({'config.toml', 'trades.json', 'positions.json', 'watchlist.json',
    'alerts.json', 'tuning_log.json', 'volume_baseline.json', 'signal_cooldowns.json',
    'trader_state.json', 'recent_exits.json', 'monitor_state.json'})
CORE_KINDS = {'trades.json': 'trades', 'positions.json': 'positions',
              'watchlist.json': 'watchlist', 'alerts.json': 'alerts'}


class BackupError(ValueError):
    pass


def _files(root):
    selected = {}
    excluded = []
    with os.scandir(root) as scan:
        entries = sorted(scan, key=lambda entry: entry.name)
    for entry in entries:
        if entry.name in FILES:
            if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                raise BackupError('backup source must contain regular files')
            selected[entry.name] = Path(entry.path)
        elif entry.name == 'snapshots':
            if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                raise BackupError('snapshot directory must not be a symlink')
            with os.scandir(entry.path) as scan:
                snapshots = sorted(scan, key=lambda child: child.name)
            for snapshot in snapshots:
                if not snapshot.name.endswith('.json'):
                    excluded.append('snapshots/' + snapshot.name)
                    continue
                if snapshot.is_symlink() or not snapshot.is_file(follow_symlinks=False):
                    raise BackupError('snapshot source must be a regular file')
                selected['snapshots/' + snapshot.name] = Path(snapshot.path)
        elif not entry.name.endswith('.lock'):
            excluded.append(entry.name)
    return selected, excluded


def _read_file(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        stream = os.fdopen(descriptor, 'rb')
    except BaseException:
        os.close(descriptor)
        raise
    with stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise BackupError('backup source is not a regular file')
        raw = stream.read(MAX_STATE_BYTES + 1)
    if len(raw) > MAX_STATE_BYTES:
        raise BackupError('backup source exceeds file budget')
    return raw


def _validate_file(name, raw):
    try:
        if name == 'config.toml':
            validate_config(_config_from_toml(tomllib.loads(raw.decode('utf-8'))))
        else:
            data = json.loads(raw)
            validate_state(data, CORE_KINDS.get(name, 'generic'), name)
            if name == 'tuning_log.json':
                entries = data.get('entries')
                if not isinstance(entries, list) or any(not isinstance(row, dict)
                        or not isinstance(row.get('params'), dict)
                        or not isinstance(row.get('ts'), str) for row in entries):
                    raise ValueError('invalid tuning log')
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise BackupError(f'{name}: backup validation failed; source preserved') from None


def export_profile(profile: str, destination: Path, policy: str = 'backup') -> dict:
    """Capture validated bytes into a private ZIP, refusing existing targets.

    Core writers share these locks. A final byte/inventory recheck detects
    concurrent changes by legacy writers; it does not claim cross-file
    transaction coherence for writers that do not share the locks yet.
    """
    if policy not in ('backup', 'private', 'evidence'):
        raise BackupError('profile backups are private; public publication requires its own policy')
    name = resolve_profile(profile)
    from rshelper import profile as profile_module
    base = profile_module.CONFIG_DIR
    lexical_root = base if name == 'default' else base / 'profiles' / name
    if (base.is_symlink() or lexical_root.is_symlink() or
            name != 'default' and (base / 'profiles').is_symlink()):
        raise BackupError('backup profile root must not be a symlink')
    root = resolve_config_path('', name)
    destination = Path(destination).absolute()
    if destination.resolve().is_relative_to(root):
        raise BackupError('backup destination must be outside the selected state root')
    if destination.exists() or destination.is_symlink():
        raise FileExistsError('backup destination already exists')
    selected, excluded = _files(root)
    if not selected:
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
    finally:
        Path(temporary).unlink(missing_ok=True)
    return manifest
