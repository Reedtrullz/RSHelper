"""State synchronizer uses disposable Git repositories and synthetic records."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import signal
import shutil
import time
import sys
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]

class SyncIndexTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name).resolve()
        self.repo=root/'repo';self.remote=root/'remote.git';self.home=root/'home';self.home.mkdir()
        self.source=self.home/'.config/rshelper';self.source.mkdir(parents=True)
        self.patch=mock.patch.dict(os.environ,{'HOME':str(self.home),
            'GIT_CONFIG_GLOBAL':os.devnull,'GIT_CONFIG_NOSYSTEM':'1'})
        self.patch.start();self.addCleanup(self.patch.stop)
        subprocess.run(['git','init','--bare',str(self.remote)],capture_output=True,check=True)
        subprocess.run(['git','init','-b','main',str(self.repo)],capture_output=True,check=True)
        self.git('config','user.name','Synthetic Sync Test');self.git('config','user.email','fixture@example.invalid')
        (self.repo/'data/state').mkdir(parents=True)
        (self.repo/'data/state/trades.json').write_text('{"trades":[]}\n')
        (self.repo/'source.py').write_text('original\n')
        self.git('add','.');self.git('-c','commit.gpgsign=false','commit','-m','fixture')
        self.git('remote','add','origin',str(self.remote));self.git('push','origin','main')
        path=ROOT/'scripts/sync-and-push-state.py'
        spec=importlib.util.spec_from_file_location('sync_index_fixture',path)
        self.sync=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.sync)
        self.trade={'id':1,'item_id':2,'name':'Synthetic item','qty':1,'buy_price':100,
            'sell_price':110,'tax_paid':2,'profit':8,'timestamp':'2026-10-04T12:00:00Z','note':''}
        (self.source/'trades.json').write_text(json.dumps({'trades':[self.trade]}))

    def git(self,*args):
        result=subprocess.run(['git','-C',str(self.repo),*args],capture_output=True,text=True)
        if result.returncode:raise AssertionError(result.stderr)
        return result.stdout.strip()

    def test_unrelated_index_and_worktree_and_head_preserved(self):
        (self.repo/'staged.py').write_text('staged source\n');self.git('add','staged.py')
        (self.repo/'source.py').write_text('unstaged source\n')
        index=(self.repo/'.git/index').read_bytes();head=self.git('rev-parse','HEAD')
        report=self.sync.run_sync(self.repo,self.source,unsigned=True)
        self.assertTrue(report['pushed'])
        self.assertEqual((self.repo/'.git/index').read_bytes(),index)
        self.assertEqual(self.git('rev-parse','HEAD'),head)
        self.assertEqual((self.repo/'source.py').read_text(),'unstaged source\n')
        self.assertEqual((self.repo/'staged.py').read_text(),'staged source\n')
        names=self.git('diff-tree','--no-commit-id','--name-only','-r',report['revision']).splitlines()
        self.assertEqual(names,['data/state/trades.json'])

    def test_no_change_retries_pending_push_without_duplicate_commit(self):
        hook=self.remote/'hooks/pre-receive';hook.write_text('#!/bin/sh\nexit 1\n');hook.chmod(0o700)
        with self.assertRaisesRegex(self.sync.SyncError,'Push failed'):
            self.sync.run_sync(self.repo,self.source,unsigned=True)
        pending=self.git('rev-parse',self.sync.PENDING_REF)
        hook.unlink()
        report=self.sync.run_sync(self.repo,self.source,unsigned=True)
        self.assertEqual(report['revision'],pending)
        remote=subprocess.check_output(['git','--git-dir',str(self.remote),'rev-parse','main'],text=True).strip()
        self.assertEqual(remote,pending)
        repeat=self.sync.run_sync(self.repo,self.source,unsigned=True)
        self.assertFalse(repeat['changed']);self.assertEqual(repeat['revision'],pending)

    def test_required_signing_failure_never_falls_back_unsigned(self):
        self.git('config','gpg.format','ssh');self.git('config','user.signingkey',str(self.home/'missing-key'))
        remote=self.git('ls-remote','origin','refs/heads/main')
        with self.assertRaisesRegex(self.sync.SyncError,'Signed state commit failed'): self.sync.run_sync(self.repo,self.source)
        self.assertEqual(self.git('ls-remote','origin','refs/heads/main'),remote)
        result=subprocess.run(['git','-C',str(self.repo),'rev-parse','--verify',self.sync.PENDING_REF],capture_output=True)
        self.assertNotEqual(result.returncode,0)

    def test_dry_run_and_status_do_not_write_state_git_or_index(self):
        index=(self.repo/'.git/index').read_bytes();before=(self.repo/'data/state/trades.json').read_bytes()
        report=self.sync.run_sync(self.repo,self.source,dry_run=True)
        self.assertEqual(report['paths'],['data/state/trades.json'])
        self.assertEqual((self.repo/'.git/index').read_bytes(),index)
        self.assertEqual((self.repo/'data/state/trades.json').read_bytes(),before)
        self.assertIsNone(self.sync.sync_status(self.repo)['pending_revision'])

    def test_required_signing_produces_verifiable_ssh_signature(self):
        key=self.home/'synthetic-signing-key'
        subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(key)],capture_output=True,check=True)
        allowed=self.home/'allowed-signers';allowed.write_text('fixture@example.invalid '+key.with_suffix('.pub').read_text())
        self.git('config','gpg.format','ssh');self.git('config','user.signingkey',str(key))
        self.git('config','gpg.ssh.allowedSignersFile',str(allowed))
        report=self.sync.run_sync(self.repo,self.source)
        self.assertTrue(report['pushed'])
        self.git('verify-commit',report['revision'])

    def test_canonical_whitespace_changes_do_not_create_commit(self):
        first=self.sync.run_sync(self.repo,self.source,unsigned=True)
        (self.source/'trades.json').write_text(json.dumps({'trades':[self.trade]},indent=4)+'\n\n')
        second=self.sync.run_sync(self.repo,self.source,unsigned=True)
        self.assertFalse(second['changed']);self.assertEqual(second['revision'],first['revision'])

    def test_unknown_snapshot_and_unknown_record_field_never_enter_public_tree(self):
        original=self.git('ls-remote','origin','refs/heads/main')
        self.trade['future_private_field']='synthetic private value'
        (self.source/'trades.json').write_text(json.dumps({'trades':[self.trade]}))
        with self.assertRaisesRegex(self.sync.SyncError,'Unknown state schema'):
            self.sync.run_sync(self.repo,self.source,unsigned=True)
        del self.trade['future_private_field']
        (self.source/'trades.json').write_text(json.dumps({'trades':[self.trade]}))
        (self.source/'snapshots').mkdir();(self.source/'snapshots/private-new.json').write_text('{}')
        with self.assertRaisesRegex(self.sync.SyncError,'Unknown state pathname'):
            self.sync.run_sync(self.repo,self.source,unsigned=True)
        self.assertEqual(self.git('ls-remote','origin','refs/heads/main'),original)

    def test_source_head_change_before_ref_update_does_not_push(self):
        original=self.git('ls-remote','origin','refs/heads/main')
        invoke=self.sync.git
        def interleave(repo,*args,**kwargs):
            result=invoke(repo,*args,**kwargs)
            if args[0]=='commit-tree':
                (self.repo/'source.py').write_text('new committed source\n')
                self.git('add','source.py');self.git('-c','commit.gpgsign=false','commit','-m','user source change')
            return result
        with mock.patch.object(self.sync,'git',side_effect=interleave):
            with self.assertRaisesRegex(self.sync.SyncError,'Source HEAD changed'):
                self.sync.run_sync(self.repo,self.source,unsigned=True)
        self.assertEqual(self.git('ls-remote','origin','refs/heads/main'),original)

    def test_fifo_source_is_rejected_without_blocking(self):
        path=self.source/'trades.json';path.unlink();os.mkfifo(path,0o600)
        def deadline(signum,frame): raise TimeoutError('FIFO read blocked')
        old=signal.signal(signal.SIGALRM,deadline)
        try:
            signal.setitimer(signal.ITIMER_REAL,.2)
            with self.assertRaisesRegex(ValueError,'regular file'):
                self.sync.run_sync(self.repo,self.source,unsigned=True)
        finally:
            signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,old)

    def test_ambient_git_paths_cannot_redirect_sync_to_another_repository(self):
        before=self.git('rev-parse','HEAD')
        with mock.patch.dict(os.environ,{'GIT_DIR':str(self.remote),
                'GIT_WORK_TREE':str(self.home),'GIT_INDEX_FILE':str(self.home/'other-index')}):
            report=self.sync.run_sync(self.repo,self.source,unsigned=True)
        self.assertTrue(report['pushed'])
        self.assertEqual(self.git('rev-parse','HEAD'),before)
        self.assertFalse((self.home/'other-index').exists())

    def test_accepted_pending_push_recovers_after_receipt_failure_and_remote_advance(self):
        invoke=self.sync.git
        def fail_receipt(repo,*args,**kwargs):
            if args[:2]==('update-ref',self.sync.LAST_REF):
                raise self.sync.SyncError('Synthetic receipt failure')
            return invoke(repo,*args,**kwargs)
        with mock.patch.object(self.sync,'git',side_effect=fail_receipt):
            with self.assertRaisesRegex(self.sync.SyncError,'receipt failure'):
                self.sync.run_sync(self.repo,self.source,unsigned=True)
        pending=self.git('rev-parse',self.sync.PENDING_REF)
        # Another source release advances the remote after the accepted push.
        tree=self.git('rev-parse',pending+':')
        later=self.git('commit-tree',tree,'-p',pending,'--no-gpg-sign','-m','later release')
        self.git('push','origin',later+':refs/heads/main')
        report=self.sync.run_sync(self.repo,self.source,unsigned=True)
        self.assertFalse(report['changed']);self.assertTrue(report['pushed'])
        self.assertEqual(report['revision'],pending)
        self.assertEqual(self.git('ls-remote','origin','refs/heads/main').split()[0],later)
        self.assertIsNone(self.sync.ref(self.repo,self.sync.PENDING_REF))

    def test_unsigned_pending_never_retries_under_required_signing(self):
        hook=self.remote/'hooks/pre-receive';hook.write_text('#!/bin/sh\nexit 1\n');hook.chmod(0o700)
        with self.assertRaisesRegex(self.sync.SyncError,'Push failed'):
            self.sync.run_sync(self.repo,self.source,unsigned=True)
        pending=self.git('rev-parse',self.sync.PENDING_REF);hook.unlink()
        original=self.git('ls-remote','origin','refs/heads/main')
        with self.assertRaisesRegex(self.sync.SyncError,'unsigned'):
            self.sync.run_sync(self.repo,self.source)
        self.assertEqual(self.git('ls-remote','origin','refs/heads/main'),original)
        self.assertEqual(self.sync.ref(self.repo,self.sync.PENDING_REF),pending)

    def test_parallel_sync_refuses_owned_repository_lease(self):
        before=self.git('ls-remote','origin','refs/heads/main')
        with self.sync.sync_lock(self.repo):
            with self.assertRaisesRegex(self.sync.SyncError,'owns the lease'):
                self.sync.run_sync(self.repo,self.source,unsigned=True)
        self.assertEqual(self.git('ls-remote','origin','refs/heads/main'),before)

    def test_source_head_change_after_pending_receipt_refuses_push(self):
        original=self.git('ls-remote','origin','refs/heads/main')
        invoke=self.sync.git
        def interleave(repo,*args,**kwargs):
            result=invoke(repo,*args,**kwargs)
            if args[:2]==('update-ref',self.sync.PENDING_REF):
                (self.repo/'source.py').write_text('new source before push\n')
                self.git('add','source.py');self.git('-c','commit.gpgsign=false','commit','-m','source advance')
            return result
        with mock.patch.object(self.sync,'git',side_effect=interleave):
            with self.assertRaisesRegex(self.sync.SyncError,'Source HEAD changed'):
                self.sync.run_sync(self.repo,self.source,unsigned=True)
        self.assertEqual(self.git('ls-remote','origin','refs/heads/main'),original)
        self.assertIsNotNone(self.sync.ref(self.repo,self.sync.PENDING_REF))

    def test_retry_receipt_uses_pinned_remote_ancestry_during_remote_race(self):
        invoke=self.sync.git
        def fail_receipt(repo,*args,**kwargs):
            if args[:2]==('update-ref',self.sync.LAST_REF): raise self.sync.SyncError('receipt failure')
            return invoke(repo,*args,**kwargs)
        with mock.patch.object(self.sync,'git',side_effect=fail_receipt):
            with self.assertRaises(self.sync.SyncError): self.sync.run_sync(self.repo,self.source,unsigned=True)
        pending=self.git('rev-parse',self.sync.PENDING_REF)
        def remote_advance():
            tree=self.git('rev-parse',pending+':')
            parent=subprocess.check_output(['git','--git-dir',str(self.remote),'rev-parse','main'],text=True).strip()
            result=subprocess.run(['git','--git-dir',str(self.remote),'-c','user.name=Remote fixture',
                '-c','user.email=remote@example.invalid','commit-tree',tree,'-p',parent,
                '--no-gpg-sign','-m','remote-only release'],capture_output=True,text=True,check=True)
            later=result.stdout.strip()
            subprocess.run(['git','--git-dir',str(self.remote),'update-ref','refs/heads/main',later],check=True)
            return later
        remote_advance()
        def race(repo,*args,**kwargs):
            result=invoke(repo,*args,**kwargs)
            if args[0]=='fetch': remote_advance()
            return result
        with mock.patch.object(self.sync,'git',side_effect=race):
            report=self.sync.run_sync(self.repo,self.source,unsigned=True)
        self.assertEqual(report['revision'],pending);self.assertFalse(report['changed'])

    def test_status_inspects_detached_head_without_enabling_sync(self):
        original=self.git('rev-parse','HEAD');self.git('checkout','--detach',original)
        index=(self.repo/'.git/index').read_bytes()
        report=self.sync.sync_status(self.repo)
        self.assertEqual(report['head'],original);self.assertIsNone(report['branch'])
        with self.assertRaisesRegex(self.sync.SyncError,'main checkout'):
            self.sync.run_sync(self.repo,self.source,unsigned=True)
        self.assertEqual((self.repo/'.git/index').read_bytes(),index)

    def test_cli_json_receipts_and_cross_process_lease_are_isolated(self):
        (self.repo/'src').symlink_to(ROOT/'src',target_is_directory=True)
        env=dict(os.environ,RSHELPER_REPO=str(self.repo))
        script=ROOT/'scripts/sync-and-push-state.py'
        index=(self.repo/'.git/index').read_bytes();head=self.git('rev-parse','HEAD')
        for flag in ('--dry-run','--status'):
            result=subprocess.run([sys.executable,str(script),flag],env=env,
                capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stderr,'');self.assertIsInstance(json.loads(result.stdout),dict)
        with self.sync.sync_lock(self.repo):
            refused=subprocess.run([sys.executable,str(script),'--unsigned'],env=env,
                capture_output=True,text=True,timeout=10)
            self.assertEqual(refused.returncode,1);self.assertIn('owns the lease',refused.stderr)
            self.assertEqual(refused.stdout,'')
        pushed=subprocess.run([sys.executable,str(script),'--unsigned'],env=env,
            capture_output=True,text=True,timeout=10)
        self.assertEqual(pushed.returncode,0,pushed.stderr);self.assertEqual(pushed.stderr,'')
        self.assertTrue(json.loads(pushed.stdout)['pushed'])
        self.assertEqual((self.repo/'.git/index').read_bytes(),index)
        self.assertEqual(self.git('rev-parse','HEAD'),head)

    def test_symlinked_source_parent_and_snapshot_directory_are_denied(self):
        original=self.git('ls-remote','origin','refs/heads/main')
        alias=self.home/'source-alias';alias.symlink_to(self.source,target_is_directory=True)
        with self.assertRaisesRegex(self.sync.SyncError,'parent must not be a symlink'):
            self.sync.run_sync(self.repo,alias,unsigned=True)
        (self.source/'snapshots').symlink_to(self.home,target_is_directory=True)
        with self.assertRaisesRegex(self.sync.SyncError,'Snapshot directory'):
            self.sync.run_sync(self.repo,self.source,unsigned=True)
        self.assertEqual(self.git('ls-remote','origin','refs/heads/main'),original)

    def test_staged_helper_uses_configured_repository_validation_modules(self):
        destination=self.home/'.config/rshelper/bin/sync-and-push-state.py'
        destination.parent.mkdir();shutil.copyfile(ROOT/'scripts/sync-and-push-state.py',destination)
        (self.repo/'src').symlink_to(ROOT/'src',target_is_directory=True)
        stray=destination.parent.parent/'src/rshelper';stray.mkdir(parents=True)
        (stray/'__init__.py').write_text("raise RuntimeError('stray helper source imported')\n")
        env=dict(os.environ,RSHELPER_REPO=str(self.repo));env.pop('PYTHONPATH',None)
        report=subprocess.run([sys.executable,str(destination),'--dry-run'],env=env,
            capture_output=True,text=True,timeout=10)
        self.assertEqual(report.returncode,0,report.stderr);self.assertEqual(report.stderr,'')
        self.assertEqual(json.loads(report.stdout)['paths'],['data/state/trades.json'])

    def test_state_selection_has_file_and_total_byte_budgets(self):
        original=self.git('ls-remote','origin','refs/heads/main')
        (self.source/'positions.json').write_text('{"positions":[]}')
        with mock.patch.object(self.sync,'MAX_SYNC_FILES',1):
            with self.assertRaisesRegex(self.sync.SyncError,'file budget'):
                self.sync.run_sync(self.repo,self.source,unsigned=True)
        with mock.patch.object(self.sync,'MAX_SYNC_BYTES',100):
            with self.assertRaisesRegex(self.sync.SyncError,'byte budget'):
                self.sync.run_sync(self.repo,self.source,unsigned=True)
        self.assertEqual(self.git('ls-remote','origin','refs/heads/main'),original)

    def fake_git(self,code):
        directory=self.home/'fake-git';directory.mkdir()
        executable=directory/'git';executable.write_text('#!'+sys.executable+'\n'+code);executable.chmod(0o700)
        return mock.patch.dict(os.environ,{'PATH':str(directory)+os.pathsep+os.environ['PATH'],
            'RSHELPER_TEST_FAKE_GIT':str(executable)})

    def test_git_command_output_is_bounded_before_capture(self):
        with self.fake_git("print('x'*4096)\n"),mock.patch.object(self.sync,'MAX_GIT_OUTPUT',1024,create=True):
            with self.assertRaisesRegex(self.sync.SyncError,'output budget'):
                self.sync.git(self.repo,'status')

    def test_git_deadline_kills_owned_descendants_and_reaps_process(self):
        marker=self.home/'descendant-survived'
        child="import time;from pathlib import Path;time.sleep(.4);Path("+repr(str(marker))+").write_text('survived')"
        code="import subprocess,sys,time\nsubprocess.Popen([sys.executable,'-c',"+repr(child)+"])\ntime.sleep(.9)\n"
        with self.fake_git(code),mock.patch.object(self.sync,'MAX_GIT_SECONDS',.1,create=True):
            with self.assertRaisesRegex(self.sync.SyncError,'deadline'):
                self.sync.git(self.repo,'status')
        time.sleep(.5)
        self.assertFalse(marker.exists(),'owned Git descendant survived the command deadline')

    def test_unborn_main_has_actionable_error_without_any_push(self):
        repository=self.home/'unborn-repo'
        subprocess.run(['git','init','-b','main',str(repository)],capture_output=True,check=True)
        with self.assertRaisesRegex(self.sync.SyncError,'initial commit'):
            self.sync.run_sync(repository,self.source,unsigned=True)
        self.assertIsNone(self.sync.sync_status(repository)['head'])

if __name__=='__main__':unittest.main()
