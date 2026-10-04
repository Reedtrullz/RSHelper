"""Release receipts bind registry digest, image identity and baked revision."""
import copy
import json
import importlib.util
import io
import tarfile
import subprocess
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from rshelper import release


class ReleaseMetadataTest(unittest.TestCase):
    def setUp(self):
        self.revision = 'a'*40
        self.digest = 'sha256:'+'b'*64
        self.image = 'ghcr.io/reedtrullz/rshelper@'+self.digest
        self.baked = {'schema_version': 1, 'source_revision': self.revision,
                      'platform': 'linux/amd64', 'base_image_digest': 'sha256:'+'c'*64}
        self.inspect = {'Id': 'sha256:'+'d'*64, 'Architecture': 'amd64', 'Os': 'linux',
                        'RepoDigests': [self.image],
                        'Config': {'Labels': {'org.opencontainers.image.revision': self.revision}}}

    def test_runtime_version_cannot_impersonate_build(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'_build.json'; path.write_text(json.dumps(self.baked))
            with mock.patch.object(release, 'BUILD_METADATA_PATH', path), \
                 mock.patch.dict(os.environ, {'VERSION': 'e'*40, 'RSHELPER_IMAGE_DIGEST': self.digest}):
                health = release.health_metadata()
            self.assertEqual(health['version'], self.revision)
            self.assertEqual(health['build_revision'], self.revision)
            self.assertEqual(health['image_digest'], self.digest)

    def test_missing_or_invalid_build_cannot_claim_configured_sha(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'_build.json'
            with mock.patch.object(release, 'BUILD_METADATA_PATH', path), \
                 mock.patch.dict(os.environ, {'VERSION': self.revision}):
                self.assertNotEqual(release.health_metadata()['version'], self.revision)
                path.write_text(json.dumps({**self.baked, 'schema_version': True}))
                with self.assertRaises(release.ReleaseMetadataError): release.health_metadata()

    def test_label_digest_revision_mismatch_rejected(self):
        receipt = release.validate_candidate(self.image, self.revision, self.inspect, self.baked)
        self.assertEqual(receipt['image'], self.image)
        self.assertEqual(receipt['revision'], self.revision)
        for field in ('label', 'digest', 'baked', 'platform', 'missing-digest'):
            with self.subTest(field=field):
                inspected = copy.deepcopy(self.inspect); baked = copy.deepcopy(self.baked)
                if field == 'label': inspected['Config']['Labels']['org.opencontainers.image.revision'] = 'e'*40
                if field == 'digest': inspected['RepoDigests'] = ['ghcr.io/reedtrullz/rshelper@sha256:'+'e'*64]
                if field == 'baked': baked['source_revision'] = 'e'*40
                if field == 'platform': inspected['Architecture'] = 'arm64'
                if field == 'missing-digest': inspected['RepoDigests'] = []
                with self.assertRaises(release.ReleaseMetadataError):
                    release.validate_candidate(self.image, self.revision, inspected, baked)

    def test_mutable_tag_and_unavailable_registry_abstain(self):
        for image, inspected in (('ghcr.io/reedtrullz/rshelper:latest', self.inspect),
                                 (self.image, None), (self.image, {})):
            with self.assertRaises(release.ReleaseMetadataError):
                release.validate_candidate(image, self.revision, inspected, self.baked)
        for config in (None, [], {'Labels': None}, {'Labels': []}):
            with self.assertRaises(release.ReleaseMetadataError):
                release.validate_candidate(self.image, self.revision,
                                           {**self.inspect, 'Config': config}, self.baked)

    def test_rollback_keeps_digest_revision_and_image_id(self):
        previous = release.previous_release(self.inspect, self.inspect['Id'],
                                             'ghcr.io/reedtrullz/rshelper')
        self.assertEqual(previous['image'], self.image)
        self.assertEqual(previous['revision'], self.revision)
        self.assertEqual(previous['image_id'], self.inspect['Id'])
        with self.assertRaises(release.ReleaseMetadataError):
            release.previous_release(self.inspect, 'sha256:'+'e'*64, 'ghcr.io/reedtrullz/rshelper')


class StaticArtifactTest(unittest.TestCase):
    def test_candidate_metadata_is_copied_without_starting_image(self):
        path = Path(__file__).resolve().parents[1]/'deploy/verify_artifact.py'
        spec = importlib.util.spec_from_file_location('artifact_verifier', path)
        helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
        raw = b'{"schema_version":1}'
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode='w') as tar:
            info = tarfile.TarInfo('_build.json'); info.size = len(raw)
            tar.addfile(info, io.BytesIO(raw))
        calls = []
        def invoke(argv, **kwargs):
            calls.append(argv)
            return archive.getvalue() if argv[0]=='cp' else b''
        with mock.patch.object(helper, '_docker_bytes', side_effect=invoke):
            self.assertEqual(helper.copy_build_metadata('ghcr.io/example/app@sha256:'+'a'*64), {'schema_version':1})
        self.assertEqual([call[0] for call in calls], ['create', 'cp', 'rm'])
        self.assertIn('--network', calls[0])
        self.assertNotIn('start', [word for call in calls for word in call])

    def test_static_metadata_rejects_oversize_and_symlink_and_cleans_up(self):
        path = Path(__file__).resolve().parents[1]/'deploy/verify_artifact.py'
        spec = importlib.util.spec_from_file_location('artifact_verifier', path)
        helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
        for kind in ('oversize', 'symlink'):
            archive = io.BytesIO()
            with tarfile.open(fileobj=archive, mode='w') as tar:
                info = tarfile.TarInfo('_build.json')
                if kind=='symlink': info.type=tarfile.SYMTYPE; info.linkname='/etc/passwd'; tar.addfile(info)
                else: info.size=4097; tar.addfile(info, io.BytesIO(b'x'*4097))
            calls=[]
            def invoke(argv, **kwargs):
                calls.append(argv)
                return archive.getvalue() if argv[0]=='cp' else b''
            with mock.patch.object(helper, '_docker_bytes', side_effect=invoke):
                with self.assertRaises(ValueError): helper.copy_build_metadata('fixture')
            self.assertEqual(calls[-1][:2], ['rm', '--force'])

    def test_child_output_is_limited_while_streaming_and_deadline_is_enforced(self):
        path = Path(__file__).resolve().parents[1]/'deploy/verify_artifact.py'
        spec = importlib.util.spec_from_file_location('artifact_verifier', path)
        helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
        with self.assertRaises(ValueError):
            helper.bounded_command([sys.executable, '-c',
                "import os,time;os.write(1,b'x'*1000000);time.sleep(20)"], limit=65536, timeout=2)
        with self.assertRaises(subprocess.TimeoutExpired):
            helper.bounded_command([sys.executable, '-c', 'import time;time.sleep(20)'], timeout=.1)
        self.assertEqual(helper.bounded_command([sys.executable,'-c',"print('small')"]), b'small\n')


if __name__ == '__main__': unittest.main()
