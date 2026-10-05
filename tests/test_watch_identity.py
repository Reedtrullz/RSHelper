"""Watch generation lineage, retained deletes and legacy writer refusal."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from rshelper import persistence, state_identity, identity_merge, watchlist, alerts

ORIGIN = '11111111-1111-4111-8111-111111111111'
OTHER = '22222222-2222-4222-8222-222222222222'
RECORD = '33333333-3333-4333-8333-333333333333'


def legacy():
    return {'items': {'561': {'name': 'Nature rune', 'added': '2026-01-01T00:00:00Z',
                            'alert_margin_above': 200, 'alert_margin_below': None}}}


class WatchIdentityTest(unittest.TestCase):
    def migrate(self, store=None, manifest=None):
        function = getattr(state_identity, 'migrate_watchlist', None)
        self.assertTrue(callable(function), 'watch lineage migration is missing')
        return function(legacy() if store is None else store,
                        state_identity.new_manifest(ORIGIN) if manifest is None else manifest)

    def merge(self, a, b):
        function = getattr(identity_merge, 'merge_watchlists', None)
        self.assertTrue(callable(function), 'watch generation merge is missing')
        return function(a, b)

    def identified(self):
        store = legacy()
        store['items']['561'].update(item_id=561, record_uuid=RECORD,
                                    origin_uuid=ORIGIN, revision=0, tombstone=False)
        return store

    def test_partial_identity_wrong_item_and_deleted_active_row_refuse(self):
        for update in ({'record_uuid': RECORD}, {'item_id': 2}, {'tombstone': True}):
            store = self.identified(); store['items']['561'].update(update)
            if update == {'record_uuid': RECORD}:
                del store['items']['561']['origin_uuid']
            with self.subTest(update=update), self.assertRaises(persistence.StateCorruptionError):
                persistence.validate_state(store, 'watchlist', 'watchlist.json')

    def test_tombstone_map_requires_identity_key_deleted_flag_and_unique_record(self):
        row = self.identified()['items']['561']
        cases = [ {'items': {}, 'tombstones': []},
                  {'items': {}, 'tombstones': {OTHER: {**row, 'tombstone': True}}},
                  {'items': {}, 'tombstones': {RECORD: row}},
                  {'items': {'561': row}, 'tombstones': {RECORD: {**row, 'tombstone': True}}} ]
        for store in cases:
            with self.subTest(store=store), self.assertRaises(persistence.StateCorruptionError):
                persistence.validate_state(store, 'watchlist', 'watchlist.json')

    def test_actual_legacy_writers_refuse_active_and_deleted_identity_without_byte_changes(self):
        row = self.identified()['items']['561']
        stores = [self.identified(), {'items': {}, 'tombstones': {RECORD: {**row, 'tombstone': True}}}]
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(watchlist, 'WATCHLIST_PATH', Path(folder)/'watchlist.json'):
            for store in stores:
                watchlist.WATCHLIST_PATH.write_text(json.dumps(store)); before = watchlist.WATCHLIST_PATH.read_bytes()
                for action in (lambda: watchlist.add(561, 'Nature rune'), lambda: watchlist.remove(561),
                               lambda: alerts.update_watch_alerts(561, 300, None)):
                    with self.subTest(action=action, store=store), self.assertRaisesRegex(persistence.StateCorruptionError, 'identity-aware writer'):
                        action()
                    self.assertEqual(watchlist.WATCHLIST_PATH.read_bytes(), before)

    def test_migration_replay_mutable_edits_and_equivalent_times_reuse_generation(self):
        source = legacy(); source['extension'] = {'preserve': True}; before = copy.deepcopy(source)
        migrated, manifest = self.migrate(source)
        self.assertEqual(source, before)
        self.assertEqual(migrated['extension'], source['extension'])
        row = migrated['items']['561']; self.assertEqual(row['item_id'], 561)
        self.assertEqual(row['revision'], 0); self.assertFalse(row['tombstone'])
        changed = copy.deepcopy(migrated)
        changed['items']['561'].update(revision=1, name='Renamed', alert_margin_above=400,
                                      added='2026-01-01T01:00:00+01:00')
        replayed, repeated = self.migrate(changed, manifest)
        self.assertEqual(replayed, changed); self.assertEqual(repeated, manifest)
        self.assertEqual(row['record_uuid'], replayed['items']['561']['record_uuid'])

    def test_migration_rejects_changed_original_generation_and_preserves_inputs(self):
        store, manifest = self.migrate(); store['items']['561']['added'] = '2026-01-02T00:00:00Z'
        before = copy.deepcopy((store, manifest))
        with self.assertRaisesRegex(ValueError, 'lineage'):
            self.migrate(store, manifest)
        self.assertEqual((store, manifest), before)

    def test_delete_resync_and_new_generation_survive_repeated_both_directions(self):
        old, manifest = self.migrate(); row = old['items']['561']; identity = row['record_uuid']
        deleted = {'items': {}, 'tombstones': {identity: {**row, 'revision': 1, 'tombstone': True}}}
        merged = self.merge(old, deleted)
        self.assertEqual(merged['items'], {}); self.assertTrue(merged['tombstones'][identity]['tombstone'])
        self.assertEqual(self.migrate(merged, manifest), (merged, manifest))
        later = legacy(); later['items']['561']['added'] = '2026-01-02T00:00:00Z'
        later, _ = self.migrate(later, manifest)
        new_identity = later['items']['561']['record_uuid']; self.assertNotEqual(new_identity, identity)
        current = self.merge(merged, later)
        for _ in range(4):
            self.assertEqual(self.merge(current, old), current)
            self.assertEqual(self.merge(old, current), current)
        self.assertEqual(current['items']['561']['record_uuid'], new_identity)
        self.assertIn(identity, current['tombstones'])

    def test_threshold_revision_wins_but_equal_revision_and_resurrection_conflict(self):
        base, _ = self.migrate(); changed = copy.deepcopy(base)
        changed['items']['561'].update(revision=1, alert_margin_above=400)
        self.assertEqual(self.merge(base, changed)['items']['561']['alert_margin_above'], 400)
        conflict = copy.deepcopy(changed); conflict['items']['561']['alert_margin_above'] = 500
        with self.assertRaisesRegex(ValueError, 'equal revision'):
            self.merge(changed, conflict)
        row = changed['items']['561']; deleted = {'items': {}, 'tombstones': {row['record_uuid']: {**row, 'revision': 2, 'tombstone': True}}}
        changed['items']['561']['revision'] = 3
        with self.assertRaisesRegex(ValueError, 'resurrect'):
            self.merge(changed, deleted)

    def test_two_independent_active_generations_of_same_item_conflict_without_guessing(self):
        a, _ = self.migrate(); b, _ = self.migrate(manifest=state_identity.new_manifest(OTHER))
        before = copy.deepcopy((a, b))
        with self.assertRaisesRegex(ValueError, 'active watch generations'):
            self.merge(a, b)
        self.assertEqual((a, b), before)

    def test_merge_canonical_byte_order_and_legacy_input_refusal(self):
        a, _ = self.migrate(); b = copy.deepcopy(a)
        b['items']['561'] = dict(reversed(list(b['items']['561'].items())))
        b['items']['561']['added'] = '2026-01-01T00:00:00.000000+00:00'
        self.assertEqual(json.dumps(self.merge(a, b)), json.dumps(self.merge(b, a)))
        with self.assertRaisesRegex(ValueError, 'migration'):
            self.merge(a, legacy())

    def test_deleted_watch_is_invisible_and_standalone_validator_matches(self):
        row = self.identified()['items']['561']; store = {'items': {}, 'tombstones': {RECORD: {**row, 'tombstone': True}}}
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(watchlist, 'WATCHLIST_PATH', Path(folder)/'watchlist.json'):
            watchlist.WATCHLIST_PATH.write_text(json.dumps(store))
            self.assertEqual(watchlist.list_all(), []); self.assertEqual(watchlist.get_watched_ids(), [])
            self.assertEqual(watchlist.load(), store)
        spec = importlib.util.spec_from_file_location('watch_standalone', persistence.__file__)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        del store['tombstones'][RECORD]['origin_uuid']
        with self.assertRaises(module.StateCorruptionError):
            module.validate_state(store, 'watchlist', 'watchlist.json')

    def test_deploy_merge_refuses_identified_watch_before_other_file_writes(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy'))
        import merge_state
        for identified_in_stage in (True,False):
            with self.subTest(stage=identified_in_stage),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);stage=root/'stage';live=root/'live';stage.mkdir();live.mkdir()
                (stage/'watchlist.json').write_text(json.dumps(self.identified() if identified_in_stage else legacy()))
                (live/'watchlist.json').write_text(json.dumps(legacy() if identified_in_stage else self.identified()))
                (stage/'trades.json').write_text('{"trades":[]}')
                (live/'trades.json').write_text('{"trades":[],"extension":"retained"}')
                before={path.name:path.read_bytes() for path in live.iterdir()}
                with self.assertRaisesRegex(persistence.StateCorruptionError,'identity-aware writer'):
                    merge_state.merge_dir(str(stage),str(live),None)
                self.assertEqual(before,{name:(live/name).read_bytes() for name in before})

    def test_watch_union_bounds_and_root_metadata_conflicts_preserve_inputs(self):
        a,_=self.migrate();b=legacy();b['items']={'2':{**b['items']['561'],'name':'Fixture'}}
        b,_=self.migrate(b);before=copy.deepcopy((a,b))
        with mock.patch.object(identity_merge,'MAX_ROWS',1):
            with self.assertRaisesRegex(ValueError,'row budget'):self.merge(a,b)
        with mock.patch.object(identity_merge,'MAX_STATE_BYTES',10):
            with self.assertRaisesRegex(ValueError,'byte budget'):self.merge(a,b)
        a['extension']={'value':1};b['extension']={'value':True}
        with self.assertRaisesRegex(ValueError,'root metadata'):self.merge(a,b)
        a.pop('extension');b.pop('extension');self.assertEqual((a,b),before)

    def test_immutable_creation_and_item_changes_conflict_despite_new_revision(self):
        base,_=self.migrate();row=base['items']['561']
        for field,value in (('added','2026-01-02T00:00:00Z'),('origin_uuid',OTHER),('item_id',2)):
            changed=copy.deepcopy(base);changed['items']['561'].update({field:value,'revision':1})
            if field=='item_id':changed['items']['2']=changed['items'].pop('561')
            with self.subTest(field=field),self.assertRaises(ValueError):self.merge(base,changed)

    def test_invalid_origin_manifest_never_mutates_legacy_watch(self):
        source=legacy();before=copy.deepcopy(source)
        manifest=state_identity.new_manifest(ORIGIN)
        manifest['mappings']['watchlist:'+'0'*64]=OTHER
        with self.assertRaises(ValueError):self.migrate(source,manifest)
        self.assertEqual(source,before)


if __name__ == '__main__': unittest.main()
