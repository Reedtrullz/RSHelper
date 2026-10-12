import contextlib
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from rshelper import profile, positions, journal, state_identity

class TradingModeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='rshelper-mode-')
        self.addCleanup(self.temp.cleanup)
        self.root = (Path(self.temp.name)/'.config/rshelper').resolve()
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(profile,'CONFIG_DIR',self.root))
        self.stack.enter_context(mock.patch.object(positions,'POSITIONS_PATH',self.root/'positions.json'))
        self.stack.enter_context(mock.patch.object(journal,'TRADES_PATH',self.root/'trades.json'))
    def api(self):
        from rshelper import trading_mode
        return trading_mode
    def set(self, mode, revision=0, operation=None):
        return self.api().set_mode('default', mode, expected_revision=revision,
                                  reason='Synthetic operator trial', operation_id=operation or str(uuid4()))
    def test_default_and_explicit_resume(self):
        self.assertEqual(self.api().read_mode('default')['mode'], 'running')
        self.set('entries-paused')
        with self.assertRaises(ValueError):
            positions.open_position(561,'Synthetic',1,100)
        self.set('running',1)
        self.assertEqual(positions.open_position(561,'Synthetic',1,100).qty,1)
    def test_stale_update_and_idempotent_retry_do_not_rewind_resume(self):
        operation = str(uuid4())
        self.set('entries-paused', operation=operation)
        with self.assertRaises(ValueError):
            self.set('running',0)
        self.set('running',1)
        retry = self.set('entries-paused', operation=operation)
        self.assertEqual(retry['mode'],'running')
        self.assertEqual(retry['revision'],2)
        self.assertEqual(retry['status'],'no_op')
    def test_pause_survives_fresh_process_and_profile_isolation(self):
        self.set('entries-paused')
        env = dict(os.environ, HOME=self.temp.name, PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
        result = subprocess.run([sys.executable,'-c',
            "from rshelper.trading_mode import read_mode; import json; print(json.dumps(read_mode('default')))"],
            env=env,capture_output=True,text=True,timeout=10,check=True)
        self.assertEqual(json.loads(result.stdout)['mode'],'entries-paused')
        self.assertEqual(self.api().read_mode('other')['mode'],'running')
    def test_pause_open_race_orders_publication_before_acknowledgment(self):
        env = dict(os.environ, HOME=self.temp.name, PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
        pause = "from rshelper.trading_mode import set_mode; import uuid; set_mode('default','entries-paused',expected_revision=0,reason='Synthetic race',operation_id=str(uuid.uuid4()))"
        opening = "from rshelper.positions import open_position\ntry: open_position(561,'Synthetic',1,100)\nexcept ValueError: pass"
        children = [subprocess.Popen([sys.executable,'-c',source],env=env,
                                    stdout=subprocess.PIPE,stderr=subprocess.PIPE) for source in (pause,opening)]
        results = [(child,child.communicate(timeout=20)) for child in children]
        for child,(_,error) in results:
            self.assertEqual(child.returncode,0,error.decode())
        mode = self.api().read_mode('default')
        for lot in positions.list_positions():
            self.assertLessEqual(datetime.fromisoformat(lot.opened_at),datetime.fromisoformat(mode['effective_at']))
        with self.assertRaises(ValueError):
            positions.open_position(562,'After pause',1,100)
    def test_drain_completion_is_durable_without_resume(self):
        positions.open_position(561,'Synthetic',1,100)
        self.set('draining')
        self.assertIsNone(self.api().update_drain('default')['drain_completed_at'])
        positions.close_positions(561,1,120)
        complete = self.api().update_drain('default')
        self.assertIsNotNone(complete['drain_completed_at'])
        self.assertEqual(complete['mode'],'draining')
        self.assertEqual(self.api().update_drain('default'),complete)
        with self.assertRaises(ValueError):
            positions.open_position(561,'Synthetic',1,100)
    def test_local_activation_without_replication_list_retains_own_authority(self):
        from rshelper.state_transaction import activate_profile
        manifest=activate_profile(self.root,str(uuid4()))
        mode=self.set('entries-paused')
        self.assertEqual(self.api().read_mode('default')['mode'],'entries-paused')
        self.assertEqual(self.api().validate_authority(mode,manifest),mode)
        for changed in ({**manifest,'financial_authority':False},
                        {**manifest,'origin_uuid':str(uuid4())},
                        {**manifest,'replication_origins':[str(uuid4())]}):
            with self.assertRaisesRegex(ValueError,'authority differs'):
                self.api().validate_authority(mode,changed)

    def test_replica_cannot_change_mode(self):
        self.root.mkdir(parents=True)
        origin = str(uuid4())
        activation = {'schema_version':1,'mode':'identified','origin_uuid':origin,
                      'profile_uuid':str(uuid4()),'financial_authority':False,'replication_origins':[origin]}
        (self.root/'identity-activation.json').write_text(json.dumps(activation))
        with self.assertRaises(ValueError):
            self.set('entries-paused')
    def test_old_reader_cannot_complete_drain_with_unreadable_paper_offers(self):
        self.set('draining')
        before=(self.root/'trading_mode.json').read_bytes()
        (self.root/'paper-offers.json').write_text('{}')
        with mock.patch.object(self.api().importlib,'import_module',side_effect=ImportError('older image')), \
                self.assertRaisesRegex(ValueError,'proof unavailable'):
            self.api().update_drain('default')
        self.assertEqual((self.root/'trading_mode.json').read_bytes(),before)
    def test_current_reader_cannot_complete_drain_with_corrupt_paper_offers(self):
        self.set('draining')
        before=(self.root/'trading_mode.json').read_bytes()
        (self.root/'paper-offers.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'invalid paper book'):
            self.api().update_drain('default')
        self.assertEqual((self.root/'trading_mode.json').read_bytes(),before)
    def test_invalid_mode_and_revision_preserve_bytes(self):
        self.set('entries-paused')
        path = self.root/'trading_mode.json'
        before = path.read_bytes()
        for mode,revision in (('invalid',1),('running',True),('running',-1)):
            with self.assertRaises(ValueError):
                self.set(mode,revision)
        self.assertEqual(path.read_bytes(),before)
    def test_interrupted_mode_publication_recovers_without_new_entries(self):
        from rshelper import state_transaction
        def checkpoint(step):
            if step == 'intent':
                raise RuntimeError('synthetic interruption')
        with mock.patch.object(state_transaction,'_checkpoint',side_effect=checkpoint), self.assertRaises(RuntimeError):
            self.set('entries-paused')
        state_transaction.recover_profile(self.root)
        self.assertEqual(self.api().read_mode('default')['mode'],'entries-paused')
        with self.assertRaises(ValueError):
            positions.open_position(561,'Synthetic',1,100)

    def test_paused_cycle_manages_exit_and_skips_candidate(self):
        from rshelper import trader
        from rshelper.config import TraderConfig
        from types import SimpleNamespace
        import time
        positions.open_position(561,'Synthetic',1,100,note='auto')
        self.set('entries-paused')
        now = time.time()
        latest = {'561':{'high':130,'low':120,'highTime':now,'lowTime':now}}
        candidate = SimpleNamespace(id=562,name='Candidate',sell_price=100,buy_price=110)
        with mock.patch('rshelper.cli._fetch_bootstrap',return_value=([],latest,{},[])), \
                mock.patch.object(trader,'select_candidates',return_value=[candidate]), \
                mock.patch.object(trader,'size_position',return_value=1), \
                mock.patch.object(trader,'exit_reason',return_value='take_profit'), \
                mock.patch.object(trader,'EXITS_PATH',self.root/'recent_exits.json'), \
                mock.patch.object(trader,'_RECENT_EXITS',{}):
            result = trader.run_cycle(TraderConfig())
        self.assertEqual(len(result['closed']),1)
        self.assertEqual(result['opened'],[])
        self.assertEqual(result['trading_mode']['mode'],'entries-paused')
        self.assertEqual(len(journal.list_trades()),1)

    def test_cli_json_mode_and_backup_inventory(self):
        from rshelper import cli, backup
        import io
        operation = str(uuid4())
        out,err = io.StringIO(),io.StringIO()
        with mock.patch.object(sys,'argv',['rshelper','trading-mode','--mode','entries-paused',
                '--expected-revision','0','--reason','Synthetic CLI','--operation-id',operation,'--json']), \
                contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
            cli.main()
        self.assertEqual(json.loads(out.getvalue())['mode'],'entries-paused')
        self.assertEqual(err.getvalue(),'')
        target = Path(self.temp.name)/'mode.zip'
        manifest = backup.export_profile('default',target)
        self.assertIn('trading_mode.json',manifest['files'])
        self.assertTrue(backup.inspect_backup(target))

    def test_fresh_daemon_cycle_keeps_paused_stance_and_stays_healthy(self):
        from rshelper import state_migration,paper_book
        origin,identity=str(uuid4()),str(uuid4())
        plan=state_migration.plan_migration('default',origin_uuid=origin,profile_uuid=identity,
                    lineage={'mode':'independent','financial_authority':True,'replication_origins':[origin]})
        state_migration.migrate_profile('default',plan=plan,operation_id=str(uuid4()))
        paper_book.initialize_budget('default',bankroll=1000,slot_limit=8,operation_id=str(uuid4()),now=0)
        self.set('entries-paused')
        env = dict(os.environ, HOME=self.temp.name, PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
        code = "from rshelper import trader,cli; from rshelper.config import TraderConfig; cli._fetch_bootstrap=lambda *args:([],{},{},[]); trader.run_trader(TraderConfig(),profile='default',once=True)"
        result = subprocess.run([sys.executable,'-c',code],env=env,
                                capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        state = json.loads((self.root/'trader_state.json').read_text())
        self.assertEqual(state['last_result']['trading_mode']['mode'],'entries-paused')
        self.assertNotIn('error',state['last_result'])
        self.assertEqual(state['last_result']['opened'],[])
        self.assertEqual(self.api().read_mode('default')['mode'],'entries-paused')

    def test_restore_cannot_rewind_an_acknowledged_stance(self):
        from rshelper import backup, state_migration
        self.set('entries-paused')
        origin, identity = str(uuid4()), str(uuid4())
        plan = state_migration.plan_migration('default',origin_uuid=origin,profile_uuid=identity,
                    lineage={'mode':'independent','financial_authority':True,'replication_origins':[origin]})
        state_migration.migrate_profile('default',plan=plan,operation_id=str(uuid4()))
        target = Path(self.temp.name)/'paused.zip'
        backup.export_profile('default',target)
        self.set('running',1)
        with self.assertRaises(backup.BackupError):
            backup.restore_profile('default',target,expected_profile_uuid=identity,
                                   operation_id=str(uuid4()),dry_run=True)
        self.assertEqual(self.api().read_mode('default')['mode'],'running')

    def test_two_processes_cannot_acknowledge_the_same_expected_revision(self):
        env = dict(os.environ,HOME=self.temp.name,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
        code = "from rshelper.trading_mode import set_mode; import uuid\ntry:\n set_mode('default','entries-paused',expected_revision=0,reason='Synthetic race',operation_id=str(uuid.uuid4()))\n print('applied')\nexcept ValueError:\n print('conflict')"
        children = [subprocess.Popen([sys.executable,'-c',code],env=env,
                                     stdout=subprocess.PIPE,stderr=subprocess.PIPE) for _ in range(2)]
        results = [(child,child.communicate(timeout=20)) for child in children]
        for child,(_,error) in results:
            self.assertEqual(child.returncode,0,error.decode())
        self.assertEqual(sorted(output.decode().strip() for _,(output,_) in results),['applied','conflict'])
        self.assertEqual(self.api().read_mode('default')['revision'],1)

if __name__ == '__main__':
    unittest.main()
