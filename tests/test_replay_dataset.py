import importlib.util
from dataclasses import asdict
import json
from pathlib import Path
import sys
import tempfile
import subprocess
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
sys.path.insert(0,str(ROOT/'scripts'))
import replay


def dataset_module():
    path=ROOT/'scripts/replay-dataset.py'
    if not path.is_file():raise AssertionError('explicit immutable replay dataset command missing')
    spec=importlib.util.spec_from_file_location('owned_replay_dataset',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


class ReplayDatasetTest(unittest.TestCase):
    def test_shared_metadata_boundary(self):
        for metadata in ([],{'0':{}},{'01':{}},{'x':{}},{'1':[]},{'1':{'limit':0}},
                         {'1':{'limit':2**63}},{'1':{'members':1}},{'1':{'name':''}},
                         {'1':{'name':'x'*1001}}):
            with self.subTest(metadata=metadata),self.assertRaises(ValueError):replay.validate_metadata(metadata)
        replay.validate_metadata({'1':{'name':'x'*1000,'limit':2**63-1,'members':None}})

    def fixture(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        root=Path(temporary.name);start=1699999800
        rows=[{'timestamp':start+i*300,'avgHighPrice':104,'avgLowPrice':100,
               'highPriceVolume':5000,'lowPriceVolume':5000} for i in range(72)]
        data=root/'input.json';mapping=root/'mapping.json'
        data.write_text(json.dumps({'1':rows}))
        mapping.write_text(json.dumps({'1':{'name':'Synthetic','members':False,'limit':10000}}))
        source={'provider':'synthetic','url':None,'fetched_at':start+21600,'selection_note':'Synthetic boundary fixture'}
        return root,start,data,mapping,source

    def test_chronological_splits_reject_empty_overlap_and_wrong_cadence(self):
        module=dataset_module();root,start,data,mapping,source=self.fixture()
        for train,validation in ((start,start+1000),(start+10800,start+10800),
                                 (start+10801,start+16200),(start+10800,start+21600)):
            with self.subTest(train=train,validation=validation),self.assertRaises(ValueError):
                module.pin_dataset(data,mapping,root/'bad',source=source,train_end=train,validation_end=validation)
            self.assertFalse((root/'bad').exists())

    def test_invalid_mapping_conflicts_and_source_rejected_before_publication(self):
        module=dataset_module();root,start,data,mapping,source=self.fixture()
        invalid_sources=[{},dict(source,provider='tracker'),dict(source,fetched_at=True),
                         dict(source,url='http://example.test'),dict(source,provider='wiki')]
        for candidate in invalid_sources:
            with self.subTest(source=candidate),self.assertRaises(ValueError):
                module.pin_dataset(data,mapping,root/'bad',source=candidate,train_end=start+10800,validation_end=start+16200)
        mapping.write_text('{"1":{"members":"true"}}')
        with self.assertRaisesRegex(ValueError,'membership'):
            module.pin_dataset(data,mapping,root/'bad',source=source,train_end=start+10800,validation_end=start+16200)
        mapping.write_text('{}');raw=json.loads(data.read_text());raw['1'].append(dict(raw['1'][0],avgHighPrice=999))
        data.write_text(json.dumps(raw))
        with self.assertRaisesRegex(ValueError,'conflicting'):
            module.pin_dataset(data,mapping,root/'bad',source=source,train_end=start+10800,validation_end=start+16200)
        self.assertFalse((root/'bad').exists())

    def test_manifest_and_selection_tampering_never_evaluate_holdout(self):
        module=dataset_module();root,start,data,mapping,source=self.fixture()
        module.pin_dataset(data,mapping,root/'pinned',source=source,train_end=start+10800,validation_end=start+16200)
        selection=module.select_parameters(root/'pinned',[replay.ReplayConfig()],slot_limit=8)
        selection['selected_config']['dip_depth_pct']=9
        with self.assertRaisesRegex(ValueError,'selection hash'):
            module.evaluate_holdout(root/'pinned',selection)
        selection['selection_hash']=replay._hash({k:v for k,v in selection.items() if k!='selection_hash'})
        with self.assertRaisesRegex(ValueError,'reproduce'):
            module.evaluate_holdout(root/'pinned',selection)
        manifest=json.loads((root/'pinned'/'manifest.json').read_text());manifest['splits']['holdout'][0]=start
        manifest['dataset_id']=replay._hash({k:v for k,v in manifest.items() if k!='dataset_id'})
        (root/'pinned'/'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError,'chronological'):
            module.load_dataset(root/'pinned')

    def test_holdout_changes_do_not_change_train_validation_selection(self):
        module=dataset_module();root,start,data,mapping,source=self.fixture()
        first=module.pin_dataset(data,mapping,root/'first',source=source,train_end=start+10800,validation_end=start+16200)
        configs=[replay.ReplayConfig(),replay.ReplayConfig.historical_baseline()]
        selection=module.select_parameters(root/'first',configs,slot_limit=8)
        raw=json.loads(data.read_text())
        for row in raw['1'][54:]:row['avgHighPrice']=999;row['avgLowPrice']=900
        data.write_text(json.dumps(raw))
        second=module.pin_dataset(data,mapping,root/'second',source=source,train_end=start+10800,validation_end=start+16200)
        changed=module.select_parameters(root/'second',configs,slot_limit=8)
        self.assertNotEqual(first['dataset_id'],second['dataset_id'])
        for key in ('candidates','selected_config','baseline_config','objective'):
            self.assertEqual(selection[key],changed[key])

    def test_cli_json_and_clear_errors_in_disposable_home(self):
        module=dataset_module();root,start,data,mapping,source=self.fixture()
        module.pin_dataset(data,mapping,root/'pinned',source=source,train_end=start+10800,validation_end=start+16200)
        configs=root/'configs.json';configs.write_text(json.dumps([asdict(replay.ReplayConfig())]))
        import os
        environment={**os.environ,'HOME':str(root/'home'),'PYTHONPATH':str(ROOT/'src')}
        script=str(ROOT/'scripts/replay-dataset.py')
        selected=subprocess.run([sys.executable,script,'select','--dataset',str(root/'pinned'),
            '--configs',str(configs),'--slots','8'],env=environment,capture_output=True,text=True)
        self.assertEqual(selected.returncode,0,selected.stderr);self.assertEqual(selected.stderr,'')
        receipt=root/'selection.json';receipt.write_text(selected.stdout)
        report=subprocess.run([sys.executable,script,'report','--dataset',str(root/'pinned'),
            '--selection',str(receipt)],env=environment,capture_output=True,text=True)
        self.assertEqual(report.returncode,0,report.stderr);self.assertEqual(report.stderr,'')
        payload=json.loads(report.stdout);self.assertEqual(payload['holdout']['trades'],0)
        self.assertEqual(payload['holdout']['candle_coverage']['1']['samples'],18)
        self.assertFalse((root/'home'/'.config').exists())
        (root/'pinned'/'mapping.json').write_text('{}')
        rejected=subprocess.run([sys.executable,script,'inspect','--dataset',str(root/'pinned')],
            env=environment,capture_output=True,text=True)
        self.assertEqual(rejected.returncode,1);self.assertEqual(rejected.stdout,'')
        self.assertIn('hash or bytes mismatch',rejected.stderr)

    def test_pin_and_deterministic_report_never_select_from_holdout(self):
        module=dataset_module()
        start=1699999800
        rows=[{'timestamp':start+i*300,'avgHighPrice':104 if i%12<6 else 99,
               'avgLowPrice':100 if i%12<6 else 95,'highPriceVolume':5000,'lowPriceVolume':5000} for i in range(72)]
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);data=root/'input.json';mapping=root/'mapping.json'
            data.write_text(json.dumps({'1':rows}))
            mapping.write_text(json.dumps({'1':{'name':'Synthetic','members':False,'limit':10000}}))
            manifest=module.pin_dataset(data,mapping,root/'pinned',source={
                'provider':'synthetic','url':None,'fetched_at':start+21600,'selection_note':'Owned fixture; no empirical claim'},
                train_end=start+10800,validation_end=start+16200)
            cfg=replay.ReplayConfig(capital=10000)
            original=module.simulate
            seen=[]
            def capture(data,*args,**kwargs):
                seen.extend(row['timestamp'] for rows in data.values() for row in rows)
                return original(data,*args,**kwargs)
            with mock.patch.object(module,'simulate',side_effect=capture):
                selection=module.select_parameters(root/'pinned',[cfg,replay.ReplayConfig.historical_baseline()],slot_limit=8)
            self.assertTrue(seen);self.assertLess(max(seen),start+16200)
            self.assertEqual(module.evaluate_holdout(root/'pinned',selection),module.evaluate_holdout(root/'pinned',selection))
            self.assertEqual(manifest['dataset_id'],selection['dataset_id'])
            with self.assertRaises(FileExistsError):
                module.pin_dataset(data,mapping,root/'pinned',source=manifest['source'],train_end=start+10800,validation_end=start+16200)
            (root/'pinned'/'candles.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'hash|bytes'):
                module.evaluate_holdout(root/'pinned',selection)


if __name__=='__main__':unittest.main()
