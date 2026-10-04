"""Exercise the launchd installer with a disposable HOME and fake launchctl."""
import os
from pathlib import Path
import shutil
import plistlib
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]

class InstallerTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.repo=self.root/'repo&with space';self.home=self.root/'home'
        (self.repo/'scripts').mkdir(parents=True);self.home.mkdir()
        for name in ('install-trader-launchd.sh','sync-and-push-state.py'):
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

    def invoke(self,action):
        return subprocess.run(['/bin/bash',str(self.repo/'scripts/install-trader-launchd.sh'),action],
            env=self.env,capture_output=True,text=True,timeout=15)

    def test_status_is_read_only_and_does_not_restage_sync(self):
        result=self.invoke('status');self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse((self.home/'.config').exists())
        self.assertFalse((self.home/'Library').exists())

    def test_unknown_action_has_no_install_side_effects(self):
        result=self.invoke('unknown-action');self.assertNotEqual(result.returncode,0)
        self.assertFalse((self.home/'.config').exists())
        self.assertFalse((self.home/'Library').exists())

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

if __name__=='__main__':unittest.main()
