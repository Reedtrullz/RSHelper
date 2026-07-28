"""OSRS Wiki Realtime Prices API client."""

import json
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

BASE_URL = "https://prices.runescape.wiki/api/v1/osrs"
USER_AGENT = "RSHelper/0.1 (rshelper@users.noreply.github.com)"
_LAST_REQUEST = 0.0


def _throttle() -> None:
    """Rate-limit to 1 req/sec per Wiki API policy."""
    global _LAST_REQUEST
    elapsed = time.time() - _LAST_REQUEST
    if elapsed < 1.0:
        time.sleep(1.0 - elapsed)
    _LAST_REQUEST = time.time()


def _get(path: str) -> Any:
    """GET a Wiki API endpoint, return parsed JSON."""
    _throttle()
    req = urllib.request.Request(
        f"{BASE_URL}/{path}",
        headers={"User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f"  Warning: failed to fetch {path}: {exc}")
        return None


def _cache_path(name: str) -> Path:
    return Path(f"/tmp/rshelper_{name}.json")


def _load_cache(name: str, max_age: int = 300) -> Any | None:
    """Load cached JSON if fresher than max_age seconds."""
    p = _cache_path(name)
    if p.exists() and (time.time() - p.stat().st_mtime) < max_age:
        return json.loads(p.read_text())
    return None


def _save_cache(name: str, data: Any) -> None:
    _cache_path(name).write_text(json.dumps(data))


def fetch_mapping() -> list[dict] | None:
    """Fetch item ID -> metadata (name, buy limit, alch value, members)."""
    cached = _load_cache("mapping", max_age=86400)  # cache 24h
    if cached is not None:
        return cached
    data = _get("mapping")
    if data is not None:
        _save_cache("mapping", data)
    return data


def fetch_latest() -> dict[str, dict] | None:
    """Fetch latest high/low prices keyed by item ID."""
    cached = _load_cache("latest", max_age=60)
    if cached is not None:
        return cached
    data = _get("latest")
    if data is not None:
        result = data.get("data", data)
        _save_cache("latest", result)
        return result
    return None


def fetch_5m() -> dict[str, dict] | None:
    """Fetch 5-minute OHLC averages keyed by item ID."""
    cached = _load_cache("5m", max_age=60)
    if cached is not None:
        return cached
    data = _get("5m")
    if data is not None:
        result = data.get("data", data)
        _save_cache("5m", result)
        return result
    return None
