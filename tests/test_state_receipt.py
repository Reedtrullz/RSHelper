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
