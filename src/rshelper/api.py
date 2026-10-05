"""OSRS GE price clients: OSRS Wiki Realtime Prices API, with a GE Tracker
fallback for datacenter IPs that the wiki's Cloudflare blocks (403)."""

import calendar
import concurrent.futures
from contextlib import contextmanager
import datetime
import email.utils
import fcntl
import json
import math
import os
import stat
import sys
import tempfile
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

from rshelper.profile import resolve_cache_path
from rshelper.market_validation import validate_payload, MarketDataError
from rshelper.market_data import MarketDataResult

BASE_URL = "https://prices.runescape.wiki/api/v1/osrs"
GE_TRACKER_URL = "https://www.ge-tracker.com/api/items"
USER_AGENT = "RSHelper/1.6 (+https://rs.reidar.tech; reed@reidar.tech)"
_LAST_REQUEST = 0.0
_THROTTLE_LOCK = threading.Lock()
REQUEST_INTERVAL = 1.0
MAX_RETRY_AFTER = 60.0
MAX_BUDGET_AHEAD = 120.0  # Bounded local queue plus shared server cooldown.
CACHE_DIR = Path.home() / ".cache" / "rshelper"
CACHE_MAX_AGE = {
    "mapping": 86400,  # 24h — item metadata rarely changes
    "latest": 120,     # 2 min — prices update frequently
    "5m": 120,         # 2 min — volume data refreshes often
    "ge_tracker": 300,  # 5 min — full GE Tracker dump; one fetch per cycle
}
STALE_MULTIPLIER = 3  # serve stale cache up to 3x max_age if API fails
CACHE_ENVELOPE_VERSION = 1
_MARKET_SOURCES = {"wiki", "ge-tracker", "unknown"}
_DELIVERIES = {"fresh-cache", "network", "stale-cache"}
_VOLUME_KINDS = {"executed-trades", "standing-orders", "unknown"}
_TRACKER_DELIVERY = threading.local()

# Ensure cache dir exists at import time (parents for fresh HOMEs)
CACHE_DIR.mkdir(parents=True, exist_ok=True)


class RequestBudgetUnavailable(RuntimeError):
    """The shared request budget cannot safely reserve an attempt."""


def _throttle_path() -> Path:
    """Shared reservation state, independent of the active account profile."""
    return CACHE_DIR / ".throttle"


def _throttle_lock_path() -> Path:
    return CACHE_DIR / ".throttle.lock"


def _load_request_budget(stamp: Path, now: float) -> tuple[float, float, float, float]:
    """Return wall clock, next slot, cooldown and completed dispatch time."""
    try:
        fd = os.open(stamp, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise RequestBudgetUnavailable('shared request budget is not a regular file')
            with os.fdopen(fd, 'rb') as stream:
                fd = None
                content = stream.read(4097)
            if len(content) > 4096:
                raise RequestBudgetUnavailable('shared request budget exceeds size limit')
            raw = content.decode('ascii').strip()
        finally:
            if fd is not None:
                os.close(fd)
    except FileNotFoundError:
        return now, now, 0.0, 0.0
    except (OSError, UnicodeDecodeError) as exc:
        raise RequestBudgetUnavailable("cannot read shared request budget") from exc
    try:
        try:
            state = json.JSONDecoder().decode(raw)
        except json.JSONDecodeError:
            # Accept the previous release's numeric timestamp during upgrade.
            legacy = float(raw)
            if not math.isfinite(legacy):
                raise ValueError("non-finite legacy timestamp")
            return legacy, legacy + REQUEST_INTERVAL, 0.0, 0.0
        if isinstance(state, (int, float)) and not isinstance(state, bool):
            legacy = float(state)
            if not math.isfinite(legacy):
                raise ValueError("non-finite legacy timestamp")
            return legacy, legacy + REQUEST_INTERVAL, 0.0, 0.0
        if not isinstance(state, dict) or type(state.get('version')) is not int or state['version'] != 1:
            raise ValueError("unknown reservation state")
        last_now = state["last_now"]
        next_at = state["next_at"]
        blocked_until = state.get('blocked_until', 0.0)
        finished = state.get('dispatch_finished', 0.0)
        if isinstance(finished, bool) or not isinstance(finished, (int, float)):
            raise ValueError('invalid dispatch timestamp')
        finished = float(finished)
        if (isinstance(last_now, bool) or isinstance(next_at, bool) or isinstance(blocked_until, bool)
                or not isinstance(last_now, (int, float))
                or not isinstance(next_at, (int, float)) or not isinstance(blocked_until, (int, float))):
            raise ValueError("invalid reservation timestamp")
        last_now, next_at, blocked_until = float(last_now), float(next_at), float(blocked_until)
        if (not all(math.isfinite(value) for value in (last_now, next_at, blocked_until, finished))
                or next_at < last_now or blocked_until < 0
                or finished < 0 or finished > last_now
                or blocked_until - last_now > MAX_RETRY_AFTER):
            raise ValueError("invalid reservation timestamp")
        if next_at - last_now > MAX_BUDGET_AHEAD:
            raise ValueError("reservation timestamp exceeds bound")
        return last_now, next_at, blocked_until, finished
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        raise RequestBudgetUnavailable("shared request budget is corrupt") from exc


def _write_request_budget(stamp: Path, last_now: float, next_at: float,
                          blocked_until: float = 0.0, finished: float = 0.0) -> None:
    payload = json.dumps({"version": 1, "last_now": last_now, "next_at": next_at,
                          'blocked_until': blocked_until, 'dispatch_finished': finished},
                         allow_nan=False)
    try:
        fd, temporary = tempfile.mkstemp(dir=stamp.parent, prefix=".throttle-", suffix=".tmp")
    except OSError as exc:
        raise RequestBudgetUnavailable('cannot create shared request budget') from exc
    try:
        try:
            stream = os.fdopen(fd, 'w')
        except BaseException:
            os.close(fd)
            raise
        with stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, stamp)
    except Exception as exc:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        if isinstance(exc, OSError):
            raise RequestBudgetUnavailable('cannot write shared request budget') from exc
        raise


@contextmanager
def _locked_request_budget():
    stamp = _throttle_path()
    fd = None
    lock_file = None
    try:
        stamp.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(_throttle_lock_path(),
                     os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise RequestBudgetUnavailable('shared request lock is not a regular file')
        lock_file = os.fdopen(fd, 'r+')
        fd = None
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
    except (OSError, OverflowError, ValueError) as exc:
        if lock_file is not None: lock_file.close()
        raise RequestBudgetUnavailable('cannot coordinate shared request budget') from exc
    except BaseException:
        if lock_file is not None: lock_file.close()
        raise
    finally:
        if fd is not None: os.close(fd)
    # Do not classify an HTTPError raised by dispatch as a lock-acquisition
    # failure: HTTPError inherits OSError and must reach the retry handler.
    with lock_file:
        try:
            yield stamp
        finally:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            except OSError as exc:
                raise RequestBudgetUnavailable('cannot release shared request lock') from exc


def _reserve_request(now: float | None, interval: float,
                     retry_after: float | None = None) -> float:
    """Atomically reserve an attempt time; the caller sleeps after unlocking."""
    if ((now is not None and not math.isfinite(now)) or not math.isfinite(interval) or interval <= 0
            or (retry_after is not None and
                (not math.isfinite(retry_after) or retry_after < 0))):
        raise RequestBudgetUnavailable("invalid request budget input")
    with _locked_request_budget() as stamp:
        # Sampling after the lock prevents stale samples from resembling rollback.
        if now is None:
            now = time.time()
        if not math.isfinite(now):
            raise RequestBudgetUnavailable('invalid request budget clock')
        last_now, next_at, blocked_until, finished = _load_request_budget(stamp, now)
        if now < last_now:
            raise RequestBudgetUnavailable('system clock moved backwards')
        if retry_after is not None:
            blocked_until = max(blocked_until, now + min(retry_after, MAX_RETRY_AFTER))
        reserved = max(now, next_at, blocked_until)
        if reserved + interval - now > MAX_BUDGET_AHEAD:
            raise RequestBudgetUnavailable('shared request queue exceeds wait budget')
        _write_request_budget(stamp, now, reserved + interval, blocked_until, finished)
        return reserved


def _record_retry_after(delay: float) -> None:
    """Publish server backoff even when this caller has exhausted its retries."""
    with _locked_request_budget() as stamp:
        now = time.time()
        last_now, next_at, blocked_until, finished = _load_request_budget(stamp, now)
        if now < last_now:
            raise RequestBudgetUnavailable('system clock moved backwards')
        blocked_until = max(blocked_until, now + min(delay, MAX_RETRY_AFTER))
        _write_request_budget(stamp, now, max(now, next_at, blocked_until), blocked_until, finished)


def _wait_for_reservation(reserved: float) -> None:
    """Recheck shared cooldown before dispatch; sleep only after unlocking."""
    while True:
        with _locked_request_budget() as stamp:
            now = time.time()
            last_now, next_at, blocked_until, finished = _load_request_budget(stamp, now)
            if now < last_now:
                raise RequestBudgetUnavailable('system clock moved backwards')
            if reserved < blocked_until:
                # A server cooldown invalidates slots already held by waiters.
                # Reassign those slots, so they cannot burst when it expires.
                reserved = max(now, next_at, blocked_until)
                if reserved + REQUEST_INTERVAL - now > MAX_BUDGET_AHEAD:
                    raise RequestBudgetUnavailable('shared request queue exceeds wait budget')
                _write_request_budget(stamp, now, reserved + REQUEST_INTERVAL, blocked_until, finished)
            delay = reserved - now
        if delay <= 0:
            return
        time.sleep(delay)


def _dispatch_request(request, attempt=0):
    """Serialize actual dispatch through response headers, then space arrivals.

    A process may pause after reserving a slot. Holding the shared lock through
    urlopen prevents that stale slot from racing another actual dispatch. The
    next attempt waits one interval after headers (or a failed connection),
    conservatively preserving spacing even if the prior dispatch was delayed.
    Response-body reads and all sleeps stay outside the lock.
    """
    while True:
        with _locked_request_budget() as stamp:
            now = time.time()
            last_now, next_at, blocked_until, finished = _load_request_budget(stamp, now)
            if not math.isfinite(now) or now < last_now:
                raise RequestBudgetUnavailable('invalid or reversed request clock')
            delay = max(blocked_until, finished + REQUEST_INTERVAL) - now
            if delay <= 0:
                response = None
                server_delay = 0.0
                try:
                    response = urllib.request.urlopen(request, timeout=15)
                    return response
                except urllib.error.HTTPError as exc:
                    if exc.code in (429, 503):
                        server_delay = min(MAX_RETRY_AFTER, max(RETRY_DELAY * (2 ** attempt),
                            _parse_retry_after((exc.headers or {}).get('Retry-After'))))
                    raise
                finally:
                    try:
                        completed = time.time()
                        if not math.isfinite(completed) or completed < now:
                            raise RequestBudgetUnavailable('invalid or reversed dispatch clock')
                        blocked_until = max(blocked_until, completed + server_delay) if server_delay else blocked_until
                        _write_request_budget(stamp, completed, max(completed, next_at),
                                              blocked_until, completed)
                    except BaseException:
                        if response is not None: response.close()
                        raise
        time.sleep(delay)


def _throttle() -> None:
    """Compatibility wrapper for callers that explicitly pace one request."""
    global _LAST_REQUEST
    reserved = _reserve_request(None, REQUEST_INTERVAL)
    _wait_for_reservation(reserved)
    _LAST_REQUEST = time.time()


def _parse_retry_after(value: str | None) -> float:
    """Parse Retry-After seconds or HTTP date, bounded to one minute."""
    if not value:
        return 0.0
    value = value.strip()
    try:
        delay = float(value)
        if not math.isfinite(delay) or delay < 0:
            return 0.0
        return min(delay, MAX_RETRY_AFTER)
    except ValueError:
        pass
    try:
        target = email.utils.parsedate_to_datetime(value)
        if target.tzinfo is None:
            target = target.replace(tzinfo=datetime.timezone.utc)
        delay = target.timestamp() - time.time()
        if not math.isfinite(delay):
            return 0.0
        return min(max(0.0, delay), MAX_RETRY_AFTER)
    except (TypeError, ValueError, OverflowError):
        return 0.0


# Backoff config for retryable errors
MAX_RETRIES = 3
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
MAX_JSON_DEPTH = 64
RETRY_DELAY = 2.0  # seconds, doubles each retry


def _fetch_url(url: str, retries: int = MAX_RETRIES) -> Any:
    """GET url with retry+backoff, return parsed JSON (None on failure)."""
    last_exc = None
    for attempt in range(retries + 1):
        try:
            reserved = _reserve_request(None, REQUEST_INTERVAL)
            _wait_for_reservation(reserved)
        except RequestBudgetUnavailable as exc:
            print(f"  Warning: shared request budget unavailable; skipping {url}: {exc}",
                  file=sys.stderr)
            return None
        req = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT},
        )
        try:
            with _dispatch_request(req, attempt) as resp:
                raw = resp.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    print("  Warning: market response exceeds 32 MiB limit", file=sys.stderr)
                    return None
                return _decode_market_json(raw)
        except RequestBudgetUnavailable as exc:
            print(f'  Warning: shared dispatch budget unavailable: {exc}', file=sys.stderr)
            return None
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 503):
                delay = max(RETRY_DELAY * (2 ** attempt),
                            _parse_retry_after((exc.headers or {}).get("Retry-After")))
            if exc.code in (429, 503) and attempt < retries:
                print(f"  Retrying {url} in {delay:.0f}s (HTTP {exc.code}, attempt {attempt + 1}/{retries + 1})", file=sys.stderr)
                time.sleep(delay)
                last_exc = exc
                continue
            print(f"  Warning: HTTP {exc.code} fetching {url}: {exc.reason}", file=sys.stderr)
            return None
        except (urllib.error.URLError, json.JSONDecodeError, MarketDataError, UnicodeDecodeError, RecursionError, OSError) as exc:
            if attempt < retries:
                delay = RETRY_DELAY * (2 ** attempt)
                print(f"  Retrying {url} in {delay:.0f}s ({type(exc).__name__}, attempt {attempt + 1}/{retries + 1})", file=sys.stderr)
                time.sleep(delay)
                last_exc = exc
                continue
            print(f"  Warning: failed to fetch {url}: {exc}", file=sys.stderr)
            return None
    return None


def _get(path: str, retries: int = MAX_RETRIES) -> Any:
    """GET a Wiki API endpoint with retry+backoff, return parsed JSON."""
    return _fetch_url(f"{BASE_URL}/{path}", retries)


def _get_ge_tracker(profile: str | None = None) -> Any | None:
    """Fetch the GE Tracker all-items dump (undocumented, no auth), cached."""
    _TRACKER_DELIVERY.value = None
    _TRACKER_DELIVERY.result = None
    cached = _cache_result("ge_tracker", profile, stale=False)
    if cached is not None:
        _TRACKER_DELIVERY.value = "fresh-cache"
        _TRACKER_DELIVERY.result = cached
        return {"data": cached.data}
    rows = _validated("ge_tracker", _fetch_url(GE_TRACKER_URL))
    data = {"data": rows} if rows else None
    if data is not None:
        now = time.time()
        _save_cache_result("ge_tracker", data, profile, source="ge-tracker",
                           fetched_at=now, last_attempt_at=now, last_success_at=now,
                           volume_kind="standing-orders", coverage={"ge-tracker": len(rows)})
        _TRACKER_DELIVERY.value = "network"
        _TRACKER_DELIVERY.result = MarketDataResult(rows, 'ge-tracker', 'network',
            now, now, now, False, 'standing-orders', {'ge-tracker': len(rows)})
        return data
    stale_result = _cache_result("ge_tracker", profile, stale=True, now=time.time())
    if stale_result is not None:
        _TRACKER_DELIVERY.value = stale_result.delivery
        _TRACKER_DELIVERY.result = stale_result
        return {"data": stale_result.data}
    return None


def _ge_tracker_items(dump: Any) -> list[dict]:
    items = dump.get("data", dump) if isinstance(dump, dict) else dump
    return items if isinstance(items, list) else []


def _parse_tracker_time(value: Any) -> int | None:
    """GE Tracker 'YYYY-MM-DD HH:MM:SS' (UTC) -> epoch seconds, None if unparseable."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return calendar.timegm(parsed.timetuple())


def _mapping_from_ge_tracker(dump: Any) -> list[dict]:
    """GE Tracker item rows -> wiki-shaped mapping entries."""
    out = []
    for e in _ge_tracker_items(dump):
        if not isinstance(e, dict) or "itemId" not in e:
            continue
        out.append({
            "id": e["itemId"],
            "name": e.get("name", ""),
            "members": bool(e.get("members", False)),
            "limit": e.get("buyLimit", 0),
            "highalch": e.get("highAlch", 0),
            "lowalch": e.get("lowAlch", 0),
        })
    return out


def _latest_from_ge_tracker(dump: Any) -> dict[str, dict]:
    """GE Tracker buying/selling -> wiki-shaped latest prices keyed by item ID."""
    out = {}
    for e in _ge_tracker_items(dump):
        if not isinstance(e, dict) or "itemId" not in e:
            continue
        out[str(e["itemId"])] = {
            "high": e.get("buying", 0),
            "low": e.get("selling", 0),
            "highTime": _parse_tracker_time(e.get("lastKnownBuyTime")),
            "lowTime": _parse_tracker_time(e.get("lastKnownSellTime")),
            "high_volume": e.get("buyingQuantity", 0),
            "low_volume": e.get("sellingQuantity", 0),
        }
    return out


def _5m_from_ge_tracker(dump: Any) -> dict[str, dict]:
    # ponytail: GE Tracker has no 5m trade volume; use its current order
    # quantities as a relative volume proxy so scans have something to rank.
    # Real 5m trade volume is wiki-only.
    out = {}
    for e in _ge_tracker_items(dump):
        if not isinstance(e, dict) or "itemId" not in e:
            continue
        out[str(e["itemId"])] = {
            "highPriceVolume": e.get("buyingQuantity", 0),
            "lowPriceVolume": e.get("sellingQuantity", 0),
        }
    return out


def _cache_path(name: str, profile: str | None = None) -> Path:
    return resolve_cache_path(name + ".json", profile)


def _provenance_path(name: str, profile: str | None = None) -> Path:
    return _cache_path(name, profile).with_name(name + ".provenance.json")


def _read_provenance_record(name: str, profile: str | None = None):
    """Read the versioned sidecar; absent sidecars denote legacy provenance."""
    path = _provenance_path(name, profile)
    try:
        envelope, modified = _read_cache_payload(path)
    except FileNotFoundError:
        return None
    except (MarketDataError, UnicodeDecodeError, RecursionError, OSError):
        raise MarketDataError("invalid market provenance")
    keys = {"schema_version", "data", "source", "fetched_at", "last_attempt_at",
            "last_success_at", "volume_kind", "coverage"}
    if not isinstance(envelope, dict) or set(envelope) != keys:
        raise MarketDataError("invalid market provenance fields")
    if (isinstance(envelope["schema_version"], bool)
            or not isinstance(envelope["schema_version"], int)
            or envelope["schema_version"] != CACHE_ENVELOPE_VERSION):
        raise MarketDataError("unsupported market provenance version")
    if (not isinstance(envelope["source"], str) or envelope["source"] not in _MARKET_SOURCES
            or not isinstance(envelope["volume_kind"], str)
            or envelope["volume_kind"] not in _VOLUME_KINDS):
        raise MarketDataError("invalid market provenance label")
    if ((envelope['source'] == 'ge-tracker' and envelope['volume_kind'] == 'executed-trades')
            or (envelope['source'] == 'unknown' and envelope['volume_kind'] != 'unknown')):
        raise MarketDataError('source cannot certify this volume semantics')
    for key in ("fetched_at", "last_attempt_at", "last_success_at"):
        value = envelope[key]
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                  or not math.isfinite(value) or value < 0):
            raise MarketDataError("invalid market provenance timestamp")
    coverage = envelope["coverage"]
    if (not isinstance(coverage, dict) or any(
            not isinstance(source, str) or source not in _MARKET_SOURCES or isinstance(count, bool)
            or not isinstance(count, int) or count < 0
            for source, count in coverage.items())):
        raise MarketDataError("invalid market provenance coverage")
    return envelope, modified


def _cache_metadata(name: str, profile: str | None = None) -> dict | None:
    record = _read_provenance_record(name, profile)
    return record[0] if record is not None else None


def _read_cache_record(name: str, profile: str | None = None):
    # This single atomic envelope is authoritative. The data-only mirror is
    # for rollback/old readers; its separate replacement cannot certify source.
    record = _read_provenance_record(name, profile)
    if record is not None:
        envelope, modified = record
        return envelope['data'], envelope, modified
    data, modified = _read_cache_payload(_cache_path(name, profile))
    return data, {'source': 'unknown', 'fetched_at': None, 'last_attempt_at': None,
                 'last_success_at': None, 'volume_kind': 'unknown', 'coverage': {}}, modified


def _atomic_json(path: Path, value: Any) -> None:
    payload = json.dumps(value, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_RESPONSE_BYTES:
        raise MarketDataError("market cache exceeds size limit")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _save_cache_result(name: str, data: Any, profile: str | None, *, source: str,
                       fetched_at: float | None, last_attempt_at: float | None,
                       last_success_at: float | None, volume_kind: str,
                       coverage: dict[str, int]) -> None:
    """Write the legacy data shape and a matching bounded provenance envelope."""
    if source not in _MARKET_SOURCES or volume_kind not in _VOLUME_KINDS:
        raise MarketDataError("invalid market provenance label")
    envelope = {"schema_version": CACHE_ENVELOPE_VERSION, "data": data,
                "source": source, "fetched_at": fetched_at,
                "last_attempt_at": last_attempt_at, "last_success_at": last_success_at,
                "volume_kind": volume_kind, "coverage": coverage}
    for value in (data, envelope):
        encoded = json.dumps(value, allow_nan=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > MAX_RESPONSE_BYTES:
            raise MarketDataError("market cache exceeds size limit")
    # Current readers use the complete atomic envelope. Separate legacy mirror
    # writes can interleave without changing the provenance of that record.
    _atomic_json(_provenance_path(name, profile), envelope)
    _atomic_json(_cache_path(name, profile), data)


def _decode_market_json(raw):
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise MarketDataError("invalid market JSON") from exc
    stack = [iter([payload])]
    while stack:
        try:
            value = next(stack[-1])
        except StopIteration:
            stack.pop()
            continue
        if isinstance(value, float) and not math.isfinite(value):
            raise MarketDataError("nonfinite market JSON number")
        if isinstance(value, dict):
            stack.append(iter(value.values()))
        elif isinstance(value, list):
            stack.append(iter(value))
        if len(stack) > MAX_JSON_DEPTH:
            raise MarketDataError("market JSON exceeds nesting limit")
    return payload


def _validated(name: str, payload: object) -> Any | None:
    endpoint = "timeseries" if name.startswith("ts_") else name
    if payload is None:
        return None
    try:
        result = validate_payload(endpoint, payload, time.time())
    except MarketDataError as exc:
        print(f"  Warning: rejected market data ({exc})", file=sys.stderr)
        return None
    if result["rejected"]:
        print(f"  Warning: rejected {result['rejected']} invalid {endpoint} rows", file=sys.stderr)
    return result["data"] or None


def _quarantine_cache(path: Path, name: str) -> None:
    """One bounded evidence file per endpoint, replaced atomically."""
    endpoint = "timeseries" if name.startswith("ts_") else name
    target = path.parent / f".invalid-{endpoint}.json"
    try:
        with path.open("rb") as stream:
            raw = stream.read(64 * 1024)
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".invalid.tmp")
        try:
            try:
                stream = os.fdopen(fd, "wb")
            except BaseException:
                os.close(fd)
                raise
            with stream:
                stream.write(raw)
            os.replace(tmp, target)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    except OSError:
        pass


def _read_cache_payload(path: Path):
    """Read one inode through a bounded descriptor, including its mtime."""
    with path.open("rb") as stream:
        modified = os.fstat(stream.fileno()).st_mtime
        raw = stream.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise MarketDataError("market cache exceeds size limit")
    return _decode_market_json(raw), modified


def _load_cache(name: str, profile: str | None = None) -> Any | None:
    """Return only validated fresh cache; disappearance is an ordinary miss."""
    path = _cache_path(name, profile)
    try:
        data, _metadata, modified = _read_cache_record(name, profile)
    except FileNotFoundError:
        return None
    except (MarketDataError, UnicodeDecodeError, RecursionError, OSError):
        _quarantine_cache(path, name)
        _quarantine_cache(_provenance_path(name, profile), name+'.provenance')
        return None
    age = time.time() - modified
    if not 0 <= age < CACHE_MAX_AGE.get(name, 300):
        return None
    valid = _validated(name, data)
    if valid is None:
        _quarantine_cache(path, name)
    return {"data": valid} if name == "ge_tracker" and valid else valid


def _load_stale_cache(name: str, profile: str | None = None) -> Any | None:
    """Return validated stale cache only after providers have failed."""
    path = _cache_path(name, profile)
    try:
        data, _metadata, modified = _read_cache_record(name, profile)
        age = time.time() - modified
        if not 0 <= age < CACHE_MAX_AGE.get(name, 300) * STALE_MULTIPLIER:
            return None
        valid = _validated(name, data)
        if valid is None:
            _quarantine_cache(path, name)
            return None
        return {"data": valid} if name == "ge_tracker" else valid
    except FileNotFoundError:
        return None
    except (MarketDataError, UnicodeDecodeError, RecursionError, OSError):
        _quarantine_cache(path, name)
        _quarantine_cache(_provenance_path(name, profile), name+'.provenance')
        return None


def _save_cache(name: str, data: Any, profile: str | None = None) -> None:
    """Write cache atomically (temp file + rename) to avoid corruption on crash."""
    _atomic_json(_cache_path(name, profile), data)


def cleanup_stale_cache(profile: str | None = None) -> int:
    """Remove cache files older than 24h. Returns count removed."""
    cache_dir = resolve_cache_path("", profile)
    removed = 0
    for p in cache_dir.glob("*.json"):
        try:
            age = time.time() - p.stat().st_mtime
        except FileNotFoundError:
            continue
        if age > 86400:
            p.unlink()
            removed += 1
    return removed


def _coverage_count(data: Any) -> int:
    return len(data) if isinstance(data, (dict, list)) else 0


def _result(data: Any, metadata: dict, delivery: str, *, stale: bool = False) -> MarketDataResult:
    return MarketDataResult(data=data, source=metadata["source"], delivery=delivery,
                            fetched_at=metadata["fetched_at"],
                            last_attempt_at=metadata["last_attempt_at"],
                            last_success_at=metadata["last_success_at"], stale=stale,
                            volume_kind=metadata["volume_kind"],
                            coverage=dict(metadata["coverage"]))


def _cache_result(name: str, profile: str | None, *, stale: bool,
                  now: float | None = None) -> MarketDataResult | None:
    data = _load_stale_cache(name, profile) if stale else _load_cache(name, profile)
    if data is None:
        return None
    if name == "ge_tracker" and isinstance(data, dict) and "data" in data:
        data = data["data"]
    try:
        raw, metadata, modified = _read_cache_record(name, profile)
        age = time.time() - modified
        ttl = CACHE_MAX_AGE.get(name, 300) * (STALE_MULTIPLIER if stale else 1)
        if not 0 <= age < ttl: return None
        # Payload and metadata must come from the same validated snapshot, even
        # if a concurrent writer refreshed it after the compatibility read.
        data = _validated(name, raw)
        if data is None: return None
        stale = stale and age >= CACHE_MAX_AGE.get(name, 300)
    except (FileNotFoundError, MarketDataError, UnicodeDecodeError, RecursionError, OSError):
        return None
    if stale:
        attempted = time.time() if now is None else now
        metadata = dict(metadata)
        metadata["last_attempt_at"] = attempted
        # Failed attempt metadata belongs to this result only. Never rewrite a
        # sidecar after an unlocked read: it could overwrite a newer success.
        delivery = "stale-cache"
        print(f"  Note: using stale cache for '{name}' ({int(age)}s old)", file=sys.stderr)
    else:
        delivery = "fresh-cache"
    return _result(data, metadata, delivery, stale=stale)


def _fetch_result(name: str, profile: str | None, *, path: str,
                  tracker_convert=None, volume_kind: str = "unknown") -> MarketDataResult | None:
    """Acquire one validated endpoint in fresh-cache -> Wiki -> Tracker -> stale order."""
    attempted_at = time.time()
    cached = _cache_result(name, profile, stale=False, now=attempted_at)
    if cached is not None:
        return cached

    wiki_data = _validated(name, _get(path))
    if wiki_data:
        now = time.time()
        metadata = {"source": "wiki", "fetched_at": now, "last_attempt_at": attempted_at,
                    "last_success_at": now, "volume_kind": volume_kind,
                    "coverage": {"wiki": _coverage_count(wiki_data)}}
        _save_cache_result(name, wiki_data, profile, **metadata)
        return _result(wiki_data, metadata, "network")

    if tracker_convert is not None:
        _TRACKER_DELIVERY.value = None
        _TRACKER_DELIVERY.result = None
        dump = _get_ge_tracker(profile)
        tracker_delivery = getattr(_TRACKER_DELIVERY, "value", None) or "network"
        if dump is not None:
            converted = _validated(name, tracker_convert(dump))
            if converted:
                tracker_result = getattr(_TRACKER_DELIVERY, 'result', None)
                if tracker_result is not None and tracker_result.data == _ge_tracker_items(dump):
                    tracker_meta = {key: getattr(tracker_result, key) for key in
                        ('source', 'fetched_at', 'last_success_at')}
                else:
                    tracker_meta = {"source": "unknown", "fetched_at": None,
                                    "last_success_at": None}
                now = time.time()
                meta = {"source": tracker_meta["source"],
                        "fetched_at": tracker_meta["fetched_at"],
                        "last_attempt_at": attempted_at,
                        "last_success_at": tracker_meta["last_success_at"],
                        "volume_kind": ("standing-orders" if tracker_meta["source"] == "ge-tracker"
                                        and name in ("latest", "5m") else
                                        "unknown" if tracker_meta["source"] == "unknown" else volume_kind),
                        "coverage": {tracker_meta["source"]: _coverage_count(converted)}
                        if tracker_meta["source"] != "unknown" else {}}
                # Only metadata attached to this exact dump certifies source.
                delivery = tracker_delivery
                if delivery != "stale-cache":
                    _save_cache_result(name, converted, profile, **meta)
                print("  Note: OSRS Wiki unavailable; using GE Tracker fallback.", file=sys.stderr)
                return _result(converted, meta, delivery,
                               stale=delivery == "stale-cache")

    return _cache_result(name, profile, stale=True, now=time.time())


def fetch_mapping_result(profile: str | None = None) -> MarketDataResult | None:
    """Return item metadata with cache/provider provenance."""
    return _fetch_result("mapping", profile, path="mapping",
                         tracker_convert=_mapping_from_ge_tracker)


def fetch_latest_result(profile: str | None = None) -> MarketDataResult | None:
    """Return latest prices with provenance and explicit order-volume semantics."""
    return _fetch_result("latest", profile, path="latest",
                         tracker_convert=_latest_from_ge_tracker)


def fetch_5m_result(profile: str | None = None) -> MarketDataResult | None:
    """Return 5-minute prices and identify whether volume is trades or orders."""
    return _fetch_result("5m", profile, path="5m", tracker_convert=_5m_from_ge_tracker,
                         volume_kind="executed-trades")


def fetch_timeseries_result(item_id: int, timestep: str = "5m",
                            profile: str | None = None) -> MarketDataResult | None:
    """Return one Wiki history series with explicit provenance."""
    cache_name = f"ts_{item_id}_{timestep}"
    return _fetch_result(cache_name, profile,
                         path=f"timeseries?id={item_id}&timestep={timestep}",
                         volume_kind="executed-trades")


def fetch_mapping(profile: str | None = None) -> list[dict] | None:
    result = fetch_mapping_result(profile)
    return result.data if result is not None else None


def fetch_latest(profile: str | None = None) -> dict[str, dict] | None:
    result = fetch_latest_result(profile)
    return result.data if result is not None else None


def fetch_5m(profile: str | None = None) -> dict[str, dict] | None:
    result = fetch_5m_result(profile)
    return result.data if result is not None else None


def fetch_timeseries(item_id: int, timestep: str = "5m",
                     profile: str | None = None) -> list[dict] | None:
    result = fetch_timeseries_result(item_id, timestep, profile)
    return result.data if result is not None else None


def fetch_timeseries_batch(
    item_ids: list[int],
    timestep: str = "5m",
    on_progress=None,
    workers: int = 4,
    profile: str | None = None,
) -> dict[int, list[dict]]:
    """Fetch timeseries for multiple items in parallel.

    Uses ThreadPoolExecutor with a shared rate limiter.
    Returns {item_id: [datapoints...]}.
    on_progress: callable(current, total) for CLI progress display.
    workers: max concurrent fetches (default 4).
    """
    results: dict[int, list[dict]] = {}
    completed = 0
    total = len(item_ids)
    lock = threading.Lock()

    def fetch_one(item_id: int) -> tuple[int, list[dict] | None]:
        ts = fetch_timeseries(item_id, timestep, profile)
        return (item_id, ts)

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(fetch_one, iid): iid for iid in item_ids}
        for future in concurrent.futures.as_completed(futures):
            item_id, ts = future.result()
            if ts:
                with lock:
                    results[item_id] = ts
            with lock:
                completed += 1
                if on_progress:
                    on_progress(completed, total)
    return results


def fetch_timeseries_batch_results(item_ids, timestep='5m', on_progress=None,
                                  workers=4, profile=None):
    """Internal historical acquisition retaining evidence for each item."""
    from rshelper.market_data import market_payload
    results = {}
    completed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(fetch_timeseries_result, iid, timestep, profile):iid
                   for iid in item_ids}
        for future in concurrent.futures.as_completed(futures):
            value = market_payload(future.result(), sequence=True)
            if value:
                results[futures[future]] = value
            completed += 1
            if on_progress:
                on_progress(completed,len(item_ids))
    return results
