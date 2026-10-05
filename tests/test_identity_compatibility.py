"""Dual-reader preparation refuses legacy writers on identified state."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from rshelper import persistence, state_identity

ORIGIN='11111111-1111-4111-8111-111111111111'

class CompatibilityTest(unittest.TestCase):
    def row(self):
        rows,_=state_identity.migrate_rows([{'id':1,'item_id':2,'name':'Fixture','qty':10,
          'buy_price':100,'direction':'traditional','opened_at':'2026-01-01T00:00:00Z'}],
          'positions',state_identity.new_manifest(ORIGIN))
        return rows[0]

    def test_reader_preserves_identity_and_rejects_partial_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'positions.json';row=self.row()
            path.write_text(json.dumps({'positions':[row]}))
            self.assertEqual(persistence.read_state(path,'positions')['positions'][0],row)
            del row['origin_uuid'];path.write_text(json.dumps({'positions':[row]}));before=path.read_bytes()
            with self.assertRaises(persistence.StateCorruptionError):persistence.read_state(path,'positions')
            self.assertEqual(before,path.read_bytes())

    def test_deploy_standalone_validator_has_same_identity_boundary(self):
        spec=importlib.util.spec_from_file_location('isolated_identity_validation',persistence.__file__)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        row=self.row();row['lot_uid']=ORIGIN
        with self.assertRaises(module.StateCorruptionError):module.validate_state({'positions':[row]},'positions','fixture.json')

    def test_legacy_writer_guard_preserves_identified_bytes(self):
        guard=getattr(persistence,'locked_writable_state',None)
        self.assertTrue(callable(guard),'legacy writer safety boundary is missing')
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'positions.json';path.write_text(json.dumps({'positions':[self.row()]}));before=path.read_bytes()
            with self.assertRaisesRegex(persistence.StateCorruptionError,'identity-aware writer'):
                with guard(path,'positions'):self.fail('identified state reached legacy writer')
            self.assertEqual(before,path.read_bytes())
            path.write_text('{"positions":[]}')
            with guard(path,'positions'):pass

    def test_actual_position_and_journal_writers_refuse_identified_state(self):
        from unittest import mock
        from rshelper import positions,journal
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'positions.json';path.write_text(json.dumps({'positions':[self.row()]}));before=path.read_bytes()
            with mock.patch.object(positions,'POSITIONS_PATH',path):
                self.assertEqual(len(positions.list_positions()),1)
                for call in (lambda:positions.close_positions(2,10,120), lambda:positions.open_position(2,'Fixture',1,100)):
                    with self.assertRaises(persistence.StateCorruptionError):call()
                    self.assertEqual(path.read_bytes(),before)
            trade={'id':1,'item_id':2,'name':'Fixture','qty':1,'buy_price':100,'sell_price':120,
                'tax_paid':2,'profit':18,'timestamp':'2026-01-01T00:00:00Z'}
            rows,_=state_identity.migrate_rows([trade],'trades',state_identity.new_manifest(ORIGIN))
            path=Path(folder)/'trades.json';path.write_text(json.dumps({'trades':rows}));before=path.read_bytes()
            with mock.patch.object(journal,'TRADES_PATH',path):
                self.assertEqual(len(journal.list_trades()),1)
                for call in (lambda:journal.delete_trade(1),lambda:journal.log_trade(2,'Fixture',1,100,120)):
                    with self.assertRaises(persistence.StateCorruptionError):call()
                    self.assertEqual(path.read_bytes(),before)

    def test_deploy_merge_refuses_identified_input_before_any_write(self):
        sys.path.insert(0,str(Path(persistence.__file__).resolve().parents[2]/'deploy'))
        import merge_state
        for identified_in_stage in (True,False):
            with self.subTest(identified_in_stage=identified_in_stage), tempfile.TemporaryDirectory() as folder:
                stage=Path(folder)/'stage';live=Path(folder)/'live';stage.mkdir();live.mkdir()
                empty={'positions':[]};identified={'positions':[self.row()]}
                (stage/'positions.json').write_text(json.dumps(identified if identified_in_stage else empty))
                target=live/'positions.json';target.write_text(json.dumps(empty if identified_in_stage else identified));before=target.read_bytes()
                with self.assertRaisesRegex(persistence.StateCorruptionError,'identity-aware writer'):
                    merge_state.merge_dir(str(stage),str(live),None)
                self.assertEqual(target.read_bytes(),before)

    def test_actual_alert_writers_preserve_identified_bytes(self):
        import contextlib,io
        from unittest import mock
        from rshelper import alerts
        row={'id':1,'ts':100.5,'type':'system','severity':'INFO','item_id':None,
             'item_name':'','title':'Fixture','message':'Message','read':False}
        rows,_=state_identity.migrate_rows([row],'alerts',state_identity.new_manifest(ORIGIN))
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'alerts.json';path.write_text(json.dumps({'alerts':rows,'watch_triggered':{}}));before=path.read_bytes()
            with mock.patch.object(alerts,'_alerts_path',return_value=path):
                self.assertEqual(len(alerts.list_alerts()),1)
                with self.assertRaises(persistence.StateCorruptionError):alerts.mark_read([1])
                with self.assertRaises(persistence.StateCorruptionError):alerts.set_watch_triggered(2)
                with contextlib.redirect_stderr(io.StringIO()) as warning:
                    alerts.push_alert('system','INFO',None,'','New','Message')
                self.assertIn('identity-aware writer',warning.getvalue())
                self.assertEqual(before,path.read_bytes())

if __name__=='__main__':unittest.main()
