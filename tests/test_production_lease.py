from pathlib import Path
import importlib.util
import io
import copy
import json
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


class ProductionLeaseTest(unittest.TestCase):
    def test_runtime_constraints_refuse_incomplete_or_weakened_inspection(self):
        spec = importlib.util.spec_from_file_location('runtime_fixture', ROOT / 'deploy/verify_artifact.py')
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        observed = {'ReadonlyRootfs':True,'Privileged':False,'CapAdd':None,'CapDrop':['ALL'],
                    'SecurityOpt':['no-new-privileges:true'],'Memory':2*1024**3,
                    'MemorySwap':2*1024**3,'PidsLimit':128,
                    'Tmpfs':{'/tmp':'rw,noexec,nosuid,nodev,size=32m,mode=1777'}}
        self.assertEqual(module.validate_runtime_constraints(observed),observed)
        self.assertEqual(module.validate_runtime_constraints({**observed,'CapAdd':[]})['CapAdd'],[])
        bad = {'ReadonlyRootfs':False,'Privileged':True,'CapAdd':['SYS_ADMIN'],
               'CapDrop':[],'SecurityOpt':[],'Memory':0,'MemorySwap':-1,
               'PidsLimit':0,'Tmpfs':{'/tmp':'rw,size=1g'}}
        for field,value in bad.items():
            with self.subTest(field=field),self.assertRaises(ValueError):
                module.validate_runtime_constraints({**observed,field:value})
        for field in observed:
            missing = copy.deepcopy(observed)
            del missing[field]
            with self.subTest(missing=field),self.assertRaises(ValueError):
                module.validate_runtime_constraints(missing)

    def test_code_deploy_and_state_apply_share_production_lease(self):
        ci = (ROOT / '.github/workflows/ci.yml').read_text()
        self.assertIn('rshelper-production', ci)
        self.assertIn('production.lock', (ROOT / 'deploy/playbook.yml').read_text())
        helper = ROOT / 'deploy/private_state.py'
        self.assertTrue(helper.is_file(), 'version-pinned private apply helper missing')
        self.assertIn('production.lock', helper.read_text())

    def test_legacy_git_state_workflow_is_retired(self):
        self.assertFalse((ROOT / '.github/workflows/state-sync.yml').exists())

    def helper(self):
        spec = importlib.util.spec_from_file_location('private_state_fixture', ROOT / 'deploy/private_state.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_apply_uses_pinned_image_private_volume_and_cleans_container_on_failure(self):
        module = self.helper()
        calls = []
        verifier = mock.Mock()
        def invoke(args):
            calls.append(args)
            if args[0] == 'run':
                raise ValueError('failed apply')
            return b''
        verifier._docker_bytes.side_effect = invoke
        verifier.bounded_command.side_effect = lambda command, **kwargs: invoke(command[1:])
        with self.assertRaises(ValueError):
            module._run_image(verifier, 'sha256:' + 'a' * 64, Path('/opt/apps/rshelper'),
                              Path('/private/stage'), ['-m', 'rshelper', 'state', 'apply'])
        self.assertIn('none', calls[0])
        self.assertIn('--read-only', calls[0])
        for flag,value in (('--cap-drop','ALL'),('--security-opt','no-new-privileges:true'),
                           ('--memory','2g'),('--memory-swap','2g'),('--pids-limit','128')):
            self.assertEqual(calls[0][calls[0].index(flag)+1],value)
        self.assertIn('1000:1000', calls[0])
        self.assertIn('type=bind,src=/private/stage,dst=/state-stage,readonly', calls[0])
        self.assertIn('sha256:' + 'a' * 64, calls[0])
        self.assertEqual(calls[1][:2], ['rm', '--force'])
        self.assertEqual(calls[1][2], calls[0][calls[0].index('--name') + 1])
        self.assertEqual(verifier.bounded_command.call_args.kwargs['timeout'], 150)

    def test_failed_apply_cleans_only_owned_stage(self):
        module = self.helper()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            retained = root / 'state-transfers' / 'retained'
            retained.mkdir(parents=True)
            (retained / 'proof').write_bytes(b'keep this backup')
            with mock.patch.object(module, 'APP_DIR', root), \
                    mock.patch.object(module, '_module', return_value=mock.Mock()), \
                    mock.patch.object(module, '_running', return_value={'image_id': 'sha256:' + 'a' * 64}), \
                    mock.patch.object(module.os, 'chown'), mock.patch.object(module.os, 'fchown'), \
                    mock.patch.object(module, '_run_image', side_effect=ValueError('failure')):
                with self.assertRaises(ValueError):
                    module.perform(root, 'apply', '11111111-1111-4111-8111-111111111111',
                                   'default', incoming=io.BytesIO(b'synthetic packet'))
            self.assertEqual(list((root / 'state-transfers').iterdir()), [retained])
            self.assertEqual((retained / 'proof').read_bytes(), b'keep this backup')

    def test_busy_host_lease_refuses_before_artifact_or_state_access(self):
        import fcntl
        module = self.helper()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (root / 'production.lock').open('wb') as lease:
                fcntl.flock(lease, fcntl.LOCK_EX)
                with mock.patch.object(module, 'APP_DIR', root), mock.patch.object(module, '_module') as load:
                    with self.assertRaises(BlockingIOError):
                        module.perform(root, 'receipt', '11111111-1111-4111-8111-111111111111', 'default')
                load.assert_not_called()


if __name__ == '__main__':
    unittest.main()
