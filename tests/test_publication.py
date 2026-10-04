"""Publication previews expose schema/counts, never private record values."""
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from rshelper.publication import export_demo, preview_publication, PublicationError

class TestPublication(unittest.TestCase):
    def setUp(self):
        self.state = {'trades.json': {'trades': [
            {'id': 1, 'item_id': 2, 'name': 'Private item label', 'qty': 1,
             'buy_price': 100, 'sell_price': 110, 'tax_paid': 2, 'profit': 8,
             'timestamp': '2026-10-04T12:00:00Z', 'note': 'Private observation'}]}}
        self.policy = {'schema_version': 1, 'mode': 'public-demo',
                       'approved_profiles': ['synthetic-demo'],
                       'files': {'trades.json': ['item_id', 'qty', 'profit', 'timestamp']}}

    def test_new_field_profile_denied_publication(self):
        with self.assertRaises(PublicationError):
            export_demo(self.state, self.policy, profile='new-account')
        self.state['trades.json']['trades'][0]['account_label'] = 'secret'
        with self.assertRaises(PublicationError):
            export_demo(self.state, self.policy, profile='synthetic-demo')

    def test_preview_matches_public_bytes(self):
        preview = preview_publication('synthetic-demo', self.policy, self.state)
        output = export_demo(self.state, self.policy, profile='synthetic-demo')
        fields = preview['files'][0]['fields']
        self.assertEqual(set(fields), set(output['trades.json']['trades'][0]))
        self.assertEqual(preview['files'][0]['records'], 1)
        self.assertNotIn('Private', json.dumps(preview))
        self.assertNotIn('Private', json.dumps(output))
        self.assertNotIn('note', output['trades.json']['trades'][0])
        self.assertEqual(self.state['trades.json']['trades'][0]['note'], 'Private observation')

    def test_default_policy_denies_all(self):
        for policy in ({}, {'schema_version': 1, 'mode': 'public-demo', 'approved_profiles': [], 'files': {}}):
            with self.assertRaises(PublicationError):
                export_demo(self.state, policy, profile='synthetic-demo')

    def test_operational_files_and_private_fields_not_public(self):
        for filename, fields in (('config.toml', ['capital']), ('trades.json', ['note']),
                                 ('trades.json', ['name']), ('../trades.json', ['profit'])):
            policy = {**self.policy, 'files': {filename: fields}}
            with self.assertRaises(PublicationError):
                export_demo(self.state, policy, profile='synthetic-demo')

    def test_unknown_root_or_file_denied(self):
        self.state['trades.json']['future_field'] = 'hidden'
        with self.assertRaises(PublicationError):
            export_demo(self.state, self.policy, profile='synthetic-demo')
        del self.state['trades.json']['future_field']
        self.state['future.json'] = {}
        with self.assertRaises(PublicationError):
            export_demo(self.state, self.policy, profile='synthetic-demo')

    def test_invalid_economics_or_nonfinite_denied(self):
        for value in (True, float('inf'), 'eight'):
            self.state['trades.json']['trades'][0]['profit'] = value
            with self.assertRaises(PublicationError):
                export_demo(self.state, self.policy, profile='synthetic-demo')

    def test_private_replication_and_backup_are_distinct(self):
        for mode in ('private-replication', 'backup'):
            with self.assertRaises(PublicationError):
                export_demo(self.state, {**self.policy, 'mode': mode}, profile='synthetic-demo')

    def test_optional_approved_field_matches_preview_without_fabrication(self):
        self.policy['files']['trades.json'].append('hold_minutes')
        preview = preview_publication('synthetic-demo', self.policy, self.state)
        row = export_demo(self.state, self.policy, profile='synthetic-demo')['trades.json']['trades'][0]
        self.assertEqual(set(preview['files'][0]['fields']), set(row))
        self.assertIsNone(row['hold_minutes'])

    def test_positions_have_explicit_public_fields_and_private_notes_stay_private(self):
        state = {'positions.json': {'positions': [{'id': 1, 'item_id': 2,
            'name': 'Private position', 'qty': 4, 'buy_price': 100,
            'direction': 'traditional', 'opened_at': '2026-10-04T12:00:00Z',
            'note': 'Private intent'}]}}
        policy = {**self.policy, 'files': {'positions.json': ['item_id', 'qty', 'direction', 'opened_at']}}
        preview = preview_publication('synthetic-demo', policy, state)
        output = export_demo(state, policy, profile='synthetic-demo')
        self.assertEqual(preview['files'][0]['records'], len(output['positions.json']['positions']))
        self.assertEqual(set(preview['files'][0]['fields']), set(output['positions.json']['positions'][0]))
        self.assertNotIn('Private', json.dumps(output))
        self.assertEqual(state['positions.json']['positions'][0]['note'], 'Private intent')

if __name__ == '__main__':
    unittest.main()
