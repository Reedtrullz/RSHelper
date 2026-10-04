"""Dashboard controls must report verified lifecycle receipts."""
from contextlib import ExitStack
import itertools
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from rshelper.dashboard import server
from rshelper import cli
from rshelper import profile as profile_module


class DashboardLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch('rshelper.profile.resolve_config_path',return_value=Path(self.temp.name)))
        self.process=mock.Mock(pid=12345);self.process.poll.return_value=None
        self.spawn=self.stack.enter_context(mock.patch.object(server.subprocess,'Popen',return_value=self.process))
        self.status=self.stack.enter_context(mock.patch('rshelper.daemon.daemon_status',return_value={
            'running':True,'ownership':'verified_lease','ready':True,'pid':12345}))
        self.status.side_effect=lambda *a,**kw: (self.status.return_value if self.spawn.called
            else {'running':False,'ownership':'synced_snapshot'})
        self.stack.enter_context(mock.patch('rshelper.daemon.wait_for_ready',
            side_effect=lambda *a,**kw:self.status(*a,**kw)))

    def test_child_exit_before_ready_is_startup_failure(self):
        self.process.poll.return_value=2
        report=server._spawn_daemon('monitor','default')
        self.assertFalse(report['ok']);self.assertIn('exited',report['error'])

    def test_success_requires_ready_receipt_for_the_spawned_child(self):
        report=server._spawn_daemon('monitor','default')
        self.assertTrue(report['ok']);self.assertEqual(report['pid'],12345)
        self.assertEqual(report['ownership'],'verified_lease');self.assertTrue(report['ready'])
        self.process.poll.assert_called()

    def test_wrong_owner_times_out_without_stopping_that_owner(self):
        self.status.return_value={'running':True,'ownership':'verified_lease','ready':True,'pid':98765}
        with mock.patch.object(server.time,'monotonic',side_effect=itertools.count()), \
                mock.patch.object(server.time,'sleep'),mock.patch('rshelper.daemon.request_stop') as stop:
            report=server._spawn_daemon('monitor','default')
        self.assertFalse(report['ok']);stop.assert_not_called()
        self.process.terminate.assert_called_once();self.process.wait.assert_called()

    def test_unmanaged_child_does_not_inherit_supervisor_identity(self):
        with mock.patch.dict(os.environ,{'RSHELPER_SUPERVISOR_KIND':'launchd',
                'RSHELPER_SERVICE_DOMAIN':'gui/999','RSHELPER_SERVICE_LABEL':'synthetic.service'}):
            self.assertTrue(server._spawn_daemon('monitor','default')['ok'])
        env=self.spawn.call_args.kwargs['env']
        for key in ('RSHELPER_SUPERVISOR_KIND','RSHELPER_SERVICE_DOMAIN','RSHELPER_SERVICE_LABEL'):
            self.assertTrue(key not in env,'spawned child inherited a supervisor variable')

    def test_stop_preserves_actual_and_desired_state_receipt(self):
        receipt={'ok':False,'stopped':False,'stop_requested':True,
            'desired_state':'disabled','supervisor':'launchd','error':'shutdown pending'}
        with mock.patch('rshelper.daemon.request_stop',return_value=receipt):
            self.assertEqual(server._stop_daemon('auto-trade','default'),receipt)

    def test_start_uses_supervisor_adapter_instead_of_unmanaged_child(self):
        self.status.return_value={'running':False,'ownership':'synced_snapshot',
            'supervisor':'launchd','desired_state':'disabled','local':True}
        self.status.side_effect=None
        receipt={'ok':True,'ready':True,'supervisor':'launchd','desired_state':'enabled'}
        with mock.patch('rshelper.daemon.start_supervised_daemon',return_value=receipt) as start:
            report=server._spawn_daemon('monitor','default')
            self.assertEqual(report,receipt);start.assert_called_once_with('monitor','default')
        self.spawn.assert_not_called()

    def test_cli_stop_json_preserves_pending_shutdown_receipt(self):
        receipt={'ok':True,'requested':True,'stopped':False,'running':True,
            'desired_state':'disabled','supervisor':'launchd'}
        args=mock.Mock(profile='default',json=True)
        with mock.patch('rshelper.daemon.request_stop',return_value=receipt), \
                mock.patch.object(cli.sys,'stdout',new_callable=io.StringIO) as out, \
                mock.patch.object(cli.sys,'stderr',new_callable=io.StringIO) as err:
            cli._daemon_stop_cmd('auto-trade',args)
        self.assertEqual(json.loads(out.getvalue()),receipt);self.assertEqual(err.getvalue(),'')

    def test_cli_stop_failure_is_actionable_and_returns_failure(self):
        receipt={'ok':False,'stopped':False,'desired_state':'disabled','error':'shutdown pending'}
        args=mock.Mock(profile='default',json=False)
        with mock.patch('rshelper.daemon.request_stop',return_value=receipt), \
                mock.patch.object(cli.sys,'stderr',new_callable=io.StringIO) as err, \
                self.assertRaises(SystemExit) as failure:
            cli._daemon_stop_cmd('monitor',args)
        self.assertEqual(failure.exception.code,1)
        self.assertIn('shutdown pending',err.getvalue());self.assertIn('disabled',err.getvalue())

    def test_failed_status_receipt_cleans_the_spawned_child(self):
        from rshelper.daemon import LeaseError
        def status(*a,**kw):
            if self.spawn.called: raise LeaseError('invalid startup receipt')
            return {'running':False,'ownership':'synced_snapshot'}
        self.status.side_effect=status
        report=server._spawn_daemon('monitor','default')
        self.assertFalse(report['ok']);self.assertIn('invalid startup receipt',report['error'])
        self.process.terminate.assert_called_once();self.process.wait.assert_called()

    def test_symlinked_daemon_log_refuses_spawn(self):
        root=Path(self.temp.name);target=root/'preserved.txt';target.write_text('preserve')
        (root/'monitor.log').symlink_to(target)
        report=server._spawn_daemon('monitor','default')
        self.assertFalse(report['ok']);self.spawn.assert_not_called()
        self.assertEqual(target.read_text(),'preserve')


class DashboardProcessProof(unittest.TestCase):
    def test_real_monitor_start_stop_and_failed_child_in_disposable_home(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder).resolve()
            native_popen=server.subprocess.Popen
            children=[]
            source=("from rshelper import monitor\n"
                "monitor._poll_cycle=lambda *args: None\n"
                "monitor.run_monitor(interval_sec=60,no_notify=True,profile='default')\n")
            def launch(command,*args,**kwargs):
                if command[1:3]==['-m','rshelper']:
                    command=[sys.executable,'-c',source]
                    process=native_popen(command,*args,**kwargs);children.append(process)
                    return process
                return native_popen(command,*args,**kwargs)
            with mock.patch.dict(os.environ,{'HOME':str(home)}), \
                    mock.patch.object(profile_module,'CONFIG_DIR',home/'.config/rshelper'), \
                    mock.patch.object(server.subprocess,'Popen',side_effect=launch):
                try:
                    started=server._spawn_daemon('monitor','default')
                    self.assertTrue(started['ok'],started);self.assertTrue(started['ready'])
                    self.assertEqual(Path(started['log']).stat().st_mode & 0o077,0,'daemon log must be private')
                    stopped=server._stop_daemon('monitor','default')
                    self.assertTrue(stopped['requested'],stopped);self.assertTrue(stopped['stopped'],stopped)
                    self.assertFalse(stopped['running']);self.assertEqual(children[-1].wait(timeout=3),0)
                    self.assertTrue((home/'.config/rshelper/monitor.pid.lease').exists())
                    source='raise SystemExit(7)\n'
                    failed=server._spawn_daemon('monitor','default')
                    self.assertFalse(failed['ok']);self.assertIn('exited',failed['error'])
                    self.assertEqual(children[-1].wait(timeout=3),7)
                finally:
                    for child in children:
                        if child.poll() is None:
                            child.terminate()
                            try: child.wait(timeout=3)
                            except server.subprocess.TimeoutExpired:
                                child.kill();child.wait(timeout=3)


if __name__=='__main__':unittest.main()
