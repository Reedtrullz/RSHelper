"""Native identity writers: authority, durable revisions and replayed attestations."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from rshelper import alerts, journal, persistence, positions, profile, state_identity, state_transaction, watchlist

ORIGIN = '11111111-1111-4111-8111-111111111111'
OPERATION = '22222222-2222-4222-8222-222222222221'
OPERATION2 = '22222222-2222-4222-8222-222222222222'


class DisposableHomeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self._swap(profile, 'CONFIG_DIR', self.tmp / 'config')
        self._swap(positions, 'POSITIONS_PATH', self.tmp / 'config' / 'positions.json')
        self._swap(journal, 'TRADES_PATH', self.tmp / 'config' / 'trades.json')
        self._swap(watchlist, 'WATCHLIST_PATH', self.tmp / 'config' / 'watchlist.json')

    def _swap(self, module, name, value):
        original = getattr(module, name)
        setattr(module, name, value)
        self.addCleanup(setattr, module, name, original)

    def activate(self, financial_authority=True):
        return state_transaction.activate_profile(
            profile.CONFIG_DIR, ORIGIN, financial_authority=financial_authority)


class NativeWriterTest(DisposableHomeTest):
    def trade_payload(self):
        return dict(item_id=2, name='Lot', qty=10, buy_price=100, sell_price=120)

    def test_same_tick_watch_readd_has_new_uuid(self):
        self.activate()
        watchlist.add(561, 'Nature rune', operation_id=OPERATION)
        first = watchlist.load()['items']['561']
        self.assertTrue(watchlist.remove(561))
        tombstone = watchlist.load()['tombstones'][first['record_uuid']]
        self.assertTrue(tombstone['tombstone'])
        watchlist.add(561, 'Nature rune', operation_id=OPERATION2)
        second = watchlist.load()['items']['561']
        self.assertNotEqual(second['record_uuid'], first['record_uuid'])
        self.assertEqual(second['origin_uuid'], ORIGIN)
        self.assertIn(first['record_uuid'], watchlist.load()['tombstones'])

    def test_read_delete_revision_survives_restart(self):
        self.activate()
        trade = journal.log_trade(operation_id=OPERATION, **self.trade_payload())
        self.assertEqual(trade.profit, 180)
        self.assertTrue(journal.delete_trade(trade.id))
        store = persistence.read_state(journal._trades_path(), 'trades')
        row = store['trades'][0]
        self.assertTrue(row['tombstone'])
        self.assertEqual(row['revision'], 1)
        self.assertEqual(row['id'], trade.id)
        self.assertEqual(journal.list_trades(), [])
        self.assertEqual(journal.compute_pnl().trade_count, 0)
        reread = persistence.read_state(journal._trades_path(), 'trades')
        self.assertEqual(reread, store)

    def test_replica_financial_writer_refuses_without_mutation(self):
        self.activate(financial_authority=False)
        trades_path = journal._trades_path()
        before = trades_path.read_bytes() if trades_path.exists() else None
        with self.assertRaises(ValueError):
            journal.log_trade(operation_id=OPERATION, **self.trade_payload())
        with self.assertRaises(ValueError):
            positions.open_position(2, 'Lot', 10, 100, operation_id=OPERATION)
        after = trades_path.read_bytes() if trades_path.exists() else None
        self.assertEqual(before, after)

    def test_native_trade_attestation_replays_without_uuid_change(self):
        self.activate()
        first = journal.log_trade(operation_id=OPERATION, **self.trade_payload())
        store = persistence.read_state(journal._trades_path(), 'trades')
        replay = journal.log_trade(operation_id=OPERATION, **self.trade_payload())
        self.assertEqual(replay.id, first.id)
        reread = persistence.read_state(journal._trades_path(), 'trades')
        self.assertEqual(reread['trades'], store['trades'])
        row = reread['trades'][0]
        self.assertEqual(row['record_uuid'],
                         state_identity.new_record_identity(
                             ORIGIN, 'trades', OPERATION)['record_uuid'])
        self.assertEqual(row['origin_uuid'], ORIGIN)

    def test_normal_callers_create_durable_native_lineage(self):
        self.activate()
        lot = positions.open_position(2, 'Lot', 10, 100)
        trade = journal.log_trade(**self.trade_payload())
        alert = alerts.push_alert('system', 'INFO', None, '', 'Test', 'Synthetic')
        watchlist.add(561, 'Nature rune')
        root = profile.CONFIG_DIR
        manifest = persistence.read_state(root / 'identity-manifest.json', 'generic')
        self.assertEqual(len(manifest['native']), 4)
        self.assertEqual(lot.origin_uuid, ORIGIN)
        self.assertEqual(trade.origin_uuid, ORIGIN)
        self.assertEqual(alert.origin_uuid, ORIGIN)
        rows = persistence.read_state(root / 'positions.json', 'positions')['positions']
        migrated, _ = state_identity.migrate_rows(rows, 'positions', manifest)
        self.assertEqual(migrated, rows)

    def test_creation_retry_cannot_change_economics(self):
        self.activate()
        journal.log_trade(operation_id=OPERATION, **self.trade_payload())
        before = journal._trades_path().read_bytes()
        with self.assertRaises(ValueError):
            journal.log_trade(operation_id=OPERATION,
                              **{**self.trade_payload(), 'qty': 11})
        self.assertEqual(before, journal._trades_path().read_bytes())

    def test_new_lot_preserves_completed_close_proof(self):
        from rshelper import realization
        self.activate()
        first = positions.open_position(2, 'Lot', 10, 100, operation_id=OPERATION)
        receipt = realization.close_and_realize('default', first.lot_uid, 10, 120,
                                               OPERATION2, 'manual')
        proof = persistence.read_state(positions._positions_path(), 'positions')['realizations']
        positions.open_position(2, 'Lot', 3, 110)
        self.assertEqual(proof, persistence.read_state(positions._positions_path(), 'positions')['realizations'])
        realization.recover_pending('default')
        self.assertEqual(receipt['trade_ids'], [journal.list_trades()[0].id])
        self.assertEqual(journal.list_trades()[0].profit, 180)

    def test_watch_update_preserves_generation_and_advances_revision(self):
        self.activate()
        watchlist.add(561, 'Nature rune', operation_id=OPERATION)
        first = watchlist.load()['items']['561']
        watchlist.add(561, 'Nature rune', alert_margin_above=10,
                      operation_id=OPERATION2)
        second = watchlist.load()['items']['561']
        self.assertEqual(first['record_uuid'], second['record_uuid'])
        self.assertEqual(second['revision'], 1)
        watchlist.add(561, 'Nature rune', alert_margin_above=10,
                      operation_id=OPERATION2)
        self.assertEqual(watchlist.load()['items']['561'], second)

    def test_identified_alert_replay_read_and_prune_retain_evidence(self):
        from unittest import mock
        self.activate()
        with mock.patch.object(alerts.time, 'time', return_value=1.0):
            first = alerts.push_alert('system', 'INFO', None, '', 'Test', 'Synthetic',
                                      operation_id=OPERATION)
        replay = alerts.push_alert('system', 'INFO', None, '', 'Test', 'Synthetic',
                                   operation_id=OPERATION)
        self.assertEqual(first.id, replay.id)
        self.assertEqual(alerts.mark_read(ids=[first.id]), 1)
        alerts.push_alert('system', 'INFO', None, '', 'New', 'Synthetic')
        rows = persistence.read_state(alerts._alerts_path(), 'alerts')['alerts']
        old = next(row for row in rows if row['id'] == first.id)
        self.assertTrue(old['tombstone'])
        self.assertEqual(old['revision'], 2)

    def test_auxiliary_writer_obeys_capture_lock(self):
        record = []

        class Probe:
            def __init__(self, root):
                self.root = root
            def __enter__(self):
                record.append(('enter', str(self.root)))
                return self
            def __exit__(self, *exception):
                record.append(('exit', str(self.root)))

        original = state_transaction._ProfileLock
        state_transaction._ProfileLock = Probe
        try:
            from rshelper import signals
            signals._save_cooldowns({'2': 12.5})
        finally:
            state_transaction._ProfileLock = original
        self.assertEqual(record[0][0], 'enter')
        self.assertEqual(record[-1][0], 'exit')

    def test_real_baseline_save_completes_and_preserves_failure_handling(self):
        import json
        from unittest import mock
        from rshelper import signals
        path = profile.resolve_config_path('volume_baseline.json', 'synthetic')
        signals._save_baselines({'561': 12.5}, 'synthetic')
        self.assertEqual(json.loads(path.read_text()), {'561': 12.5})
        before = path.read_bytes()
        with mock.patch.object(signals.os, 'replace', side_effect=OSError('fixture failure')):
            with self.assertRaises(OSError):
                signals._save_baselines({'561': 99.0}, 'synthetic')
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(path.parent.glob('*.tmp')), [])

    def test_threshold_update_and_dedupe_clear_recover_together(self):
        from unittest import mock
        self.activate()
        watchlist.add(561, 'Nature rune')
        alerts.set_watch_triggered(561)
        def interrupt(step):
            if step == 'data:watchlist.json':
                raise OSError('fixture interrupted threshold update')
        with mock.patch.object(state_transaction, '_checkpoint', side_effect=interrupt):
            with self.assertRaises(OSError):
                alerts.update_watch_alerts(561, 10, None)
        state_transaction.recover_profile(profile.CONFIG_DIR)
        self.assertEqual(watchlist.load()['items']['561']['alert_margin_above'], 10)
        self.assertNotIn('561', alerts._load()['watch_triggered'])

    def test_corrupt_activation_does_not_crash_alert_caller(self):
        from contextlib import redirect_stderr
        import io
        profile.CONFIG_DIR.mkdir(parents=True)
        (profile.CONFIG_DIR / 'identity-activation.json').write_text('{}')
        warning = io.StringIO()
        with redirect_stderr(warning):
            fallback = alerts.push_alert('system', 'INFO', None, '', 'Fixture', 'Synthetic')
        self.assertIsNone(fallback.record_uuid)
        self.assertIn('could not persist', warning.getvalue())
        self.assertFalse((profile.CONFIG_DIR / 'alerts.json').exists())


class AuthorityUnitTest(unittest.TestCase):
    def test_new_record_identity_is_deterministic_and_kind_scoped(self):
        first = state_identity.new_record_identity(ORIGIN, 'trades', OPERATION)
        second = state_identity.new_record_identity(ORIGIN, 'trades', OPERATION)
        other = state_identity.new_record_identity(ORIGIN, 'positions', OPERATION)
        self.assertEqual(first, second)
        self.assertNotEqual(first['record_uuid'], other['record_uuid'])
        self.assertEqual(first['revision'], 0)
        self.assertFalse(first['tombstone'])
        with self.assertRaises(ValueError):
            state_identity.new_record_identity('nope', 'trades', OPERATION)

    def test_require_financial_authority_gate(self):
        state_identity.require_financial_authority(
            {'mode': 'identified', 'financial_authority': True, 'origin_uuid': ORIGIN})
        with self.assertRaises(ValueError):
            state_identity.require_financial_authority(
                {'mode': 'identified', 'financial_authority': False, 'origin_uuid': ORIGIN})
        with self.assertRaises(ValueError):
            state_identity.require_financial_authority({'mode': 'legacy'})


if __name__ == '__main__':
    unittest.main()
