"""Explicit, evidence-preserving quarantine of malformed scan snapshots only."""
from datetime import datetime, timezone
from contextlib import contextmanager, ExitStack
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import zipfile

from rshelper.persistence import MAX_STATE_BYTES, MAX_STATE_DEPTH


class RecoveryError(ValueError):
    pass


def _regular_path(root, relative):
    root = Path(root).absolute()
    parts = Path(relative).parts
    if ('..' in root.parts or Path(relative).is_absolute() or '..' in parts or
            not (len(parts) == 2 and parts[0] == 'snapshots' or
                 len(parts) == 3 and parts[:2] == ('state', 'snapshots')) or
            not parts[-1].endswith('.json')):
        raise RecoveryError('only a selected scan snapshot can be quarantined')
    path = root / relative
    for ancestor in (root, *path.parents):
        if ancestor.is_symlink():
            raise RecoveryError('snapshot parents must not be symlinks')
    if not root.is_dir() or path.is_symlink() or not path.is_file():
        raise RecoveryError('snapshot must be a regular file')
    return root, path


def _open_directory(path, create=False):
    """Walk from the filesystem root, refusing aliases at every component."""
    path = Path(path).absolute()
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(path.anchor, flags)
    try:
        for name in path.parts[1:]:
            if name == '..':
                raise RecoveryError('directory path must be canonical')
            try:
                child = os.open(name, flags, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(name, mode=0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
                child = os.open(name, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _identity(info):
    return info.st_dev, info.st_ino


def _directory_matches(path, descriptor):
    try:
        current = _open_directory(path)
        try:
            return _identity(os.fstat(current)) == _identity(os.fstat(descriptor))
        finally:
            os.close(current)
    except (OSError, ValueError):
        return False


def _read_at(directory_fd, name):
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise RecoveryError('snapshot must be a regular file')
        stream = os.fdopen(descriptor, 'rb')
    except BaseException:
        os.close(descriptor)
        raise
    with stream:
        raw = stream.read(MAX_STATE_BYTES + 1)
    if len(raw) > MAX_STATE_BYTES:
        raise RecoveryError('snapshot exceeds file budget')
    return raw, _identity(info)


@contextmanager
def _source_lock(directory_fd, filename):
    # Same persistent flock sidecar as shared state writers, pinned to this
    # directory. Never unlink: doing so would split cooperating lock inodes.
    fd = os.open(filename + '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
                 0o600, dir_fd=directory_fd)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise RecoveryError('snapshot lock must be a regular file')
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _malformed(raw):
    # Bound nested parser allocation before decoding. Brackets in JSON strings
    # do not count; malformed over-budget input is retained for manual diagnosis.
    depth = 0
    quoted = escaped = False
    for char in raw:
        if quoted:
            if escaped:
                escaped = False
            elif char == 92:
                escaped = True
            elif char == 34:
                quoted = False
        elif char == 34:
            quoted = True
        elif char in (91, 123):
            depth += 1
            if depth > MAX_STATE_DEPTH:
                raise RecoveryError('JSON exceeds decoder limits; automatic quarantine refused')
        elif char in (93, 125):
            depth -= 1
    try:
        json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return
    except (ValueError, RecursionError):
        raise RecoveryError('JSON exceeds decoder limits; automatic quarantine refused') from None
    raise RecoveryError('parseable JSON cannot be quarantined by this tool')


def preview_snapshot_quarantine(root: Path, relative: str) -> dict:
    """Inspect without creating evidence or changing the selected snapshot."""
    _, path = _regular_path(root, relative)
    directory = _open_directory(path.parent)
    try:
        raw, _ = _read_at(directory, path.name)
        if not _directory_matches(path.parent, directory):
            raise RecoveryError('snapshot directory changed; retry preview')
    finally:
        os.close(directory)
    _malformed(raw)
    return {'path': relative, 'bytes': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest(), 'action': 'quarantine',
            'sensitivity': 'private'}


def quarantine_snapshot(root: Path, relative: str, evidence_root: Path,
                        expected_sha: str) -> dict:
    """Keep verified private evidence and raw original before releasing locks.

    A noncooperating writer race is detected after the atomic move. Restoration
    uses an exclusive link, so any newer active file is never overwritten.
    Cross-filesystem moves fail safely; there is no copy/delete fallback.
    """
    root, source = _regular_path(root, relative)
    evidence_root = Path(evidence_root).absolute()
    if evidence_root.resolve().is_relative_to(root):
        raise RecoveryError('evidence must be outside the active state root')
    if any(path.is_symlink() for path in (evidence_root, *evidence_root.parents)):
        raise RecoveryError('evidence parents must not be symlinks')
    with ExitStack() as handles:
        source_dir = _open_directory(source.parent)
        handles.callback(os.close, source_dir)
        handles.enter_context(_source_lock(source_dir, source.name))
        raw, source_identity = _read_at(source_dir, source.name)
        _malformed(raw)
        digest = hashlib.sha256(raw).hexdigest()
        if expected_sha != digest:
            raise RecoveryError('snapshot changed; source preserved')
        if not _directory_matches(source.parent, source_dir):
            raise RecoveryError('snapshot directory changed; source preserved')
        evidence_dir = _open_directory(evidence_root, create=True)
        handles.callback(os.close, evidence_dir)
        folder_name = 'snapshot-' + secrets.token_hex(16)
        os.mkdir(folder_name, mode=0o700, dir_fd=evidence_dir)
        folder_dir = os.open(folder_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                             dir_fd=evidence_dir)
        handles.callback(os.close, folder_dir)
        folder = evidence_root / folder_name
        archive = folder / 'evidence.zip'
        manifest = {'schema_version': 1, 'path': relative, 'sha256': digest,
                    'bytes': len(raw), 'sensitivity': 'private',
                    'validation': 'malformed-json',
                    'created_at': datetime.now(timezone.utc).isoformat()}
        fd = os.open('evidence.zip', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=folder_dir)
        try:
            stream = os.fdopen(fd, 'wb')
        except BaseException:
            os.close(fd)
            raise
        with stream:
            with zipfile.ZipFile(stream, 'w') as bundle:
                for name, content in ((relative, raw), ('manifest.json', json.dumps(manifest).encode())):
                    info = zipfile.ZipInfo(name)
                    info.external_attr = 0o600 << 16
                    bundle.writestr(info, content)
            stream.flush()
            os.fsync(stream.fileno())
        fd = os.open('evidence.zip', os.O_RDONLY | os.O_NOFOLLOW, dir_fd=folder_dir)
        try:
            stream = os.fdopen(fd, 'rb')
        except BaseException:
            os.close(fd)
            raise
        with stream, zipfile.ZipFile(stream) as bundle:
            if bundle.read(relative) != raw or json.loads(bundle.read('manifest.json')) != manifest:
                raise RecoveryError('evidence verification failed; source preserved')
        os.fsync(folder_dir)
        if (not _directory_matches(source.parent, source_dir) or
                not _directory_matches(folder, folder_dir)):
            raise RecoveryError('snapshot/evidence directory changed; source preserved')
        original = folder / 'original.json'
        try:
            os.rename(source.name, 'original.json', src_dir_fd=source_dir, dst_dir_fd=folder_dir)
        except OSError:
            raise RecoveryError('snapshot move failed; source and evidence preserved') from None
        # Original retains its original mode inside a private 0700 directory.
        try:
            moved, moved_identity = _read_at(folder_dir, 'original.json')
            verified = (hashlib.sha256(moved).hexdigest() == digest and
                        moved_identity == source_identity and
                        _directory_matches(source.parent, source_dir) and
                        _directory_matches(folder, folder_dir))
        except (OSError, ValueError):
            verified = False
        if not verified:
            try:
                os.link('original.json', source.name, src_dir_fd=folder_dir,
                        dst_dir_fd=source_dir, follow_symlinks=False)
                status = ('selected snapshot restored' if _directory_matches(source.parent, source_dir)
                          else 'original restored in displaced source directory; selected path changed')
            except OSError:
                try:
                    os.stat(source.name, dir_fd=source_dir, follow_symlinks=False)
                    status = 'checked source path exists'
                except FileNotFoundError:
                    status = 'active snapshot absent'
            retained = (f'original retained at {original}' if _directory_matches(folder, folder_dir)
                        else f'original retained in displaced evidence directory (initial path: {folder})')
            raise RecoveryError(f'post-move verification failed; {status}; {retained}')
        return {**manifest, 'archive': str(archive), 'original': str(original)}


def main(argv=None):
    import argparse
    import sys
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--snapshot', required=True)
    parser.add_argument('--evidence-dir', type=Path)
    parser.add_argument('--expected-sha')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    if args.apply and (args.evidence_dir is None or args.expected_sha is None):
        parser.error('--apply requires --evidence-dir and --expected-sha')
    try:
        if args.apply:
            report = quarantine_snapshot(args.root, args.snapshot, args.evidence_dir, args.expected_sha)
        else:
            report = preview_snapshot_quarantine(args.root, args.snapshot)
        print(json.dumps(report))
        return 0
    except (ValueError, OSError) as exc:
        print(f'Recovery refused: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
