"""OSRS GE price clients: OSRS Wiki Realtime Prices API, with a GE Tracker
fallback for datacenter IPs that the wiki's Cloudflare blocks (403)."""

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

from rshelper.profile import resolve_cache_path

BASE_URL = "https://prices.runescape.wiki/api/v1/osrs"
GE_TRACKER_URL = "https://www.ge-tracker.com/api/items"
USER_AGENT = "RSHelper/1.6 (+https://rs.reidar.tech; reed@reidar.tech)"
_LAST_REQUEST = 0.0
_THROTTLE_LOCK = threading.Lock()
CACHE_DIR = Path.home() / ".cache" / "rshelper"
CACHE_MAX_AGE = {
    "mapping": 86400,  # 24h — item metadata rarely changes
    "latest": 120,     # 2 min — prices update frequently
    "5m": 120,         # 2 min — volume data refreshes often
    "ge_tracker": 300,  # 5 min — full GE Tracker dump; one fetch per cycle
}
STALE_MULTIPLIER = 3  # serve stale cache up to 3x max_age if API fails

# Ensure cache dir exists at import time (parents for fresh HOMEs)
CACHE_DIR.mkdir(parents=True, exist_ok=True)


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


def _fetch_url(url: str, retries: int = MAX_RETRIES) -> Any:
    """GET url with retry+backoff, return parsed JSON (None on failure)."""
    last_exc = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 503) and attempt < retries:
                delay = RETRY_DELAY * (2 ** attempt)
                print(f"  Retrying {url} in {delay:.0f}s (HTTP {exc.code}, attempt {attempt + 1}/{retries + 1})")
                time.sleep(delay)
                last_exc = exc
                continue
            print(f"  Warning: HTTP {exc.code} fetching {url}: {exc.reason}")
            return None
        except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
            if attempt < retries:
                delay = RETRY_DELAY * (2 ** attempt)
                print(f"  Retrying {url} in {delay:.0f}s ({type(exc).__name__}, attempt {attempt + 1}/{retries + 1})")
                time.sleep(delay)
                last_exc = exc
                continue
            print(f"  Warning: failed to fetch {url}: {exc}")
            return None
    return None


def _get(path: str, retries: int = MAX_RETRIES) -> Any:
    """GET a Wiki API endpoint with retry+backoff, return parsed JSON."""
    _throttle()  # retries sleep RETRY_DELAY*2^n below, so no re-throttle
    return _fetch_url(f"{BASE_URL}/{path}", retries)


def _get_ge_tracker(profile: str | None = None) -> Any | None:
    """Fetch the GE Tracker all-items dump (undocumented, no auth), cached."""
    cached = _load_cache("ge_tracker", profile)
    if cached is not None:
        return cached
    _throttle()
    data = _fetch_url(GE_TRACKER_URL)
    if data is not None:
        _save_cache("ge_tracker", data, profile)
        return data
    return _load_stale_cache("ge_tracker", profile)


def _ge_tracker_items(dump: Any) -> list[dict]:
    items = dump.get("data", dump) if isinstance(dump, dict) else dump
    return items if isinstance(items, list) else []


def _mapping_from_ge_tracker(dump: Any) -> list[dict]:
    """GE Tracker item rows -> wiki-shaped mapping entries."""
    return [
        {
            "id": e["itemId"],
            "name": e["name"],
            "members": e["members"],
            "limit": e["buyLimit"],
            "highalch": e["highAlch"],
            "lowalch": e["lowAlch"],
        }
        for e in _ge_tracker_items(dump)
    ]


def _latest_from_ge_tracker(dump: Any) -> dict[str, dict]:
    """GE Tracker buying/selling -> wiki-shaped latest prices keyed by item ID."""
    return {
        str(e["itemId"]): {"high": e["buying"], "low": e["selling"]}
        for e in _ge_tracker_items(dump)
    }


def _5m_from_ge_tracker(dump: Any) -> dict[str, dict]:
    # ponytail: GE Tracker has no 5m trade volume; use its current order
    # quantities as a relative volume proxy so scans have something to rank.
    # Real 5m trade volume is wiki-only.
    return {
        str(e["itemId"]): {
            "highPriceVolume": e["buyingQuantity"],
            "lowPriceVolume": e["sellingQuantity"],
        }
        for e in _ge_tracker_items(dump)
    }


def _cache_path(name: str, profile: str | None = None) -> Path:
    return resolve_cache_path(name + ".json", profile)


def _load_cache(name: str, profile: str | None = None) -> Any | None:
    """Load cached JSON. Returns data only if fresh (< max_age)."""
    p = _cache_path(name, profile)
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


def _load_stale_cache(name: str, profile: str | None = None) -> Any | None:
    """Return stale cache data (within STALE_MULTIPLIER * max_age) when API fails."""
    p = _cache_path(name, profile)
    if not p.exists():
        return None
    max_age = CACHE_MAX_AGE.get(name, 300)
    age = time.time() - p.stat().st_mtime
    if age >= max_age * STALE_MULTIPLIER:
        return None
    try:
        data = json.loads(p.read_text())
        print(f"  Note: using stale cache for '{name}' ({int(age)}s old)", file=sys.stderr)
        return data
    except (json.JSONDecodeError, OSError):
        return None


def _save_cache(name: str, data: Any, profile: str | None = None) -> None:
    """Write cache atomically (temp file + rename) to avoid corruption on crash."""
    target = _cache_path(name, profile)
    cache_dir = target.parent
    cache_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=cache_dir, suffix=".tmp")
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


def fetch_mapping(profile: str | None = None) -> list[dict] | None:
    """Fetch item ID -> metadata (name, buy limit, alch value, members).

    Wiki first; falls back to the GE Tracker dump when the wiki is
    unreachable (e.g. Cloudflare 403 from datacenter IPs).
    """
    cached = _load_cache("mapping", profile)
    if cached is not None:
        return cached
    data = _get("mapping")
    if data is not None:
        result = data.get("data", data) if isinstance(data, dict) else data
        _save_cache("mapping", result, profile)
        return result
    dump = _get_ge_tracker(profile)
    if dump is not None:
        print("  Note: OSRS Wiki unavailable; using GE Tracker fallback.", file=sys.stderr)
        result = _mapping_from_ge_tracker(dump)
        _save_cache("mapping", result, profile)
        return result
    return _load_stale_cache("mapping", profile)


def fetch_latest(profile: str | None = None) -> dict[str, dict] | None:
    """Fetch latest high/low prices keyed by item ID (wiki, GE Tracker fallback)."""
    cached = _load_cache("latest", profile)
    if cached is not None:
        return cached
    data = _get("latest")
    if data is not None:
        result = data.get("data", data)
        _save_cache("latest", result, profile)
        return result
    dump = _get_ge_tracker(profile)
    if dump is not None:
        result = _latest_from_ge_tracker(dump)
        _save_cache("latest", result, profile)
        return result
    return _load_stale_cache("latest", profile)


def fetch_5m(profile: str | None = None) -> dict[str, dict] | None:
    """Fetch 5-minute OHLC averages keyed by item ID (wiki, GE Tracker fallback)."""
    cached = _load_cache("5m", profile)
    if cached is not None:
        return cached
    data = _get("5m")
    if data is not None:
        result = data.get("data", data)
        _save_cache("5m", result, profile)
        return result
    dump = _get_ge_tracker(profile)
    if dump is not None:
        result = _5m_from_ge_tracker(dump)
        _save_cache("5m", result, profile)
        return result
    return _load_stale_cache("5m", profile)


def fetch_timeseries(item_id: int, timestep: str = "5m", profile: str | None = None) -> list[dict] | None:
    """Fetch historical OHLC data for a single item.

    timestep: '5m', '1h', '6h', '24h'
    Returns list of dicts with keys:
        timestamp, avgHighPrice, avgLowPrice, highPriceVolume, lowPriceVolume
    """
    cache_name = f"ts_{item_id}_{timestep}"
    cached = _load_cache(cache_name, profile)
    if cached is not None:
        return cached
    data = _get(f"timeseries?id={item_id}&timestep={timestep}")
    if data and "data" in data:
        _save_cache(cache_name, data["data"], profile)
        return data["data"]
    return _load_stale_cache(cache_name, profile)


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
