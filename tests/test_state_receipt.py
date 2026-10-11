"""Private sync proof keeps credentials and record counts out of public logs."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))

class TestPrivateStateReceipt(unittest.TestCase):
    def test_real_http_owner_receipt_requires_auth_and_exact_durable_hash(self):
        import threading
        import urllib.error
        from http.server import ThreadingHTTPServer
        from rshelper.dashboard.handlers import make_handler
        expected = {'profile_uuid': '11111111-1111-4111-8111-111111111111',
                    'origin_uuid': '22222222-2222-4222-8222-222222222222',
                    'requested_revision': 3, 'requested_hash': 'c' * 64}
        receipt = {'schema_version': 1, 'status': 'applied', **expected,
                   'applied_revision': 3, 'applied_hash': 'c' * 64}
        calls = []
        from rshelper import profile, state_replication, state_transaction
        root = Path(self.tmp.name) / 'config'
        with state_transaction.profile_transaction('default', root) as txn:
            txn.stage('replication-state.json', {'schema_version': 1,
                      'receipts': {expected['origin_uuid']: receipt}, 'outgoing': None})
            txn.commit(expected['origin_uuid'])
        def read(origin):
            calls.append(origin)
            with mock.patch.object(profile, 'CONFIG_DIR', root):
                return state_replication.read_receipt('default', origin)
        handler = make_handler(None, lambda: [], mode='owner', owner_token='a' * 64,
                               state_receipt_fn=read)
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f'http://127.0.0.1:{server.server_port}/api/state/receipt?origin={expected["origin_uuid"]}'
            with self.assertRaises(urllib.error.HTTPError) as denied:
                self.module.urllib.request.urlopen(url, timeout=2)
            self.assertEqual(denied.exception.code, 401)
            denied.exception.close()
            self.assertEqual(calls, [])
            self.assertEqual(self.module.private_state_receipt(self.token, url, expected=expected), receipt)
            self.assertEqual(calls, [expected['origin_uuid']])
            with self.assertRaises(ValueError):
                self.module.private_state_receipt(self.token, url, expected={**expected, 'requested_hash': 'd' * 64})
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)
    def test_exact_receipt_requires_matching_durable_revision_hash_and_origin(self):
        expected = {'profile_uuid': '11111111-1111-4111-8111-111111111111',
                    'origin_uuid': '22222222-2222-4222-8222-222222222222',
                    'requested_revision': 3, 'requested_hash': 'c' * 64}
        receipt = {'schema_version': 1, 'status': 'applied', **expected,
                   'applied_revision': 3, 'applied_hash': 'c' * 64}
        with mock.patch.object(self.module.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(receipt).encode())):
            self.assertEqual(self.module.private_state_receipt(self.token, expected=expected), receipt)
        for field, bad in (('origin_uuid', expected['profile_uuid']), ('applied_revision', 2),
                           ('applied_hash', 'd' * 64), ('status', 'conflict')):
            wrong = {**receipt, field: bad}
            with self.subTest(field=field), mock.patch.object(self.module.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(wrong).encode())):
                with self.assertRaises(ValueError):
                    self.module.private_state_receipt(self.token, expected=expected)

    def setUp(self):
        path=Path(__file__).resolve().parents[1]/'deploy/check_state.py'
        spec=importlib.util.spec_from_file_location('state_receipt',path)
        self.module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.token=Path(self.tmp.name).resolve()/'owner.token'
        self.token.write_text('a'*64+'\n');self.token.chmod(0o600)

    def test_authenticated_shape_receipt_discloses_no_records_count_or_token(self):
        response=io.BytesIO(json.dumps({'trades':[{'name':'PRIVATE RECORD'}],'count':987}).encode())
        with mock.patch.object(self.module.urllib.request,'urlopen',return_value=response) as open_url:
            proof=self.module.private_state_receipt(self.token)
        headers=dict(open_url.call_args.args[0].header_items())
        self.assertEqual(headers['Authorization'],'Bearer '+'a'*64)
        self.assertEqual(proof,{'authenticated':True,'private_shape_valid':True})
        encoded=json.dumps(proof)
        for private in ('PRIVATE RECORD','987','a'*64):self.assertNotIn(private,encoded)

    def test_invalid_credential_prevents_http_request_and_preserves_file(self):
        before=self.token.read_bytes();self.token.chmod(0o644)
        with mock.patch.object(self.module.urllib.request,'urlopen') as fetch:
            with self.assertRaises(ValueError):self.module.private_state_receipt(self.token)
        fetch.assert_not_called();self.assertEqual(self.token.read_bytes(),before)

    def test_missing_credential_is_never_provisioned_by_receipt(self):
        self.token.unlink()
        with mock.patch.object(self.module.urllib.request,'urlopen') as fetch:
            with self.assertRaises(FileNotFoundError):self.module.private_state_receipt(self.token)
        fetch.assert_not_called();self.assertFalse(self.token.exists())

    def test_wrong_or_oversized_response_cannot_report_success(self):
        for payload in ({'trades':[],'count':True},[],{'trades':{},'count':0},
                        {'trades':[]}, {'trades':[],'count':0.0}):
            with mock.patch.object(self.module.urllib.request,'urlopen',return_value=io.BytesIO(json.dumps(payload).encode())):
                with self.assertRaises(ValueError):self.module.private_state_receipt(self.token)
        with mock.patch.object(self.module.urllib.request,'urlopen',return_value=io.BytesIO(b' '*65)):
            with mock.patch.object(self.module,'MAX_RECEIPT_BYTES',64):
                with self.assertRaises(ValueError):self.module.private_state_receipt(self.token)
        valid=json.dumps({'trades':[],'count':0}).encode()
        with mock.patch.object(self.module.urllib.request,'urlopen',return_value=io.BytesIO(valid)), \
             mock.patch.object(self.module,'MAX_RECEIPT_BYTES',len(valid)):
            self.assertTrue(self.module.private_state_receipt(self.token)['private_shape_valid'])

if __name__=='__main__':unittest.main()
