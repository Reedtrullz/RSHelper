"""Watchlist state file — JSON-backed, atomic writes."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

WATCHLIST_PATH = Path.home() / ".config" / "rshelper" / "watchlist.json"


def _ensure_dir() -> None:
    WATCHLIST_PATH.parent.mkdir(parents=True, exist_ok=True)


def load() -> dict:
    """Load watchlist, returning default empty if missing or corrupt."""
    _ensure_dir()
    try:
        return json.loads(WATCHLIST_PATH.read_text()) if WATCHLIST_PATH.exists() else {"items": {}}
    except json.JSONDecodeError:
        return {"items": {}}


def _save(data: dict) -> None:
    """Atomic write: temp file + rename."""
    _ensure_dir()
    tmp = WATCHLIST_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, WATCHLIST_PATH)


def add(item_id: int, name: str,
        alert_margin_above: int | None = None,
        alert_margin_below: int | None = None) -> None:
    """Add or update a watched item."""
    data = load()
    data["items"][str(item_id)] = {
        "name": name,
        "added": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "alert_margin_above": alert_margin_above,
        "alert_margin_below": alert_margin_below,
    }
    _save(data)


def remove(item_id: int) -> bool:
    """Remove a watched item. Returns True if it existed."""
    data = load()
    popped = data["items"].pop(str(item_id), None)
    if popped is not None:
        _save(data)
    return popped is not None


def list_all() -> list[dict]:
    """Return all watched items as a list of dicts."""
    return list(load()["items"].values())


def get_watched_ids() -> list[int]:
    """Return list of watched item IDs."""
    return [int(k) for k in load()["items"]]
