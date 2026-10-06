"""Recoverable profile-wide state transactions on disposable homes."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from rshelper import persistence, state_transaction

ORIGIN = '11111111-1111-4111-8111-111111111111'
OPERATION = '22222222-2222-4222-8222-222222222221'
POSITION = {'id': 1, 'item_id': 2, 'name': 'Lot', 'qty': 10, 'buy_price': 100,
            'direction': 'traditional', 'opened_at': '2026-01-01T00:00:00Z'}
TRADE = {'id': 1, 'item_id': 2, 'name': 'Lot', 'qty': 10, 'buy_price': 100,
         'sell_price': 120, 'tax_paid': 2, 'profit': 18,
         'timestamp': '2026-01-01T01:00:00Z'}


class TransactionTest(unittest.TestCase):
    def transaction(self, root, updates, operation=OPERATION):
        with state_transaction.profile_transaction('default', Path(root)) as txn:
            for name, data in updates.items():
                txn.stage(name, data)
            return txn.commit(operation_id=operation)

    def test_commit_publishes_staged_files_and_durable_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            receipt = self.transaction(root, {
                'positions.json': {'positions': [POSITION]},
                'trades.json': {'trades': [TRADE]},
            })
            self.assertEqual(receipt['operation_id'], OPERATION)
            self.assertEqual(receipt['files'], ['positions.json', 'trades.json'])
            durable = json.loads(state_transaction.receipt_path(root).read_text())
            self.assertEqual(durable, receipt)
            for name in receipt['files']:
                payload = (root / name).read_bytes()
                self.assertEqual(receipt['hashes'][name],
                                 __import__('hashlib').sha256(payload).hexdigest())
            self.assertEqual(persistence.read_state(root / 'positions.json', 'positions')['positions'][0], POSITION)
            self.assertEqual(persistence.read_state(root / 'trades.json', 'trades')['trades'][0], TRADE)
            self.assertFalse((root / 'alerts.json').exists())

    def test_unknown_file_rejected_without_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with self.assertRaises(ValueError):
                self.transaction(root, {'notes.txt': {'anything': True}})
            self.assertEqual(list(root.iterdir()), [])
            self.assertFalse(state_transaction.receipt_path(root).exists())

    def test_read_snapshot_missing_files_are_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            snapshot = state_transaction.read_profile_snapshot('default', Path(folder))
            self.assertEqual(snapshot['positions'], {'positions': []})
            self.assertEqual(snapshot['trades'], {'trades': []})
            self.assertEqual(snapshot['alerts'], {'alerts': [], 'watch_triggered': {}})
            self.assertEqual(snapshot['watchlist'], {'items': {}})

    def test_activated_profile_refuses_legacy_writer(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / 'positions.json'
            path.write_text(json.dumps({'positions': []}))
            with persistence.locked_writable_state(path, 'positions'):
                pass
            state_transaction.activate_profile(root, ORIGIN)
            before = path.read_bytes()
            with self.assertRaises(persistence.StateCorruptionError):
                with persistence.locked_writable_state(path, 'positions'):
                    pass
            self.assertEqual(before, path.read_bytes())
            self.assertTrue(state_transaction.activation_path(root).exists())

    def test_read_blocks_during_partial_publish(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / 'positions.json'
            path.write_text(json.dumps({'positions': []}))
            state_transaction._publish_marker_only(path)
            with self.assertRaises(persistence.StateCorruptionError):
                persistence.read_state(path, 'positions')

    def test_profile_lock_precedes_sorted_file_locks(self):
        record = []

        class Probe:
            def __init__(self, name):
                self.name = name
            def __enter__(self):
                record.append(('enter', self.name))
                return self
            def __exit__(self, *exception):
                record.append(('exit', self.name))

        original_lock = state_transaction._ProfileLock
        original_locked = state_transaction.locked_state
        state_transaction._ProfileLock = lambda root: Probe('profile')
        state_transaction.locked_state = lambda path: Probe(str(path))
        try:
            with state_transaction._ordered_locks(Path('/root'), [Path('/root/b.json'), Path('/root/a.json')]):
                record.append(('body',))
        finally:
            state_transaction._ProfileLock = original_lock
            state_transaction.locked_state = original_locked
        self.assertEqual(record, [('enter', 'profile'), ('enter', '/root/a.json'),
                                  ('enter', '/root/b.json'), ('body',),
                                  ('exit', '/root/b.json'), ('exit', '/root/a.json'),
                                  ('exit', 'profile')])


class RecoveryTest(unittest.TestCase):
    WORKER = '''
import os, sys
from pathlib import Path
from rshelper import state_transaction
root, mode = Path(sys.argv[1]), sys.argv[2]
def checkpoint(step):
    if step == mode:
        os._exit(9)
state_transaction._checkpoint = checkpoint
payloads = {
    'positions.json': {'positions': []},
    'trades.json': {'trades': []},
    'alerts.json': {'alerts': [], 'watch_triggered': {}},
    'watchlist.json': {'items': {}},
}
with state_transaction.profile_transaction('default', root) as txn:
    for name, payload in payloads.items():
        txn.stage(name, payload)
    txn.commit(operation_id='22222222-2222-4222-8222-222222222221')
'''

    def run_worker(self, root, mode):
        environment = dict(os.environ)
        environment['PYTHONPATH'] = str(Path(__file__).resolve().parents[1] / 'src')
        return subprocess.run([sys.executable, '-c', self.WORKER, str(root), mode],
                              env=environment, capture_output=True, text=True, timeout=60)

    def test_kill_after_each_publish_step_recovers(self):
        kinds = {'positions.json': 'positions', 'trades.json': 'trades',
                 'alerts.json': 'alerts', 'watchlist.json': 'watchlist'}
        for step in ('data:positions.json', 'data:trades.json', 'data:alerts.json',
                     'data:watchlist.json', 'receipt'):
            with self.subTest(step=step):
                with tempfile.TemporaryDirectory() as folder:
                    root = Path(folder)
                    killed = self.run_worker(root, step)
                    self.assertEqual(killed.returncode, 9, killed.stderr)
                    if step.startswith('data:'):
                        name = step.split(':', 1)[1]
                        with self.assertRaises(persistence.StateCorruptionError):
                            persistence.read_state(root / name, kinds[name])
                    completed = self.run_worker(root, 'none')
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                    self.assertFalse(any(root.glob('.*.publishing')))
                    self.assertTrue(state_transaction.receipt_path(root).exists())


if __name__ == '__main__':
    unittest.main()
