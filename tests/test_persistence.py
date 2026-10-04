"""Corrupt state and lock failures must never turn into destructive writes."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from rshelper import journal, positions, watchlist, alerts, profile


class TestPersistence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for module, key, value in [(journal, 'TRADES_PATH', self.root / 'trades.json'),
                (positions, 'POSITIONS_PATH', self.root / 'positions.json'),
                (watchlist, 'WATCHLIST_PATH', self.root / 'watchlist.json'),
                (profile, 'CONFIG_DIR', self.root), (profile, 'ACTIVE_PROFILE_PATH', self.root / 'active_profile')]:
            patch = mock.patch.object(module, key, value)
            patch.start()
            self.addCleanup(patch.stop)

    def test_corrupt_load_then_append_preserves_bytes(self):
        operations = [('trades.json', lambda: journal.log_trade(2, 'Cannonball', 1, 100, 110)),
                      ('positions.json', lambda: positions.open_position(2, 'Cannonball', 1, 100)),
                      ('watchlist.json', lambda: watchlist.add(2, 'Cannonball')),
                      ('alerts.json', lambda: alerts.push_alert('system', 'INFO', None, '', 'test', 'test'))]
        for filename, operation in operations:
            for raw in ('{', '[]', '{}', '{"'+filename[:-5]+'": [true]}'):
                path = self.root / filename
                path.write_text(raw)
                try:
                    operation()
                except (ValueError, OSError, TypeError, AttributeError):
                    pass
                self.assertEqual(path.read_text(), raw, filename)

    def test_position_extensions_survive_and_invalid_mutation_preserves(self):
        positions.open_position(2, 'Fixture', 1, 100)
        path = self.root / 'positions.json'
        data = json.loads(path.read_text())
        data['extension'] = {'kept': True}
        data['positions'][0]['future'] = 'preserve'
        path.write_text(json.dumps(data))
        positions.open_position(3, 'Second', 1, 100)
        saved = json.loads(path.read_text())
        self.assertEqual(saved['extension'], {'kept': True})
        self.assertEqual(saved['positions'][0]['future'], 'preserve')
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            positions.open_position(True, 'Invalid', 1, 100)
        self.assertEqual(path.read_bytes(), before)

    def test_threshold_update_preserves_concurrent_watch_add(self):
        import threading
        watchlist.add(2, 'Fixture')
        loaded, attempted, finished = threading.Event(), threading.Event(), threading.Event()
        original = watchlist.load
        errors = []
        def gated(profile=None):
            data = original(profile)
            if threading.current_thread().name == 'threshold':
                loaded.set()
                attempted.wait(2)
                finished.wait(0.2)
            return data
        def update():
            try:
                alerts.update_watch_alerts(2, 5, None, 'default')
            except Exception as exc:
                errors.append(exc)
        def add():
            loaded.wait(2)
            attempted.set()
            try:
                watchlist.add(3, 'Concurrent')
            except Exception as exc:
                errors.append(exc)
            finally:
                finished.set()
        with mock.patch.object(watchlist, 'load', side_effect=gated):
            threads = [threading.Thread(target=update, name='threshold'), threading.Thread(target=add)]
            for thread in threads: thread.start()
            for thread in threads: thread.join(3)
            self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        saved = watchlist.load('default')['items']
        self.assertIn('3', saved)
        self.assertEqual(saved['2']['alert_margin_above'], 5)

    def test_missing_file_initializes_normally(self):
        journal.log_trade(2, 'Cannonball', 1, 100, 110)
        positions.open_position(2, 'Cannonball', 1, 100)
        watchlist.add(2, 'Cannonball')
        alerts.push_alert('system', 'INFO', None, '', 'test', 'test')
        for name in ('trades', 'positions', 'watchlist', 'alerts'):
            self.assertIsInstance(json.loads((self.root / (name+'.json')).read_text()), dict)

    def test_lock_failure_blocks_write(self):
        import fcntl
        with mock.patch.object(fcntl, 'flock', side_effect=OSError('fixture lock unavailable')):
            with self.assertRaises(OSError):
                journal.log_trade(2, 'Cannonball', 1, 100, 110)
        self.assertFalse((self.root / 'trades.json').exists())

    def test_unknown_supported_fields_survive_roundtrip(self):
        journal.log_trade(2, 'Cannonball', 1, 100, 110)
        path = self.root / 'trades.json'
        data = json.loads(path.read_text())
        data['extension'] = {'owner': 'fixture'}
        data['trades'][0]['future_field'] = {'keep': True}
        path.write_text(json.dumps(data))
        journal.log_trade(2, 'Cannonball', 1, 100, 120)
        result = json.loads(path.read_text())
        self.assertEqual(result['extension'], data['extension'])
        self.assertEqual(result['trades'][0]['future_field'], {'keep': True})
        self.assertEqual(len(journal.list_trades()), 2)

    def test_wrong_required_types_and_future_schema_fail(self):
        from rshelper.persistence import read_state, StateCorruptionError
        journal.log_trade(2, 'Cannonball', 1, 100, 110)
        path = self.root / 'trades.json'
        good = json.loads(path.read_text())
        for patch in ({'qty': True}, {'id': None}, {'timestamp': 'not a date'}):
            data = json.loads(json.dumps(good))
            data['trades'][0].update(patch)
            path.write_text(json.dumps(data))
            with self.assertRaises(StateCorruptionError):
                read_state(path, 'trades')
        path.write_text(json.dumps({**good, 'schema_version': 999}))
        with self.assertRaises(StateCorruptionError):
            read_state(path, 'trades')

    def test_nested_process_lock_is_reentrant(self):
        import os
        import subprocess
        path = self.root / 'nested.json'
        code = ('from pathlib import Path; from rshelper.persistence import locked_state\n'
                f'p=Path({str(path)!r})\n'
                'with locked_state(p):\n with locked_state(p): pass\n')
        result = subprocess.run([sys.executable, '-c', code],
                                env={**os.environ, 'PYTHONPATH': 'src'},
                                capture_output=True, text=True, timeout=2)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_extension_depth_and_exponent_overflow_fail_closed(self):
        from rshelper.persistence import read_state, StateCorruptionError
        journal.log_trade(2, 'Cannonball', 1, 100, 110)
        path = self.root / 'trades.json'
        good = json.loads(path.read_text())
        nested = True
        for _ in range(66):
            nested = [nested]
        good['extension'] = nested
        path.write_text(json.dumps(good))
        with self.assertRaises(StateCorruptionError):
            read_state(path, 'trades')
        path.write_text(json.dumps({**json.loads(json.dumps(good)), 'extension': 1e999}))
        with self.assertRaises(StateCorruptionError):
            read_state(path, 'trades')
        raw = path.read_text().replace('Infinity', '1e999')
        path.write_text(raw)
        with self.assertRaises(StateCorruptionError):
            read_state(path, 'trades')

    def test_generic_json_snapshot_is_bounded_and_future_schema_rejected(self):
        from rshelper.persistence import read_state, StateCorruptionError
        path = self.root / 'snapshot.json'
        path.write_text('{"schema_version":1,"items":[{"price":1.25}],"future":{"ok":true}}')
        result = read_state(path, 'generic')
        self.assertEqual(result['future'], {'ok': True})
        path.write_text('{"schema_version":999,"items":[]}')
        with self.assertRaises(StateCorruptionError):
            read_state(path, 'generic')

    def test_broken_symlink_is_corrupt_not_a_missing_default(self):
        from rshelper.persistence import read_state, StateCorruptionError
        path = self.root / 'trades.json'
        path.symlink_to(self.root / 'absent.json')
        with self.assertRaises(StateCorruptionError):
            read_state(path, 'trades')

    def test_zero_item_id_trade_roundtrips_but_position_requires_positive_id(self):
        from rshelper.persistence import read_state, validate_state, StateCorruptionError
        journal.log_trade(0, 'Legacy unresolved item', 1, 100, 110)
        path = self.root / 'trades.json'
        saved = read_state(path, 'trades')
        self.assertEqual(saved['trades'][0]['item_id'], 0)
        self.assertEqual(journal.list_trades()[0].item_id, 0)
        invalid_position = {'positions': [{
            'id': 1, 'item_id': 0, 'qty': 1, 'buy_price': 100,
            'name': 'Legacy unresolved item', 'direction': 'traditional',
            'opened_at': '2026-01-01T00:00:00Z'}]}
        with self.assertRaises(StateCorruptionError):
            validate_state(invalid_position, 'positions', self.root / 'positions.json')


if __name__ == '__main__':
    unittest.main()
