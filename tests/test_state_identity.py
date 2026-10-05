"""Stable legacy mapping is shared by realization and state merge contracts."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

ORIGIN_A = '11111111-1111-4111-8111-111111111111'
ORIGIN_B = '22222222-2222-4222-8222-222222222222'

class IdentityTest(unittest.TestCase):
    def api(self):
        from rshelper import state_identity
        return state_identity

    def position(self, qty=10):
        return {'id': 1, 'item_id': 2, 'name': 'Fixture', 'qty': qty,
                'buy_price': 100, 'direction': 'traditional',
                'opened_at': '2026-01-01T00:00:00Z', 'note': ''}

    def test_migration_repeat_and_mutation_keep_lot_identity(self):
        api=self.api();original=self.position()
        manifest=api.new_manifest(ORIGIN_A)
        rows,mapping=api.migrate_rows([original], 'positions', manifest)
        again,replayed=api.migrate_rows([self.position(5)], 'positions', mapping)
        self.assertEqual(rows[0]['record_uuid'], again[0]['record_uuid'])
        self.assertEqual(rows[0]['lot_uid'], rows[0]['record_uuid'])
        self.assertEqual(replayed, mapping)
        self.assertEqual(original, self.position())
        self.assertEqual(manifest['mappings'], {})

    def test_independent_legacy_id_collision_stays_distinct(self):
        api=self.api()
        first,_=api.migrate_rows([self.position()], 'positions', api.new_manifest(ORIGIN_A))
        second,_=api.migrate_rows([self.position()], 'positions', api.new_manifest(ORIGIN_B))
        self.assertNotEqual(first[0]['record_uuid'], second[0]['record_uuid'])
        self.assertEqual(first[0]['id'], second[0]['id'])

    def test_existing_record_survives_display_id_renumber(self):
        api=self.api()
        rows,manifest=api.migrate_rows([self.position()], 'positions', api.new_manifest(ORIGIN_A))
        rows[0]['id']=99
        again,_=api.migrate_rows(rows, 'positions', manifest)
        self.assertEqual(again, rows)

    def test_alert_read_is_mutable_and_does_not_duplicate_identity(self):
        api=self.api();row={'id':1, 'ts':100.5, 'type':'system', 'severity':'INFO',
            'item_id':None, 'item_name':'', 'title':'Fixture', 'message':'Message', 'read':False}
        first,manifest=api.migrate_rows([row], 'alerts', api.new_manifest(ORIGIN_A))
        row['read']=True
        second,_=api.migrate_rows([row], 'alerts', manifest)
        self.assertEqual(first[0]['record_uuid'], second[0]['record_uuid'])
        self.assertTrue(second[0]['read'])

    def test_ambiguous_legacy_twins_are_refused(self):
        api=self.api()
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            api.migrate_rows([self.position(),self.position()], 'positions', api.new_manifest(ORIGIN_A))

    def test_partial_or_forged_metadata_refused(self):
        api=self.api()
        rows,manifest=api.migrate_rows([self.position()], 'positions', api.new_manifest(ORIGIN_A))
        for field,value in [('record_uuid','not-a-uuid'),('origin_uuid',True),('revision',True),
                            ('tombstone','false'),('lot_uid',ORIGIN_B),('legacy_id',True)]:
            broken=copy.deepcopy(rows);broken[0][field]=value
            with self.assertRaises(ValueError):api.migrate_rows(broken,'positions',manifest)
        partial=self.position();partial['record_uuid']=ORIGIN_A
        with self.assertRaises(ValueError):api.migrate_rows([partial],'positions',manifest)

    def test_manifest_conflicts_and_unknown_kinds_refused(self):
        api=self.api();rows,manifest=api.migrate_rows([self.position()], 'positions', api.new_manifest(ORIGIN_A))
        broken=copy.deepcopy(manifest)
        broken['mappings'][next(iter(broken['mappings']))]=ORIGIN_B
        with self.assertRaisesRegex(ValueError,'conflict'):api.migrate_rows(rows,'positions',broken)
        with self.assertRaises(ValueError):api.migrate_rows([self.position()], 'generic', manifest)

    def test_equivalent_timestamp_representations_keep_identity(self):
        api=self.api();first=self.position();second=self.position()
        second['opened_at']='2026-01-01T01:00:00+01:00'
        rows,manifest=api.migrate_rows([first],'positions',api.new_manifest(ORIGIN_A))
        again,_=api.migrate_rows([second],'positions',manifest)
        self.assertEqual(rows[0]['record_uuid'],again[0]['record_uuid'])

    def test_out_of_range_utc_conversion_refuses_without_mutation(self):
        api=self.api();row=self.position();row['opened_at']='9999-12-31T23:59:59-01:00'
        manifest=api.new_manifest(ORIGIN_A);original=copy.deepcopy(row)
        with self.assertRaises(ValueError):api.migrate_rows([row],'positions',manifest)
        self.assertEqual(row,original)
        self.assertEqual(manifest['mappings'],{})

    def test_changed_uuid_after_display_renumber_refused(self):
        api=self.api();rows,manifest=api.migrate_rows([self.position()],'positions',api.new_manifest(ORIGIN_A))
        rows[0].update(id=99,record_uuid=ORIGIN_B,lot_uid=ORIGIN_B)
        before=copy.deepcopy(rows)
        with self.assertRaisesRegex(ValueError,'conflict'):api.migrate_rows(rows,'positions',manifest)
        self.assertEqual(rows,before)

    def test_record_uuid_swaps_between_manifest_records_refused(self):
        api=self.api();second=self.position();second.update(id=2,item_id=3)
        rows,manifest=api.migrate_rows([self.position(),second],'positions',api.new_manifest(ORIGIN_A))
        first,second_uuid=[r['record_uuid'] for r in rows]
        rows[0].update(id=10,record_uuid=second_uuid,lot_uid=second_uuid)
        rows[1].update(id=20,record_uuid=first,lot_uid=first)
        with self.assertRaisesRegex(ValueError,'conflict'):api.migrate_rows(rows,'positions',manifest)

    def test_changed_immutable_cost_basis_refused_on_replay(self):
        api=self.api();rows,manifest=api.migrate_rows([self.position()],'positions',api.new_manifest(ORIGIN_A))
        rows[0].update(id=99,buy_price=101)
        with self.assertRaisesRegex(ValueError,'conflict'):api.migrate_rows(rows,'positions',manifest)

    def test_foreign_identified_and_local_legacy_collision_is_order_independent(self):
        api=self.api();foreign,_=api.migrate_rows([self.position()],'positions',api.new_manifest(ORIGIN_B))
        identities=[]
        for rows in ([foreign[0],self.position()],[self.position(),foreign[0]]):
            upgraded,_=api.migrate_rows(rows,'positions',api.new_manifest(ORIGIN_A))
            identities.append({row['record_uuid'] for row in upgraded})
        self.assertEqual(identities[0],identities[1])
        self.assertEqual(len(identities[0]),2)

    def test_malformed_timestamp_types_refused_before_migration_key(self):
        api=self.api()
        for value in (None,123,'invalid'):
            row=self.position();row['opened_at']=value
            with self.assertRaises(ValueError):api.migrate_rows([row],'positions',api.new_manifest(ORIGIN_A))

if __name__ == '__main__':unittest.main()
