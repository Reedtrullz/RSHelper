from datetime import datetime
import math
import sys
import time

from rshelper import persistence, profile
from rshelper.market_data import provenance

SOURCE_MAX_AGE = 360
CYCLE_MAX_AGE = 600
SYNC_MAX_AGE = 1800


def _age(timestamp, now):
    if type(timestamp) not in (int, float) or not math.isfinite(timestamp) or timestamp > now:
        return None
    return now - timestamp


def _iso_epoch(value):
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
    except (ValueError, AttributeError, OverflowError):
        return None


def record_sync(selected_profile, result, *, now=None):
    try:
        return _record_sync(selected_profile, result, now=now)
    except (OSError, ValueError):
        print('  Warning: sync readiness unavailable; financial publication must recover first', file=sys.stderr)
        return False


def _record_sync(selected_profile, result, *, now=None):
    root = profile.resolve_config_path('', selected_profile)
    path = root/'sync-status.json'
    with persistence.locked_state(root/'.profile'):
        now = time.time() if now is None else now
        prior = persistence.read_state(path, 'generic')
        status = result.get('status', 'failed')
        if status not in ('applied', 'no_op', 'obsolete', 'conflict', 'failed'):
            raise ValueError('invalid sync status')
        summary = {'schema_version': 1, 'status': status, 'last_attempt_at': now,
                   'last_success_at': now if status in ('applied', 'no_op') else prior.get('last_success_at'),
                   'applied_revision': result.get('applied_revision', prior.get('applied_revision')),
                   'applied_hash': result.get('applied_hash', prior.get('applied_hash'))}
        profile.atomic_write_json(path, summary)
    return True


def status(selected_profile, *, sources=None, now=None):
    from rshelper import api
    now = time.time() if now is None else now
    root = profile.resolve_config_path('', selected_profile)
    if sources is None:
        sources = {name: api._cache_result(name, selected_profile, stale=True, now=now)
                   for name in ('latest', '5m')}
    reasons = []
    source_status = {}
    for name in ('latest', '5m'):
        meta = provenance(sources.get(name))
        age = _age(meta['last_success_at'], now)
        ready = (meta['source'] in ('wiki', 'ge-tracker') and not meta['stale']
                 and age is not None and age <= SOURCE_MAX_AGE)
        source_status[name] = {key: meta[key] for key in
            ('source', 'delivery', 'last_attempt_at', 'last_success_at', 'stale', 'volume_kind')}
        source_status[name].update(ready=ready, age_sec=age)
        if not ready:
            reasons.append('source:'+name)
    activation = persistence.read_state(root/'identity-activation.json', 'generic')
    if activation and type(activation.get('financial_authority')) is not bool:
        raise ValueError('invalid financial authority status')
    state = persistence.read_state(root/'trader_state.json', 'generic')
    required_cycle = activation.get('financial_authority') is True
    completed = _iso_epoch(state.get('last_cycle_iso'))
    succeeded = _iso_epoch(state.get('last_success_iso'))
    last_result = state.get('last_result') or {}
    if not isinstance(last_result, dict):
        raise ValueError('invalid cycle status')
    if succeeded is None and not last_result.get('error'):
        succeeded = completed
    cycle_age = _age(succeeded, now)
    cycle_ready = not required_cycle or (cycle_age is not None and cycle_age <= CYCLE_MAX_AGE
                                        and not last_result.get('error'))
    if not cycle_ready:
        reasons.append('cycle:trader')
    sync = persistence.read_state(root/'sync-status.json', 'generic')
    sync_age = _age(sync.get('last_success_at'), now)
    required_sync = bool(activation)
    sync_ready = not required_sync or (sync.get('status') in ('applied', 'no_op')
                                      and sync_age is not None and sync_age <= SYNC_MAX_AGE)
    exact_revision = None
    if required_sync and sync.get('status') in ('applied', 'no_op'):
        from rshelper.state_replication import _metadata
        packet_state = _metadata(root)
        receipts = packet_state['receipts']
        assert isinstance(receipts, dict)
        cursors = list(receipts.values())
        outgoing = packet_state['outgoing']
        if outgoing is not None:
            assert isinstance(outgoing, dict)
            cursors.append({'applied_revision': outgoing['source_revision'],
                            'applied_hash': outgoing['packet_hash']})
        exact_revision = any(cursor['applied_revision'] == sync.get('applied_revision')
                             and cursor['applied_hash'] == sync.get('applied_hash') for cursor in cursors)
        if not exact_revision:
            sync_ready = False
            reasons.append('sync:revision-mismatch')
    if not sync_ready:
        reasons.append('sync:'+str(sync.get('status', 'unknown')))
    return {'schema_version': 1, 'ready': not reasons, 'status': 'degraded' if reasons else 'ready',
            'observed_at': now, 'reasons': reasons, 'sources': source_status,
            'cycle': {'required': required_cycle, 'ready': cycle_ready,
                      'last_completed_at': completed, 'last_success_at': succeeded,
                      'age_sec': cycle_age},
            'sync': {**{key: sync.get(key) for key in ('status', 'last_attempt_at', 'last_success_at',
                      'applied_revision', 'applied_hash')}, 'required': required_sync,
                     'ready': sync_ready, 'age_sec': sync_age, 'exact_revision': exact_revision},
            'thresholds_sec': {'source': SOURCE_MAX_AGE, 'cycle': CYCLE_MAX_AGE, 'sync': SYNC_MAX_AGE}}
