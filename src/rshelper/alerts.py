"""Persistent alert feed: signals, watchlist triggers, trader exits, system."""

import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from rshelper.profile import atomic_write_json, resolve_config_path

ALERTS_PATH = "alerts.json"
MAX_ALERTS = 200           # cap the persisted feed
PRUNE_AFTER_DAYS = 14      # drop alerts older than this on write
WATCH_DEDUPE_SEC = 15 * 60  # don't re-fire a watch threshold within 15 min

_ALERT_LOCK = threading.Lock()
_next_id = 1  # per-process monotonic fallback for in-memory ids


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


def _load(profile: str | None = None) -> dict:
    path = _alerts_path(profile)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if path.exists():
            data = json.loads(path.read_text())
            if isinstance(data, dict) and isinstance(data.get("alerts"), list):
                return data
    except (json.JSONDecodeError, OSError):
        pass
    return {"alerts": [], "watch_triggered": {}}


def _save(data: dict, profile: str | None = None) -> None:
    atomic_write_json(_alerts_path(profile), data)


def push_alert(type: str, severity: str, item_id: int | None,
               item_name: str, title: str, message: str,
               profile: str | None = None,
               data: dict | None = None) -> Alert:
    """Append an alert to the feed. Returns the created Alert.

    Caller-facing, thread-safe, atomic. A failure must never raise: alert
    delivery is best-effort for daemons and the dashboard.
    """
    global _next_id
    try:
        with _ALERT_LOCK:
            store = _load(profile)
            _next_id += 1
            alert = {
                "id": _next_id,
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
    except OSError as exc:
        # Disk trouble must not break a trader/monitor cycle.
        import sys
        print(f"[alerts] warning: could not persist alert: {exc}", file=sys.stderr)
        _next_id += 1
        return Alert(id=_next_id, ts=time.time(), type=type, severity=severity,
                     item_id=item_id, item_name=item_name, title=title,
                     message=message, data=data)


def _prune(store: dict) -> None:
    alerts = store.get("alerts", [])
    now = time.time()
    alerts = [a for a in alerts
              if now - float(a.get("ts", 0)) <= PRUNE_AFTER_DAYS * 86400]
    store["alerts"] = alerts[-MAX_ALERTS:]


def list_alerts(limit: int = 50, profile: str | None = None) -> list[Alert]:
    """Newest-first alert feed, capped at `limit`."""
    store = _load(profile)
    alerts = [Alert(**a) for a in store.get("alerts", []) if isinstance(a, dict)]
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
    with _ALERT_LOCK:
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
    with _ALERT_LOCK:
        store = _load(profile)
        store.setdefault("watch_triggered", {})[str(item_id)] = time.time()
        _save(store, profile)
