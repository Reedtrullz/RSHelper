"""Private file provisioning; credential values never enter logs or arguments."""
import os
from pathlib import Path
import re
import secrets
import stat
import tempfile


def _read_token(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or
                info.st_uid != os.getuid() or info.st_size > 65):
            raise ValueError('owner token must be a private regular file owned by this user')
        raw = os.read(fd, 66)
    finally:
        os.close(fd)
    if re.fullmatch(rb'[0-9a-f]{64}\n?', raw) is None:
        raise ValueError('invalid owner token file; refused to replace it')
    return raw.decode('ascii').rstrip('\n')


def load_or_create_token(path: Path) -> str:
    """Read a private token or publish a new random one exclusively."""
    path = Path(path).absolute()
    if any(parent.is_symlink() for parent in path.parents) or path.is_symlink():
        raise ValueError('owner token path must not use symlinks')
    try:
        return _read_token(path)
    except FileNotFoundError:
        pass
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.owner-token-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(secrets.token_hex(32).encode('ascii') + b'\n')
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            pass
    finally:
        Path(temporary).unlink(missing_ok=True)
    return _read_token(path)
