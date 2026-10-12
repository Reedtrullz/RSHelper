"""Persistent alert feed: signals, watchlist triggers, trader exits, system."""

import json
import hashlib
import math
import os
import threading
import time
from uuid import uuid4
from dataclasses import dataclass
from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone

from rshelper.persistence import (read_state, locked_writable_state, locked_state,
    StateCorruptionError, validate_state, validate_writable_state, validate_watch_policy)
from rshelper import state_identity, state_transaction
from rshelper.profile import atomic_write_json, filter_fields, resolve_config_path

ALERTS_PATH = "alerts.json"
MAX_ALERTS = 200           # cap the persisted feed
PRUNE_AFTER_DAYS = 14      # drop alerts older than this on write
WATCH_DEDUPE_SEC = 15 * 60  # don't re-fire a watch threshold within 15 min

_ALERT_LOCK = threading.Lock()
_fallback_id = 0  # per-process monotonic ids when persistence fails


@contextmanager
def _file_lock(profile: str | None = None):
    path = _alerts_path(profile)
    with state_transaction.profile_transaction(profile or 'default', path.parent):
        if state_identity.activation_manifest(path.with_name('identity-activation.json')) is not None:
            yield
        else:
            with locked_writable_state(path, 'alerts'):
                yield


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
    record_uuid: str | None = None
    origin_uuid: str | None = None
    revision: int | None = None


def _alerts_path(profile: str | None = None):
    if profile is None:
        profile = "default"
    return resolve_config_path(ALERTS_PATH, profile)


def _load(profile: str | None = None):
    path = _alerts_path(profile)
    return state_identity.validate_activated_store(read_state(path, 'alerts'), 'alerts', path)


def _save(data: dict, profile: str | None = None) -> None:
    validate_state(data, "alerts", _alerts_path(profile))
    path = _alerts_path(profile)
    if state_identity.activation_manifest(path.with_name('identity-activation.json')) is not None:
        with state_transaction.profile_transaction(profile or 'default', path.parent) as txn:
            txn.stage('alerts.json', data)
            txn.commit(str(uuid4()))
        return
    atomic_write_json(_alerts_path(profile), data)


def _next_alert_id(store: dict) -> int:
    """Next id: max of persisted ids + 1 (cross-process safe under the lock)."""
    ids = [a.get("id", 0) for a in store.get("alerts", []) if isinstance(a, dict)]
    return (max(ids) + 1) if ids else 1


def push_alert(type: str, severity: str, item_id: int | None,
               item_name: str, title: str, message: str,
               profile: str | None = None,
               data: dict | None = None,
               operation_id: str | None = None) -> Alert:
    """Append an alert to the feed. Returns the created Alert.

    Caller-facing, thread-safe, atomic. A failure must never raise: alert
    delivery is best-effort for daemons and the dashboard. Identified
    profiles mint a native identity per operation; callers supply
    operation_id so retries reuse the same identity.
    """
    try:
        path = _alerts_path(profile)
        manifest = state_identity.activation_manifest(path.with_name('identity-activation.json'))
    except (OSError, ValueError) as exc:
        return _fallback_alert(type, severity, item_id, item_name, title, message, data, exc)
    if manifest is not None:
        try:
            operation_id = operation_id or str(uuid4())
            request = dict(type=type, severity=severity, item_id=item_id,
                           item_name=item_name, title=title, message=message, data=data)
            identity = state_identity.new_record_identity(
                manifest['origin_uuid'], 'alerts', operation_id)
            with state_transaction.profile_transaction(profile or 'default',
                                                       path.parent) as txn:
                store = _load(profile)
                for row in store['alerts']:
                    if row.get('record_uuid') == identity['record_uuid']:
                        state_identity.validate_native_retry(path.parent, 'alerts', row, request)
                        return Alert(**filter_fields(Alert, row))
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
                    **identity,
                }
                store["alerts"].append(alert)
                state_identity.attest_native(txn, path.parent, 'alerts', alert, operation_id, request)
                _prune(store)
                txn.stage('alerts.json', store)
                txn.commit(operation_id=operation_id)
            return Alert(**filter_fields(Alert, alert))
        except (OSError, StateCorruptionError, ValueError) as exc:
            return _fallback_alert(type, severity, item_id, item_name, title, message, data, exc)
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
    except (OSError, StateCorruptionError, ValueError) as exc:
        return _fallback_alert(type, severity, item_id, item_name, title, message, data, exc)


def _fallback_alert(type, severity, item_id, item_name, title, message, data, error):
    import sys
    print(f"[alerts] warning: could not persist alert: {error}", file=sys.stderr)
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
    if any('record_uuid' in row for row in alerts):
        active = [row for row in alerts if not row.get('tombstone')
                  and now - row['ts'] <= PRUNE_AFTER_DAYS * 86400][-MAX_ALERTS:]
        retained = {row['record_uuid'] for row in active}
        for row in alerts:
            if not row.get('tombstone') and row['record_uuid'] not in retained:
                row.update(tombstone=True, revision=row['revision'] + 1)
        return
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
    alerts = [Alert(**filter_fields(Alert, a)) for a in store.get("alerts", [])
              if isinstance(a, dict) and not a.get('tombstone', False)]
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
                if not a.get('tombstone') and not a.get("read"):
                    a["read"] = True
                    if 'record_uuid' in a:
                        a['revision'] = a.get('revision', 0) + 1
                    changed += 1
        elif ids:
            id_set = set(ids)
            for a in store.get("alerts", []):
                if not a.get('tombstone') and a.get("id") in id_set and not a.get("read"):
                    a["read"] = True
                    if 'record_uuid' in a:
                        a['revision'] = a.get('revision', 0) + 1
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
                        profile: str | None = None, *, policy=None) -> None:
    """Update (or clear) a watched item's margin alert thresholds.

    A clean add/update: preserves the existing name + added timestamp,
    and clears a previous dedupe so a newly-set threshold can fire.
    """
    from rshelper import watchlist
    if policy is not None:
        policy = _watch_policy(policy)
    if any(value is not None and type(value) is not int for value in (above, below)):
        raise ValueError('watch thresholds must be integers')
    with _watch_transaction(profile) as txn:
        data = watchlist.load(profile)
        store = _load(profile)
        entry = data.get("items", {}).get(str(item_id))
        if entry is None:
            raise ValueError(f"item {item_id} is not on the watchlist")
        entry["alert_margin_above"] = above
        entry["alert_margin_below"] = below
        if 'record_uuid' in entry:
            entry['revision'] += 1
        entry['alert_rule_revision'] = entry.get('alert_rule_revision', 0) + 1
        if policy is not None:
            entry['alert_policy'] = policy
        store.setdefault("watch_triggered", {}).pop(str(item_id), None)
        store.setdefault('watch_crossings', {}).pop(str(item_id), None)
        txn.stage('watchlist.json', data)
        txn.stage('alerts.json', store)
        txn.commit(str(uuid4()))


def _watch_policy(policy):
    policy = dict({'mode': 'crossing', 'cooldown_sec': WATCH_DEDUPE_SEC, 'hysteresis_gp': 0}
                  if policy is None else policy)
    return validate_watch_policy(policy)


@contextmanager
def _watch_transaction(profile):
    from rshelper import watchlist
    paths = tuple(path.resolve() for path in (_alerts_path(profile), watchlist._watchlist_path(profile)))
    if paths[0].parent != paths[1].parent:
        raise ValueError('watch and alert profile roots differ')
    with state_transaction.profile_transaction(profile or 'default', paths[0].parent) as txn:
        with ExitStack() as locks:
            for path, kind in sorted(zip(paths, ('alerts', 'watchlist'))):
                locks.enter_context(locked_state(path))
                if state_identity.activation_manifest(path.with_name('identity-activation.json')) is None:
                    validate_writable_state(read_state(path, kind), kind, path)
            yield txn


def emit_watch_if_due(profile, item_id, margin, *, now=None, source_revision='', notify_fn=None):
    """Commit the rule observation and event together; delivery follows commit."""
    from rshelper import watchlist
    from rshelper.identity_merge import canonical_record
    now = time.time() if now is None else now
    if (type(item_id) is not int or item_id <= 0 or type(margin) is not int
            or type(now) not in (int, float) or not math.isfinite(now) or now < 0
            or not isinstance(source_revision, (str, int)) or len(str(source_revision)) > 128):
        raise ValueError('invalid watch observation')
    key, event = str(item_id), None
    with _watch_transaction(profile) as txn:
        entry = watchlist.load(profile)['items'].get(key)
        if entry is None:
            return None
        policy = _watch_policy(entry.get('alert_policy'))
        above, below = entry.get('alert_margin_above'), entry.get('alert_margin_below')
        if above is None and below is None:
            return None
        rule = hashlib.sha256(json.dumps([entry.get('record_uuid'), canonical_record(entry, 'watchlist').get('added'), entry.get('alert_rule_revision', 0),
            above, below, policy], sort_keys=True).encode()).hexdigest()
        store = _load(profile)
        previous = store.setdefault('watch_crossings', {}).get(key, {})
        same_rule = previous.get('rule') == rule
        side = ('above' if above is not None and margin > above else
                'below' if below is not None and margin < below else '')
        breached = bool(side)
        hysteresis = policy['hysteresis_gp']
        if not side and same_rule:
            if previous.get('side') == 'above' and above is not None and margin > above-hysteresis:
                side = 'above'
            elif previous.get('side') == 'below' and below is not None and margin < below+hysteresis:
                side = 'below'
        fired = same_rule and previous.get('side') == side and previous.get('fired', False)
        last = store.get('watch_triggered', {}).get(key)
        due = last is None or now-last >= policy['cooldown_sec']
        observation = {'rule': rule, 'side': side, 'fired': bool(fired), 'observed_at': now,
                       'revision': previous.get('revision', 0) + 1,
                       'source_revision': str(source_revision),
                       'notification_status': previous.get('notification_status', 'not-requested'),
                       'event_id': previous.get('event_id')}
        if breached and due and (policy['mode'] == 'reminder' or not fired):
            operation = str(uuid4())
            request = dict(type='watch', severity='HIGH', item_id=item_id,
                item_name=entry.get('name', key), title='Watchlist alert',
                message=f"{entry.get('name', key)}: margin {margin:,} gp {side} {above if side == 'above' else below:,}",
                data={'margin': margin, 'mode': policy['mode'], 'source_revision': str(source_revision)})
            row = dict(request, id=_next_alert_id(store), ts=now, read=False)
            root = _alerts_path(profile).parent
            manifest = state_identity.activation_manifest(root/'identity-activation.json')
            if manifest is not None:
                row.update(state_identity.new_record_identity(manifest['origin_uuid'], 'alerts', operation))
                state_identity.attest_native(txn, root, 'alerts', row, operation, request)
            store['alerts'].append(row)
            store.setdefault('watch_triggered', {})[key] = now
            observation.update(fired=True, event_id=operation,
                               notification_status='pending' if notify_fn else 'not-requested')
            event = Alert(**filter_fields(Alert, row))
            _prune(store)
        store['watch_crossings'][key] = observation
        txn.stage('alerts.json', store)
        txn.commit(str(uuid4()))
    if event is not None and notify_fn is not None:
        try:
            delivered = notify_fn(event.title, event.message) is not False
        except Exception:
            delivered = False
        with _watch_transaction(profile) as txn:
            store = _load(profile)
            current = store.get('watch_crossings', {}).get(key)
            if current and current['event_id'] == observation['event_id']:
                current['notification_status'] = 'sent' if delivered else 'failed'
                current['revision'] += 1
                txn.stage('alerts.json', store)
                txn.commit(str(uuid4()))
    return event
