"""Persistent alert feed: signals, watchlist triggers, trader exits, system."""

import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from rshelper.persistence import read_state, locked_state, StateCorruptionError, validate_state
from rshelper.profile import atomic_write_json, filter_fields, resolve_config_path

ALERTS_PATH = "alerts.json"
MAX_ALERTS = 200           # cap the persisted feed
PRUNE_AFTER_DAYS = 14      # drop alerts older than this on write
WATCH_DEDUPE_SEC = 15 * 60  # don't re-fire a watch threshold within 15 min

_ALERT_LOCK = threading.Lock()
_fallback_id = 0  # per-process monotonic ids when persistence fails


def _file_lock(profile: str | None = None):
    return locked_state(_alerts_path(profile))


@dataclass
class Alert:
    id: int
    ts: float          # epoch seconds
    type: str          # "signal" | "watch" | "trader" | "system"
    severity: str      # "HIGH" | "MEDIUM" | "LOW" | "INFO"
    item_id: int | None
    item_name: str
    title: str
    message: str
    read: bool = False
    data: dict | None = None


def _alerts_path(profile: str | None = None):
    if profile is None:
        profile = "default"
    return resolve_config_path(ALERTS_PATH, profile)


def _load(profile: str | None = None):
    return read_state(_alerts_path(profile), "alerts")


def _save(data: dict, profile: str | None = None) -> None:
    validate_state(data, "alerts", _alerts_path(profile))
    atomic_write_json(_alerts_path(profile), data)


def _next_alert_id(store: dict) -> int:
    """Next id: max of persisted ids + 1 (cross-process safe under the lock)."""
    ids = [a.get("id", 0) for a in store.get("alerts", []) if isinstance(a, dict)]
    return (max(ids) + 1) if ids else 1


def push_alert(type: str, severity: str, item_id: int | None,
               item_name: str, title: str, message: str,
               profile: str | None = None,
               data: dict | None = None) -> Alert:
    """Append an alert to the feed. Returns the created Alert.

    Caller-facing, thread-safe, atomic. A failure must never raise: alert
    delivery is best-effort for daemons and the dashboard.
    """
    try:
        with _file_lock(profile):
            store = _load(profile)
            alert = {
                "id": _next_alert_id(store),
                "ts": time.time(),
                "type": type,
                "severity": severity,
                "item_id": item_id,
                "item_name": item_name,
                "title": title,
                "message": message,
                "read": False,
                "data": data,
            }
            store["alerts"].append(alert)
            _prune(store)
            _save(store, profile)
        return Alert(**alert)
    except (OSError, StateCorruptionError) as exc:
        # Disk trouble must not break a trader/monitor cycle.
        import sys
        print(f"[alerts] warning: could not persist alert: {exc}", file=sys.stderr)
        return Alert(id=_next_id(), ts=time.time(), type=type, severity=severity,
                     item_id=item_id, item_name=item_name, title=title,
                     message=message, data=data)


def _next_id() -> int:
    """Per-process monotonic fallback id (only used when persistence fails)."""
    global _fallback_id
    _fallback_id += 1
    return _fallback_id


def _prune(store: dict) -> None:
    alerts = store.get("alerts", [])
    now = time.time()
    kept = []
    for a in alerts:
        try:
            ts = float(a.get("ts", 0))
        except (TypeError, ValueError):
            continue  # corrupt row: drop it rather than crash the caller
        if now - ts <= PRUNE_AFTER_DAYS * 86400:
            kept.append(a)
    store["alerts"] = kept[-MAX_ALERTS:]


def list_alerts(limit: int = 50, profile: str | None = None) -> list[Alert]:
    """Newest-first alert feed, capped at `limit`."""
    store = _load(profile)
    alerts = [Alert(**filter_fields(Alert, a)) for a in store.get("alerts", []) if isinstance(a, dict)]
    alerts.sort(key=lambda a: a.ts, reverse=True)
    return alerts[:limit]


def unread_count(profile: str | None = None) -> int:
    return sum(1 for a in list_alerts(limit=MAX_ALERTS, profile=profile)
               if not a.read)


def mark_read(ids: list[int] | None = None, all: bool = False,
              profile: str | None = None) -> int:
    """Mark alerts read. Returns how many were changed.

    ids=None + all=True marks everything; ids=None + all=False is a no-op.
    """
    with _file_lock(profile):
        store = _load(profile)
        changed = 0
        if all:
            for a in store.get("alerts", []):
                if not a.get("read"):
                    a["read"] = True
                    changed += 1
        elif ids:
            id_set = set(ids)
            for a in store.get("alerts", []):
                if a.get("id") in id_set and not a.get("read"):
                    a["read"] = True
                    changed += 1
        if changed:
            _save(store, profile)
        return changed


def watch_triggered(item_id: int, profile: str | None = None) -> bool:
    """True if the item's threshold alert is still in its dedupe window."""
    store = _load(profile)
    last = store.get("watch_triggered", {}).get(str(item_id), 0)
    return time.time() - float(last) < WATCH_DEDUPE_SEC


def set_watch_triggered(item_id: int, profile: str | None = None) -> None:
    """Record the moment a watch threshold fired (dedupe window)."""
    with _file_lock(profile):
        store = _load(profile)
        store.setdefault("watch_triggered", {})[str(item_id)] = time.time()
        _save(store, profile)


def update_watch_alerts(item_id: int, above: int | None, below: int | None,
                        profile: str | None = None) -> None:
    """Update (or clear) a watched item's margin alert thresholds.

    A clean add/update: preserves the existing name + added timestamp,
    and clears a previous dedupe so a newly-set threshold can fire.
    """
    from rshelper import watchlist
    with watchlist._watchlist_lock(profile):
        data = watchlist.load(profile)
        entry = data.get("items", {}).get(str(item_id))
        if entry is None:
            raise ValueError(f"item {item_id} is not on the watchlist")
        entry["alert_margin_above"] = above
        entry["alert_margin_below"] = below
        watchlist._save(data, profile)
    with _file_lock(profile):
        store = _load(profile)
        store.setdefault("watch_triggered", {}).pop(str(item_id), None)
        _save(store, profile)
