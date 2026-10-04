"""Private file provisioning; credential values never enter logs or arguments."""
import os
from pathlib import Path
import re
import secrets
import stat
from rshelper.recovery import _open_directory, _directory_matches


def _read_token(path, directory_fd=None):
    path = Path(path).absolute()
    own_directory = directory_fd is None
    if own_directory:
        directory_fd = _open_directory(path.parent)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=directory_fd)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or
                    info.st_uid != os.getuid() or info.st_size > 65):
                raise ValueError('owner token must be a private regular file owned by this user')
            raw = os.read(fd, 66)
        finally:
            os.close(fd)
        if not _directory_matches(path.parent, directory_fd):
            raise ValueError('owner token directory changed; access refused')
    finally:
        if own_directory:
            os.close(directory_fd)
    if re.fullmatch(rb'[0-9a-f]{64}\n?', raw) is None:
        raise ValueError('invalid owner token file; refused to replace it')
    return raw.decode('ascii').rstrip('\n')


def load_or_create_token(path: Path) -> str:
    """Read a private token or publish a new random one exclusively."""
    path = Path(path).absolute()
    if any(parent.is_symlink() for parent in path.parents) or path.is_symlink():
        raise ValueError('owner token path must not use symlinks')
    directory = _open_directory(path.parent, create=True)
    try:
        try:
            return _read_token(path, directory)
        except FileNotFoundError:
            pass
        if not _directory_matches(path.parent, directory):
            raise ValueError('owner token directory changed; access refused')
        temporary = '.owner-token-' + secrets.token_hex(16)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=directory)
        try:
            try:
                stream = os.fdopen(fd, 'wb')
            except BaseException:
                os.close(fd)
                raise
            with stream:
                stream.write(secrets.token_hex(32).encode('ascii') + b'\n')
                stream.flush()
                os.fsync(stream.fileno())
            if not _directory_matches(path.parent, directory):
                raise ValueError('owner token directory changed; access refused')
            try:
                os.link(temporary, path.name, src_dir_fd=directory,
                        dst_dir_fd=directory, follow_symlinks=False)
            except FileExistsError:
                pass
            os.fsync(directory)
        finally:
            os.unlink(temporary, dir_fd=directory)
        return _read_token(path, directory)
    finally:
        os.close(directory)
