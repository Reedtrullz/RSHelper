"""Watchlist state file — JSON-backed, atomic writes."""

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4
from contextlib import contextmanager

from rshelper.persistence import read_state, locked_writable_state, StateCorruptionError, validate_state, validate_watch_policy
from rshelper.profile import atomic_write_json, resolve_config_path
from rshelper import state_identity, state_transaction

WATCHLIST_PATH = Path.home() / ".config" / "rshelper" / "watchlist.json"


def _watchlist_path(profile: str | None = None) -> Path:
    if profile is None:
        profile = "default"
    if profile == "default":
        return WATCHLIST_PATH
    return resolve_config_path("watchlist.json", profile)


@contextmanager
def _watchlist_lock(profile: str | None = None):
    path = _watchlist_path(profile)
    with state_transaction.profile_transaction(profile or 'default', path.parent):
        if state_identity.activation_manifest(path.with_name('identity-activation.json')) is not None:
            yield
        else:
            with locked_writable_state(path, 'watchlist'):
                yield


def load(profile: str | None = None):
    path = _watchlist_path(profile)
    return state_identity.validate_activated_store(read_state(path, 'watchlist'), 'watchlist', path)


def _save(data: dict, profile: str | None = None) -> None:
    """Atomic write: temp file + rename."""
    validate_state(data, "watchlist", _watchlist_path(profile))
    path = _watchlist_path(profile)
    if state_identity.activation_manifest(path.with_name('identity-activation.json')) is not None:
        with state_transaction.profile_transaction(profile or 'default', path.parent) as txn:
            txn.stage('watchlist.json', data)
            txn.commit(str(uuid4()))
        return
    atomic_write_json(_watchlist_path(profile), data, indent=2)


def _stage_alert_policy(txn, row, policy, profile):
    if policy is None:
        return
    from rshelper import alerts
    row['alert_policy'] = policy
    row['alert_rule_revision'] = row.get('alert_rule_revision', 0) + 1
    store = alerts._load(profile)
    key = str(row.get('item_id'))
    store.setdefault('watch_triggered', {}).pop(key, None)
    store.setdefault('watch_crossings', {}).pop(key, None)
    txn.stage('alerts.json', store)


def add(item_id: int, name: str,
        alert_margin_above: int | None = None,
        alert_margin_below: int | None = None,
        profile: str | None = None,
        operation_id: str | None = None, *, alert_policy=None) -> None:
    """Add or update a watched item.

    Re-adding an existing item preserves its original added timestamp so
    the UI doesn't claim a long-watched item was just added. Existing alert
    thresholds are preserved when the caller does not specify new ones
    (e.g. watch add after watch remove) — only an explicit None clears.
    Identified profiles mint a fresh record identity per creation generation;
    a re-add after remove is a new record and the old one stays tombstoned.
    """
    if alert_policy is not None:
        alert_policy = validate_watch_policy(alert_policy)
    path = _watchlist_path(profile)
    manifest = state_identity.activation_manifest(
        path.with_name('identity-activation.json'))
    if manifest is not None:
        operation_id = operation_id or str(uuid4())
        identity = state_identity.new_record_identity(
            manifest['origin_uuid'], 'watchlist', operation_id)
        with state_transaction.profile_transaction(profile or 'default',
                                                   path.parent) as txn:
            data = load(profile)
            existing = data["items"].get(str(item_id))
            if existing is not None:
                identity = {key: existing[key] for key in ('record_uuid', 'origin_uuid', 'revision', 'tombstone')}
            elif identity['record_uuid'] in data.get('tombstones', {}):
                raise ValueError('creation retry cannot resurrect a removed watch')
            added = existing.get("added") if existing else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            if alert_margin_above is None and existing is not None:
                alert_margin_above = existing.get("alert_margin_above")
            if alert_margin_below is None and existing is not None:
                alert_margin_below = existing.get("alert_margin_below")
            row = {
                **(existing or {}),
                "name": name, "added": added, "item_id": int(item_id),
                "alert_margin_above": alert_margin_above,
                "alert_margin_below": alert_margin_below,
                **identity,
            }
            _stage_alert_policy(txn, row, alert_policy, profile)
            if existing == row:
                return
            if existing is not None:
                row['revision'] += 1
            else:
                state_identity.attest_native(txn, path.parent, 'watchlist', row, operation_id,
                    dict(item_id=item_id, name=name, alert_margin_above=alert_margin_above,
                         alert_margin_below=alert_margin_below))
            data['items'][str(item_id)] = row
            txn.stage('watchlist.json', data)
            txn.commit(operation_id=operation_id)
        return
    with _watchlist_lock(profile):
        data = load(profile)
        existing = data["items"].get(str(item_id))
        added = existing.get("added") if existing else             datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if alert_margin_above is None and existing is not None:
            alert_margin_above = existing.get("alert_margin_above")
        if alert_margin_below is None and existing is not None:
            alert_margin_below = existing.get("alert_margin_below")
        row = {
            **(existing or {}),
            "name": name,
            "added": added,
            "alert_margin_above": alert_margin_above,
            "alert_margin_below": alert_margin_below,
        }
        with state_transaction.profile_transaction(profile or 'default', path.parent) as txn:
            row['item_id'] = int(item_id)
            _stage_alert_policy(txn, row, alert_policy, profile)
            data['items'][str(item_id)] = row
            txn.stage('watchlist.json', data)
            txn.commit(operation_id or str(uuid4()))


def remove(item_id: int, profile: str | None = None) -> bool:
    """Remove a watched item. Returns True if it existed.

    Identified profiles retain a tombstone so deletions replicate; legacy
    profiles drop the row entirely.
    """
    path = _watchlist_path(profile)
    if state_identity.activation_manifest(
            path.with_name('identity-activation.json')) is not None:
        with state_transaction.profile_transaction(profile or 'default',
                                                   path.parent) as txn:
            data = load(profile)
            popped = data["items"].pop(str(item_id), None)
            if popped is None:
                return False
            identity = popped.get('record_uuid')
            if identity is not None:
                tombstones = data.setdefault('tombstones', {})
                tombstones[identity] = {
                    **popped, 'tombstone': True,
                    'revision': popped.get('revision', 0) + 1,
                    'item_id': int(item_id),
                }
                operation = identity
            else:
                origin = state_identity.activation_manifest(
                    path.with_name('identity-activation.json'))['origin_uuid']
                operation = str(UUID(origin))
            txn.stage('watchlist.json', data)
            txn.commit(operation_id=operation)
        return True
    with _watchlist_lock(profile):
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
