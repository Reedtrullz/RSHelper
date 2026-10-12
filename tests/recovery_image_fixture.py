"""Synthetic old/new/old image rehearsal; run only on an owned disposable HOME."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time

from rshelper import backup, profile, realization, state_identity, state_transaction

ORIGIN = '11111111-1111-4111-8111-111111111111'
PROFILE = '22222222-2222-4222-8222-222222222222'
FIRST = '33333333-3333-4333-8333-333333333333'
SECOND = '44444444-4444-4444-8444-444444444444'
RESTORE = '55555555-5555-4555-8555-555555555555'
NAME = 'recovery-rehearsal'


def fingerprint(root):
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in sorted(backup.FILES) if (root / name).exists()}


def main():
    assert os.environ.get('RSHELPER_RECOVERY_REHEARSAL') == '1', 'owned disposable HOME required'
    phase = sys.argv[1]
    started = time.monotonic()
    root = profile.resolve_config_path('', NAME)
    archive = Path.home() / 'before.zip'
    if phase == 'start':
        assert not root.exists() and not archive.exists(), 'refuse existing rehearsal data'
        root.mkdir(parents=True)
        activation = {'schema_version': 1, 'mode': 'identified', 'origin_uuid': ORIGIN,
            'profile_uuid': PROFILE, 'financial_authority': True, 'replication_origins': [ORIGIN]}
        lot = {'id': 1, 'item_id': 2, 'name': 'Synthetic', 'qty': 10, 'buy_price': 100,
            'direction': 'traditional', 'opened_at': '2026-01-01T00:00:00Z'}
        lots, manifest = state_identity.migrate_rows([lot], 'positions', state_identity.new_manifest(ORIGIN))
        for name, data in {'identity-activation.json': activation,
                'identity-manifest.json': manifest, 'positions.json': {'positions': lots},
                'trades.json': {'trades': []}}.items():
            profile.atomic_write_json(root / name, data)
        realization.close_and_realize(NAME, lots[0]['lot_uid'], 5, 120, FIRST, 'manual')
        backup.export_profile(NAME, archive)
    elif phase == 'advance':
        lots = json.loads((root / 'positions.json').read_bytes())['positions']
        realization.close_and_realize(NAME, lots[0]['lot_uid'], 5, 120, SECOND, 'manual')
        backup.export_profile(NAME, Path.home() / 'after.zip')
    elif phase == 'kill-restore':
        def checkpoint(step):
            if step == 'data:trades.json':
                os._exit(9)
        state_transaction._checkpoint = checkpoint
        backup.restore_profile('recovery-staging', Path.home() / 'after.zip',
            expected_profile_uuid=PROFILE, operation_id=RESTORE)
        raise AssertionError('restore checkpoint not reached')
    elif phase == 'verify':
        state_transaction.recover_profile(profile.resolve_config_path('', 'recovery-staging'))
        realization.recover_pending('recovery-staging')
        restored = backup.restore_profile('recovery-staging', Path.home() / 'after.zip',
            expected_profile_uuid=PROFILE, operation_id=RESTORE)
        before = fingerprint(root)
        try:
            backup.restore_profile(NAME, archive, expected_profile_uuid=PROFILE,
                operation_id=RESTORE, expected_source_revision=backup.inspect_backup(archive)['source_revision'])
        except backup.BackupError:
            pass
        else:
            raise AssertionError('old backup erased later acknowledged writes')
        assert fingerprint(root) == before
        for name in (NAME, 'recovery-staging'):
            trades = json.loads(profile.resolve_config_path('trades.json', name).read_bytes())['trades']
            assert sum(row['qty'] for row in trades) == 10
            assert sum(row['profit'] for row in trades) == 180
            assert len({row['record_uuid'] for row in trades}) == 2
            realization.recover_pending(name)
        assert fingerprint(root) == before
        assert restored['source_revision'] == backup.inspect_backup(Path.home() / 'after.zip')['source_revision']
    else:
        raise AssertionError('unknown phase')
    print(json.dumps({'phase': phase, 'elapsed_seconds': round(time.monotonic() - started, 3),
        'source_revision': backup.inspect_backup(archive)['source_revision'], 'checksums': fingerprint(root)}))


if __name__ == '__main__':
    main()
