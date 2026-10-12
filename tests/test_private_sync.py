import importlib.util
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from rshelper import profile, state_identity, state_replication

A = '11111111-1111-4111-8111-111111111111'
B = '22222222-2222-4222-8222-222222222222'
P = '33333333-3333-4333-8333-333333333333'


class PrivateSyncTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        patch = mock.patch.object(profile, 'CONFIG_DIR', self.base / 'state')
        patch.start()
        self.addCleanup(patch.stop)
        self.outbox = self.base / 'outbox'
        for name, origin in (('a', A), ('b', B)):
            root = profile.resolve_config_path('', name)
            root.mkdir(parents=True)
            (root / 'identity-manifest.json').write_text(json.dumps(state_identity.new_manifest(origin)))
            (root / 'identity-activation.json').write_text(json.dumps({
                'schema_version': 1, 'mode': 'identified', 'origin_uuid': origin,
                'profile_uuid': P, 'replication_origins': [A, B], 'financial_authority': name == 'a'}))
        self.applies = 0

    def api(self):
        path = ROOT / 'scripts/sync-private-state.py'
        self.assertTrue(path.is_file(), 'authenticated private sync contract is missing')
        spec = importlib.util.spec_from_file_location('private_sync_fixture', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def transport(self, host, destination, mode, origin, selected_profile, packet=None,verification=None):
        if mode == 'receipt':
            return state_replication.read_receipt('b', origin)
        if mode=='verify':return state_replication.verify_receipt('b',verification)
        self.applies += 1
        return state_replication.apply_packet('b', packet)

    def run_sync(self, module, **kwargs):
        return module.run_sync('a', 'Racknerd-Deploy', '/opt/apps/rshelper', self.outbox, **kwargs)

    def test_unchanged_sync_verifies_exact_cursor_without_another_packet_apply(self):
        from rshelper import persistence
        module=self.api()
        with mock.patch.object(module,'_ssh',side_effect=self.transport):first=self.run_sync(module)
        root=profile.resolve_config_path('','b')
        before={path.name:path.read_bytes() for path in root.glob('*.json') if path.name!='sync-status.json'}
        profile.atomic_write_json(root/'sync-status.json',{'schema_version':1,'status':'applied','last_success_at':1})
        with mock.patch.object(module,'_ssh',side_effect=self.transport) as ssh:second=self.run_sync(module)
        self.assertEqual(self.applies,1)
        self.assertIn('verify',[call.args[2] for call in ssh.call_args_list])
        self.assertEqual((first['applied_revision'],first['applied_hash']),(second['applied_revision'],second['applied_hash']))
        self.assertGreater(persistence.read_state(root/'sync-status.json','generic')['last_success_at'],1)
        self.assertEqual(before,{path.name:path.read_bytes() for path in root.glob('*.json') if path.name!='sync-status.json'})

    def test_wrong_verification_and_lost_verification_response_keep_freshness_and_packet_safe(self):
        module=self.api()
        with mock.patch.object(module,'_ssh',side_effect=self.transport):receipt=self.run_sync(module)
        request={key:receipt[key] for key in ('profile_uuid','origin_uuid','applied_revision','applied_hash')}
        root=profile.resolve_config_path('','b');before=(root/'sync-status.json').read_bytes()
        self.assertFalse((self.outbox/'pending.json').exists())
        for change in ({'applied_hash':'f'*64},{'applied_revision':receipt['applied_revision']+1},{'profile_uuid':A},{'origin_uuid':B}):
            with self.assertRaises(ValueError):state_replication.verify_receipt('b',{**request,**change})
            self.assertEqual((root/'sync-status.json').read_bytes(),before)
        def lost(*args,**kwargs):
            result=self.transport(*args,**kwargs)
            if args[2]=='verify':raise OSError('lost verification response')
            return result
        with mock.patch.object(module,'_ssh',side_effect=lost):
            with self.assertRaises(OSError):self.run_sync(module)
        self.assertTrue((self.outbox/'pending.json').exists())
        pending=json.loads((self.outbox/'pending.json').read_bytes())
        self.assertEqual(pending['manifest']['packet_hash'],receipt['applied_hash'])
        with mock.patch.object(module,'_ssh',side_effect=self.transport):retried=self.run_sync(module)
        self.assertEqual(retried['applied_hash'],receipt['applied_hash']);self.assertEqual(self.applies,1)
        self.assertFalse((self.outbox/'pending.json').exists())

    def test_verification_cannot_refresh_a_non_exact_stored_acknowledgement(self):
        module=self.api()
        with mock.patch.object(module,'_ssh',side_effect=self.transport):receipt=self.run_sync(module)
        root=profile.resolve_config_path('','b');before=(root/'sync-status.json').read_bytes()
        metadata=json.loads((root/'replication-state.json').read_bytes())
        metadata['receipts'][A]['requested_hash']='f'*64
        (root/'replication-state.json').write_text(json.dumps(metadata))
        with self.assertRaises(ValueError):
            state_replication.verify_receipt('b',{key:receipt[key] for key in ('profile_uuid','origin_uuid','applied_revision','applied_hash')})
        self.assertEqual((root/'sync-status.json').read_bytes(),before)

    def test_receiver_helper_bounds_and_validates_verification_before_invocation(self):
        spec=importlib.util.spec_from_file_location('verification_receiver',ROOT/'deploy/private_state.py')
        self.assertIsNotNone(spec);self.assertIsNotNone(spec.loader)
        helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
        root=self.base/'receiver';root.mkdir()
        request={'profile_uuid':P,'origin_uuid':A,'applied_revision':1,'applied_hash':'a'*64}
        raw=json.dumps(request).encode()
        with mock.patch.object(helper,'APP_DIR',root),mock.patch.object(helper,'_module',return_value=object()), \
             mock.patch.object(helper,'_running',return_value={'image_id':'synthetic'}),mock.patch.object(helper,'_run_image',return_value={}) as run:
            helper.perform(root,'verify',A,'a',incoming=io.BytesIO(raw))
            self.assertIn('verify',run.call_args.args[-1]);run.reset_mock()
            for invalid in (b'x'*4097,json.dumps({**request,'extra':1}).encode(),raw[:-1]+b',"applied_revision":2}',json.dumps({**request,'applied_revision':True}).encode()):
                with self.assertRaises(ValueError):helper.perform(root,'verify',A,'a',incoming=io.BytesIO(invalid))
                run.assert_not_called()

    def test_cli_verification_emits_only_json_and_keeps_packet_identity(self):
        from rshelper import cli
        module=self.api()
        with mock.patch.object(module,'_ssh',side_effect=self.transport):receipt=self.run_sync(module)
        out=io.StringIO()
        with mock.patch.object(sys,'argv',['rshelper','--profile','b','state','verify','--origin',A,'--profile-uuid',P,
                '--revision',str(receipt['applied_revision']),'--hash',receipt['applied_hash'],'--json']),contextlib.redirect_stdout(out):cli.main()
        self.assertEqual(json.loads(out.getvalue()),receipt)

    def test_apply_has_finite_budget_above_receiver_deadline(self):
        module = self.api()
        packet = self.base / 'packet.zip'
        packet.write_bytes(b'synthetic packet')
        process = mock.Mock()
        process.run_command.return_value = mock.Mock(returncode=0, stdout=b'{}')
        spec = mock.Mock()
        with mock.patch.object(module.importlib.util, 'spec_from_file_location', return_value=spec), \
                mock.patch.object(module.importlib.util, 'module_from_spec', return_value=process):
            module._ssh('Racknerd-Deploy', '/opt/apps/rshelper', 'apply', A, 'a', packet)
            self.assertEqual(process.run_command.call_args.kwargs['timeout'], 180)
            self.assertEqual(process.run_command.call_args.kwargs['output_limit'], 65536)
            self.assertEqual(process.run_command.call_args.kwargs['data'], b'synthetic packet')
            module._ssh('Racknerd-Deploy', '/opt/apps/rshelper', 'receipt', A, 'a')
            self.assertEqual(process.run_command.call_args.kwargs['timeout'], 60)

    def test_transfer_disconnect_retries_same_packet(self):
        module = self.api()
        def disconnect(*args, **kwargs):
            result = self.transport(*args, **kwargs)
            if args[2] == 'apply':
                raise OSError('lost SSH response')
            return result
        with mock.patch.object(module, '_ssh', side_effect=disconnect):
            with self.assertRaises(OSError):
                self.run_sync(module)
        pending = (self.outbox / 'pending.json').read_bytes()
        packet = next(self.outbox.glob('*.zip'))
        original = packet.read_bytes()
        with mock.patch.object(module, '_ssh', side_effect=self.transport):
            receipt = self.run_sync(module)
        self.assertEqual(receipt['status'], 'applied')
        self.assertEqual(self.applies, 1)
        self.assertFalse((self.outbox / 'pending.json').exists())
        self.assertFalse(packet.exists())
        self.assertEqual(json.loads(pending)['manifest']['packet_hash'], receipt['applied_hash'])
        self.assertGreater(len(original), 0)

    def test_remote_wrong_receipt_never_acknowledged(self):
        module = self.api()
        def wrong(*args, **kwargs):
            receipt = self.transport(*args, **kwargs)
            return {**receipt, 'applied_hash': 'f' * 64} if receipt else None
        with mock.patch.object(module, '_ssh', side_effect=wrong):
            with self.assertRaises(ValueError):
                self.run_sync(module)
        self.assertTrue((self.outbox / 'pending.json').exists())
        self.assertFalse((self.outbox / 'acknowledged.json').exists())

    def test_dry_run_status_reveal_no_private_values_and_do_not_capture(self):
        module = self.api()
        before = (profile.resolve_config_path('', 'a') / 'identity-manifest.json').read_bytes()
        with mock.patch.object(module, '_ssh') as ssh:
            report = self.run_sync(module, dry_run=True)
            status = self.run_sync(module, status=True)
        ssh.assert_not_called()
        self.assertEqual(report['profile_uuid'], P)
        self.assertEqual(status['pending'], False)
        self.assertEqual(before, (profile.resolve_config_path('', 'a') / 'identity-manifest.json').read_bytes())
        self.assertFalse((profile.resolve_config_path('', 'a') / 'replication-state.json').exists())

    def test_failed_sync_preserves_checkout_and_pending_packet(self):
        module = self.api()
        checkout = self.base / 'checkout'
        checkout.mkdir()
        index = checkout / 'index'
        index.write_bytes(b'unrelated staged source')
        with mock.patch.object(module, '_ssh', side_effect=OSError('offline')):
            with self.assertRaises(OSError):
                self.run_sync(module)
            pending = (self.outbox / 'pending.json').read_bytes()
            packet = next(self.outbox.glob('*.zip')).read_bytes()
            with self.assertRaises(OSError):
                self.run_sync(module)
        self.assertEqual(index.read_bytes(), b'unrelated staged source')
        self.assertEqual((self.outbox / 'pending.json').read_bytes(), pending)
        self.assertEqual(next(self.outbox.glob('*.zip')).read_bytes(), packet)

    def test_pending_target_cannot_be_substituted(self):
        module = self.api()
        with mock.patch.object(module, '_ssh', side_effect=OSError('offline')):
            with self.assertRaises(OSError):
                self.run_sync(module)
        with mock.patch.object(module, '_ssh') as ssh:
            with self.assertRaises(ValueError):
                module.run_sync('a', 'other-host', '/opt/apps/rshelper', self.outbox)
        ssh.assert_not_called()

    def test_status_refuses_corrupt_ack_without_disclosing_private_fields(self):
        module = self.api()
        self.outbox.mkdir()
        path = self.outbox / 'acknowledged.json'
        path.write_text(json.dumps({'private_row': 'PRIVATE VALUE'}))
        with self.assertRaises(ValueError):
            self.run_sync(module, status=True)

    def test_pending_invalid_manifest_refuses_before_transport(self):
        module = self.api()
        with mock.patch.object(module, '_ssh', side_effect=OSError('offline')):
            with self.assertRaises(OSError):
                self.run_sync(module)
        path = self.outbox / 'pending.json'
        pending = json.loads(path.read_text())
        pending['manifest'] = []
        path.write_text(json.dumps(pending))
        with mock.patch.object(module, '_ssh') as ssh:
            with self.assertRaises(ValueError):
                self.run_sync(module)
        ssh.assert_not_called()

    def test_snapshot_information_is_coherent_and_runtime_state_stays_local(self):
        root = profile.resolve_config_path('', 'a')
        (root / 'snapshots').mkdir()
        (root / 'snapshots' / 'flip-2026-10-11.json').write_text('{"items": [], "count": 0}')
        (root / 'trader_state.json').write_text('{"pid": 987654321, "running": true}')
        packet = self.base / 'information.zip'
        state_replication.capture_packet('a', packet)
        state_replication.apply_packet('b', packet)
        remote = profile.resolve_config_path('', 'b')
        stored = json.loads((remote / 'peer-information.json').read_text())
        self.assertEqual(stored['origins'][A]['files']['snapshots/flip-2026-10-11.json']['count'], 0)
        self.assertNotIn('987654321', packet.read_bytes().decode('utf-8', errors='ignore'))
        self.assertFalse((remote / 'trader_state.json').exists())

    def test_lost_capture_commit_resumes_exact_packet_before_new_capture(self):
        from rshelper import state_transaction
        module = self.api()
        def interrupt(step):
            if step == 'receipt-published':
                raise OSError('source capture response lost')
        with mock.patch.object(state_transaction, '_checkpoint', interrupt), mock.patch.object(module, '_ssh') as ssh:
            with self.assertRaises(OSError):
                self.run_sync(module)
        ssh.assert_not_called()
        original = next(self.outbox.glob('*.zip')).read_bytes()
        with mock.patch.object(module, '_ssh', side_effect=self.transport):
            receipt = self.run_sync(module)
        self.assertEqual(receipt['applied_revision'], 1)
        self.assertEqual(self.applies, 1)
        self.assertGreater(len(original), 0)


if __name__ == '__main__':
    unittest.main()
