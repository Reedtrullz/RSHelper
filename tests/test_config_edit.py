import json
import contextlib
import io
import http.client
import threading
import sys
import unittest
from pathlib import Path
from unittest import mock
from uuid import uuid4

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_native_writers import DisposableHomeTest
from rshelper import profile,tuning,state_transaction,paper_book

class ConfigEditTest(DisposableHomeTest):
    def test_verified_trader_status_retains_the_actual_loaded_configuration(self):
        from rshelper import trader
        evidence=tuning.config_evidence(None,now=1000)
        with mock.patch.object(trader,'_read_state',return_value={'configuration':evidence}), \
             mock.patch.object(trader,'daemon_status',return_value={'ownership':'verified_lease','running':True,'local':True,'pid':123,'ready':True}):
            status=trader.trader_status()
        self.assertEqual(status.get('configuration'),evidence)

    def test_configuration_receipt_gaps_fail_at_all_import_boundaries(self):
        from rshelper import config_edit,backup,state_replication
        self.activate()
        revision=config_edit.preview_config(None)['revision']
        operation=str(uuid4())
        config_edit.apply_config(None,self.candidate,expected_revision=revision,
            operation_id=operation,backup_path=self.tmp/'gap-before.zip',now=2000)
        log=tuning._load_log()
        receipt=dict(log['config_operations'][operation])
        receipt['operation_revision']=3;receipt['revision']='3:'+receipt['revision'].split(':')[1]
        log['config_operations'][str(uuid4())]=receipt;log['config_revision']=3
        with self.assertRaises(ValueError):tuning.validate_log(log)
        with self.assertRaises(ValueError):backup._validate_file('tuning_log.json',json.dumps(log).encode())
        information={'schema_version':1,'origin_uuid':self.activate()['origin_uuid'],'files':{'tuning_log.json':log}}
        with self.assertRaises(ValueError):state_replication._information(information)

    def test_cli_preview_missing_document_does_not_create_configuration(self):
        from rshelper import cli
        self.path.unlink()
        out=io.StringIO()
        with mock.patch.object(sys,'argv',['rshelper','config','preview','--json']),contextlib.redirect_stdout(out):
            cli.main()
        self.assertIn('effective',json.loads(out.getvalue()))
        self.assertFalse(self.path.exists())

    def test_apply_cannot_precede_latest_unsorted_utc_evidence(self):
        from rshelper import config_edit
        self.activate()
        current=config_edit.preview_config(None)['current']
        log={'entries':[{'ts':'2026-10-12T12:00:00+00:00','params':current},
                        {'ts':'2026-10-12T10:00:00+00:00','params':current}]}
        profile.atomic_write_json(tuning.log_path(),log)
        revision=config_edit.preview_config(None)['revision']
        with self.assertRaisesRegex(ValueError,'effective time'):
            config_edit.apply_config(None,self.candidate,expected_revision=revision,
                operation_id=str(uuid4()),backup_path=self.tmp/'clock.zip',now=1791802800)
        self.assertFalse((self.tmp/'clock.zip').exists())
        self.assertEqual(self.path.read_text(),self.original)

    def test_cli_preview_apply_and_rollback_share_exact_transition(self):
        from rshelper import cli
        self.activate()
        candidate=self.tmp/'candidate.toml';candidate.write_text(self.candidate)
        def command(arguments):
            out=io.StringIO()
            with mock.patch.object(sys,'argv',['rshelper','config',*arguments]),contextlib.redirect_stdout(out):
                cli.main()
            return json.loads(out.getvalue())
        preview=command(['preview','--input',str(candidate),'--json'])
        operation=str(uuid4())
        applied=command(['apply','--input',str(candidate),'--expected-revision',preview['revision'],
                 '--operation-id',operation,'--backup',str(self.tmp/'cli-before.zip'),'--json'])
        restored=command(['rollback','--restore-operation-id',operation,'--expected-revision',applied['revision'],
                 '--operation-id',str(uuid4()),'--backup',str(self.tmp/'cli-rollback.zip'),'--json'])
        self.assertEqual(self.path.read_text(),self.original)
        self.assertEqual(restored['operation_revision'],2)

    def test_http_authentication_disabled_controls_and_strict_fields(self):
        from http.server import ThreadingHTTPServer
        from rshelper.dashboard.handlers import make_handler
        from rshelper.scanner import FlipScanner
        calls=[]
        handler=make_handler(FlipScanner(),lambda:[],owner_token='a'*64,control=False,
            settings_fn=lambda body=None:calls.append(body) or {'revision':'synthetic'})
        server=ThreadingHTTPServer(('127.0.0.1',0),handler)
        server.daemon_threads=True
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            def request(method,body=None,auth=True):
                client=http.client.HTTPConnection(*server.server_address,timeout=2)
                headers={'Authorization':'Bearer '+'a'*64} if auth else {}
                client.request(method,'/api/settings',None if body is None else json.dumps(body),headers)
                response=client.getresponse();response.read();client.close();return response.status
            self.assertEqual(request('GET',auth=False),401)
            self.assertEqual(calls,[])
            self.assertEqual(request('GET'),200)
            self.assertEqual(request('POST',{'action':'preview','candidate':self.candidate}),200)
            count=len(calls)
            self.assertEqual(request('POST',{'action':'apply','candidate':self.candidate,'expected_revision':'0:synthetic',
                'operation_id':str(uuid4()),'backup_path':str(self.tmp/'denied.zip')}),403)
            self.assertEqual(request('POST',{'action':'preview','candidate':self.candidate,'unexpected':True}),400)
            self.assertEqual(len(calls),count)
        finally:
            server.shutdown();server.server_close();thread.join(timeout=2)

    def setUp(self):
        super().setUp()
        self.path=profile.resolve_config_path('config.toml')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.original='# Preserve owner comments\n[trader]\ncapital=1000 # paper sizing\n'
        self.path.write_text(self.original)
        self.candidate=self.original.replace('capital=1000','capital=2000')

    def test_preview_validates_diff_without_publication(self):
        from rshelper import config_edit
        preview=config_edit.preview_config(None,self.candidate)
        self.assertEqual(preview['effective']['trader']['capital'],2000)
        self.assertEqual(preview['current']['trader']['capital'],1000)
        self.assertEqual(preview['diff'],[{'field':'trader.capital','before':1000,'after':2000}])
        self.assertEqual(self.path.read_text(),self.original)
        self.assertFalse(tuning.log_path().exists())
        for candidate in ('[extension]\nunknown=1\n','[trader]\ncapital=true\n'):
            with self.assertRaises(ValueError):config_edit.preview_config(None,candidate)
        self.assertEqual(self.path.read_text(),self.original)

    def test_apply_exact_retry_retains_backup_comments_and_budget_baseline(self):
        from rshelper import config_edit,backup
        self.activate()
        paper_book.initialize_budget(None,bankroll=1000,slot_limit=8,operation_id=str(uuid4()),now=1000)
        revision=config_edit.preview_config(None,self.candidate)['revision']
        operation=str(uuid4());archive=self.tmp/'before.zip'
        result=config_edit.apply_config(None,self.candidate,expected_revision=revision,
                    operation_id=operation,backup_path=archive,now=2000)
        self.assertEqual(self.path.read_text(),self.candidate)
        self.assertEqual(len(tuning.load_entries()),1)
        _,content=backup._inspect(archive)
        self.assertEqual(content['config.toml'].decode(),self.original)
        retry=config_edit.apply_config(None,self.candidate,expected_revision=revision,
                    operation_id=operation,backup_path=archive,now=2001)
        self.assertTrue(retry['retry'])
        self.assertEqual(retry['operation_revision'],result['operation_revision'])
        self.assertEqual(len(tuning.load_entries()),1)
        self.assertEqual(paper_book.budget_snapshot(None,now=2001)['budget']['initial_bankroll'],1000)

    def test_stale_or_replica_apply_changes_no_files_or_backup(self):
        from rshelper import config_edit
        self.activate(financial_authority=False)
        revision=config_edit.preview_config(None,self.candidate)['revision']
        with self.assertRaises(ValueError):
            config_edit.apply_config(None,self.candidate,expected_revision=revision,
                operation_id=str(uuid4()),backup_path=self.tmp/'denied.zip')
        self.assertFalse((self.tmp/'denied.zip').exists())
        self.assertEqual(self.path.read_text(),self.original)

    def test_rollback_is_a_new_transition_and_stale_revision_is_refused(self):
        from rshelper import config_edit
        self.activate()
        revision=config_edit.preview_config(None,self.candidate)['revision']
        operation=str(uuid4())
        config_edit.apply_config(None,self.candidate,expected_revision=revision,
            operation_id=operation,backup_path=self.tmp/'first.zip',now=2000)
        with self.assertRaisesRegex(ValueError,'revision'):
            config_edit.apply_config(None,self.original,expected_revision=revision,
                operation_id=str(uuid4()),backup_path=self.tmp/'stale.zip',now=2001)
        self.assertFalse((self.tmp/'stale.zip').exists())
        current=config_edit.preview_config(None)['revision']
        config_edit.rollback_config(None,operation,expected_revision=current,
            operation_id=str(uuid4()),backup_path=self.tmp/'rollback.zip',now=2002)
        self.assertEqual(self.path.read_text(),self.original)
        self.assertEqual(len(tuning.load_entries()),2)
        self.assertEqual(tuning.load_entries()[0]['params']['trader']['capital'],2000)
        self.assertEqual(tuning.load_entries()[1]['params']['trader']['capital'],1000)

    def test_interrupted_publication_recovers_config_and_one_transition_together(self):
        from rshelper import config_edit,config
        self.activate()
        for index,step in enumerate(('intent','data:config.toml','data:tuning_log.json','receipt')):
            with self.subTest(step=step):
                candidate=self.candidate if index%2==0 else self.original
                revision=config_edit.preview_config(None,candidate)['revision']
                operation=str(uuid4());archive=self.tmp/f'before-{index}.zip'
                def interrupt(label):
                    if label==step:raise RuntimeError('Synthetic interruption')
                with mock.patch.object(state_transaction,'_checkpoint',side_effect=interrupt):
                    with self.assertRaisesRegex(RuntimeError,'Synthetic interruption'):
                        config_edit.apply_config(None,candidate,expected_revision=revision,
                            operation_id=operation,backup_path=archive,now=2000+index*2)
                observed=config.load_config()
                self.assertEqual(observed.trader.capital,2000 if index%2==0 else 1000)
                retry=config_edit.apply_config(None,candidate,expected_revision=revision,
                            operation_id=operation,backup_path=archive,now=2001+index*2)
                self.assertTrue(retry['retry'])
                self.assertEqual(self.path.read_text(),candidate)
                self.assertEqual(len(tuning.load_entries()),index+1)

if __name__=='__main__':unittest.main()
