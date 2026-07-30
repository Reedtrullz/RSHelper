"""Watchlist state file — JSON-backed, atomic writes."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from rshelper.profile import resolve_config_path

WATCHLIST_PATH = Path.home() / ".config" / "rshelper" / "watchlist.json"


def _watchlist_path(profile: str | None = None) -> Path:
    if profile is None:
        profile = "default"
    if profile == "default":
        return WATCHLIST_PATH
    return resolve_config_path("watchlist.json", profile)


def load(profile: str | None = None) -> dict:
    """Load watchlist, returning default empty if missing or corrupt."""
    path = _watchlist_path(profile)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        return json.loads(path.read_text()) if path.exists() else {"items": {}}
    except json.JSONDecodeError:
        return {"items": {}}


def _save(data: dict, profile: str | None = None) -> None:
    """Atomic write: temp file + rename."""
    path = _watchlist_path(profile)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)


def add(item_id: int, name: str,
        alert_margin_above: int | None = None,
        alert_margin_below: int | None = None,
        profile: str | None = None) -> None:
    """Add or update a watched item."""
    data = load(profile)
    data["items"][str(item_id)] = {
        "name": name,
        "added": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "alert_margin_above": alert_margin_above,
        "alert_margin_below": alert_margin_below,
    }
    _save(data, profile)


def remove(item_id: int, profile: str | None = None) -> bool:
    """Remove a watched item. Returns True if it existed."""
    data = load(profile)
    popped = data["items"].pop(str(item_id), None)
    if popped is not None:
        _save(data, profile)
    return popped is not None


def list_all(profile: str | None = None) -> list[dict]:
    """Return all watched items as a list of dicts."""
    return list(load(profile)["items"].values())


def get_watched_ids(profile: str | None = None) -> list[int]:
    """Return list of watched item IDs."""
    return [int(k) for k in load(profile)["items"]]
