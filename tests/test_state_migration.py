import importlib
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from rshelper import profile, state_replication, state_transaction

A = '11111111-1111-4111-8111-111111111111'
B = '22222222-2222-4222-8222-222222222222'
P = '33333333-3333-4333-8333-333333333333'


class MigrationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        patch = mock.patch.object(profile, 'CONFIG_DIR', self.base / 'state')
        patch.start()
        self.addCleanup(patch.stop)
        for name in ('a', 'b'):
            root = profile.resolve_config_path('', name)
            root.mkdir(parents=True)
            (root / 'positions.json').write_text(json.dumps({'positions': [{
                'id': 1, 'item_id': 2, 'name': 'Synthetic', 'qty': 10, 'buy_price': 100,
                'direction': 'traditional', 'opened_at': '2026-01-01T00:00:00Z'}]}))

    def api(self):
        path = Path(__file__).resolve().parents[1] / 'src/rshelper/state_migration.py'
        self.assertTrue(path.is_file(), 'explicit hash-bound migration contract missing')
        return importlib.import_module('rshelper.state_migration')

    def plan(self, name='a', common=None):
        lineage = {'mode': 'common' if common else 'independent',
                   'financial_authority': name == 'a', 'replication_origins': [A, B]}
        if common:
            lineage['common_origin_uuid'] = common
        return self.api().plan_migration(name, origin_uuid=A if name == 'a' else B,
                                         profile_uuid=P, lineage=lineage)

    def test_changed_source_invalidates_plan(self):
        plan = self.plan()
        path = profile.resolve_config_path('positions.json', 'a')
        changed = json.loads(path.read_text())
        changed['positions'][0]['qty'] = 11
        path.write_text(json.dumps(changed))
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            self.api().migrate_profile('a', plan=plan, operation_id=B)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(path.with_name('identity-activation.json').exists())

    def test_malformed_lineage_is_rejected_without_mutation(self):
        root = profile.resolve_config_path('', 'a')
        before = (root / 'positions.json').read_bytes()
        for mode, peers in (({}, [A]), ('independent', [{}]), ('independent', [True])):
            with self.subTest(mode=mode, peers=peers), self.assertRaises(ValueError):
                self.api().plan_migration('a', origin_uuid=A, profile_uuid=P,
                    lineage={'mode': mode, 'financial_authority': True, 'replication_origins': peers})
        self.assertEqual((root / 'positions.json').read_bytes(), before)
        self.assertFalse((root / 'identity-activation.json').exists())

    def test_migration_restart_keeps_every_uuid(self):
        plan = self.plan()
        root = profile.resolve_config_path('', 'a')
        def interrupt(step):
            if step == 'data:positions.json':
                raise OSError('interrupted migration')
        with mock.patch.object(state_transaction, '_checkpoint', side_effect=interrupt):
            with self.assertRaises(OSError):
                self.api().migrate_profile('a', plan=plan, operation_id=B)
        state_transaction.recover_profile(root)
        before = (root / 'positions.json').read_bytes()
        first = self.api().migrate_profile('a', plan=plan, operation_id=B)
        again = self.api().migrate_profile('a', plan=plan, operation_id=B)
        self.assertEqual(first, again)
        self.assertEqual((root / 'positions.json').read_bytes(), before)
        self.assertEqual(first['profile_uuid'], P)

    def test_killed_migration_recovers_without_resubmission(self):
        import os
        import subprocess
        plan = self.plan()
        code = (
            'import json,os,sys; from pathlib import Path; '
            'from rshelper import profile,state_migration,state_transaction; '
            'profile.CONFIG_DIR=Path(sys.argv[1]); '
            'state_transaction._checkpoint=lambda step: os._exit(91) if step=="receipt-published" else None; '
            'state_migration.migrate_profile("a",plan=json.loads(sys.argv[2]),operation_id=sys.argv[3])'
        )
        result = subprocess.run([sys.executable, '-c', code, str(profile.CONFIG_DIR), json.dumps(plan), B],
            env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')},
            capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 91, result.stderr.decode())
        root = profile.resolve_config_path('', 'a')
        state_transaction.recover_profile(root)
        receipt = json.loads((root / 'migration-receipts.json').read_text())['operations'][B]
        self.assertEqual(receipt['plan_hash'], hashlib.sha256(state_replication._json(plan)).hexdigest())
        self.assertEqual(json.loads((root / 'positions.json').read_text())['positions'][0]['qty'], 10)
        self.assertFalse((root / '.profile-pending.json').exists())

    def test_migration_cli_stdout_contains_only_plan_receipt_or_contract(self):
        import contextlib
        import io
        from rshelper import cli
        lineage = self.base / 'lineage.json'
        lineage.write_text(json.dumps({'mode': 'independent', 'financial_authority': True,
                                       'replication_origins': [A, B]}))
        output = io.StringIO()
        with contextlib.redirect_stdout(output), mock.patch.object(sys, 'argv',
                ['rshelper', '--profile', 'a', 'state', 'migration-plan', '--origin', A,
                 '--profile-uuid', P, '--lineage', str(lineage), '--json']):
            cli.main()
        plan = self.base / 'plan.json'
        plan.write_text(output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['profile_uuid'], P)
        for command in (['migrate', '--plan', str(plan), '--operation-id', B, '--json'],
                        ['check', '--json']):
            output = io.StringIO()
            with contextlib.redirect_stdout(output), mock.patch.object(sys, 'argv',
                    ['rshelper', '--profile', 'a', 'state', *command]):
                cli.main()
            report = json.loads(output.getvalue())
            self.assertEqual(report['profile_uuid'], P)
            self.assertNotIn('Synthetic', output.getvalue())

    def test_legacy_common_lineage_not_double_counted(self):
        from rshelper import state_replication, realization, journal, positions, watchlist, alerts
        self.api().migrate_profile('a', plan=self.plan(), operation_id=B)
        self.api().migrate_profile('b', plan=self.plan('b', common=A), operation_id=A)
        packet = self.base / 'first.zip'
        state_replication.capture_packet('a', packet)
        self.assertEqual(state_replication.apply_packet('b', packet)['status'], 'applied')
        root = profile.resolve_config_path('', 'b')
        self.assertEqual(len(json.loads((root / 'positions.json').read_text())['positions']), 1)
        lot = positions.list_positions('a')[0]
        realization.close_and_realize('a', lot.lot_uid, 10, 120, P, 'manual')
        positions.open_position(2, 'Synthetic', 3, 110, profile='a')
        watchlist.add(561, 'Nature rune', profile='a')
        alerts.push_alert('system', 'INFO', None, '', 'Fixture', 'Synthetic', profile='b')
        alerts.mark_read(all=True, profile='b')
        second = self.base / 'second.zip'
        state_replication.capture_packet('a', second)
        self.assertEqual(state_replication.apply_packet('b', second)['status'], 'applied')
        returned = self.base / 'returned.zip'
        state_replication.capture_packet('b', returned)
        self.assertEqual(state_replication.apply_packet('a', returned)['status'], 'applied')
        realization.recover_pending('a')
        for name in ('a', 'b'):
            self.assertEqual(sum(lot.qty for lot in positions.list_positions(name)), 3)
            self.assertEqual(sum(trade.profit for trade in journal.list_trades(profile=name)), 180)
            self.assertTrue(state_replication.validate_profile(name)['initialized'])

    def test_ambiguous_lineage_requires_resolution(self):
        with self.assertRaises(ValueError):
            self.api().plan_migration('a', origin_uuid=A, profile_uuid=P,
                lineage={'financial_authority': True, 'replication_origins': [A, B]})
        with self.assertRaises(ValueError):
            self.api().plan_migration('a', origin_uuid=A, profile_uuid=P,
                lineage={'mode': 'resolved', 'financial_authority': True,
                         'replication_origins': [A, B], 'record_origins': {}})

    def test_financial_authority_cannot_adopt_foreign_open_lots(self):
        with self.assertRaises(ValueError):
            self.plan('a', common=B)

    def test_independent_numeric_collision_retains_both_lots(self):
        from rshelper import state_replication, positions
        self.api().migrate_profile('a', plan=self.plan(), operation_id=B)
        self.api().migrate_profile('b', plan=self.plan('b'), operation_id=A)
        packet = self.base / 'independent.zip'
        state_replication.capture_packet('a', packet)
        state_replication.apply_packet('b', packet)
        self.assertEqual(len(positions.list_positions('b')), 2)


if __name__ == '__main__':
    unittest.main()
