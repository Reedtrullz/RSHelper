"""Only selected malformed snapshots can move after verified private evidence."""
import hashlib
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from rshelper import recovery

class TestSnapshotRecovery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve() / 'state'
        (self.root / 'snapshots').mkdir(parents=True)
        self.path = self.root / 'snapshots' / 'flip-2026-07-31.json'
        self.raw = b'x\n'
        self.path.write_bytes(self.raw)
        self.sha = hashlib.sha256(self.raw).hexdigest()
        self.evidence = Path(self.tmp.name).resolve() / 'private-evidence'

    def test_cli_preview_is_json_and_apply_requires_hash(self):
        arguments = ['--root', str(self.root), '--snapshot', 'snapshots/flip-2026-07-31.json']
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(recovery.main(arguments), 0)
        self.assertEqual(json.loads(output.getvalue())['sha256'], self.sha)
        self.assertEqual(self.path.read_bytes(), self.raw)
        with contextlib.redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(recovery.main(arguments + ['--apply', '--evidence-dir', str(self.evidence), '--expected-sha', '0'*64]), 2)
        self.assertIn('changed', errors.getvalue())
        self.assertEqual(self.path.read_bytes(), self.raw)

    def test_preview_read_only(self):
        report = recovery.preview_snapshot_quarantine(self.root, 'snapshots/flip-2026-07-31.json')
        self.assertEqual(report['sha256'], self.sha)
        self.assertEqual(self.path.read_bytes(), self.raw)
        self.assertFalse(self.evidence.exists())

    def test_explicit_quarantine_preserves_original_and_archive(self):
        report = recovery.quarantine_snapshot(self.root, 'snapshots/flip-2026-07-31.json', self.evidence, self.sha)
        self.assertFalse(self.path.exists())
        self.assertEqual(Path(report['original']).read_bytes(), self.raw)
        with zipfile.ZipFile(report['archive']) as bundle:
            self.assertEqual(bundle.read('snapshots/flip-2026-07-31.json'), self.raw)
            manifest = json.loads(bundle.read('manifest.json'))
            self.assertEqual(manifest['sha256'], self.sha)
            self.assertEqual(manifest['sensitivity'], 'private')
        self.assertEqual(Path(report['archive']).stat().st_mode & 0o777, 0o600)

    def test_valid_json_and_non_snapshot_files_refused(self):
        for raw in (b'{}', b'[]', b'{"unknown": 1}'):
            self.path.write_bytes(raw)
            with self.assertRaises(ValueError):
                recovery.preview_snapshot_quarantine(self.root, 'snapshots/flip-2026-07-31.json')
            self.assertEqual(self.path.read_bytes(), raw)
        (self.root / 'trades.json').write_bytes(b'broken')
        with self.assertRaises(ValueError):
            recovery.preview_snapshot_quarantine(self.root, 'trades.json')

    def test_stale_hash_and_root_escape_preserve_source(self):
        for path in ('../snapshots/flip-2026-07-31.json', '/etc/passwd', 'profiles/alt/snapshots/flip-2026-07-31.json'):
            with self.assertRaises(ValueError):
                recovery.preview_snapshot_quarantine(self.root, path)
        with self.assertRaises(ValueError):
            recovery.quarantine_snapshot(self.root, 'snapshots/flip-2026-07-31.json', self.evidence, '0' * 64)
        self.assertEqual(self.path.read_bytes(), self.raw)
        self.assertFalse(self.evidence.exists())

    def test_source_symlink_and_inside_evidence_denied(self):
        self.path.unlink()
        self.path.symlink_to(self.root / 'trades.json')
        (self.root / 'trades.json').write_bytes(self.raw)
        with self.assertRaises(ValueError):
            recovery.preview_snapshot_quarantine(self.root, 'snapshots/flip-2026-07-31.json')
        self.path.unlink(); self.path.write_bytes(self.raw)
        with self.assertRaises(ValueError):
            recovery.quarantine_snapshot(self.root, 'snapshots/flip-2026-07-31.json', self.root / 'recovery', self.sha)

    def test_failed_move_keeps_source_and_evidence(self):
        with mock.patch.object(recovery.os, 'rename', side_effect=OSError('fixture')):
            with self.assertRaises(ValueError):
                recovery.quarantine_snapshot(self.root, 'snapshots/flip-2026-07-31.json', self.evidence, self.sha)
        self.assertEqual(self.path.read_bytes(), self.raw)
        self.assertEqual(len(list(self.evidence.glob('*/evidence.zip'))), 1)

    def test_noncooperative_race_restores_without_overwrite(self):
        rename = recovery.os.rename
        changed = b'{"scan": [1]}'
        def replace_before_move(source, destination, **kwargs):
            self.path.write_bytes(changed)
            rename(source, destination, **kwargs)
        with mock.patch.object(recovery.os, 'rename', side_effect=replace_before_move):
            with self.assertRaises(ValueError):
                recovery.quarantine_snapshot(self.root, 'snapshots/flip-2026-07-31.json', self.evidence, self.sha)
        self.assertEqual(self.path.read_bytes(), changed)
        self.assertEqual(len(list(self.evidence.glob('*/original.json'))), 1)

    def test_failed_moved_file_verification_restores_source(self):
        read = recovery._read_at
        def fail_original(directory_fd, name):
            if name == 'original.json':
                raise OSError('verification fixture')
            return read(directory_fd, name)
        with mock.patch.object(recovery, '_read_at', side_effect=fail_original):
            with self.assertRaises(ValueError):
                recovery.quarantine_snapshot(self.root, 'snapshots/flip-2026-07-31.json', self.evidence, self.sha)
        self.assertEqual(self.path.read_bytes(), self.raw)
        self.assertEqual(len(list(self.evidence.glob('*/original.json'))), 1)

    def test_legacy_snapshot_and_evidence_alias(self):
        relative = 'state/snapshots/flip-2026-07-31.json'
        target = self.root / relative
        target.parent.mkdir(parents=True)
        target.write_bytes(self.raw)
        alias = self.root.parent / 'alias'
        self.evidence.mkdir()
        alias.symlink_to(self.evidence)
        with self.assertRaises(ValueError):
            recovery.quarantine_snapshot(self.root, relative, alias, self.sha)
        self.assertEqual(target.read_bytes(), self.raw)
        report = recovery.quarantine_snapshot(self.root, relative, self.evidence, self.sha)
        self.assertEqual(Path(report['original']).read_bytes(), self.raw)

    def test_decoder_limit_is_not_malformed_evidence(self):
        for raw in (b'1' * 5000, b'[' * 2000 + b']' * 2000):
            self.path.write_bytes(raw)
            with self.assertRaisesRegex(ValueError, 'limits'):
                recovery.preview_snapshot_quarantine(self.root, 'snapshots/flip-2026-07-31.json')

    def test_failed_restoration_reports_retained_original(self):
        read = recovery._read_at
        def fail_original(directory_fd, name):
            if name == 'original.json': raise OSError('fixture')
            return read(directory_fd, name)
        with mock.patch.object(recovery, '_read_at', side_effect=fail_original), \
             mock.patch.object(recovery.os, 'link', side_effect=PermissionError('fixture')):
            with self.assertRaisesRegex(ValueError, 'active snapshot absent.*original retained'):
                recovery.quarantine_snapshot(self.root, 'snapshots/flip-2026-07-31.json', self.evidence, self.sha)
        self.assertFalse(self.path.exists())
        self.assertEqual(next(self.evidence.glob('*/original.json')).read_bytes(), self.raw)

    def test_directory_replacement_cannot_move_an_external_snapshot(self):
        external = self.root.parent / 'external'
        external.mkdir()
        outsider = external / self.path.name
        outsider.write_bytes(self.raw)
        original_directory = self.root / 'original-snapshots'
        rename = recovery.os.rename
        def replace_directory(source, destination, **kwargs):
            rename(self.path.parent, original_directory)
            self.path.parent.symlink_to(external, target_is_directory=True)
            rename(source, destination, **kwargs)
        with mock.patch.object(recovery.os, 'rename', side_effect=replace_directory):
            with self.assertRaisesRegex(ValueError, 'displaced source directory.*selected path changed'):
                recovery.quarantine_snapshot(self.root, 'snapshots/flip-2026-07-31.json', self.evidence, self.sha)
        self.assertEqual(outsider.read_bytes(), self.raw)
        self.assertEqual((original_directory / self.path.name).read_bytes(), self.raw)

    def test_equal_bytes_replacement_is_not_reported_as_success(self):
        rename = recovery.os.rename
        def replace_file(source, destination, **kwargs):
            self.path.unlink(); self.path.write_bytes(self.raw)
            rename(source, destination, **kwargs)
        with mock.patch.object(recovery.os, 'rename', side_effect=replace_file):
            with self.assertRaises(ValueError):
                recovery.quarantine_snapshot(self.root, 'snapshots/flip-2026-07-31.json', self.evidence, self.sha)
        self.assertEqual(self.path.read_bytes(), self.raw)

    def test_evidence_directory_replacement_cannot_overwrite_outsider(self):
        rename = recovery.os.rename
        external = self.root.parent / 'external-evidence'; external.mkdir()
        outsider = external / 'original.json'; outsider.write_bytes(b'outside-original')
        def replace_evidence(source, destination, **kwargs):
            folder = next(self.evidence.glob('snapshot-*'))
            rename(folder, self.evidence / 'retained-evidence')
            folder.symlink_to(external, target_is_directory=True)
            rename(source, destination, **kwargs)
        with mock.patch.object(recovery.os, 'rename', side_effect=replace_evidence):
            with self.assertRaisesRegex(ValueError, 'displaced evidence directory'):
                recovery.quarantine_snapshot(self.root, 'snapshots/flip-2026-07-31.json', self.evidence, self.sha)
        self.assertEqual(outsider.read_bytes(), b'outside-original')
        self.assertEqual(self.path.read_bytes(), self.raw)
        self.assertEqual((self.evidence / 'retained-evidence' / 'original.json').read_bytes(), self.raw)

if __name__ == '__main__':
    unittest.main()
