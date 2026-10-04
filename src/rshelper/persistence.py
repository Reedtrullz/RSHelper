"""Fail-closed reads and process locks for user-owned JSON state."""
import contextlib
import copy
from datetime import datetime
import fcntl
import json
import math
import os
from pathlib import Path
import stat
import threading

MAX_STATE_BYTES = 64 * 1024 * 1024
MAX_STATE_DEPTH = 64
MAX_STATE_NODES = 1_000_000
_locks = {}
_registry_lock = threading.Lock()
_held = threading.local()


class StateCorruptionError(ValueError):
    """The original state needs explicit diagnosis/recovery before mutation."""


def _fail(path, reason):
    raise StateCorruptionError(f'{Path(path).name}: {reason}; original bytes preserved')


def _integer(value, minimum=None):
    return isinstance(value, int) and not isinstance(value, bool) and (minimum is None or value >= minimum)


def _finite(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and (isinstance(value, int) or math.isfinite(value)))


def _bounded_json(data, path):
    """Bound extension data and reject values JSON cannot safely round-trip."""
    pending = [(data, 0)]
    visited = 0
    while pending:
        value, depth = pending.pop()
        visited += 1
        if visited > MAX_STATE_NODES or depth > MAX_STATE_DEPTH:
            _fail(path, 'state extension exceeds structural limits')
        if isinstance(value, dict):
            for key, child in value.items():
                if not isinstance(key, str):
                    _fail(path, 'state object keys must be strings')
                pending.append((child, depth + 1))
        elif isinstance(value, list):
            pending.extend((child, depth + 1) for child in value)
        elif value is None or isinstance(value, (str, bool)):
            continue
        elif not _finite(value):
            _fail(path, 'state contains a non-finite or unsupported value')


def validate_state(data, kind, path):
    if kind not in ('watchlist', 'alerts', 'trades', 'positions', 'generic'):
        _fail(path, 'unknown state kind')
    if not isinstance(data, dict):
        _fail(path, 'state root must be an object')
    _bounded_json(data, path)
    version = data.get('schema_version', 1)
    if not _integer(version) or version != 1:
        _fail(path, 'unsupported schema version')
    if kind == 'generic':
        return data
    key = 'items' if kind == 'watchlist' else kind
    expected = dict if kind == 'watchlist' else list
    if key not in data or not isinstance(data[key], expected):
        _fail(path, f'{key} must be a {expected.__name__}')
    rows = data[key].values() if kind == 'watchlist' else data[key]
    for row in rows:
        if not isinstance(row, dict):
            _fail(path, 'state row must be an object')
        if kind in ('trades', 'positions'):
            for field in ('id', 'qty', 'buy_price'):
                if not _integer(row.get(field), 1):
                    _fail(path, f'invalid {field}')
            if not _integer(row.get('item_id'), 0 if kind == 'trades' else 1):
                _fail(path, 'invalid item_id')
            required = ('sell_price', 'tax_paid', 'profit') if kind == 'trades' else ()
            for field in required:
                minimum = 1 if field == 'sell_price' else 0 if field == 'tax_paid' else None
                if not _integer(row.get(field), minimum):
                    _fail(path, f'invalid {field}')
            timestamp = 'timestamp' if kind == 'trades' else 'opened_at'
            if not isinstance(row.get(timestamp), str):
                _fail(path, f'invalid {timestamp}')
            try:
                datetime.fromisoformat(row[timestamp].replace('Z', '+00:00'))
            except ValueError:
                _fail(path, f'invalid {timestamp}')
            if not isinstance(row.get('name'), str):
                _fail(path, 'invalid name')
            if kind == 'positions' and row.get('direction') not in ('traditional', 'arbitrage'):
                _fail(path, 'invalid direction')
            for field in ('hold_minutes', 'quote_sell', 'entry_spread_pct', 'entry_sell', 'entry_offer'):
                if row.get(field) is not None and not _finite(row[field]):
                    _fail(path, f'invalid {field}')
            for field in ('note', 'strategy', 'exit_reason'):
                if field in row and not isinstance(row[field], str):
                    _fail(path, f'invalid {field}')
            if 'fill_guard' in row and not isinstance(row['fill_guard'], bool):
                _fail(path, 'invalid fill guard flag')
        elif kind == 'alerts':
            if not _integer(row.get('id'), 1) or not _finite(row.get('ts')) or row['ts'] < 0:
                _fail(path, 'invalid alert identity/time')
            for field in ('type', 'severity', 'item_name', 'title', 'message'):
                if not isinstance(row.get(field), str):
                    _fail(path, f'invalid alert {field}')
            if row.get('item_id') is not None and not _integer(row['item_id'], 1):
                _fail(path, 'invalid alert item id')
            if not isinstance(row.get('read', False), bool):
                _fail(path, 'invalid alert read flag')
            if row.get('data') is not None and not isinstance(row['data'], dict):
                _fail(path, 'invalid alert data')
        elif kind == 'watchlist':
            if not isinstance(row.get('name'), str) or not isinstance(row.get('added'), str):
                _fail(path, 'invalid watched item name/time')
            for field in ('alert_margin_above', 'alert_margin_below'):
                if row.get(field) is not None and not _integer(row[field]):
                    _fail(path, f'invalid {field}')
        else:
            _fail(path, 'unknown state kind')
    if kind == 'watchlist':
        for item_id in data[key]:
            if not isinstance(item_id, str) or not item_id.isdigit() or len(item_id) > 19 or int(item_id) <= 0:
                _fail(path, 'invalid watched item id')
    if kind == 'alerts':
        triggered = data.get('watch_triggered', {})
        if not isinstance(triggered, dict) or any(not _finite(value) or value < 0 for value in triggered.values()):
            _fail(path, 'invalid watch dedupe timestamps')
    return data


def read_state(path: Path, kind: str) -> dict:
    defaults = {'watchlist': {'items': {}}, 'alerts': {'alerts': [], 'watch_triggered': {}},
                'trades': {'trades': []}, 'positions': {'positions': []}, 'generic': {}}
    if kind not in defaults:
        _fail(path, 'unknown state kind')
    try:
        state_path = Path(path)
        info = state_path.lstat()
    except FileNotFoundError:
        return copy.deepcopy(defaults[kind])
    except OSError:
        _fail(path, 'unable to inspect state')
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        _fail(path, 'state path is not a regular file')
    try:
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
        fd = os.open(state_path, flags)
        try:
            stream = os.fdopen(fd, 'rb')
        except BaseException:
            os.close(fd)
            raise
        with stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                _fail(path, 'state path is not a regular file')
            raw = stream.read(MAX_STATE_BYTES + 1)
    except OSError:
        _fail(path, 'unable to read state')
    if len(raw) > MAX_STATE_BYTES:
        _fail(path, 'state exceeds 64 MiB limit')
    try:
        def finite_float(value):
            number = float(value)
            if not math.isfinite(number):
                raise ValueError('nonfinite JSON number')
            return number
        data = json.loads(raw,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')),
                          parse_float=finite_float)
    except (ValueError, UnicodeDecodeError, RecursionError):
        _fail(path, 'invalid JSON')
    return validate_state(data, kind, path)


@contextlib.contextmanager
def locked_state(path: Path):
    """An unavailable interprocess lock prevents mutation; never fall back."""
    canonical = Path(path).resolve()
    with _registry_lock:
        lock = _locks.setdefault(str(canonical), threading.RLock())
    with lock:
        if not hasattr(_held, 'paths'):
            _held.paths = set()
        if canonical in _held.paths:
            yield
            return
        sidecar = canonical.with_suffix(canonical.suffix + '.lock')
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0)
        fd = os.open(sidecar, flags, 0o600)
        acquired = False
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise OSError('state lock sidecar is not a regular file')
            fcntl.flock(fd, fcntl.LOCK_EX)
            acquired = True
            _held.paths.add(canonical)
            yield
        finally:
            _held.paths.discard(canonical)
            try:
                if acquired:
                    fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)
