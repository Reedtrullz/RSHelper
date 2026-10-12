import json
import contextlib
import io
import http.client
import threading
import sys
import unittest
from pathlib import Path
from uuid import uuid4
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_native_writers import DisposableHomeTest
from rshelper import positions,journal,profile,realization,backup

class TradeReviewTest(DisposableHomeTest):
    def setUp(self):
        super().setUp();self.activate()
        self.lot=positions.open_position(2,'Synthetic',10,100,direction='traditional',note='manual',operation_id=str(uuid4()))
        self.entry={'hypothesis':'Reversion <private>','planned_exit':'At target after costs',
                    'tags':['reversion'],'review':'','deleted':False}

    def test_append_retry_partial_children_and_economics_are_separate(self):
        from rshelper import trade_reviews
        operation=str(uuid4())
        first=trade_reviews.append_review(None,self.lot.lot_uid,self.entry,expected_revision=0,operation_id=operation,now=1000)
        retry=trade_reviews.append_review(None,self.lot.lot_uid,self.entry,expected_revision=0,operation_id=operation,now=1001)
        self.assertTrue(retry['retry']);self.assertEqual(first['revision'],retry['revision'])
        realization.close_and_realize(None,self.lot.lot_uid,2,120,str(uuid4()),reason='manual',metadata={'note':'manual','strategy':'manual'})
        realization.close_and_realize(None,self.lot.lot_uid,3,130,str(uuid4()),reason='manual',metadata={'note':'manual','strategy':'manual'})
        before={name:(profile.CONFIG_DIR/name).read_bytes() for name in ('positions.json','trades.json','realizations.json')}
        changed={**self.entry,'review':'Followed plan'}
        trade_reviews.append_review(None,self.lot.lot_uid,changed,expected_revision=1,operation_id=str(uuid4()),now=1002)
        summary=trade_reviews.review_queue(None,journal.list_trades(note='manual'))
        self.assertEqual(summary['sample_count'],2)
        self.assertEqual(summary['reviewed_count'],2)
        self.assertEqual({row['lot_uid'] for row in summary['trades']},{self.lot.lot_uid})
        self.assertEqual(len(trade_reviews.read_reviews(None)['entries']),2)
        self.assertEqual(before,{name:(profile.CONFIG_DIR/name).read_bytes() for name in before})

    def test_stale_unknown_lot_invalid_fields_and_replica_are_refused(self):
        from rshelper import trade_reviews
        for uid,entry,revision in ((str(uuid4()),self.entry,0),(self.lot.lot_uid,{**self.entry,'profit':999},0),
                                  (self.lot.lot_uid,{**self.entry,'tags':[True]},0),(self.lot.lot_uid,self.entry,1)):
            with self.assertRaises(ValueError):
                trade_reviews.append_review(None,uid,entry,expected_revision=revision,operation_id=str(uuid4()))
        self.assertFalse((profile.CONFIG_DIR/'trade-reviews.json').exists())
        self.activate(financial_authority=False)
        with self.assertRaises(ValueError):
            trade_reviews.append_review(None,self.lot.lot_uid,self.entry,expected_revision=0,operation_id=str(uuid4()))

    def test_tombstones_and_backup_restore_preserve_append_history(self):
        from rshelper import trade_reviews
        operation=str(uuid4())
        trade_reviews.append_review(None,self.lot.lot_uid,self.entry,expected_revision=0,operation_id=operation,now=1000)
        trade_reviews.append_review(None,self.lot.lot_uid,{**self.entry,'deleted':True},expected_revision=1,operation_id=str(uuid4()),now=1001)
        archive=self.tmp/'reviews.zip';backup.export_profile(None,archive)
        _,files=backup._inspect(archive)
        self.assertIn('trade-reviews.json',files)
        restored=json.loads(files['trade-reviews.json']);trade_reviews.validate_store(restored)
        self.assertEqual(len(restored['entries']),2)
        self.assertTrue(trade_reviews.latest_reviews(restored)[self.lot.lot_uid]['entry']['deleted'])
        older={**restored,'revision':1,'entries':{operation:restored['entries'][operation]}}
        with self.assertRaises(ValueError):trade_reviews.require_successor(restored,older)

    def test_backup_rejects_review_authority_different_from_activation(self):
        from rshelper import trade_reviews
        trade_reviews.append_review(None,self.lot.lot_uid,self.entry,expected_revision=0,operation_id=str(uuid4()),now=1000)
        store=trade_reviews.read_reviews(None);store['authority_origin']=str(uuid4())
        (profile.CONFIG_DIR/'trade-reviews.json').write_text(json.dumps(store))
        archive=self.tmp/'wrong-authority.zip';backup.export_profile(None,archive)
        with self.assertRaisesRegex(ValueError,'review authority'):backup._inspect(archive)

    def test_explicit_review_exclusion_validates_private_json_and_csv(self):
        from rshelper import trade_reviews,profile_transfer
        trade_reviews.append_review(None,self.lot.lot_uid,self.entry,expected_revision=0,operation_id=str(uuid4()),now=1000)
        for format in ('json','csv'):
            full=self.tmp/('full.'+format);filtered=self.tmp/('filtered.'+format)
            profile_transfer.export_profile(None,full,format)
            result=profile_transfer.export_profile(None,filtered,format,include_reviews=False)
            self.assertIn(b'Reversion <private>',full.read_bytes())
            self.assertNotIn(b'Reversion <private>',filtered.read_bytes())
            self.assertNotIn('trade-reviews.json',result['files'])
            self.assertEqual(result['sensitivity'],'private')
            with self.assertRaises(ValueError):
                profile_transfer.import_profile(None,filtered,format,expected_profile_uuid=result['profile_uuid'])

    def test_corrupt_peer_inventory_and_non_roundtrip_tags_are_refused(self):
        from rshelper import trade_reviews
        (profile.CONFIG_DIR/'peer-information.json').write_text('{}')
        with self.assertRaises(ValueError):trade_reviews.read_reviews(None)
        with self.assertRaises(ValueError):backup._validate_file('peer-information.json',b'{}')
        (profile.CONFIG_DIR/'peer-information.json').unlink()
        for tag in (' two words ','two\nlines','tab\there'):
            with self.assertRaises(ValueError):
                trade_reviews.append_review(None,self.lot.lot_uid,{**self.entry,'tags':[tag]},expected_revision=0,operation_id=str(uuid4()))

    def test_publication_interruption_recovers_one_receipt_on_retry(self):
        from rshelper import trade_reviews,state_transaction
        for index,point in enumerate(('intent','data:trade-reviews.json','receipt')):
            revision=trade_reviews.read_reviews(None)['revision'];operation=str(uuid4())
            def fail(phase):
                if phase==point:raise RuntimeError('owned interruption')
            with mock.patch.object(state_transaction,'_checkpoint',side_effect=fail):
                with self.assertRaisesRegex(RuntimeError,'owned interruption'):
                    trade_reviews.append_review(None,self.lot.lot_uid,self.entry,expected_revision=revision,operation_id=operation,now=1000+index)
            retry=trade_reviews.append_review(None,self.lot.lot_uid,self.entry,expected_revision=revision,operation_id=operation,now=2000)
            self.assertTrue(retry['retry']);self.assertEqual(trade_reviews.read_reviews(None)['revision'],revision+1)

    def test_cli_append_retry_and_history_do_not_initialize_config(self):
        from rshelper import cli
        candidate=self.tmp/'entry.json';candidate.write_text(json.dumps(self.entry));operation=str(uuid4())
        (profile.CONFIG_DIR/'config.toml').unlink(missing_ok=True)
        def command(arguments):
            out=io.StringIO()
            with mock.patch.object(sys,'argv',['rshelper','reviews',*arguments]),contextlib.redirect_stdout(out):cli.main()
            return json.loads(out.getvalue())
        args=['append',self.lot.lot_uid,'--input',str(candidate),'--operation-id',operation,'--expected-revision','0','--json']
        self.assertEqual(command(args)['revision'],1);self.assertTrue(command(args)['retry'])
        self.assertEqual(command(['history',self.lot.lot_uid,'--json'])['history_count'],1)
        self.assertFalse((profile.CONFIG_DIR/'config.toml').exists())

    def test_http_privacy_validation_and_replica_write_denial(self):
        from http.server import ThreadingHTTPServer
        from rshelper.dashboard.handlers import make_handler
        from rshelper.scanner import FlipScanner
        calls=[]
        def reviews(body=None,lot_uid=''):
            calls.append((body,lot_uid))
            if body and body['action']=='append':raise PermissionError('Replica')
            return {'can_write':False}
        handler=make_handler(FlipScanner(),lambda:[],owner_token='a'*64,reviews_fn=reviews)
        server=ThreadingHTTPServer(('127.0.0.1',0),handler);server.daemon_threads=True
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            def request(method,body=None,auth=True,path='/api/reviews'):
                client=http.client.HTTPConnection(*server.server_address,timeout=2)
                client.request(method,path,None if body is None else json.dumps(body),{'Authorization':'Bearer '+'a'*64} if auth else {})
                response=client.getresponse();response.read();client.close();return response.status
            self.assertEqual(request('GET',auth=False),401);self.assertFalse(calls)
            self.assertEqual(request('GET'),200)
            self.assertEqual(request('GET',path='/api/reviews?tag=private'),400)
            fields={'action':'append','lot_uid':self.lot.lot_uid,'entry':self.entry,'operation_id':str(uuid4()),'expected_revision':0}
            self.assertEqual(request('POST',{**fields,'entry':{**self.entry,'profit':1}}),400)
            self.assertEqual(len(calls),1)
            self.assertEqual(request('POST',fields),403)
        finally:server.shutdown();server.server_close();thread.join(timeout=2)

if __name__=='__main__':unittest.main()
