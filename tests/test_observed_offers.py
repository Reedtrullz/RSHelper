import copy
import csv
import io
import json
import sys
import unittest
import contextlib
import http.client
import threading
from pathlib import Path
from uuid import uuid4
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_native_writers import DisposableHomeTest
from rshelper import profile,backup,state_transaction,state_identity

class ObservedOffersTest(DisposableHomeTest):
    def setUp(self):
        super().setUp();self.activate();self.offer=str(uuid4())
        path=profile.CONFIG_DIR/'identity-activation.json'
        activation=json.loads(path.read_text());activation['profile_uuid']=str(uuid4());path.write_text(json.dumps(activation))
        (profile.CONFIG_DIR/'identity-manifest.json').write_text(json.dumps(state_identity.new_manifest(activation['origin_uuid'])))
        self.event={'state':'planned','item_id':2,'side':'buy','qty':10,'limit_price':100,
                    'filled_qty':0,'collected_qty':0,'actual_gp':0,'fees':0,
                    'observed_at':'2026-10-12T10:00:00+00:00','source':'manual','evidence':'Synthetic receipt','corrects':None}

    def record(self,**changes):
        from rshelper import observed_offers as offers
        revision=offers.read_store(None)['revision']
        return offers.record_observation(None,self.offer,{**self.event,**changes},operation_id=str(uuid4()),expected_revision=revision)

    def test_partial_cancel_collect_retry_and_separate_reservations(self):
        from rshelper import observed_offers as offers
        self.record();self.record(state='placed');operation=str(uuid4())
        event={**self.event,'state':'partial','filled_qty':4,'actual_gp':380}
        first=offers.record_observation(None,self.offer,event,operation_id=operation,expected_revision=2)
        self.assertTrue(offers.record_observation(None,self.offer,event,operation_id=operation,expected_revision=2)['retry'])
        summary=offers.summary(offers.read_store(None),slot_limit=8)
        self.assertEqual((summary['reserved_cash'],summary['used_slots'],summary['actual_cash_flow']), (600,1,-380))
        self.assertIsNone(summary['available_cash']);self.assertIsNone(summary['realized_profit'])
        self.record(state='canceled',filled_qty=4,actual_gp=380)
        self.assertEqual(offers.summary(offers.read_store(None))['reserved_cash'],0)
        self.record(state='collected',filled_qty=4,collected_qty=4,actual_gp=380)
        self.assertEqual(offers.summary(offers.read_store(None))['used_slots'],0)
        self.assertEqual(first['revision'],3)
        self.assertFalse((profile.CONFIG_DIR/'paper-offers.json').exists())

    def test_invalid_transitions_overcollection_and_fake_provenance_fail_closed(self):
        from rshelper import observed_offers as offers
        for changes in ({'state':'partial','filled_qty':4,'actual_gp':380},{'source':'paper'},{'qty':True},{'fees':1}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.record(**changes)
        self.record();self.record(state='placed')
        for changes in ({'state':'collected','collected_qty':1},{'state':'partial','filled_qty':11,'actual_gp':1000},{'state':'partial','filled_qty':2,'actual_gp':0}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.record(**changes)
        with self.assertRaises(ValueError):offers.record_observation(None,self.offer,self.event,operation_id=str(uuid4()),expected_revision=0)
        self.activate(financial_authority=False)
        with self.assertRaises(ValueError):self.record(state='partial',filled_qty=1,actual_gp=90)

    def test_correction_keeps_receipt_history_and_backup_cannot_rewind(self):
        from rshelper import observed_offers as offers
        self.record();self.record(state='placed');result=self.record(state='partial',filled_qty=4,actual_gp=380)
        self.record(state='partial',filled_qty=4,actual_gp=390,corrects=result['operation_id'])
        store=offers.read_store(None)
        self.assertEqual(offers.summary(store)['actual_cash_flow'],-390)
        self.assertEqual(len(store['entries']),4)
        archive=self.tmp/'offers.zip';backup.export_profile(None,archive)
        _,files=backup._inspect(archive);self.assertIn(offers.FILENAME,files)
        older=copy.deepcopy(store);older['entries'].pop(next(k for k,v in older['entries'].items() if v['revision']==4));older['revision']=3
        with self.assertRaises(ValueError):offers.require_successor(store,older)
        self.assertEqual(json.loads(files[offers.FILENAME]),store)

    def test_transaction_interruption_retry_is_exactly_once(self):
        from rshelper import observed_offers as offers
        for point in ('intent','data:observed-offers.json','receipt'):
            offer=str(uuid4());operation=str(uuid4());revision=offers.read_store(None)['revision']
            def fail(phase):
                if phase==point:raise RuntimeError('owned interruption')
            with mock.patch.object(state_transaction,'_checkpoint',side_effect=fail),self.assertRaises(RuntimeError):
                offers.record_observation(None,offer,self.event,operation_id=operation,expected_revision=revision)
            result=offers.record_observation(None,offer,self.event,operation_id=operation,expected_revision=revision)
            self.assertTrue(result['retry']);self.assertEqual(offers.read_store(None)['revision'],revision+1)

    def test_csv_preview_unknown_item_conflict_and_backup_before_atomic_apply(self):
        from rshelper import observed_offers as offers
        event={**self.event,'source':'csv'};operation=str(uuid4())
        output=io.StringIO();writer=csv.DictWriter(output,fieldnames=offers.CSV_FIELDS)
        writer.writeheader();writer.writerow({'offer_uuid':self.offer,'operation_id':operation,'expected_revision':0,**event})
        raw=output.getvalue().encode()
        invalid=offers.import_csv(None,raw,known_items=set())
        self.assertFalse(invalid['valid']);self.assertEqual(invalid['unknown_item_ids'],[2])
        preview=offers.import_csv(None,raw,known_items={2})
        self.assertTrue(preview['valid']);self.assertFalse((profile.CONFIG_DIR/offers.FILENAME).exists())
        archive=self.tmp/'pre-import.zip'
        with self.assertRaises(ValueError):offers.import_csv(None,raw,known_items={2},apply=True,expected_import_hash='0'*64,backup_path=archive)
        self.assertFalse(archive.exists())
        result=offers.import_csv(None,raw,known_items={2},apply=True,expected_import_hash=preview['import_hash'],backup_path=archive)
        self.assertEqual(result['status'],'applied');self.assertTrue(archive.exists())
        _,files=backup._inspect(archive);self.assertNotIn(offers.FILENAME,files)
        retry=offers.import_csv(None,raw,known_items={2},apply=True,expected_import_hash=preview['import_hash'],backup_path=archive)
        self.assertTrue(retry['retry']);self.assertEqual(offers.read_store(None)['revision'],1)

    def test_missing_acknowledged_ledger_refuses_backup_and_recording(self):
        from rshelper import observed_offers as offers
        older=self.tmp/'before-observed.zip';backup.export_profile(None,older)
        self.record();(profile.CONFIG_DIR/offers.FILENAME).unlink()
        activation=state_identity.activation_manifest(profile.CONFIG_DIR/'identity-activation.json')
        with self.assertRaises(backup.BackupError):
            backup.restore_profile(None,older,expected_profile_uuid=activation['profile_uuid'],operation_id=None,dry_run=True)
        with self.assertRaises(ValueError):offers.read_store(None)
        with self.assertRaises(ValueError):backup.export_profile(None,self.tmp/'missing.zip')
        from rshelper import state_replication
        with self.assertRaises(ValueError):state_replication.validate_profile(None)

    def test_csv_interrupted_commit_recovers_without_rewriting_preapply_backup(self):
        from rshelper import observed_offers as offers
        output=io.StringIO();writer=csv.DictWriter(output,fieldnames=offers.CSV_FIELDS)
        writer.writeheader();writer.writerow({'offer_uuid':self.offer,'operation_id':str(uuid4()),'expected_revision':0,**{**self.event,'source':'csv'}})
        raw=output.getvalue().encode();preview=offers.import_csv(None,raw,known_items={2})
        archive=self.tmp/'interrupted-import.zip'
        def interrupt(phase):
            if phase=='data:observed-offers.json':raise RuntimeError('owned interruption')
        with mock.patch.object(state_transaction,'_checkpoint',side_effect=interrupt),self.assertRaises(RuntimeError):
            offers.import_csv(None,raw,known_items={2},apply=True,expected_import_hash=preview['import_hash'],backup_path=archive)
        before=archive.read_bytes()
        result=offers.import_csv(None,raw,known_items={2},apply=True,expected_import_hash=preview['import_hash'],backup_path=archive)
        self.assertTrue(result['retry']);self.assertEqual(archive.read_bytes(),before)
        self.assertEqual(offers.read_store(None)['revision'],1)

    def test_unfilled_canceled_plan_never_reserves_a_game_slot(self):
        from rshelper import observed_offers as offers
        self.record();self.record(state='canceled')
        self.assertEqual(offers.summary(offers.read_store(None))['used_slots'],0)
        self.record(state='collected')
        self.assertEqual(offers.summary(offers.read_store(None))['used_slots'],0)
        self.offer=str(uuid4());self.record();self.record(state='placed');self.record(state='canceled')
        self.assertEqual(offers.summary(offers.read_store(None))['used_slots'],1)
        self.record(state='collected')
        self.assertEqual(offers.summary(offers.read_store(None))['used_slots'],0)

    def test_sell_reservation_actual_fees_and_csv_conflict_preview(self):
        from rshelper import observed_offers as offers
        self.event.update(side='sell')
        self.record();self.record(state='placed')
        self.record(state='partial',filled_qty=4,actual_gp=420,fees=8)
        summary=offers.summary(offers.read_store(None),slot_limit=8)
        self.assertEqual(summary['reserved_inventory'],{'2':6})
        self.assertEqual((summary['reserved_cash'],summary['actual_cash_flow']),(0,412))
        self.assertIsNone(summary['realized_profit'])
        event={**self.event,'source':'csv'}
        output=io.StringIO();writer=csv.DictWriter(output,fieldnames=offers.CSV_FIELDS)
        writer.writeheader();writer.writerow({'offer_uuid':self.offer,'operation_id':str(uuid4()),'expected_revision':0,**event})
        before=(profile.CONFIG_DIR/offers.FILENAME).read_bytes()
        preview=offers.import_csv(None,output.getvalue().encode(),known_items={2})
        self.assertFalse(preview['valid']);self.assertEqual(preview['conflicts'][0]['row'],1)
        self.assertEqual((profile.CONFIG_DIR/offers.FILENAME).read_bytes(),before)

    def test_host_contract_rejects_missing_support_and_missing_acknowledged_data(self):
        import importlib.util
        from rshelper import cli,observed_offers as offers
        path=Path(__file__).resolve().parents[1]/'deploy/state_contract.py'
        spec=importlib.util.spec_from_file_location('observed_contract',path)
        contract=importlib.util.module_from_spec(spec);spec.loader.exec_module(contract)
        with mock.patch.object(sys,'argv',['contract']),mock.patch.object(cli,'main') as run:
            contract.main();run.assert_called_once()
        self.record()
        with mock.patch.object(sys,'argv',['contract']),mock.patch.dict(sys.modules,{'rshelper.observed_offers':None}),mock.patch.object(cli,'main') as run:
            with self.assertRaises(ModuleNotFoundError):contract.main()
            run.assert_not_called()
        (profile.CONFIG_DIR/offers.FILENAME).unlink()
        with mock.patch.object(sys,'argv',['contract']),mock.patch.object(cli,'main') as run:
            with self.assertRaises(ValueError):contract.main()
            run.assert_not_called()

    def test_private_transfer_contains_observations_and_publication_refuses_them(self):
        from rshelper import observed_offers as offers,profile_transfer,publication
        self.record()
        destination=self.tmp/'private-export.json'
        receipt=profile_transfer.export_profile(None,destination)
        self.assertEqual(receipt['sensitivity'],'private')
        self.assertEqual(json.loads(json.loads(destination.read_text())['files'][offers.FILENAME]),offers.read_store(None))
        policy={'schema_version':1,'mode':'public-demo','approved_profiles':['synthetic-demo'],
                'files':{offers.FILENAME:['item_id','actual_gp']}}
        with self.assertRaises(publication.PublicationError):publication.export_demo({offers.FILENAME:offers.read_store(None)},policy,profile='synthetic-demo')
        profile.atomic_write_json(profile.CONFIG_DIR/offers.FILENAME,offers.empty_store())
        with self.assertRaises(ValueError):offers.read_store(None)

    def test_cli_record_history_and_json_do_not_initialize_config(self):
        from rshelper import cli
        candidate=self.tmp/'receipt.json';candidate.write_text(json.dumps(self.event));operation=str(uuid4())
        def command(args):
            output=io.StringIO()
            with mock.patch.object(sys,'argv',['rshelper','observed',*args]),contextlib.redirect_stdout(output):cli.main()
            return json.loads(output.getvalue())
        args=['record',self.offer,'--input',str(candidate),'--expected-revision','0','--operation-id',operation,'--json']
        self.assertEqual(command(args)['revision'],1);self.assertTrue(command(args)['retry'])
        self.assertEqual(command(['history',self.offer,'--json'])['total'],1)
        self.assertEqual(command(['list','--slots','8','--json'])['slot_limit'],8)
        self.assertFalse((profile.CONFIG_DIR/'config.toml').exists())

    def test_private_http_validation_and_replica_denial(self):
        from http.server import ThreadingHTTPServer
        from rshelper.dashboard.handlers import make_handler
        from rshelper.scanner import FlipScanner
        calls=[]
        def callback(body=None):
            calls.append(body)
            if body is not None:raise PermissionError('Read-only replica')
            return {'can_write':False}
        server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(FlipScanner(),lambda:[],owner_token='a'*64,observed_fn=callback));server.daemon_threads=True
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            def request(method,body=None,auth=True,path='/api/observed'):
                client=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=2)
                client.request(method,path,None if body is None else json.dumps(body),{'Authorization':'Bearer '+'a'*64} if auth else {})
                response=client.getresponse();response.read();client.close();return response.status
            fields={'offer_uuid':self.offer,'event':self.event,'operation_id':str(uuid4()),'expected_revision':0}
            self.assertEqual(request('GET',auth=False),401);self.assertFalse(calls)
            self.assertEqual(request('GET'),200)
            self.assertEqual(request('POST',{**fields,'event':{**self.event,'source':'paper'}}),400)
            self.assertEqual(request('GET',path='/api/observed?note=private'),400)
            self.assertEqual(len(calls),1);self.assertEqual(request('POST',fields),403)
        finally:server.shutdown();server.server_close();thread.join(timeout=2)

if __name__=='__main__':unittest.main()
