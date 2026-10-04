"""Private backup capture is validated, bounded and never overwrites state."""
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from rshelper import backup, profile

class TestBackup(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.root = Path(self.scratch.name)
        self.state = self.root / 'state'
        self.state.mkdir()
        self.old_root = profile.CONFIG_DIR
        profile.CONFIG_DIR = self.state
        self.trade = {'id': 1, 'item_id': 2, 'name': 'Fixture', 'qty': 1,
                      'buy_price': 100, 'sell_price': 110, 'tax_paid': 2,
                      'profit': 8, 'timestamp': '2026-10-04T12:00:00Z',
                      'note': 'private observation', 'extension': {'retained': 1}}
        (self.state / 'trades.json').write_text(json.dumps({'trades': [self.trade]}))
        (self.state / 'positions.json').write_text('{"positions": []}')
        (self.state / 'config.toml').write_text('[flip]\nmin_volume = 10\n')
        self.destination = self.root / 'backup.zip'

    def tearDown(self):
        profile.CONFIG_DIR = self.old_root
        self.scratch.cleanup()

    def test_profile_alias_cannot_capture_another_profile(self):
        (self.state / 'profiles').mkdir()
        (self.state / 'profiles' / 'alt').symlink_to(self.state, target_is_directory=True)
        with self.assertRaises(backup.BackupError):
            backup.export_profile('alt', self.destination)
        self.assertFalse(self.destination.exists())

    def test_backup_hashes_permissions_and_extensions(self):
        before = (self.state / 'trades.json').read_bytes()
        manifest = backup.export_profile('default', self.destination, 'backup')
        self.assertEqual(stat.S_IMODE(self.destination.stat().st_mode), 0o600)
        self.assertEqual(manifest['sensitivity'], 'private')
        with zipfile.ZipFile(self.destination) as bundle:
            embedded = json.loads(bundle.read('manifest.json'))
            self.assertEqual(embedded, manifest)
            saved = bundle.read('trades.json')
            self.assertEqual(saved, before)
            self.assertEqual(manifest['files']['trades.json']['sha256'], hashlib.sha256(saved).hexdigest())
            self.assertEqual(json.loads(saved)['trades'][0], self.trade)
        self.assertEqual((self.state / 'trades.json').read_bytes(), before)

    def test_secret_and_runtime_files_excluded(self):
        for name in ('owner.token', 'trader.pid', 'active_profile', 'unrecognized.json'):
            (self.state / name).write_text('SECRET_VALUE')
        backup.export_profile('default', self.destination, 'backup')
        with zipfile.ZipFile(self.destination) as bundle:
            self.assertNotIn(b'SECRET_VALUE', b''.join(bundle.read(n) for n in bundle.namelist()))

    def test_corrupt_source_preserves_bytes_and_no_bundle(self):
        path = self.state / 'positions.json'
        path.write_bytes(b'{broken')
        with self.assertRaises(ValueError):
            backup.export_profile('default', self.destination, 'backup')
        self.assertEqual(path.read_bytes(), b'{broken')
        self.assertFalse(self.destination.exists())

    def test_evidence_bundle_retains_invalid_snapshot_and_labels_it(self):
        (self.state / 'snapshots').mkdir()
        (self.state / 'snapshots' / 'flip-2026-07-31.json').write_bytes(b'x\n')
        manifest = backup.export_profile('default', self.destination, 'evidence')
        self.assertEqual(manifest['validation'], 'unvalidated-evidence')
        self.assertEqual(manifest['files']['snapshots/flip-2026-07-31.json']['validation'], 'invalid')
        with zipfile.ZipFile(self.destination) as bundle:
            self.assertEqual(bundle.read('snapshots/flip-2026-07-31.json'), b'x\n')
        self.assertEqual((self.state / 'snapshots' / 'flip-2026-07-31.json').read_bytes(), b'x\n')

    def test_existing_destination_never_overwritten(self):
        self.destination.write_bytes(b'original')
        with self.assertRaises(FileExistsError):
            backup.export_profile('default', self.destination, 'backup')
        self.assertEqual(self.destination.read_bytes(), b'original')

    def test_public_policy_and_nested_destination_refused(self):
        with self.assertRaises(ValueError):
            backup.export_profile('default', self.destination, 'public-demo')
        with self.assertRaises(ValueError):
            backup.export_profile('default', self.state / 'backup.zip', 'backup')

    def test_total_budget_blocks_publication(self):
        with mock.patch.object(backup, 'MAX_BUNDLE_BYTES', 1):
            with self.assertRaises(ValueError):
                backup.export_profile('default', self.destination, 'backup')
        self.assertFalse(self.destination.exists())
        self.assertEqual(list(self.root.glob('.rshelper-backup-*')), [])

    def test_snapshot_manifest_name_is_not_reserved_root_entry(self):
        (self.state / 'snapshots').mkdir()
        (self.state / 'snapshots' / 'manifest.json').write_bytes(b'{"scan": []}')
        backup.export_profile('default', self.destination, 'backup')
        with zipfile.ZipFile(self.destination) as bundle:
            self.assertEqual(bundle.read('snapshots/manifest.json'), b'{"scan": []}')
            self.assertEqual(json.loads(bundle.read('manifest.json'))['schema_version'], 1)

    def test_failed_publication_cleans_temp_and_preserves_racing_target(self):
        def collide(source, destination):
            Path(destination).write_bytes(b'other writer')
            raise FileExistsError('fixture')
        with mock.patch.object(backup.os, 'link', side_effect=collide):
            with self.assertRaises(FileExistsError):
                backup.export_profile('default', self.destination, 'backup')
        self.assertEqual(self.destination.read_bytes(), b'other writer')
        self.assertEqual(list(self.root.glob('.rshelper-backup-*')), [])

    def test_symlink_source_refused(self):
        linked = self.state / 'positions.json'
        linked.unlink()
        linked.symlink_to(self.state / 'trades.json')
        with self.assertRaises(ValueError):
            backup.export_profile('default', self.destination, 'backup')
        self.assertFalse(self.destination.exists())

    def test_evidence_cli_preserves_invalid_config_without_work(self):
        import contextlib
        import io
        from rshelper import cli
        original = b'[trader\n'
        (self.state / 'config.toml').write_bytes(original)
        with mock.patch.object(sys, 'argv', ['rshelper', '--quiet', '--profile', 'default', 'profile', 'backup', str(self.destination), '--evidence', '--json']), \
                mock.patch.object(cli, '_fetch_bootstrap') as fetch, \
                contextlib.redirect_stdout(io.StringIO()) as output, \
                contextlib.redirect_stderr(io.StringIO()) as errors:
            cli.main()
        self.assertEqual(json.loads(output.getvalue())['validation'], 'unvalidated-evidence')
        self.assertEqual((self.state / 'config.toml').read_bytes(), original)
        self.assertEqual(errors.getvalue(), '')
        fetch.assert_not_called()

    def test_backup_cli_json_and_no_fetch(self):
        import contextlib
        import io
        from rshelper import cli
        with mock.patch.object(sys, 'argv', ['rshelper', '--profile', 'default', 'profile', 'backup', str(self.destination), '--json']), \
                mock.patch.object(cli, '_fetch_bootstrap') as fetch, \
                contextlib.redirect_stdout(io.StringIO()) as output, \
                contextlib.redirect_stderr(io.StringIO()) as errors:
            cli.main()
        self.assertEqual(json.loads(output.getvalue())['sensitivity'], 'private')
        self.assertEqual(errors.getvalue(), '')
        fetch.assert_not_called()
        self.assertTrue(self.destination.exists())

    def test_concurrent_capture_change_aborts(self):
        original = backup._read_file
        count = 0
        def changed(path):
            nonlocal count
            raw = original(path)
            if path.name == 'trades.json':
                count += 1
                if count == 1:
                    path.write_text(json.dumps({'trades': []}))
            return raw
        with mock.patch.object(backup, '_read_file', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'changed'):
                backup.export_profile('default', self.destination, 'backup')
        self.assertFalse(self.destination.exists())

    def test_snapshot_capture_and_profile_scope(self):
        alt = self.state / 'profiles' / 'alt'
        alt.mkdir(parents=True)
        (alt / 'snapshots').mkdir()
        (alt / 'snapshots' / '2026-10-04.json').write_text('{"scan": []}')
        (alt / 'trades.json').write_text('{"trades": []}')
        manifest = backup.export_profile('alt', self.destination, 'backup')
        self.assertEqual(manifest['profile'], 'alt')
        self.assertIn('snapshots/2026-10-04.json', manifest['files'])
        self.assertNotIn('config.toml', manifest['files'])

if __name__ == '__main__':
    unittest.main()
