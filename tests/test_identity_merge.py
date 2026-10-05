"""Stable identity and revision reconciliation; no activation or disk writes."""
import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from rshelper import state_identity

ORIGIN_A='11111111-1111-4111-8111-111111111111'
ORIGIN_B='22222222-2222-4222-8222-222222222222'


class IdentityMergeTest(unittest.TestCase):
    def api(self):
        from rshelper import identity_merge
        return identity_merge

    def row(self,kind,origin=ORIGIN_A):
        fields={
            'positions':{'id':1,'item_id':2,'name':'Fixture','qty':10,'buy_price':100,
                         'direction':'traditional','opened_at':'2026-01-01T00:00:00Z'},
            'trades':{'id':1,'item_id':2,'name':'Fixture','qty':10,'buy_price':100,
                      'sell_price':120,'tax_paid':20,'profit':180,'timestamp':'2026-01-01T00:00:00Z'},
            'alerts':{'id':1,'ts':100.0,'type':'watch','severity':'INFO','item_id':2,
                      'item_name':'Fixture','title':'Fixture','message':'Fixture','read':False}}
        rows,_=state_identity.migrate_rows([fields[kind]],kind,state_identity.new_manifest(origin))
        return rows[0]

    def test_merge_idempotent_bidirectional_and_preserves_independent_collisions(self):
        api=self.api()
        for kind in ('positions','trades','alerts'):
            with self.subTest(kind=kind):
                left=[self.row(kind)];right=[self.row(kind,ORIGIN_B)]
                originals=copy.deepcopy((left,right))
                merged=api.merge_rows(left,right,kind)
                self.assertEqual(len(merged),2)
                self.assertEqual({row['record_uuid'] for row in merged},{left[0]['record_uuid'],right[0]['record_uuid']})
                self.assertEqual(len({row['id'] for row in merged}),2)
                self.assertEqual(api.merge_rows(right,left,kind),merged)
                for _ in range(5):merged_again=api.merge_rows(merged,right,kind);self.assertEqual(merged_again,merged)
                self.assertEqual((left,right),originals)

    def test_read_toggle_and_deletion_survive_obsolete_peer(self):
        api=self.api();base=self.row('alerts')
        current={**base,'revision':1,'read':True}
        merged=api.merge_rows([base],[current],'alerts')
        self.assertTrue(merged[0]['read']);self.assertEqual(len(merged),1)
        unread={**current,'revision':2,'read':False}
        merged=api.merge_rows(merged,[unread],'alerts')
        self.assertFalse(merged[0]['read'])
        deleted={**unread,'revision':3,'tombstone':True}
        merged=api.merge_rows(merged,[deleted],'alerts')
        for stale in (base,current,unread):
            merged=api.merge_rows([stale],merged,'alerts');self.assertTrue(merged[0]['tombstone']);self.assertEqual(len(merged),1)

    def test_closed_lot_cannot_resurrect_and_quantity_cannot_increase(self):
        api=self.api();base=self.row('positions');partial={**base,'revision':1,'qty':6}
        merged=api.merge_rows([base],[partial],'positions');self.assertEqual(merged[0]['qty'],6)
        closed={**partial,'revision':2,'tombstone':True}
        merged=api.merge_rows(merged,[closed],'positions')
        self.assertTrue(api.merge_rows([base],merged,'positions')[0]['tombstone'])
        for invalid in ({**partial,'revision':2,'qty':10},{**closed,'revision':3,'tombstone':False}):
            with self.assertRaises(ValueError):api.merge_rows(merged,[invalid],'positions')

    def test_financial_identity_conflicts_never_choose_a_winner(self):
        api=self.api();base=self.row('trades')
        for update in ({'buy_price':101},{'profit':999},{'origin_uuid':ORIGIN_B},
                       {'legacy_id':2},{'item_id':3},{'qty':9}):
            other={**base,**update,'revision':1};inputs=copy.deepcopy(([base],[other]))
            with self.subTest(update=update),self.assertRaises(ValueError):api.merge_rows(*inputs,'trades')
            self.assertEqual(inputs,([base],[other]))

    def test_equal_revision_mutable_conflict_and_json_type_change_refuse(self):
        api=self.api();base=self.row('alerts')
        with self.assertRaises(ValueError):api.merge_rows([base],[{**base,'read':True}],'alerts')
        base={**base,'data':{'value':1}}
        with self.assertRaises(ValueError):api.merge_rows([base],[{**base,'data':{'value':True}}],'alerts')

    def test_legacy_or_duplicate_identity_refuses_without_guessing_lineage(self):
        api=self.api();row=self.row('trades');legacy={key:value for key,value in row.items() if key not in {'record_uuid','origin_uuid','revision','tombstone','legacy_id'}}
        with self.assertRaises(ValueError):api.merge_rows([legacy],[],'trades')
        with self.assertRaises(ValueError):api.merge_rows([row,row],[],'trades')

    def test_realization_linkage_must_bind_trade_uuid_and_unique_operation(self):
        from uuid import UUID,uuid5
        api=self.api();operation='33333333-3333-4333-8333-333333333333'
        left={**self.row('trades'),'operation_id':operation,
              'closed_lot_uid':self.row('positions')['lot_uid']}
        with self.assertRaises(ValueError):api.merge_rows([left],[],'trades')
        left['record_uuid']=str(uuid5(UUID(ORIGIN_A),operation));left.pop('legacy_id')
        self.assertEqual(len(api.merge_rows([left],[],'trades')),1)
        right={**left,'origin_uuid':ORIGIN_B,'record_uuid':str(uuid5(UUID(ORIGIN_B),operation))}
        with self.assertRaises(ValueError):api.merge_rows([left],[right],'trades')

    def test_mutable_result_does_not_alias_input_and_bounds_are_enforced(self):
        from unittest import mock
        api=self.api();row={**self.row('alerts'),'data':{'value':[1]}}
        merged=api.merge_rows([row],[],'alerts');merged[0]['data']['value'].append(2)
        self.assertEqual(row['data']['value'],[1])
        with mock.patch.object(api,'MAX_ROWS',1):
            with self.assertRaises(ValueError):api.merge_rows([row],[self.row('alerts',ORIGIN_B)],'alerts')

    def test_display_renumbering_retains_attested_legacy_mapping(self):
        api=self.api();row=self.row('positions');manifest=state_identity.new_manifest(ORIGIN_A)
        row,manifest=state_identity.migrate_rows([{key:value for key,value in row.items() if key not in {'record_uuid','origin_uuid','revision','tombstone','legacy_id','lot_uid'}}],'positions',manifest)
        renumbered={**row[0],'id':999}
        merged=api.merge_rows(row,[renumbered],'positions')
        replayed,replayed_manifest=state_identity.migrate_rows(merged,'positions',manifest)
        self.assertEqual(replayed,merged);self.assertEqual(replayed_manifest,manifest)

    def test_invalid_kind_and_extreme_timestamp_report_validation_error(self):
        api=self.api();row=self.row('alerts')
        for kind in ('unknown',None,[]):
            with self.subTest(kind=kind),self.assertRaises(ValueError):api.merge_rows([row],[],kind)
        with self.assertRaises(ValueError):api.merge_rows([{**row,'ts':10**400}],[],'alerts')

    def test_union_byte_budget_refuses_without_changing_inputs(self):
        from unittest import mock
        api=self.api();left=[{**self.row('alerts'),'message':'x'*1000}]
        right=[{**self.row('alerts',ORIGIN_B),'message':'x'*1000}]
        originals=copy.deepcopy((left,right))
        with mock.patch.object(api,'MAX_STATE_BYTES',2000,create=True):
            with self.assertRaisesRegex(ValueError,'byte budget'):api.merge_rows(left,right,'alerts')
        self.assertEqual((left,right),originals)

    def test_alert_timestamp_comparison_does_not_round_integer_precision(self):
        api=self.api();row=self.row('alerts')
        left={**row,'ts':2**53};right={**row,'ts':2**53+1,'revision':1}
        with self.assertRaises(ValueError):api.merge_rows([left],[right],'alerts')
        # Ordinary integer/float representations remain equivalent on a later
        # revision, but different fractional timestamps are immutable changes.
        self.assertEqual(api.merge_rows([{**row,'ts':100}],[{**row,'ts':100.0,'revision':1}],'alerts')[0]['revision'],1)
        with self.assertRaises(ValueError):api.merge_rows([row],[{**row,'ts':100.5,'revision':1}],'alerts')

    def test_equivalent_timestamp_encodings_at_equal_revision_merge_deterministically(self):
        api=self.api()
        for kind,field in (('positions','opened_at'),('trades','timestamp')):
            with self.subTest(kind=kind):
                left=self.row(kind);right={**left,field:'2026-01-01T00:00:00.000000+00:00'}
                original=copy.deepcopy((left,right))
                a=api.merge_rows([left],[right],kind);b=api.merge_rows([right],[left],kind)
                self.assertEqual(a,b);self.assertEqual(len(a),1);self.assertEqual((left,right),original)
        left=self.row('alerts');right={**left,'ts':100}
        self.assertEqual(api.merge_rows([left],[right],'alerts'),api.merge_rows([right],[left],'alerts'))

    def test_closed_tombstone_quantity_is_frozen_after_deletion(self):
        api=self.api();row={**self.row('positions'),'tombstone':True,'revision':1,'qty':6}
        with self.assertRaises(ValueError):api.merge_rows([row],[{**row,'qty':5,'revision':2}],'positions')

    def test_time_normalization_preserves_unrelated_extension_fields(self):
        api=self.api()
        for kind,field in (('positions','timestamp'),('alerts','opened_at')):
            with self.subTest(kind=kind):
                row={**self.row(kind),field:{'extension':'retained'}}
                self.assertEqual(api.merge_rows([row],[],kind)[0][field],row[field])

    def test_nested_key_order_yields_identical_serialized_result(self):
        import json
        api=self.api();left={**self.row('alerts'),'data':{'a':1,'b':2}}
        right=dict(reversed(list(left.items())));right['data']={'b':2,'a':1}
        a=api.merge_rows([left],[right],'alerts');b=api.merge_rows([right],[left],'alerts')
        self.assertEqual(json.dumps(a),json.dumps(b))

    def test_boolean_negative_or_string_alert_times_refuse_before_canonicalization(self):
        api=self.api();row=self.row('alerts')
        for value in (True,False,-1,'100',None):
            with self.subTest(value=value),self.assertRaises(ValueError):api.merge_rows([{**row,'ts':value}],[],'alerts')


if __name__=='__main__':unittest.main()
