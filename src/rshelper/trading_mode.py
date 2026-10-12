from datetime import datetime, timezone
import hashlib
import importlib
import json
import time
from pathlib import Path
from uuid import uuid4

from rshelper import persistence, state_identity, state_transaction
from rshelper.profile import resolve_config_path

MODES = ('running', 'entries-paused', 'draining')
MAX_RECEIPTS = 128

class EntriesPaused(ValueError):
    pass

def _default():
    return {'schema_version':1, 'mode':'running', 'revision':0, 'reason':'',
            'source':'legacy-default', 'effective_at':None, 'operation_id':None,
            'authority_origin':None, 'drain_completed_at':None, 'operations':{}}

def validate_mode(data):
    if (not isinstance(data,dict) or set(data) != set(_default())
            or type(data['schema_version']) is not int or data['schema_version'] != 1
            or data['mode'] not in MODES or type(data['revision']) is not int
            or not 0 < data['revision'] < 2**63
            or not isinstance(data['reason'],str) or not 0 < len(data['reason']) <= 500
            or not isinstance(data['source'],str) or not 0 < len(data['source']) <= 100
            or not isinstance(data['operations'],dict) or not 0 < len(data['operations']) <= MAX_RECEIPTS):
        raise ValueError('invalid trading stance')
    persistence.canonical_uuid(data['operation_id'])
    if data['authority_origin'] is not None:
        persistence.canonical_uuid(data['authority_origin'])
    for key in ('effective_at','drain_completed_at'):
        if data[key] is not None:
            instant = datetime.fromisoformat(data[key])
            offset = instant.utcoffset()
            if offset is None or offset.total_seconds() != 0:
                raise ValueError('trading stance timestamps must use UTC')
        elif key == 'effective_at':
            raise ValueError('trading stance requires an effective timestamp')
    if data['drain_completed_at'] is not None and data['mode'] != 'draining':
        raise ValueError('only draining can report drain completion')
    for operation,receipt in data['operations'].items():
        persistence.canonical_uuid(operation)
        if (not isinstance(receipt,dict) or set(receipt) != {'request_hash','revision'}
                or not isinstance(receipt['request_hash'],str) or len(receipt['request_hash']) != 64
                or any(c not in '0123456789abcdef' for c in receipt['request_hash'])
                or type(receipt['revision']) is not int or not 0 < receipt['revision'] <= data['revision']):
            raise ValueError('invalid trading stance receipt')
    if data['operation_id'] not in data['operations']:
        raise ValueError('trading stance operation lacks receipt')
    return data

def validate_authority(mode, manifest):
    if not manifest or mode['revision'] == 0:
        return mode
    origin = mode['authority_origin']
    origins = manifest.get('replication_origins')
    if (origin is None
            or (origins is not None and origin not in origins)
            or (origins is None and manifest.get('financial_authority') is not True)
            or (manifest.get('financial_authority') is True and origin != manifest['origin_uuid'])
            or (manifest.get('financial_authority') is False and origin == manifest['origin_uuid'])):
        raise ValueError('trading stance authority differs from the activated profile')
    return mode

def _read(root):
    root = Path(root)
    mode = persistence.read_state(root/'trading_mode.json','trading_mode') or _default()
    return validate_authority(mode,state_identity.activation_manifest(root/'identity-activation.json'))

def read_mode(profile):
    root = resolve_config_path('',profile)
    with state_transaction.profile_transaction(profile or 'default',root):
        return _read(root)

def _authority(root):
    manifest = state_identity.activation_manifest(root/'identity-activation.json')
    if manifest is not None:
        state_identity.require_financial_authority(manifest)
    return manifest['origin_uuid'] if manifest else None

def set_mode(profile, mode, *, expected_revision, reason, operation_id, source='cli'):
    if (mode not in MODES or type(expected_revision) is not int or expected_revision < 0
            or not isinstance(reason,str) or not reason.strip() or len(reason) > 500
            or not isinstance(source,str) or not source.strip() or len(source) > 100):
        raise ValueError('invalid trading stance request')
    persistence.canonical_uuid(operation_id)
    request_hash = hashlib.sha256(json.dumps([mode,expected_revision,reason,source]).encode()).hexdigest()
    root = resolve_config_path('',profile)
    with state_transaction.profile_transaction(profile or 'default',root) as txn:
        origin = _authority(root)
        current = _read(root)
        prior = current['operations'].get(operation_id)
        if prior:
            if prior['request_hash'] != request_hash:
                raise ValueError('trading stance operation reused with different request')
            return {**current,'status':'no_op','operation_revision':prior['revision']}
        if current['revision'] != expected_revision:
            raise ValueError('trading stance revision changed; read status before retry')
        revision = current['revision'] + 1
        operations = {**current['operations'],operation_id:{'request_hash':request_hash,'revision':revision}}
        operations = dict(sorted(operations.items(),key=lambda entry:entry[1]['revision'])[-MAX_RECEIPTS:])
        value = {**current,'mode':mode,'revision':revision,'reason':reason,'source':source,
                 'effective_at':datetime.now(timezone.utc).isoformat(),'operation_id':operation_id,
                 'authority_origin':origin,'drain_completed_at':None,'operations':operations}
        txn.stage('trading_mode.json',value)
        txn.commit(operation_id)
        return {**value,'status':'applied','operation_revision':revision}

def require_entries_running(root):
    mode = _read(root)
    if mode['mode'] != 'running':
        raise EntriesPaused(f"new paper entries blocked: {mode['mode']} at revision {mode['revision']}")

def update_drain(profile):
    from rshelper.positions import list_positions
    root = resolve_config_path('',profile)
    with state_transaction.profile_transaction(profile or 'default',root) as txn:
        current = _read(root)
        if current['mode'] != 'draining' or current['drain_completed_at'] is not None or list_positions(profile):
            return current
        manifest = state_identity.activation_manifest(root/'identity-activation.json')
        if manifest and manifest.get('financial_authority') is False:
            return current
        if (root/'paper-offers.json').exists() or (manifest or {}).get('paper_budget_origin'):
            try:
                paper_book=importlib.import_module('rshelper.paper_book')
            except ImportError as exc:
                raise ValueError('paper offer proof unavailable; drain remains incomplete') from exc
            book=paper_book.budget_snapshot(profile,now=time.time())
            if book['pending_collections'] or any(record['offer']['stage'] not in ('collected','canceled')
                                                  for record in book['offers'].values()):
                return current
        _authority(root)
        current['revision'] += 1
        current['drain_completed_at'] = datetime.now(timezone.utc).isoformat()
        txn.stage('trading_mode.json',current)
        txn.commit(str(uuid4()))
        return current
