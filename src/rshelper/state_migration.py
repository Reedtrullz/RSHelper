import copy
import hashlib
from pathlib import Path

from rshelper import persistence, state_identity, state_replication, state_transaction
from rshelper.backup import _read_file
from rshelper.profile import resolve_config_path

CORE = state_replication.CORE


def _source(root):
    hashes, stores = {}, {}
    for name, kind in CORE.items():
        path = root / name
        hashes[name] = hashlib.sha256(_read_file(path)).hexdigest() if path.exists() else None
        stores[name] = persistence.read_state(path, kind)
        persistence.validate_writable_state(stores[name], kind, path)
    mode_path = root/'trading_mode.json'
    hashes['trading_mode.json'] = hashlib.sha256(_read_file(mode_path)).hexdigest() if mode_path.exists() else None
    if hashes['trading_mode.json'] is not None:
        stores['trading_mode.json'] = persistence.read_state(mode_path,'trading_mode')
    return hashes, stores


def _upgrade(stores, origin_uuid, profile_uuid, lineage):
    persistence.canonical_uuid(origin_uuid)
    persistence.canonical_uuid(profile_uuid)
    if not isinstance(lineage, dict):
        raise ValueError('explicit source lineage is required')
    base = {'mode', 'financial_authority', 'replication_origins'}
    mode = lineage.get('mode')
    extra = {'independent': set(), 'common': {'common_origin_uuid'},
             'resolved': {'record_origins'}}
    if type(mode) is not str or mode not in extra or set(lineage) != base | extra[mode]:
        raise ValueError('explicit independent, common or resolved lineage is required')
    peers = lineage['replication_origins']
    if (type(lineage['financial_authority']) is not bool or not isinstance(peers, list)
            or not peers or len(peers) > 512 or any(type(peer) is not str for peer in peers)
            or len(set(peers)) != len(peers)):
        raise ValueError('invalid authority or replication lineage')
    for peer in peers:
        persistence.canonical_uuid(peer)
    if origin_uuid not in peers:
        raise ValueError('local origin must be explicitly declared')
    common = lineage.get('common_origin_uuid')
    if common is not None:
        persistence.canonical_uuid(common)
        if common not in peers:
            raise ValueError('common lineage origin must be declared')
    assignments = lineage.get('record_origins', {})
    if not isinstance(assignments, dict) or set(assignments) - set(CORE.values()):
        raise ValueError('invalid explicit record lineage')
    manifests = {origin_uuid: state_identity.new_manifest(origin_uuid)}
    output = copy.deepcopy(stores)
    used = {}
    count = 0
    for name, kind in CORE.items():
        store = output[name]
        rows = list(store['items'].values()) if kind == 'watchlist' else store[kind]
        if kind == 'watchlist':
            for key, row in store['items'].items():
                row['item_id'] = int(key)
        mappings = assignments.get(kind, {})
        if not isinstance(mappings, dict):
            raise ValueError('invalid record origin mapping')
        used[kind] = set()
        groups = {}
        for row in rows:
            key = state_identity._migration_key(row, kind)
            selected = (origin_uuid if mode == 'independent' else common if mode == 'common'
                        else mappings.get(key))
            if selected not in peers:
                raise ValueError('ambiguous record lineage requires explicit resolution')
            if key in used[kind]:
                raise ValueError('ambiguous duplicate source record requires resolution')
            used[kind].add(key)
            groups.setdefault(selected, []).append(row)
        upgraded = {}
        for selected, source_rows in groups.items():
            manifest = manifests.setdefault(selected, state_identity.new_manifest(selected))
            if kind == 'watchlist':
                migrated, manifest = state_identity.migrate_watchlist(
                    {'items': {str(row['item_id']): row for row in source_rows}}, manifest)
                migrated_rows = list(migrated['items'].values())
            else:
                migrated_rows, manifest = state_identity.migrate_rows(source_rows, kind, manifest)
            upgraded.update({state_identity._migration_key(row, kind): row for row in migrated_rows})
            manifests[selected] = manifest
        if mode == 'resolved' and set(mappings) != used[kind]:
            raise ValueError('explicit lineage inventory differs from source')
        count += len(rows)
        if count > state_replication.MAX_ROWS:
            raise ValueError('migration record budget exceeded')
        ordered = [upgraded[state_identity._migration_key(row, kind)] for row in rows]
        if kind == 'watchlist':
            store['items'] = {str(row['item_id']): row for row in ordered}
        else:
            store[kind] = ordered
        store['schema_version'] = 2
    if lineage['financial_authority'] and any(row['origin_uuid'] != origin_uuid
            for row in output['positions.json']['positions']):
        raise ValueError('authority cannot adopt foreign open lots; resolve ownership explicitly')
    output['identity-manifest.json'] = manifests.pop(origin_uuid)
    output['identity-lineage.json'] = {'schema_version': 1, 'origins': manifests}
    if 'trading_mode.json' in output:
        authority = origin_uuid if lineage['financial_authority'] else common
        if authority is None or (not lineage['financial_authority'] and authority == origin_uuid):
            raise ValueError('legacy stance requires explicit financial authority lineage')
        output['trading_mode.json']['authority_origin'] = authority
    state_replication._validate_files({name: state_replication._json(value) for name, value in output.items()})
    output['identity-activation.json'] = {
        'schema_version': 1, 'mode': 'identified', 'profile_uuid': profile_uuid,
        'origin_uuid': origin_uuid, 'financial_authority': lineage['financial_authority'],
        'replication_origins': sorted(peers)}
    return output


def plan_migration(profile, *, origin_uuid, profile_uuid, lineage):
    root = resolve_config_path('', profile)
    with state_transaction.profile_transaction(profile, root):
        if (root / 'identity-activation.json').exists():
            raise ValueError('migration planning requires an inactive legacy profile')
        hashes, stores = _source(root)
        upgraded = _upgrade(stores, origin_uuid, profile_uuid, lineage)
        return {'schema_version': 1, 'profile_uuid': profile_uuid, 'origin_uuid': origin_uuid,
                'source_hashes': hashes, 'lineage': copy.deepcopy(lineage),
                'target_hashes': {name: hashlib.sha256(state_replication._json(value)).hexdigest()
                                  for name, value in upgraded.items()}}


def migrate_profile(profile, *, plan, operation_id):
    persistence.canonical_uuid(operation_id)
    if (not isinstance(plan, dict) or set(plan) != {'schema_version', 'profile_uuid', 'origin_uuid',
            'source_hashes', 'lineage', 'target_hashes'} or type(plan['schema_version']) is not int
            or plan['schema_version'] != 1):
        raise ValueError('invalid explicit migration plan')
    persistence.validate_state(plan, 'generic', 'migration-plan')
    persistence.canonical_uuid(plan['profile_uuid'])
    persistence.canonical_uuid(plan['origin_uuid'])
    digest = hashlib.sha256(state_replication._json(plan)).hexdigest()
    root = resolve_config_path('', profile)
    with state_transaction.profile_transaction(profile, root) as txn:
        receipts = persistence.read_state(root / 'migration-receipts.json', 'generic').get('operations', {})
        if operation_id in receipts:
            receipt = receipts[operation_id]
            if receipt['plan_hash'] != digest:
                raise ValueError('migration operation reused with another plan')
            state_replication.validate_profile(profile)
            return receipt
        if (root / 'identity-activation.json').exists():
            raise ValueError('profile is already activated under another operation')
        hashes, stores = _source(root)
        if hashes != plan['source_hashes']:
            raise ValueError('migration source changed; refresh explicit lineage plan')
        upgraded = _upgrade(stores, plan['origin_uuid'], plan['profile_uuid'], plan['lineage'])
        targets = {name: hashlib.sha256(state_replication._json(value)).hexdigest()
                   for name, value in upgraded.items()}
        if targets != plan['target_hashes']:
            raise ValueError('migration preview target changed')
        receipt = {'schema_version': 1, 'status': 'migrated', 'operation_id': operation_id,
                   'profile_uuid': plan['profile_uuid'], 'origin_uuid': plan['origin_uuid'],
                   'plan_hash': digest, 'target_hashes': targets}
        receipts[operation_id] = receipt
        for name, value in upgraded.items():
            txn.stage(name, value)
        txn.stage('migration-receipts.json', {'schema_version': 1, 'operations': receipts})
        txn.commit(operation_id)
        return receipt
