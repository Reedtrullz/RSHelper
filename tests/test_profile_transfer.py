import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from rshelper import profile, profile_transfer, state_identity

ORIGIN = '11111111-1111-4111-8111-111111111111'
PROFILE = '22222222-2222-4222-8222-222222222222'
OP = '33333333-3333-4333-8333-333333333333'


class TransferTest(unittest.TestCase):
    temp: tempfile.TemporaryDirectory
    base: Path
    root: Path

    def test_existing_and_aliased_export_targets_preserved(self):
        outside = self.base/'original.json'; outside.write_bytes(b'original')
        alias = self.base/'alias.json'; alias.symlink_to(outside)
        for destination in (outside, alias, self.root/'inside.json'):
            with self.subTest(destination=destination.name), self.assertRaises((ValueError, FileExistsError)):
                profile_transfer.export_profile('source', destination, 'json')
            self.assertEqual(outside.read_bytes(), b'original')
        self.assertFalse((self.root/'inside.json').exists())

    def test_duplicate_foreign_identity_and_changed_revision_refuse(self):
        import hashlib
        source = self.base/'export.json'
        profile_transfer.export_profile('source', source, 'json')
        original = json.loads(source.read_bytes())
        before = {p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        for kind in ('duplicate', 'foreign', 'revision'):
            data = json.loads(json.dumps(original))
            rows = json.loads(data['files']['positions.json'])
            if kind == 'duplicate':
                rows['positions'].append(dict(rows['positions'][0]))
            elif kind == 'foreign':
                rows['positions'][0]['origin_uuid'] = OP
            else:
                rows['positions'][0]['buy_price'] += 1
            raw = json.dumps(rows).encode()
            data['files']['positions.json'] = raw.decode()
            record = data['manifest']['files']['positions.json']
            record.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
            data['manifest']['source_revision'] = hashlib.sha256(
                json.dumps(data['manifest']['files'], sort_keys=True).encode()).hexdigest()
            source.write_text(json.dumps(data))
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                profile_transfer.import_profile('source', source, 'json', expected_profile_uuid=PROFILE)
            self.assertEqual(before, {p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file()})

    def test_cli_export_preview_and_readiness_stdout_are_json(self):
        from rshelper import cli
        import contextlib
        import io
        source = self.base/'cli.csv'
        commands = [(['profile','export',str(source),'--format','csv','--json'], 'source'),
                    (['profile','import','--input',str(source),'--format','csv',
                      '--expected-profile-uuid',PROFILE,'--json'], 'fresh'),
                    (['readiness','--json'], 'fresh')]
        for command, name in commands:
            output = io.StringIO()
            with mock.patch.object(sys, 'argv', ['rshelper','--profile',name,*command]), \
                    contextlib.redirect_stdout(output):
                cli.main()
            self.assertIsInstance(json.loads(output.getvalue()), dict)
        self.assertFalse(profile.resolve_config_path('', 'fresh').exists())

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        patch = mock.patch.object(profile, 'CONFIG_DIR', self.base/'state')
        patch.start(); self.addCleanup(patch.stop)
        self.root = profile.resolve_config_path('', 'source'); self.root.mkdir(parents=True)
        lot = {'id': 1, 'item_id': 2, 'name': 'Synthetic', 'qty': 10, 'buy_price': 100,
               'direction': 'traditional', 'opened_at': '2026-01-01T00:00:00Z'}
        lots, manifest = state_identity.migrate_rows([lot], 'positions', state_identity.new_manifest(ORIGIN))
        files = {'positions.json': {'positions': lots}, 'trades.json': {'trades': []},
            'watchlist.json': {'items': {}}, 'identity-manifest.json': manifest,
            'identity-activation.json': {'schema_version': 1, 'mode': 'identified',
                'origin_uuid': ORIGIN, 'profile_uuid': PROFILE, 'financial_authority': True,
                'replication_origins': [ORIGIN]}}
        for name, value in files.items():
            (self.root/name).write_text(json.dumps(value))
        (self.root/'config.toml').write_text('[flip]\nmin_volume = 10\n')

    def test_json_csv_roundtrip_preview_and_preapply_backup(self):
        from rshelper import realization, watchlist
        lot = json.loads((self.root/'positions.json').read_bytes())['positions'][0]
        realization.close_and_realize('source', lot['lot_uid'], 5, 120, ORIGIN, 'manual')
        watchlist.add(2, 'Synthetic', profile='source', operation_id=PROFILE)
        for format in ('json', 'csv'):
            with self.subTest(format=format):
                source = self.base/('export.'+format)
                result = profile_transfer.export_profile('source', source, format)
                self.assertEqual(result['sensitivity'], 'private')
                target = 'target_'+format
                target_root = profile.resolve_config_path('', target)
                preview = profile_transfer.import_profile(target, source, format,
                    expected_profile_uuid=PROFILE)
                self.assertEqual(preview['status'], 'preview')
                self.assertFalse(target_root.exists())
                saved = self.base/('before_'+format+'.zip')
                receipt = profile_transfer.import_profile(target, source, format,
                    expected_profile_uuid=PROFILE, apply=True, operation_id=OP, backup_path=saved)
                self.assertEqual(receipt['status'], 'restored')
                self.assertTrue(saved.exists())
                for name in ('config.toml', 'positions.json', 'trades.json', 'watchlist.json'):
                    self.assertEqual((self.root/name).read_bytes(), (target_root/name).read_bytes())
                again = profile_transfer.import_profile(target, source, format,
                    expected_profile_uuid=PROFILE)
                self.assertEqual(again['changes'], [])
                watchlist.add(99, 'Later watch', profile=target,
                    operation_id='44444444-4444-4444-8444-444444444444')
                retry = profile_transfer.import_profile(target, source, format,
                    expected_profile_uuid=PROFILE, apply=True, operation_id=OP, backup_path=saved)
                self.assertEqual(retry, receipt)
                self.assertIn('99', watchlist.load(target)['items'])

    def test_bad_import_and_wrong_profile_leave_tree_unchanged(self):
        source = self.base/'export.json'
        profile_transfer.export_profile('source', source, 'json')
        before = {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        with self.assertRaises(ValueError):
            profile_transfer.import_profile('source', source, 'json', expected_profile_uuid=ORIGIN)
        valid = source.read_bytes()
        for raw in (b'{', b'{"manifest":{},"manifest":{},"files":{}}',
                    valid.replace(b'positions.json', b'../escape.json')):
            source.write_bytes(raw)
            with self.assertRaises(ValueError):
                profile_transfer.import_profile('source', source, 'json', expected_profile_uuid=PROFILE,
                    apply=True, operation_id=OP, backup_path=self.base/'before.zip')
            self.assertEqual(before, {p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file()})

    def test_failed_preapply_backup_leaves_live_state_unchanged(self):
        from rshelper import backup
        source = self.base/'export.json'
        profile_transfer.export_profile('source', source, 'json')
        before = {p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        with mock.patch.object(backup, '_export_profile', side_effect=OSError('fixture backup unavailable')):
            with self.assertRaises(OSError):
                profile_transfer.import_profile('source', source, 'json', expected_profile_uuid=PROFILE,
                    apply=True, operation_id=OP, backup_path=self.base/'before.zip')
        self.assertEqual(before, {p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file()})


if __name__ == '__main__':
    unittest.main()
