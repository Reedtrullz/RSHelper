import copy
import argparse
import contextlib
import io
from datetime import date
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from rshelper import snapshot, cli

SPEC = {'direction':'arbitrage','units':'gp-per-item','members_only':False,
        'min_volume':10,'min_margin':1,'capital':0,'top':10,'selection':'ranked-top'}
META = {'latest':{'source':'wiki','volume_kind':'unknown','stale':False,'coverage':{'wiki':2}},
        '5m':{'source':'wiki','volume_kind':'executed-trades','stale':False,'coverage':{'wiki':2}}}

class ScanManifestTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        patch = mock.patch.object(snapshot,'SNAPSHOT_DIR',Path(self.home.name))
        patch.start()
        self.addCleanup(patch.stop)
        patch = mock.patch('rshelper.tuning.params',return_value={})
        patch.start()
        self.addCleanup(patch.stop)

    def saved(self,spec=SPEC,metadata=META,profit=100):
        path = snapshot.save('flip',[{'item_id':1,'profit':profit}],
                             scan_spec=spec,market_metadata=metadata)
        return json.loads(path.read_text())

    def test_fingerprint_is_deterministic_and_same_spec_is_comparable(self):
        first = self.saved()
        second = self.saved(dict(reversed(list(SPEC.items()))))
        self.assertEqual(first['manifest']['specification_sha256'],second['manifest']['specification_sha256'])
        self.assertEqual(snapshot.compare_manifests(first,second),{'status':'compatible','reasons':[]})

    def test_changed_specs_cannot_emit_unqualified_gains(self):
        before = self.saved()
        for key,value in [('direction','traditional'),('units','gp-per-hour'),('members_only',True),
                          ('min_volume',20),('min_margin',2),('capital',1000),('top',20)]:
            with self.subTest(key=key):
                changed = dict(SPEC,**{key:value})
                self.saved(changed,profit=200)
                previous = snapshot.SNAPSHOT_DIR/'flip-2020-01-01.json'
                previous.write_text(json.dumps(before))
                diff = snapshot.diff_scan_type('flip','2020-01-01')
                self.assertEqual(diff['comparison']['status'],'incompatible')
                self.assertIn(key,' '.join(diff['comparison']['reasons']))
                self.assertEqual(diff['improved'],[])
                self.assertEqual(diff['fell_off'],[])

    def test_unknown_source_changed_coverage_and_legacy_are_qualified(self):
        original = self.saved()
        changed = copy.deepcopy(META)
        changed['5m']['volume_kind']='standing-orders'
        self.assertEqual(snapshot.compare_manifests(original,self.saved(metadata=changed))['status'],'partially-comparable')
        changed = copy.deepcopy(META)
        changed['5m']['coverage']['wiki']=1
        self.assertEqual(snapshot.compare_manifests(original,self.saved(metadata=changed))['status'],'partially-comparable')
        legacy = {'items':[{'item_id':1,'profit':50}]}
        raw = json.dumps(legacy).encode()
        path = snapshot.SNAPSHOT_DIR/'flip-2020-01-01.json'
        path.write_bytes(raw)
        diff = snapshot.diff_scan_type('flip','2020-01-01')
        self.assertEqual(diff['comparison']['status'],'partially-comparable')
        self.assertIn('unknown',' '.join(diff['comparison']['reasons']))
        self.assertEqual(path.read_bytes(),raw)

    def test_missing_items_remain_unknown_and_tampered_fingerprint_is_not_compatible(self):
        before = self.saved()
        before['items'].append({'item_id':2,'profit':300})
        (snapshot.SNAPSHOT_DIR/'flip-2020-01-01.json').write_text(json.dumps(before))
        self.saved(profit=110)
        diff = snapshot.diff_scan_type('flip','2020-01-01')
        self.assertEqual(diff['removed'][0]['removal_reason'],'unknown: absent from saved selection')
        self.assertEqual([x['item_id'] for x in diff['fell_off']],[])
        broken = copy.deepcopy(before)
        broken['manifest']['scan_spec']['capital']=100
        self.assertEqual(snapshot.compare_manifests(before,broken)['status'],'incompatible')
        broken = copy.deepcopy(before)
        broken['manifest']['specification_sha256']='0'*64
        self.assertEqual(snapshot.compare_manifests(before,broken)['reasons'],
                         ['scan specification fingerprint invalid'])

    def test_invalid_specification_does_not_replace_a_saved_snapshot(self):
        self.saved()
        path = next(snapshot.SNAPSHOT_DIR.glob('flip-*.json'))
        before = path.read_bytes()
        with self.assertRaises(ValueError):self.saved(dict(SPEC,capital=float('nan')))
        self.assertEqual(path.read_bytes(),before)

    def test_cli_json_preserves_comparison_reasons_without_text_leakage(self):
        before = self.saved()
        (snapshot.SNAPSHOT_DIR/'flip-2020-01-01.json').write_text(json.dumps(before))
        self.saved(dict(SPEC,capital=1000),profit=200)
        stdout,stderr = io.StringIO(),io.StringIO()
        with contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stderr):
            cli.diff_cmd(argparse.Namespace(scan_type='flip',date='2020-01-01',json=True))
        result = json.loads(stdout.getvalue())
        self.assertEqual(result['comparison']['status'],'incompatible')
        self.assertIn('capital',' '.join(result['comparison']['reasons']))
        self.assertEqual(result['improved'],[])
        self.assertEqual(stderr.getvalue(),'')

    def test_processing_models_are_qualified_and_changed_recipes_are_incompatible(self):
        spec = dict(SPEC,units='illustrative-gp-per-output-after-tax',recipe_model_sha256='a'*64)
        before = self.saved(spec)
        self.assertEqual(snapshot.compare_manifests(before,before)['status'],'partially-comparable')
        changed = self.saved(dict(spec,recipe_model_sha256='b'*64))
        self.assertEqual(snapshot.compare_manifests(before,changed)['reasons'],['recipe_model_sha256 changed'])

if __name__ == '__main__':
    unittest.main()
