"""Exercise the launchd installer with a disposable HOME and fake launchctl."""
import os
from pathlib import Path
import shutil
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import importlib.util

ROOT=Path(__file__).resolve().parents[1]

class InstallerTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.repo=self.root/'repo&with space';self.home=self.root/'home'
        (self.repo/'scripts').mkdir(parents=True);self.home.mkdir()
        for name in ('install-trader-launchd.sh','sync-and-push-state.py', 'sync-private-state.py', 'quiesce-daemons.py'):
            shutil.copyfile(ROOT/'scripts'/name,self.repo/'scripts'/name)
        (self.repo/'.venv/bin').mkdir(parents=True)
        (self.repo/'.venv/bin/python').symlink_to(sys.executable)
        (self.repo/'src').symlink_to(ROOT/'src',target_is_directory=True)
        self.bin=self.root/'bin';self.bin.mkdir()
        launchctl=self.bin/'launchctl'
        launchctl.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$RSHELPER_LAUNCHCTL_LOG"\nexit 0\n')
        launchctl.chmod(0o700)
        self.env={**os.environ,'HOME':str(self.home),'PATH':str(self.bin)+':/usr/bin:/bin',
            'RSHELPER_LAUNCHCTL_LOG':str(self.root/'launchctl.log')}

    def invoke(self,action,*options):
        return subprocess.run(['/bin/bash',str(self.repo/'scripts/install-trader-launchd.sh'),action,*options],
            env=self.env,capture_output=True,text=True,timeout=15)

    def test_status_is_read_only_and_does_not_restage_sync(self):
        result=self.invoke('status');self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse((self.home/'.config').exists())
        self.assertFalse((self.home/'Library').exists())

    def test_quiesce_bootout_prevents_keepalive_without_rewriting_plists(self):
        base = self.home / 'Library/LaunchAgents'
        base.mkdir(parents=True)
        label = 'com.reidar.rshelper-trader'
        path = base / (label + '.plist')
        path.write_bytes(plistlib.dumps({'Label': label, 'KeepAlive': True,
            'ProgramArguments': [str(self.repo / '.venv/bin/python'), '-m', 'rshelper', 'auto-trade']}))
        loaded = self.root / 'loaded'
        loaded.touch()
        launchctl = self.bin / 'launchctl'
        launchctl.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$RSHELPER_LAUNCHCTL_LOG"\n'
            'case "$1" in\nprint) if test -f "$RSHELPER_TEST_LOADED"; then exit 0; '
            'else echo "Could not find service" >&2; exit 113; fi;;\n'
            'bootout) rm "$RSHELPER_TEST_LOADED";;\n'
            'bootstrap) touch "$RSHELPER_TEST_LOADED";;\nesac\n')
        launchctl.chmod(0o700)
        self.env['RSHELPER_TEST_LOADED'] = str(loaded)
        before = path.read_bytes()
        stopped = self.invoke('quiesce')
        self.assertEqual(stopped.returncode, 0, stopped.stderr)
        self.assertFalse(loaded.exists())
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.invoke('quiesce').returncode, 0)
        resumed = self.invoke('resume')
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertTrue(loaded.exists())
        calls = (self.root / 'launchctl.log').read_text()
        self.assertIn('bootout gui/', calls)
        self.assertNotIn('disable ', calls)
        self.assertNotIn('enable ', calls)

    def test_unknown_action_has_no_install_side_effects(self):
        result=self.invoke('unknown-action');self.assertNotEqual(result.returncode,0)
        self.assertFalse((self.home/'.config').exists())
        self.assertFalse((self.home/'Library').exists())

    def test_resume_checks_all_plists_before_loading_any_job(self):
        spec = importlib.util.spec_from_file_location('quiescence_fixture', ROOT/'scripts/quiesce-daemons.py')
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        folder = self.home/'Library/LaunchAgents'
        folder.mkdir(parents=True)
        for label in module.LABELS[:2]:
            (folder/(label+'.plist')).write_bytes(plistlib.dumps({'Label':label,
                'ProgramArguments':[sys.executable, '-m', 'rshelper', 'auto-trade']}))
        with mock.patch.object(module, 'loaded', side_effect=[True, True, False, False]), mock.patch.object(module, 'command'):
            module.manage('quiesce', self.home)
        changed = folder/(module.LABELS[0]+'.plist')
        changed.write_bytes(changed.read_bytes()+b' ')
        with mock.patch.object(module, 'loaded', return_value=False), mock.patch.object(module, 'command') as command:
            with self.assertRaises(ValueError):
                module.manage('resume', self.home)
        command.assert_not_called()

    def test_partial_bootout_failure_retains_original_resume_checkpoint(self):
        spec=importlib.util.spec_from_file_location('quiescence_failure',ROOT/'scripts/quiesce-daemons.py')
        assert spec is not None and spec.loader is not None
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        folder=self.home/'Library/LaunchAgents';folder.mkdir(parents=True)
        for label in module.LABELS[:2]:
            (folder/(label+'.plist')).write_bytes(plistlib.dumps({'Label':label,
                'ProgramArguments':[sys.executable,'-m','rshelper','auto-trade']}))
        with mock.patch.object(module,'loaded',side_effect=[True,True,True,False,True]), \
                mock.patch.object(module,'command',side_effect=[mock.Mock(returncode=0),mock.Mock(returncode=1)]):
            with self.assertRaises(OSError):module.manage('quiesce',self.home)
        import json
        checkpoint=self.home/'Library/Application Support/RSHelper/quiescence.json'
        saved=json.loads(checkpoint.read_text())
        self.assertTrue(all(job['loaded'] for job in saved['jobs'].values()))
        with mock.patch.object(module,'loaded',side_effect=[False,True,True]), \
                mock.patch.object(module,'command',return_value=mock.Mock(returncode=0)) as command:
            module.manage('resume',self.home)
        self.assertEqual(command.call_count,1)
        self.assertFalse(checkpoint.exists())

    def test_successful_bootstrap_without_ready_daemon_is_reported_as_failure(self):
        (self.home/'Library/LaunchAgents').mkdir(parents=True)
        result=self.invoke('install')
        self.assertNotEqual(result.returncode,0,'bootstrap receipt alone cannot certify daemon startup')
        self.assertIn('startup',result.stderr.lower())
        self.assertNotIn('Installed and started',result.stdout)
        calls=(self.root/'launchctl.log').read_text().splitlines()
        target='gui/'+str(os.getuid())+'/com.reidar.rshelper-trader'
        self.assertIn('disable '+target,calls)
        self.assertEqual(calls[-1],'bootout '+target)

    def test_generated_plists_preserve_repository_and_supervisor_identity(self):
        python=self.repo/'.venv/bin/python';python.unlink();python.write_text('#!/bin/sh\nexit 0\n');python.chmod(0o700)
        result=self.invoke('install');self.assertEqual(result.returncode,0,result.stderr)
        base=self.home/'Library/LaunchAgents'
        sync=plistlib.loads((base/'com.reidar.rshelper-state-sync.plist').read_bytes())
        self.assertEqual(sync['EnvironmentVariables']['RSHELPER_REPO'],str(self.repo))
        self.assertNotIn('--unsigned',sync['ProgramArguments'])
        trader=plistlib.loads((base/'com.reidar.rshelper-trader.plist').read_bytes())
        env=trader['EnvironmentVariables'];self.assertEqual(env['RSHELPER_SUPERVISOR_KIND'],'launchd')
        self.assertEqual(env['RSHELPER_SERVICE_LABEL'],'com.reidar.rshelper-trader')
        self.assertEqual(env['RSHELPER_SERVICE_DOMAIN'],'gui/'+str(os.getuid()))

    def test_keep_sync_installs_trader_without_touching_existing_feed(self):
        python=self.repo/'.venv/bin/python'
        python.unlink();python.write_text('#!/bin/sh\nexit 0\n');python.chmod(0o700)
        base=self.home/'Library/LaunchAgents';base.mkdir(parents=True)
        plist=base/'com.reidar.rshelper-state-sync.plist'
        plist.write_bytes(b'existing feed configuration')
        helper=self.home/'.config/rshelper/bin/sync-and-push-state.py'
        helper.parent.mkdir(parents=True);helper.write_bytes(b'existing feed helper')
        result=self.invoke('install','--keep-sync')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(plist.read_bytes(),b'existing feed configuration')
        self.assertEqual(helper.read_bytes(),b'existing feed helper')
        self.assertNotIn('state-sync',(self.root/'launchctl.log').read_text())
        result=self.invoke('install','--keep-sync','--private-sync')
        self.assertNotEqual(result.returncode,0)

    def test_private_sync_install_is_explicit_and_staged_helper_uses_configured_repository(self):
        python=self.repo/'.venv/bin/python'
        python.unlink();python.write_text('#!/bin/sh\nexit 0\n');python.chmod(0o700)
        result=self.invoke('install','--private-sync')
        self.assertEqual(result.returncode,0,result.stderr)
        staged=self.home/'.config/rshelper/bin/sync-private-state.py'
        self.assertEqual(staged.read_bytes(),(ROOT/'scripts/sync-private-state.py').read_bytes())
        sync=plistlib.loads((self.home/'Library/LaunchAgents/com.reidar.rshelper-state-sync.plist').read_bytes())
        self.assertEqual(sync['ProgramArguments'][1],str(staged))
        result=subprocess.run([sys.executable,str(staged),'--status','--json'],
            env={**self.env,'RSHELPER_REPO':str(self.repo)},capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        import json
        self.assertFalse(json.loads(result.stdout)['pending'])

if __name__=='__main__':unittest.main()
