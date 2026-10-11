import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from rshelper import backup, profile, state_identity, state_transaction

ORIGIN = '11111111-1111-4111-8111-111111111111'
PROFILE = '22222222-2222-4222-8222-222222222222'
OP = '33333333-3333-4333-8333-333333333333'


class RestoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        patch = mock.patch.object(profile, 'CONFIG_DIR', self.base / 'config')
        patch.start()
        self.addCleanup(patch.stop)
        self.root = profile.resolve_config_path('', 'source')
        self.root.mkdir(parents=True)
        (self.root / 'identity-activation.json').write_text(json.dumps({
            'schema_version': 1, 'mode': 'identified', 'origin_uuid': ORIGIN,
            'profile_uuid': PROFILE, 'financial_authority': True,
            'replication_origins': [ORIGIN]}))
        (self.root / 'identity-manifest.json').write_text(json.dumps(state_identity.new_manifest(ORIGIN)))
        (self.root / 'trades.json').write_text('{"trades": []}')

    def test_backup_restore_round_trip_includes_identity_intents_receipts(self):
        target = self.base / 'private.zip'
        backup.export_profile('source', target)
        inspected = backup.inspect_backup(target)
        self.assertEqual(inspected['profile_uuid'], PROFILE)
        self.assertIn('identity-manifest.json', inspected['files'])
        receipt = backup.restore_profile('restored', target, expected_profile_uuid=PROFILE, operation_id=OP)
        restored = profile.resolve_config_path('', 'restored')
        self.assertEqual(json.loads((restored / 'identity-activation.json').read_text())['origin_uuid'], ORIGIN)
        self.assertEqual(receipt['operation_id'], OP)
        self.assertEqual(backup.restore_profile('restored', target, expected_profile_uuid=PROFILE, operation_id=OP), receipt)

    def test_legacy_restore_requires_explicit_revision_and_empty_target(self):
        legacy = profile.resolve_config_path('', 'legacy')
        legacy.mkdir(parents=True)
        original = b'{"positions":[{"id":1,"item_id":2,"name":"Synthetic","qty":10,"buy_price":100,"direction":"traditional","opened_at":"2026-01-01T00:00:00Z"}]}'
        (legacy / 'positions.json').write_bytes(original)
        source = self.base / 'legacy.zip'
        manifest = backup.export_profile('legacy', source)
        with self.assertRaises(ValueError):
            backup.restore_profile('legacy-restored', source, expected_profile_uuid=PROFILE, operation_id=OP)
        receipt = backup.restore_profile('legacy-restored', source, expected_profile_uuid=PROFILE,
            operation_id=OP, expected_source_revision=manifest['source_revision'])
        target = profile.resolve_config_path('positions.json', 'legacy-restored')
        self.assertEqual(target.read_bytes(), original)
        self.assertEqual(receipt['profile_uuid'], PROFILE)
        with self.assertRaises(ValueError):
            backup.restore_profile('legacy-restored', source, expected_profile_uuid=PROFILE,
                operation_id=ORIGIN, expected_source_revision=manifest['source_revision'])

    def test_legacy_restore_cli_does_not_initialize_target_config(self):
        import contextlib
        import io
        from rshelper import cli
        legacy = profile.resolve_config_path('', 'legacy-cli')
        legacy.mkdir(parents=True)
        original = b'{"positions":[]}'
        (legacy/'positions.json').write_bytes(original)
        archive = self.base/'legacy-cli.zip'
        manifest = backup.export_profile('legacy-cli', archive)
        output = io.StringIO()
        with contextlib.redirect_stdout(output), mock.patch.object(sys, 'argv',
                ['rshelper','--profile','restored-cli','backup','restore','--input',str(archive),
                 '--expected-profile-uuid',PROFILE,'--expected-source-revision',manifest['source_revision'],
                 '--operation-id',OP,'--json']):
            cli.main()
        self.assertEqual(json.loads(output.getvalue())['status'], 'restored')
        restored = profile.resolve_config_path('', 'restored-cli')
        self.assertEqual((restored/'positions.json').read_bytes(), original)
        self.assertFalse((restored/'config.toml').exists())

    def test_wrong_profile_restore_leaves_live_bytes_unchanged(self):
        target = self.base / 'private.zip'
        backup.export_profile('source', target)
        before = (self.root / 'trades.json').read_bytes()
        with self.assertRaises(ValueError):
            backup.restore_profile('source', target, expected_profile_uuid=ORIGIN, operation_id=OP)
        self.assertEqual(before, (self.root / 'trades.json').read_bytes())

    def test_backup_manifest_origin_must_match_activation(self):
        (self.root / 'identity-manifest.json').write_text(json.dumps(state_identity.new_manifest(OP)))
        target = self.base / 'wrong-origin.zip'
        backup.export_profile('source', target)
        with self.assertRaises(ValueError):
            backup.inspect_backup(target)

    def test_restore_refuses_newer_acknowledged_receipt(self):
        target = self.base / 'old.zip'
        backup.export_profile('source', target)
        receipt = {'schema_version': 1, 'profile_uuid': PROFILE, 'origin_uuid': ORIGIN,
                   'status': 'applied', 'requested_revision': 2, 'applied_revision': 2,
                   'requested_hash': 'a' * 64, 'applied_hash': 'a' * 64}
        live = {'schema_version': 1, 'outgoing': None, 'receipts': {ORIGIN: receipt}}
        path = self.root / 'replication-state.json'
        path.write_text(json.dumps(live))
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            backup.restore_profile('source', target, expected_profile_uuid=PROFILE, operation_id=OP)
        self.assertEqual(path.read_bytes(), before)

    def test_restore_config_snapshots_recovers_after_interruption(self):
        (self.root / 'config.toml').write_text('[flip]\nmin_volume = 10\n')
        (self.root / 'snapshots').mkdir()
        (self.root / 'snapshots' / 'one.json').write_text('{"entries": []}')
        target = self.base / 'private.zip'
        backup.export_profile('source', target)
        restored = profile.resolve_config_path('', 'restored')
        def interrupt(step):
            if step == 'receipt-published':
                raise OSError('lost response')
        with mock.patch.object(state_transaction, '_checkpoint', interrupt):
            with self.assertRaises(OSError):
                backup.restore_profile('restored', target, expected_profile_uuid=PROFILE, operation_id=OP)
        state_transaction.recover_profile(restored)
        receipt = backup.restore_profile('restored', target, expected_profile_uuid=PROFILE, operation_id=OP)
        self.assertEqual(receipt['status'], 'restored')
        for name in ('config.toml', 'snapshots/one.json'):
            self.assertEqual((restored / name).read_bytes(), (self.root / name).read_bytes())
        self.assertFalse(list(restored.rglob('*.publishing')))

    def test_archive_duplicates_traversal_and_expansion_budget_refused(self):
        for label, names in (('duplicate', ['manifest.json', 'manifest.json']),
                             ('traversal', ['manifest.json', '../trades.json']),
                             ('budget', ['manifest.json', 'trades.json'])):
            with self.subTest(label=label):
                target = self.base / (label + '.zip')
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore', UserWarning)
                    with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                        for name in names:
                            archive.writestr(name, '{}' if label != 'budget' else ' ' * 2048)
                with mock.patch.object(backup, 'MAX_STATE_BYTES', 1024):
                    with self.assertRaises(ValueError):
                        backup.inspect_backup(target)
        self.assertFalse((self.base / 'trades.json').exists())

    def test_new_snapshot_writer_waits_for_capture_lease(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        started = threading.Event()
        def write():
            started.set()
            profile.atomic_write_json(self.root / 'snapshots' / 'new.json', {'entries': []})
        with ThreadPoolExecutor(max_workers=1) as pool:
            with state_transaction.profile_transaction('source', self.root):
                future = pool.submit(write)
                self.assertTrue(started.wait(2))
                with self.assertRaises(TimeoutError):
                    future.result(timeout=0.1)
            future.result(timeout=2)

    def test_backup_cli_inspect_restore_stdout_is_json(self):
        import contextlib
        import io
        from rshelper import cli
        target = self.base / 'private.zip'
        backup.export_profile('source', target)
        for command in (['inspect', '--input', str(target)],
                        ['restore', '--input', str(target), '--expected-profile-uuid', PROFILE,
                         '--operation-id', OP]):
            output, error = io.StringIO(), io.StringIO()
            with mock.patch.object(sys, 'argv', ['rshelper', '--profile', 'restored', 'backup', *command, '--json']), \
                    contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                cli.main()
            self.assertEqual(json.loads(output.getvalue())['profile_uuid'], PROFILE)
            self.assertEqual(error.getvalue(), '')

    def test_restore_interruption_preserves_acknowledged_trade_and_profit(self):
        from rshelper import realization
        lot = {'id': 1, 'item_id': 2, 'name': 'Synthetic', 'qty': 10, 'buy_price': 100,
               'direction': 'traditional', 'opened_at': '2026-01-01T00:00:00Z'}
        lots, manifest = state_identity.migrate_rows([lot], 'positions', state_identity.new_manifest(ORIGIN))
        (self.root / 'positions.json').write_text(json.dumps({'positions': lots}))
        (self.root / 'identity-manifest.json').write_text(json.dumps(manifest))
        realization.close_and_realize('source', lots[0]['lot_uid'], 10, 120, OP, 'manual')
        target = self.base / 'acknowledged.zip'
        backup.export_profile('source', target)
        restored = profile.resolve_config_path('', 'restored')
        def interrupt(step):
            if step == 'data:trades.json':
                raise OSError('interrupted restore')
        with mock.patch.object(state_transaction, '_checkpoint', interrupt):
            with self.assertRaises(OSError):
                backup.restore_profile('restored', target, expected_profile_uuid=PROFILE, operation_id=PROFILE)
        state_transaction.recover_profile(restored)
        realization.recover_pending('restored')
        trades = json.loads((restored / 'trades.json').read_text())['trades']
        self.assertEqual(sum(row['qty'] for row in trades), 10)
        self.assertEqual(sum(row['profit'] for row in trades), 180)
        self.assertEqual(trades[0]['record_uuid'], json.loads((self.root / 'trades.json').read_text())['trades'][0]['record_uuid'])


if __name__ == '__main__':
    unittest.main()
