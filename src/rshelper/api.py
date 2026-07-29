"""OSRS Wiki Realtime Prices API client."""

import concurrent.futures
import json
import os
import sys
import tempfile
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

BASE_URL = "https://prices.runescape.wiki/api/v1/osrs"
USER_AGENT = "RSHelper/0.1 (rshelper@users.noreply.github.com)"
_LAST_REQUEST = 0.0
_THROTTLE_LOCK = threading.Lock()
CACHE_DIR = Path.home() / ".cache" / "rshelper"
CACHE_MAX_AGE = {
    "mapping": 86400,  # 24h — item metadata rarely changes
    "latest": 120,     # 2 min — prices update frequently
    "5m": 120,         # 2 min — volume data refreshes often
}
STALE_MULTIPLIER = 3  # serve stale cache up to 3x max_age if API fails

# Ensure cache dir exists at import time
CACHE_DIR.mkdir(exist_ok=True)


def _throttle() -> None:
    """Rate-limit to 1 req/sec per Wiki API policy. Thread-safe."""
    global _LAST_REQUEST
    with _THROTTLE_LOCK:
        elapsed = time.time() - _LAST_REQUEST
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)
        _LAST_REQUEST = time.time()


# Backoff config for retryable errors
MAX_RETRIES = 3
RETRY_DELAY = 2.0  # seconds, doubles each retry


def _get(path: str, retries: int = MAX_RETRIES) -> Any:
    """GET a Wiki API endpoint with retry+backoff, return parsed JSON."""
    last_exc = None
    for attempt in range(retries + 1):
        _throttle()
        req = urllib.request.Request(
            f"{BASE_URL}/{path}",
            headers={"User-Agent": USER_AGENT},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 503) and attempt < retries:
                delay = RETRY_DELAY * (2 ** attempt)
                print(f"  Retrying {path} in {delay:.0f}s (HTTP {exc.code}, attempt {attempt + 1}/{retries + 1})")
                time.sleep(delay)
                last_exc = exc
                continue
            print(f"  Warning: HTTP {exc.code} fetching {path}: {exc.reason}")
            return None
        except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
            if attempt < retries:
                delay = RETRY_DELAY * (2 ** attempt)
                print(f"  Retrying {path} in {delay:.0f}s ({type(exc).__name__}, attempt {attempt + 1}/{retries + 1})")
                time.sleep(delay)
                last_exc = exc
                continue
            print(f"  Warning: failed to fetch {path}: {exc}")
            return None
    return None


def _cache_path(name: str) -> Path:
    return CACHE_DIR / f"{name}.json"


def _load_cache(name: str) -> Any | None:
    """Load cached JSON. Returns data only if fresh (< max_age)."""
    p = _cache_path(name)
    if not p.exists():
        return None
    max_age = CACHE_MAX_AGE.get(name, 300)
    age = time.time() - p.stat().st_mtime
    try:
        data = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        p.unlink(missing_ok=True)
        return None
    if age < max_age:
        return data
    return None


def _load_stale_cache(name: str) -> Any | None:
    """Return stale cache data (within STALE_MULTIPLIER * max_age) when API fails."""
    p = _cache_path(name)
    if not p.exists():
        return None
    max_age = CACHE_MAX_AGE.get(name, 300)
    age = time.time() - p.stat().st_mtime
    if age >= max_age * STALE_MULTIPLIER:
        return None
    try:
        data = json.loads(p.read_text())
        print(f"  Note: using stale cache, file=sys.stderr) for '{name}' ({int(age)}s old)")
        return data
    except (json.JSONDecodeError, OSError):
        return None


def _save_cache(name: str, data: Any) -> None:
    """Write cache atomically (temp file + rename) to avoid corruption on crash."""
    target = _cache_path(name)
    fd, tmp_path = tempfile.mkstemp(dir=CACHE_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.replace(tmp_path, target)  # atomic on POSIX
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


def cleanup_stale_cache() -> int:
    """Remove cache files older than 24h. Returns count removed."""
    removed = 0
    for p in CACHE_DIR.glob("*.json"):
        try:
            age = time.time() - p.stat().st_mtime
        except FileNotFoundError:
            continue  # race: file deleted between glob and stat
        if age > 86400:
            p.unlink()
            removed += 1
    return removed


def fetch_mapping() -> list[dict] | None:
    """Fetch item ID -> metadata (name, buy limit, alch value, members)."""
    cached = _load_cache("mapping")
    if cached is not None:
        return cached
    data = _get("mapping")
    if data is not None:
        result = data.get("data", data) if isinstance(data, dict) else data
        _save_cache("mapping", result)
        return result
    return _load_stale_cache("mapping")


def fetch_latest() -> dict[str, dict] | None:
    """Fetch latest high/low prices keyed by item ID."""
    cached = _load_cache("latest")
    if cached is not None:
        return cached
    data = _get("latest")
    if data is not None:
        result = data.get("data", data)
        _save_cache("latest", result)
        return result
    return _load_stale_cache("latest")


def fetch_5m() -> dict[str, dict] | None:
    """Fetch 5-minute OHLC averages keyed by item ID."""
    cached = _load_cache("5m")
    if cached is not None:
        return cached
    data = _get("5m")
    if data is not None:
        result = data.get("data", data)
        _save_cache("5m", result)
        return result
    return _load_stale_cache("5m")


def fetch_timeseries(item_id: int, timestep: str = "5m") -> list[dict] | None:
    """Fetch historical OHLC data for a single item.

    timestep: '5m', '1h', '6h', '24h'
    Returns list of dicts with keys:
        timestamp, avgHighPrice, avgLowPrice, highPriceVolume, lowPriceVolume
    """
    cache_name = f"ts_{item_id}_{timestep}"
    cached = _load_cache(cache_name)
    if cached is not None:
        return cached
    data = _get(f"timeseries?id={item_id}&timestep={timestep}")
    if data and "data" in data:
        _save_cache(cache_name, data["data"])
        return data["data"]
    return _load_stale_cache(cache_name)


def fetch_timeseries_batch(
    item_ids: list[int],
    timestep: str = "5m",
    on_progress=None,
    workers: int = 4,
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
        ts = fetch_timeseries(item_id, timestep)
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
