"""Crash recovery, exact lot ownership and idempotent paper realization."""
import contextlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from rshelper import positions,journal,state_identity

ORIGIN='11111111-1111-4111-8111-111111111111'
OP='22222222-2222-4222-8222-222222222222'

class RealizationTest(unittest.TestCase):
    @staticmethod
    def crash_at(target):
        def checkpoint(step):
            if step == target: raise RuntimeError("crash")
        return checkpoint

    def api(self):
        from rshelper import realization
        return realization

    @contextlib.contextmanager
    def fixture(self,api):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            rows,manifest=state_identity.migrate_rows([
                {'id':1,'item_id':2,'name':'Fixture','qty':10,'buy_price':100,
                 'direction':'traditional','opened_at':'2026-01-01T00:00:00Z'},
                {'id':2,'item_id':2,'name':'Fixture','qty':7,'buy_price':130,
                 'direction':'arbitrage','opened_at':'2026-01-01T00:01:00Z'},
            ],'positions',state_identity.new_manifest(ORIGIN))
            (root/'positions.json').write_text(json.dumps({'positions':rows}))
            (root/'trades.json').write_text('{"trades":[]}')
            (root/'identity-manifest.json').write_text(json.dumps(manifest))
            with mock.patch.object(positions,'POSITIONS_PATH',root/'positions.json'), mock.patch.object(journal,'TRADES_PATH',root/'trades.json'), mock.patch.object(api,'_intent_path',return_value=root/'realizations.json'), mock.patch.object(api,'_manifest_path',return_value=root/'identity-manifest.json'):
                yield root,rows

    def test_crash_restart_realizes_once(self):
        api=self.api()
        for crash in ('intent','journal','positions','receipt'):
            with self.subTest(crash=crash),self.fixture(api) as (root,rows):
                def checkpoint(step):
                    if step==crash:raise RuntimeError('injected crash')
                with mock.patch.object(api,'_checkpoint',side_effect=checkpoint):
                    with self.assertRaisesRegex(RuntimeError,'injected crash'):
                        api.close_and_realize('default',rows[0]['lot_uid'],4,120,OP,'manual')
                api.recover_pending('default')
                receipt=api.close_and_realize('default',rows[0]['lot_uid'],4,120,OP,'manual')
                self.assertTrue(receipt['replayed'])
                trades=journal.list_trades()
                self.assertEqual(len(trades),1)
                self.assertEqual((trades[0].qty,trades[0].buy_price,trades[0].profit),(4,100,72))
                remaining=json.loads((root/'positions.json').read_text())['positions']
                self.assertEqual(next(p['qty'] for p in remaining if p['record_uuid']==rows[0]['record_uuid']),6)
                self.assertEqual(sum(p['qty'] for p in remaining)+sum(t.qty for t in trades),17)

    def test_repeated_operation_and_competing_close_cannot_double_realize(self):
        api=self.api()
        with self.fixture(api) as (root,rows):
            first=api.close_and_realize('default',rows[0]['lot_uid'],10,120,OP,'manual')
            again=api.close_and_realize('default',rows[0]['lot_uid'],10,120,OP,'manual')
            self.assertEqual(first['trade_ids'],again['trade_ids'])
            self.assertTrue(again['replayed'])
            with self.assertRaises(ValueError):
                api.close_and_realize('default',rows[0]['lot_uid'],1,120,'33333333-3333-4333-8333-333333333333','manual')
            self.assertEqual(len(journal.list_trades()),1)
            self.assertEqual(positions.open_qty(2),7)

    def test_same_item_mixed_direction_lots_keep_target_cost_basis(self):
        api=self.api()
        with self.fixture(api) as (root,rows):
            api.close_and_realize('default',rows[1]['lot_uid'],3,140,OP,'manual')
            trade=journal.list_trades()[0]
            self.assertEqual((trade.qty,trade.buy_price,trade.sell_price,trade.tax_paid,trade.profit),(3,130,140,6,24))
            quantities={p['record_uuid']:p['qty'] for p in json.loads((root/'positions.json').read_text())['positions']}
            self.assertEqual(quantities[rows[0]['record_uuid']],10)
            self.assertEqual(quantities[rows[1]['record_uuid']],4)

    def test_durable_persist_syncs_file_before_directory(self):
        import os,stat
        api=self.api();synced=[];real_sync=os.fsync
        def sync(fd):synced.append(stat.S_ISDIR(os.fstat(fd).st_mode));real_sync(fd)
        with tempfile.TemporaryDirectory() as folder,mock.patch.object(api.os,'fsync',side_effect=sync):
            path=Path(folder)/'fixture.json';api._persist(path,{'schema_version':1})
            self.assertEqual(synced,[False,True])
            self.assertEqual(path.stat().st_mode & 0o777,0o600)

    def test_pending_position_conflict_refuses_before_journal_mutation(self):
        api=self.api()
        with self.fixture(api) as (root,rows):
            with mock.patch.object(api,'_checkpoint',side_effect=self.crash_at('intent')):
                with self.assertRaises(RuntimeError):api.close_and_realize('default',rows[0]['lot_uid'],4,120,OP,'manual')
            state=json.loads((root/'positions.json').read_text());state['positions'][0]['qty']=8
            (root/'positions.json').write_text(json.dumps(state));before=(root/'trades.json').read_bytes()
            with self.assertRaises(ValueError):api.recover_pending('default')
            self.assertEqual(before,(root/'trades.json').read_bytes())

    def test_corrupt_intent_shape_refuses_without_financial_writes(self):
        api=self.api()
        for malformed in (None, {'operation_id':OP,'lot_uid':ORIGIN,'qty':4}):
            with self.subTest(malformed=malformed),self.fixture(api) as (root,rows):
                with mock.patch.object(api,'_checkpoint',side_effect=self.crash_at('intent')):
                    with self.assertRaises(RuntimeError):api.close_and_realize('default',rows[0]['lot_uid'],4,120,OP,'manual')
                path=root/'realizations.json';data=json.loads(path.read_text());data['operations'][OP]['request']=malformed;path.write_text(json.dumps(data))
                before=(root/'trades.json').read_bytes()
                with self.assertRaises(ValueError):api.recover_pending('default')
                self.assertEqual(before,(root/'trades.json').read_bytes())

    def test_corrupt_completed_proof_cannot_report_success(self):
        api=self.api()
        for damaged in ('journal', 'marker', 'done', 'origin'):
            with self.subTest(damaged=damaged),self.fixture(api) as (root,rows):
                if damaged=='done':
                    with mock.patch.object(api,'_checkpoint',side_effect=self.crash_at('intent')):
                        with self.assertRaises(RuntimeError):api.close_and_realize('default',rows[0]['lot_uid'],4,120,OP,'manual')
                    path=root/'realizations.json';data=json.loads(path.read_text());data['operations'][OP]['done']=True
                else:
                    api.close_and_realize('default',rows[0]['lot_uid'],4,120,OP,'manual')
                    if damaged=='journal':path=root/'trades.json';data={'trades':[]}
                    elif damaged=='marker':
                        path=root/'positions.json';data=json.loads(path.read_text());data['realizations']={}
                    else:
                        path=root/'identity-manifest.json';data=state_identity.new_manifest('33333333-3333-4333-8333-333333333333')
                path.write_text(json.dumps(data))
                before={name:(root/name).read_bytes() for name in ('positions.json','trades.json','realizations.json','identity-manifest.json')}
                with self.assertRaises(ValueError):api.close_and_realize('default',rows[0]['lot_uid'],4,120,OP,'manual')
                self.assertEqual(before,{name:(root/name).read_bytes() for name in before})

    def test_wrong_economics_or_invalid_intent_refuses_before_writes(self):
        api=self.api()
        mutations=(lambda d:d['operations'][OP]['trade'].__setitem__('profit',999),
                   lambda d:d['operations'][OP]['before'].__setitem__('tombstone',True),
                   lambda d:d['operations'][OP]['trade'].__setitem__('revision',1),
                   lambda d:d['operations'][OP]['trade'].__setitem__('tombstone',True),
                   lambda d:d['operations'][OP]['receipt'].__setitem__('trade_ids',[True]))
        for change in mutations:
            with self.subTest(change=change),self.fixture(api) as (root,rows):
                with mock.patch.object(api,'_checkpoint',side_effect=self.crash_at('intent')):
                    with self.assertRaises(RuntimeError):api.close_and_realize('default',rows[0]['lot_uid'],4,120,OP,'manual')
                path=root/'realizations.json';data=json.loads(path.read_text());change(data);path.write_text(json.dumps(data))
                before={name:(root/name).read_bytes() for name in ('positions.json','trades.json')}
                with self.assertRaises(ValueError):api.recover_pending('default')
                self.assertEqual(before,{name:(root/name).read_bytes() for name in before})

    def test_reused_operation_conflicts_and_capacity_preserve_bytes(self):
        api=self.api()
        with self.fixture(api) as (root,rows):
            api.close_and_realize('default',rows[0]['lot_uid'],4,120,OP,'manual')
            before={name:(root/name).read_bytes() for name in ('positions.json','trades.json','realizations.json')}
            for args in ((rows[1]['lot_uid'],4,120,OP,'manual'),(rows[0]['lot_uid'],5,120,OP,'manual'),(rows[0]['lot_uid'],4,121,OP,'manual'),(rows[0]['lot_uid'],4,120,OP,'stop')):
                with self.assertRaisesRegex(ValueError,'reused'):api.close_and_realize('default',*args)
            with mock.patch.object(api,'MAX_OPERATIONS',1):
                with self.assertRaisesRegex(ValueError,'budget'):api.close_and_realize('default',rows[0]['lot_uid'],1,120,'33333333-3333-4333-8333-333333333333','manual')
            self.assertEqual(before,{name:(root/name).read_bytes() for name in before})

    def test_metadata_survives_recovery_and_conflicting_retry_refuses(self):
        api=self.api()
        with self.fixture(api) as (root,rows):
            metadata={'note':'paper','strategy':'auto','hold_minutes':20.5,'quote_sell':122,
                      'entry_spread_pct':6.25,'fill_guard':True,
                      'market_data':{'latest':{'source':'fixture','stale':False}}}
            with mock.patch.object(api,'_checkpoint',side_effect=self.crash_at('journal')):
                with self.assertRaises(RuntimeError):api.close_and_realize('default',rows[0]['lot_uid'],4,120,OP,'stop_loss',metadata=metadata)
            original=json.loads(json.dumps(metadata));metadata['market_data']['latest']['source']='changed after call'
            api.recover_pending('default')
            receipt=api.close_and_realize('default',rows[0]['lot_uid'],4,120,OP,'stop_loss',metadata=original)
            self.assertTrue(receipt['replayed'])
            trade=json.loads((root/'trades.json').read_text())['trades'][0]
            self.assertEqual({key:trade[key] for key in original},original)
            with self.assertRaisesRegex(ValueError,'reused'):
                api.close_and_realize('default',rows[0]['lot_uid'],4,120,OP,'stop_loss',metadata=metadata)

    def test_invalid_metadata_refuses_before_intent_or_financial_writes(self):
        api=self.api()
        for metadata in ({'strategy':None},{'strategy':'x'*65},{'hold_minutes':float('nan')},
                         {'hold_minutes':-1},{'quote_sell':True},{'fill_guard':1},
                         {'market_data':[]},{'market_data':{'body':'x'*17000}},
                         {'buy_price':999}):
            with self.subTest(metadata=metadata),self.fixture(api) as (root,rows):
                before={name:(root/name).read_bytes() for name in ('positions.json','trades.json')}
                with self.assertRaises(ValueError):api.close_and_realize('default',rows[0]['lot_uid'],4,120,OP,'manual',metadata=metadata)
                self.assertFalse((root/'realizations.json').exists())
                self.assertEqual(before,{name:(root/name).read_bytes() for name in before})

    def test_applied_marker_cannot_hide_restored_or_changed_units(self):
        api=self.api()
        for qty,complete in ((4,False),(10,False),(4,True)):
            with self.subTest(qty=qty,complete=complete),self.fixture(api) as (root,rows):
                if complete:api.close_and_realize('default',rows[0]['lot_uid'],qty,120,OP,'manual')
                else:
                    with mock.patch.object(api,'_checkpoint',side_effect=self.crash_at('positions')):
                        with self.assertRaises(RuntimeError):api.close_and_realize('default',rows[0]['lot_uid'],qty,120,OP,'manual')
                path=root/'positions.json';data=json.loads(path.read_text())
                data['positions']=[rows[0],rows[1]];path.write_text(json.dumps(data))
                before={name:(root/name).read_bytes() for name in ('positions.json','trades.json','realizations.json')}
                with self.assertRaises(ValueError):api.close_and_realize('default',rows[0]['lot_uid'],qty,120,OP,'manual')
                self.assertEqual(before,{name:(root/name).read_bytes() for name in before})

    def test_duplicate_tombstoned_identity_refuses_before_intent(self):
        api=self.api()
        with self.fixture(api) as (root,rows):
            path=root/'positions.json';data=json.loads(path.read_text())
            data['positions'].append({**rows[0],'tombstone':True,'revision':1});path.write_text(json.dumps(data))
            before=path.read_bytes()
            with self.assertRaises(ValueError):api.close_and_realize('default',rows[0]['lot_uid'],4,120,OP,'manual')
            self.assertFalse((root/'realizations.json').exists())
            self.assertEqual(before,path.read_bytes())

    def test_earlier_receipt_replays_after_later_partial_and_full_closes(self):
        api=self.api()
        with self.fixture(api) as (root,rows):
            args=('default',rows[0]['lot_uid'],4,120,OP,'manual')
            first=api.close_and_realize(*args)
            second='33333333-3333-4333-8333-333333333333'
            api.close_and_realize('default',rows[0]['lot_uid'],3,125,second,'manual')
            self.assertEqual(api.close_and_realize(*args)['trade_ids'],first['trade_ids'])
            api.close_and_realize('default',rows[0]['lot_uid'],3,130,'44444444-4444-4444-8444-444444444444','manual')
            self.assertEqual(api.close_and_realize(*args)['trade_ids'],first['trade_ids'])
            self.assertEqual(sum(trade.qty for trade in journal.list_trades()),10)

    def test_restart_or_new_operation_audits_prior_completed_evidence(self):
        api=self.api()
        for action in ('recover','new'):
            with self.subTest(action=action),self.fixture(api) as (root,rows):
                api.close_and_realize('default',rows[0]['lot_uid'],4,120,OP,'manual')
                path=root/'positions.json';data=json.loads(path.read_text());data['positions'][0]=rows[0]
                path.write_text(json.dumps(data));before={name:(root/name).read_bytes() for name in ('positions.json','trades.json','realizations.json')}
                with self.assertRaises(ValueError):
                    if action=='recover':api.recover_pending('default')
                    else:api.close_and_realize('default',rows[0]['lot_uid'],1,120,'33333333-3333-4333-8333-333333333333','manual')
                self.assertEqual(before,{name:(root/name).read_bytes() for name in before})

    def test_projected_financial_byte_budget_refuses_before_intent(self):
        api=self.api()
        with self.fixture(api) as (root,rows):
            path=root/'trades.json';path.write_text(json.dumps({'trades':[],'extension':'x'*5500}))
            before=path.read_bytes()
            with mock.patch.object(api,'MAX_STATE_BYTES',5000):
                with self.assertRaisesRegex(ValueError,'budget'):api.close_and_realize('default',rows[0]['lot_uid'],4,120,OP,'manual')
            self.assertFalse((root/'realizations.json').exists())
            self.assertEqual(before,path.read_bytes())

    def test_unowned_journal_operation_identity_refuses_before_intent(self):
        from uuid import UUID,uuid5
        api=self.api()
        with self.fixture(api) as (root,rows):
            path=root/'trades.json'
            row={'id':1,'item_id':2,'name':'Other','qty':1,'buy_price':10,'sell_price':20,
                 'tax_paid':0,'profit':10,'timestamp':'2026-01-01T00:00:00Z',
                 'record_uuid':str(uuid5(UUID(ORIGIN),OP)),'origin_uuid':ORIGIN,
                 'revision':0,'tombstone':False}
            path.write_text(json.dumps({'trades':[row]}));before=path.read_bytes()
            with self.assertRaises(ValueError):api.close_and_realize('default',rows[0]['lot_uid'],4,120,OP,'manual')
            self.assertFalse((root/'realizations.json').exists())
            self.assertEqual(before,path.read_bytes())

    def test_cleanup_error_still_closes_directory_descriptor(self):
        import os
        api=self.api();opened=[];real_open=os.open
        def open_file(*args,**kwargs):
            descriptor=real_open(*args,**kwargs);opened.append(descriptor);return descriptor
        with tempfile.TemporaryDirectory() as folder:
            with mock.patch.object(api.os,'open',side_effect=open_file),mock.patch.object(api.os,'unlink',side_effect=PermissionError('injected cleanup failure')):
                with self.assertRaises(PermissionError):api._persist(Path(folder)/'fixture.json',{'value':1})
            for descriptor in opened:
                with self.assertRaises(OSError):os.fstat(descriptor)

    def test_nested_metadata_retry_preserves_json_types(self):
        api=self.api()
        with self.fixture(api) as (root,rows):
            api.close_and_realize('default',rows[0]['lot_uid'],4,120,OP,'manual',metadata={'market_data':{'volume':1}})
            for value in (True,1.0):
                with self.subTest(value=value),self.assertRaisesRegex(ValueError,'reused'):
                    api.close_and_realize('default',rows[0]['lot_uid'],4,120,OP,'manual',metadata={'market_data':{'volume':value}})
            path=root/'realizations.json';data=json.loads(path.read_text())
            data['operations'][OP]['trade']['market_data']['volume']=True;path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):api.recover_pending('default')

    def test_existing_empty_intent_object_is_corruption(self):
        api=self.api()
        with self.fixture(api) as (root,rows):
            path=root/'realizations.json';path.write_text('{}')
            before={name:(root/name).read_bytes() for name in ('positions.json','trades.json','realizations.json')}
            with self.assertRaises(ValueError):api.close_and_realize('default',rows[0]['lot_uid'],4,120,OP,'manual')
            self.assertEqual(before,{name:(root/name).read_bytes() for name in before})

    def test_journal_evidence_preserves_nested_json_types(self):
        api=self.api()
        with self.fixture(api) as (root,rows):
            api.close_and_realize('default',rows[0]['lot_uid'],4,120,OP,'manual',metadata={'market_data':{'volume':1}})
            path=root/'trades.json';data=json.loads(path.read_text());data['trades'][0]['market_data']['volume']=True
            path.write_text(json.dumps(data));before=path.read_bytes()
            with self.assertRaises(ValueError):api.recover_pending('default')
            with self.assertRaises(ValueError):api.close_and_realize('default',rows[0]['lot_uid'],4,120,OP,'manual',metadata={'market_data':{'volume':1}})
            self.assertEqual(before,path.read_bytes())

    def test_full_close_retains_mergeable_tombstone_without_counting_open_units(self):
        from rshelper import identity_merge
        api=self.api()
        with self.fixture(api) as (root,rows):
            receipt=api.close_and_realize('default',rows[0]['lot_uid'],10,120,OP,'manual')
            state=json.loads((root/'positions.json').read_text())['positions']
            closed=[row for row in state if row['lot_uid']==rows[0]['lot_uid']]
            self.assertEqual(len(closed),1,'full close lost deletion evidence')
            self.assertTrue(closed[0]['tombstone']);self.assertEqual(closed[0]['revision'],1)
            self.assertEqual(positions.open_qty(2),7);self.assertEqual(len(positions.list_positions()),1)
            merged=identity_merge.merge_rows(rows,state,'positions')
            self.assertTrue(next(row for row in merged if row['lot_uid']==rows[0]['lot_uid'])['tombstone'])
            self.assertEqual(receipt['remaining_qty'],0)

    def test_recovery_accepts_merge_aliases_canonical_times_and_retained_journal_delete(self):
        from rshelper import identity_merge
        api=self.api()
        with self.fixture(api) as (root,rows):
            args=('default',rows[0]['lot_uid'],4,120,OP,'manual')
            first=api.close_and_realize(*args)
            position_path=root/'positions.json';store=json.loads(position_path.read_text())
            store['positions']=identity_merge.merge_rows(store['positions'],[],'positions')
            for row in store['positions']:row['id']+=20
            position_path.write_text(json.dumps(store))
            trade_path=root/'trades.json';store=json.loads(trade_path.read_text())
            store['trades']=identity_merge.merge_rows(store['trades'],[],'trades')
            store['trades'][0].update(id=71,revision=1,tombstone=True)
            trade_uuid=store['trades'][0]['record_uuid'];trade_path.write_text(json.dumps(store))
            before={name:(root/name).read_bytes() for name in ('positions.json','trades.json','realizations.json')}
            api.recover_pending('default');replayed=api.close_and_realize(*args)
            self.assertTrue(replayed['replayed']);self.assertEqual(replayed['trade_ids'],[71])
            self.assertEqual(replayed['trade_uuids'],[trade_uuid])
            self.assertEqual(journal.list_trades(),[])
            self.assertEqual(before,{name:(root/name).read_bytes() for name in before})
            api.close_and_realize('default',rows[0]['lot_uid'],6,120,'33333333-3333-4333-8333-333333333333','manual')
            self.assertEqual(positions.open_qty(2),7)
            self.assertEqual(api.close_and_realize(*args)['trade_uuids'],[trade_uuid])

    def test_pending_close_recovers_after_safe_merge_alias_normalization(self):
        from rshelper import identity_merge
        api=self.api()
        for checkpoint in ('intent','journal','positions'):
            with self.subTest(checkpoint=checkpoint),self.fixture(api) as (root,rows):
                with mock.patch.object(api,'_checkpoint',side_effect=self.crash_at(checkpoint)):
                    with self.assertRaises(RuntimeError):api.close_and_realize('default',rows[0]['lot_uid'],10,120,OP,'manual')
                for filename,kind in (('positions.json','positions'),('trades.json','trades')):
                    path=root/filename;store=json.loads(path.read_text())
                    store[kind]=identity_merge.merge_rows(store[kind],[],kind)
                    for row in store[kind]:row['id']+=20
                    path.write_text(json.dumps(store))
                api.recover_pending('default')
                receipt=api.close_and_realize('default',rows[0]['lot_uid'],10,120,OP,'manual')
                self.assertTrue(receipt['replayed']);self.assertEqual(positions.open_qty(2),7)
                self.assertEqual(sum(row.qty for row in journal.list_trades()),10)

    def test_deleted_journal_still_requires_original_economics_and_lot_link(self):
        api=self.api()
        for field,value in (('buy_price',101),('profit',999),('closed_lot_uid',ORIGIN),
                            ('market_data',{'volume':True})):
            with self.subTest(field=field),self.fixture(api) as (root,rows):
                api.close_and_realize('default',rows[0]['lot_uid'],4,120,OP,'manual',metadata={'market_data':{'volume':1}})
                path=root/'trades.json';store=json.loads(path.read_text())
                store['trades'][0].update({field:value,'revision':1,'tombstone':True})
                path.write_text(json.dumps(store))
                before={name:(root/name).read_bytes() for name in ('positions.json','trades.json','realizations.json')}
                with self.assertRaises(ValueError):api.recover_pending('default')
                self.assertEqual(before,{name:(root/name).read_bytes() for name in before})

    def test_pending_intent_reassigns_colliding_display_alias_without_reassigning_uuid(self):
        from rshelper import identity_merge
        api=self.api()
        with self.fixture(api) as (root,rows):
            with mock.patch.object(api,'_checkpoint',side_effect=self.crash_at('intent')):
                with self.assertRaises(RuntimeError):api.close_and_realize('default',rows[0]['lot_uid'],4,120,OP,'manual')
            original=json.loads((root/'realizations.json').read_text())['operations'][OP]['trade']
            unrelated={'id':1,'item_id':3,'name':'Other','qty':1,'buy_price':10,'sell_price':20,
                       'tax_paid':0,'profit':10,'timestamp':'2026-01-01T00:00:00Z'}
            other,_=state_identity.migrate_rows([unrelated],'trades',state_identity.new_manifest(ORIGIN))
            (root/'trades.json').write_text(json.dumps({'trades':other}))
            api.recover_pending('default')
            receipt=api.close_and_realize('default',rows[0]['lot_uid'],4,120,OP,'manual')
            self.assertEqual(receipt['trade_ids'],[2]);self.assertEqual(receipt['trade_uuids'],[original['record_uuid']])
            trades=json.loads((root/'trades.json').read_text())['trades']
            self.assertEqual(len(trades),2);self.assertEqual(len({trade['id'] for trade in trades}),2)
            self.assertEqual(next(trade for trade in trades if trade['record_uuid']==original['record_uuid'])['profit'],72)

if __name__=='__main__':unittest.main()
