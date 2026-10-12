"""Cross-process watch events, rule changes and delivery preservation."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from rshelper import alerts, profile, watchlist

class WatchCrossingsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='rshelper-crossing-')
        self.root = (Path(self.temp.name)/'.config/rshelper').resolve()
        self.stack = __import__('contextlib').ExitStack()
        self.stack.enter_context(mock.patch.object(profile, 'CONFIG_DIR', self.root))
        self.stack.enter_context(mock.patch.object(watchlist, 'WATCHLIST_PATH', self.root/'watchlist.json'))
        self.now = time.time()
        watchlist.add(561, 'Synthetic', alert_margin_above=100)
    def tearDown(self):
        self.stack.close(); self.temp.cleanup()
    def emit(self, margin, seconds=0, **kwargs):
        return alerts.emit_watch_if_due('default', 561, margin,
            now=self.now+seconds, source_revision='fixture', **kwargs)
    def test_persistent_breach_is_one_crossing_until_recovery(self):
        self.assertIsNotNone(self.emit(101))
        self.assertIsNone(self.emit(102, 1000))
        self.assertIsNone(self.emit(90, 1001))
        self.assertIsNotNone(self.emit(101, 1002))
        self.assertEqual(len(alerts.list_alerts()), 2)
    def test_hysteresis_and_cooldown_delay_new_episode(self):
        alerts.update_watch_alerts(561, 100, None, policy={
            'mode': 'crossing', 'cooldown_sec': 900, 'hysteresis_gp': 10})
        self.assertIsNotNone(self.emit(101))
        self.assertIsNone(self.emit(95, 1000))
        self.assertIsNone(self.emit(101, 1001))
        self.assertIsNone(self.emit(90, 1002))
        self.assertIsNotNone(self.emit(101, 1003))
        self.assertIsNone(self.emit(90, 1004))
        self.assertIsNone(self.emit(101, 1005))
        self.assertIsNotNone(self.emit(101, 2004))
    def test_reminder_mode_repeats_only_after_cooldown(self):
        alerts.update_watch_alerts(561, 100, None, policy={
            'mode': 'reminder', 'cooldown_sec': 900, 'hysteresis_gp': 0})
        self.assertIsNotNone(self.emit(101))
        self.assertIsNone(self.emit(101, 899))
        self.assertIsNotNone(self.emit(101, 900))
    def test_threshold_revision_resets_episode_without_losing_other_item(self):
        self.emit(101)
        watchlist.add(562, 'Other', alert_margin_below=50)
        alerts.update_watch_alerts(561, 90, None)
        self.assertIsNotNone(self.emit(101, 1))
        self.assertIn('562', watchlist.load()['items'])
    def test_failed_notification_retains_durable_event_and_status(self):
        notify = mock.Mock(side_effect=RuntimeError('fixture delivery'))
        result = self.emit(101, notify_fn=notify)
        self.assertIsNotNone(result)
        self.assertEqual(len(alerts.list_alerts()), 1)
        self.assertEqual(alerts._load()['watch_crossings']['561']['notification_status'], 'failed')
        self.assertIsNone(self.emit(101, 1000, notify_fn=notify))
        self.assertEqual(notify.call_count, 1)
    def test_two_real_processes_create_one_event(self):
        env = dict(os.environ, HOME=self.temp.name,
                   PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
        code = "from rshelper.alerts import emit_watch_if_due; emit_watch_if_due('default',561,101,source_revision='fixture')"
        workers = [subprocess.Popen([sys.executable, '-c', code], env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
        results = [(worker, worker.communicate(timeout=20)) for worker in workers]
        for worker, (_, error) in results:
            self.assertEqual(worker.returncode, 0, error.decode())
        self.assertEqual(len(alerts.list_alerts()), 1)
    def test_invalid_policy_is_rejected_before_any_write(self):
        original = watchlist.load()
        with self.assertRaises(ValueError):
            alerts.update_watch_alerts(561, 100, None, policy={'mode':'crossing','cooldown_sec':-1,'hysteresis_gp':0})
        self.assertEqual(watchlist.load(), original)

    def test_concurrent_threshold_edits_retain_both_items(self):
        watchlist.add(562, 'Other', alert_margin_above=100)
        env = dict(os.environ, HOME=self.temp.name,
                   PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
        code = "from rshelper.alerts import update_watch_alerts; import sys; update_watch_alerts(int(sys.argv[1]),200,None)"
        workers = [subprocess.Popen([sys.executable, '-c', code, str(item)], env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE) for item in (561,562)]
        results = [(worker, worker.communicate(timeout=20)) for worker in workers]
        for worker, (_, error) in results:
            self.assertEqual(worker.returncode, 0, error.decode())
        self.assertEqual([row['alert_margin_above'] for row in watchlist.load()['items'].values()], [200,200])

    def test_interrupted_event_publication_recovers_once(self):
        from rshelper import state_transaction
        def checkpoint(step):
            if step == 'intent':
                raise RuntimeError('synthetic interruption')
        with mock.patch.object(state_transaction, '_checkpoint', side_effect=checkpoint), self.assertRaises(RuntimeError):
            self.emit(101)
        state_transaction.recover_profile(self.root)
        self.assertIsNone(self.emit(101, 1))
        self.assertEqual(len(alerts.list_alerts()), 1)

    def test_profile_observations_are_isolated(self):
        watchlist.add(561, 'Other profile', alert_margin_above=100, profile='other')
        self.emit(101)
        self.assertIsNotNone(alerts.emit_watch_if_due('other', 561, 101, now=self.now,
                                                    source_revision='fixture'))
        self.assertEqual(len(alerts.list_alerts(profile='other')), 1)

    def test_name_edits_preserve_rule_and_cleared_threshold_never_reminds(self):
        self.emit(101)
        watchlist.add(561, 'Renamed', alert_margin_above=100)
        self.assertIsNone(self.emit(101, 1000))
        alerts.update_watch_alerts(561, None, None)
        self.assertIsNone(self.emit(101, 2000))
        self.assertNotIn('561', alerts._load()['watch_crossings'])

    def test_watch_add_preserves_configured_policy(self):
        policy = {'mode':'reminder','cooldown_sec':60,'hysteresis_gp':10}
        alerts.update_watch_alerts(561, 100, None, policy=policy)
        watchlist.add(561, 'Renamed')
        self.assertEqual(watchlist.load()['items']['561']['alert_policy'], policy)

    def test_watch_add_policy_and_episode_reset_publish_together(self):
        from rshelper import state_transaction
        self.emit(101)
        policy = {'mode':'reminder','cooldown_sec':60,'hysteresis_gp':10}
        def checkpoint(step):
            if step == 'intent':
                raise RuntimeError('synthetic interruption')
        with mock.patch.object(state_transaction, '_checkpoint', side_effect=checkpoint), self.assertRaises(RuntimeError):
            watchlist.add(561, 'Renamed', alert_policy=policy)
        state_transaction.recover_profile(self.root)
        self.assertEqual(watchlist.load()['items']['561']['alert_policy'], policy)
        self.assertNotIn('561', alerts._load()['watch_crossings'])
        self.assertIsNotNone(self.emit(101, 1))

if __name__ == '__main__':
    unittest.main()
