import copy
import contextlib
import hashlib
import json
import io
from pathlib import Path
import sys
import stat
import tempfile
import unittest
from unittest import mock
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from rshelper import profile, state_identity, state_transaction

A = '11111111-1111-4111-8111-111111111111'
B = '22222222-2222-4222-8222-222222222222'
P = '33333333-3333-4333-8333-333333333333'


class ReplicationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        patch = mock.patch.object(profile, 'CONFIG_DIR', self.base / 'config')
        patch.start()
        self.addCleanup(patch.stop)
        for name, origin in (('a', A), ('b', B)):
            root = self.root(name)
            root.mkdir(parents=True)
            activation = {'schema_version': 1, 'mode': 'identified',
                          'origin_uuid': origin, 'profile_uuid': P,
                          'financial_authority': name == 'a',
                          'replication_origins': [A, B]}
            (root / 'identity-activation.json').write_text(json.dumps(activation))
            (root / 'identity-manifest.json').write_text(json.dumps(state_identity.new_manifest(origin)))
            for filename, kind in state_transaction.STATE_FILES.items():
                if kind in ('watchlist', 'trades', 'alerts', 'positions'):
                    payload = {'items': {}} if kind == 'watchlist' else {kind: []}
                    (root / filename).write_text(json.dumps(payload))

    def root(self, name):
        return profile.resolve_config_path('', name)

    def api(self):
        from rshelper import state_replication
        return state_replication

    def row(self, origin=A):
        row = {'id': 1, 'item_id': 2, 'name': 'Synthetic', 'qty': 10,
               'buy_price': 100, 'sell_price': 120, 'tax_paid': 20,
               'profit': 180, 'timestamp': '2026-01-01T00:00:00Z'}
        return state_identity.migrate_rows([row], 'trades', state_identity.new_manifest(origin))[0][0]

    def write_trades(self, name, rows):
        (self.root(name) / 'trades.json').write_text(json.dumps({'trades': rows}))
        path = self.root(name) / 'identity-manifest.json'
        manifest = json.loads(path.read_text())
        for row in rows:
            if row.get('origin_uuid') == manifest['origin_uuid'] and 'legacy_id' in row:
                manifest['mappings'][state_identity._migration_key(row, 'trades')] = row['record_uuid']
        path.write_text(json.dumps(manifest))

    def test_native_creation_proof_reaches_replica_and_survives_return(self):
        from rshelper import journal
        journal.log_trade(2, 'Synthetic', 10, 100, 120, profile='a', operation_id=B)
        self.api().apply_packet('b', self.packet())
        self.api().apply_packet('a', self.packet('b'))
        row = journal.list_trades(profile='a')[0]
        self.assertEqual(row.profit, 180)
        lineage = json.loads((self.root('b') / 'identity-lineage.json').read_text())
        self.assertIn(row.record_uuid, lineage['origins'][A]['native'])

    def test_growing_native_lineage_converges_over_three_round_trips(self):
        from rshelper import journal
        from uuid import uuid4
        for index in range(3):
            journal.log_trade(2, 'Synthetic', 10, 100, 120, profile='a', operation_id=str(uuid4()))
            forward = self.api().apply_packet('b', self.packet('a', 'grow-' + str(index)))
            reverse = self.api().apply_packet('a', self.packet('b', 'grow-' + str(index)))
            self.assertEqual((forward['status'], reverse['status']), ('applied', 'applied'))
        self.assertEqual(len(journal.list_trades(profile='a')), 3)
        self.assertEqual(len(journal.list_trades(profile='b')), 3)

    def test_unattested_native_row_cannot_leave_source(self):
        from rshelper import journal
        journal.log_trade(2, 'Synthetic', 10, 100, 120, profile='a', operation_id=B)
        manifest = self.root('a') / 'identity-manifest.json'
        manifest.write_text(json.dumps(state_identity.new_manifest(A)))
        with self.assertRaises(ValueError):
            self.packet()

    def test_partial_native_close_reconciles_attested_creation_quantity(self):
        from rshelper import positions, realization
        lot = positions.open_position(2, 'Synthetic', 10, 100, profile='a')
        realization.close_and_realize('a', lot.lot_uid, 4, 120, P, 'manual')
        self.assertEqual(self.api().apply_packet('b', self.packet())['status'], 'applied')
        path = self.root('a') / 'positions.json'
        store = json.loads(path.read_text())
        store['positions'][0]['qty'] += 1
        path.write_text(json.dumps(store))
        with self.assertRaises(ValueError):
            self.packet(suffix='forged-quantity')

    def test_undeclared_foreign_origin_cannot_enter_replica(self):
        packet = self.packet()
        self.api().apply_packet('b', packet)
        activation_path = self.root('a') / 'identity-activation.json'
        activation = json.loads(activation_path.read_text())
        activation['replication_origins'] = [A]
        activation_path.write_text(json.dumps(activation))
        with self.assertRaises(ValueError):
            self.api().apply_packet('a', self.packet('b'))

    def packet(self, name='a', suffix='one'):
        target = self.base / (name + '-' + suffix + '.zip')
        self.api().capture_packet(name, target)
        return target

    def test_repeat_merge_stays_byte_stable(self):
        self.write_trades('a', [self.row()])
        packet = self.packet()
        receipt = self.api().apply_packet('b', packet)
        before = (self.root('b') / 'trades.json').read_bytes()
        self.assertEqual(receipt.get('status'), 'applied')
        retry = self.api().apply_packet('b', packet)
        self.assertEqual(retry['status'], 'no_op')
        self.assertEqual(before, (self.root('b') / 'trades.json').read_bytes())
        self.assertEqual(retry['applied_hash'], receipt['requested_hash'])

    def test_independent_numeric_ids_survive_once(self):
        self.write_trades('a', [self.row()])
        self.write_trades('b', [self.row(B)])
        self.api().apply_packet('b', self.packet())
        rows = json.loads((self.root('b') / 'trades.json').read_text())['trades']
        self.assertEqual(len(rows), 2)
        self.assertEqual(len({row['id'] for row in rows}), 2)
        self.assertEqual({row['origin_uuid'] for row in rows}, {A, B})

    def test_older_packet_cannot_rollback(self):
        first = self.packet()
        self.api().apply_packet('b', first)
        self.write_trades('a', [self.row()])
        second = self.packet(suffix='two')
        self.api().apply_packet('b', second)
        before = (self.root('b') / 'trades.json').read_bytes()
        receipt = self.api().apply_packet('b', first)
        self.assertEqual(receipt['status'], 'obsolete')
        self.assertEqual(receipt['applied_revision'], 2)
        self.assertEqual(before, (self.root('b') / 'trades.json').read_bytes())

    def test_missing_parent_quarantines(self):
        self.packet()
        self.write_trades('a', [self.row()])
        before = (self.root('b') / 'trades.json').read_bytes()
        receipt = self.api().apply_packet('b', self.packet(suffix='two'))
        self.assertEqual(receipt['status'], 'conflict')
        self.assertEqual(before, (self.root('b') / 'trades.json').read_bytes())
        self.assertTrue(list((self.root('b') / 'replication-quarantine').glob('*.zip')))

    def test_same_revision_different_hash_conflicts(self):
        first = self.packet()
        self.api().apply_packet('b', first)
        alternate = self.base / 'alternate.zip'
        api = self.api()
        with zipfile.ZipFile(first) as source:
            files = {name: source.read(name) for name in source.namelist()}
        manifest = json.loads(files.pop('manifest.json'))
        row = self.row()
        identity = state_identity.new_manifest(A)
        identity['mappings'][state_identity._migration_key(row, 'trades')] = row['record_uuid']
        files['identity-manifest.json'] = json.dumps(identity).encode()
        files['trades.json'] = json.dumps({'trades': [row]}).encode()
        for entry in manifest['files']:
            entry.update(bytes=len(files[entry['path']]), sha256=hashlib.sha256(files[entry['path']]).hexdigest())
        manifest['packet_hash'] = api.packet_hash(manifest, files)
        with zipfile.ZipFile(alternate, 'w') as output:
            output.writestr('manifest.json', json.dumps(manifest))
            for name, payload in files.items():
                output.writestr(name, payload)
        receipt = api.apply_packet('b', alternate)
        self.assertEqual(receipt['status'], 'conflict')

    def test_wrong_profile_leaves_live_bytes_unchanged(self):
        packet = self.packet()
        before = (self.root('b') / 'trades.json').read_bytes()
        activation = json.loads((self.root('b') / 'identity-activation.json').read_text())
        activation['profile_uuid'] = B
        (self.root('b') / 'identity-activation.json').write_text(json.dumps(activation))
        with self.assertRaises(ValueError):
            self.api().apply_packet('b', packet)
        self.assertEqual(before, (self.root('b') / 'trades.json').read_bytes())

    def test_duplicate_zip_path_refuses_before_write(self):
        import warnings
        bad = self.base / 'duplicate.zip'
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(bad, 'w') as archive:
                archive.writestr('manifest.json', '{}')
                archive.writestr('manifest.json', '{}')
        before = (self.root('b') / 'trades.json').read_bytes()
        with self.assertRaises(ValueError):
            self.api().apply_packet('b', bad)
        self.assertEqual(before, (self.root('b') / 'trades.json').read_bytes())

    def test_receipt_loss_retry_reports_durable_apply(self):
        packet = self.packet()
        def interrupt(step):
            if step == 'receipt-published':
                raise OSError('response lost')
        with mock.patch.object(state_transaction, '_checkpoint', interrupt):
            with self.assertRaises(OSError):
                self.api().apply_packet('b', packet)
        receipt = self.api().apply_packet('b', packet)
        self.assertEqual(receipt['status'], 'no_op')
        self.assertEqual(receipt['requested_hash'], receipt['applied_hash'])

    def test_read_delete_reaches_both_peers(self):
        row = {'id': 1, 'ts': 100.0, 'type': 'watch', 'severity': 'INFO',
               'item_id': 2, 'item_name': 'Synthetic', 'title': 'Fixture',
               'message': 'Fixture', 'read': False}
        rows, manifest = state_identity.migrate_rows([row], 'alerts', state_identity.new_manifest(A))
        row = rows[0]
        (self.root('a') / 'identity-manifest.json').write_text(json.dumps(manifest))
        path = self.root('a') / 'alerts.json'
        path.write_text(json.dumps({'alerts': [row]}))
        self.api().apply_packet('b', self.packet())
        remote = self.root('b') / 'alerts.json'
        changed = json.loads(remote.read_text())
        changed['alerts'][0].update(revision=1, read=True)
        remote.write_text(json.dumps(changed))
        self.api().apply_packet('a', self.packet('b'))
        self.assertTrue(json.loads(path.read_text())['alerts'][0]['read'])
        deleted = json.loads(path.read_text())
        deleted['alerts'][0].update(revision=2, tombstone=True)
        path.write_text(json.dumps(deleted))
        self.api().apply_packet('b', self.packet(suffix='deleted'))
        self.assertTrue(json.loads(remote.read_text())['alerts'][0]['tombstone'])

    def test_closed_lot_never_resurrects(self):
        from rshelper import realization
        lot = {'id': 1, 'item_id': 2, 'name': 'Synthetic', 'qty': 10,
               'buy_price': 100, 'direction': 'traditional',
               'opened_at': '2026-01-01T00:00:00Z'}
        lots, manifest = state_identity.migrate_rows([lot], 'positions', state_identity.new_manifest(A))
        (self.root('a') / 'positions.json').write_text(json.dumps({'positions': lots}))
        (self.root('a') / 'identity-manifest.json').write_text(json.dumps(manifest))
        self.api().apply_packet('b', self.packet())
        realization.close_and_realize('a', lots[0]['lot_uid'], 10, 120, B, 'manual')
        self.api().apply_packet('b', self.packet(suffix='closed'))
        realization.recover_pending('b')
        self.api().apply_packet('a', self.packet('b', 'return'))
        for name in ('a', 'b'):
            stored = json.loads((self.root(name) / 'positions.json').read_text())['positions']
            trades = json.loads((self.root(name) / 'trades.json').read_text())['trades']
            self.assertTrue(stored[0]['tombstone'])
            self.assertEqual(sum(row['qty'] for row in trades), 10)
            self.assertEqual(sum(row['profit'] for row in trades), 180)

    def test_foreign_receipt_origin_is_preserved(self):
        applied = self.api().apply_packet('b', self.packet())
        self.api().apply_packet('a', self.packet('b'))
        peers = json.loads((self.root('a') / 'peer-receipts.json').read_text())
        self.assertEqual(peers['sources'][B][A], applied)
        self.assertEqual(self.api().read_receipt('b', A), applied)

    def test_packet_duplicate_traversal_symlink_fifo_and_budget_refuse(self):
        api = self.api()
        for filename, mode in (('../trades.json', 0), ('trades.json', stat.S_IFLNK),
                               ('trades.json', stat.S_IFIFO), ('private.json', 0)):
            bad = self.base / 'bad.zip'
            with zipfile.ZipFile(bad, 'w') as archive:
                archive.writestr('manifest.json', '{}')
                info = zipfile.ZipInfo(filename)
                info.external_attr = mode << 16
                archive.writestr(info, '{}')
            before = (self.root('b') / 'trades.json').read_bytes()
            with self.assertRaises(ValueError):
                api.apply_packet('b', bad)
            self.assertEqual(before, (self.root('b') / 'trades.json').read_bytes())
        packet = self.packet()
        with mock.patch.object(api, 'MAX_FILES', 1):
            with self.assertRaises(ValueError):
                api.apply_packet('b', packet)

    def test_capture_rejects_unlabelled_legacy_rows(self):
        row = self.row()
        for key in ('record_uuid', 'origin_uuid', 'revision', 'tombstone', 'legacy_id'):
            row.pop(key)
        self.write_trades('a', [row])
        with self.assertRaisesRegex(ValueError, 'explicit legacy migration'):
            self.packet()

    def test_state_cli_capture_apply_and_receipt_stdout_is_one_sanitized_json_value(self):
        from rshelper import cli
        output = self.base / 'cli.zip'
        self.write_trades('a', [self.row()])
        commands = [('a', ['capture', '--output', str(output)]),
                    ('b', ['apply', '--input', str(output)]),
                    ('b', ['receipt', '--origin', A])]
        for name, command in commands:
            stdout, stderr = io.StringIO(), io.StringIO()
            with mock.patch.object(sys, 'argv', ['rshelper', '--profile', name, 'state', *command, '--json']), \
                    contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                cli.main()
            result = json.loads(stdout.getvalue())
            self.assertIsInstance(result, dict)
            self.assertNotIn('Synthetic', stdout.getvalue())
            self.assertEqual(stderr.getvalue(), '')

    def test_apply_via_deployment_adapter_returns_exact_receipt(self):
        import importlib.util
        path = Path(__file__).resolve().parents[1] / 'deploy' / 'merge_state.py'
        spec = importlib.util.spec_from_file_location('merge_packet', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        stage = self.base / 'stage'
        stage.mkdir()
        packet = self.packet()
        (stage / 'state-packet.zip').write_bytes(packet.read_bytes())
        receipt = module.merge_dir(str(stage), str(self.root('b')), None)
        self.assertEqual(receipt, self.api().read_receipt('b', A))

    def test_empty_schema_two_refuses_legacy_writer(self):
        from rshelper import persistence
        with self.assertRaises(persistence.StateCorruptionError):
            persistence.validate_writable_state({'schema_version': 2, 'positions': []},
                                                'positions', Path('positions.json'))

    def test_concurrent_apply_publishes_once_and_truncated_packet_refuses(self):
        from concurrent.futures import ThreadPoolExecutor
        self.write_trades('a', [self.row()])
        packet = self.packet()
        with ThreadPoolExecutor(max_workers=4) as pool:
            receipts = list(pool.map(lambda _: self.api().apply_packet('b', packet), range(8)))
        self.assertEqual(sum(receipt['status'] == 'applied' for receipt in receipts), 1)
        self.assertEqual(sum(receipt['status'] == 'no_op' for receipt in receipts), 7)
        truncated = self.base / 'truncated.zip'
        truncated.write_bytes(packet.read_bytes()[:100])
        before = (self.root('b') / 'trades.json').read_bytes()
        with self.assertRaises(zipfile.BadZipFile):
            self.api().apply_packet('b', truncated)
        self.assertEqual(before, (self.root('b') / 'trades.json').read_bytes())

    def test_pinned_batch_budget_is_checked_before_write(self):
        from rshelper import realization
        path = self.base / 'batches.json'
        path.write_bytes(b'original')
        with mock.patch.object(realization, 'MAX_STATE_BYTES', 2):
            with self.assertRaises(ValueError):
                realization._persist_batches(path, {'schema_version': 1, 'batches': {}})
        self.assertEqual(path.read_bytes(), b'original')


if __name__ == '__main__':
    unittest.main()
