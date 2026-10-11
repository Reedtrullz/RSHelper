"""Run inside the owner container; emit a sanitized private-state receipt."""
import json
import argparse
from pathlib import Path
import urllib.request
from urllib.parse import urlencode

from rshelper.dashboard.owner_token import _read_token

MAX_RECEIPT_BYTES = 64 * 1024 * 1024


def private_state_receipt(credential=Path('/home/rshelper/.config/rshelper/owner.token'),
                          url=None, *, expected=None):
    fields = {'profile_uuid', 'origin_uuid', 'requested_revision', 'requested_hash'}
    if expected is not None:
        from rshelper.persistence import canonical_uuid
        if not isinstance(expected, dict) or set(expected) != fields:
            raise ValueError('invalid expected private state identity')
        canonical_uuid(expected['origin_uuid'])
        canonical_uuid(expected['profile_uuid'])
    if url is None:
        url = ('http://127.0.0.1:5555/api/state/receipt?' + urlencode({'origin': expected['origin_uuid']})
               if expected is not None else 'http://127.0.0.1:5555/api/trades')
    token = _read_token(Path(credential))
    request = urllib.request.Request(url, headers={
        'Authorization': 'Bearer ' + token,
        'User-Agent': 'RSHelper private state receipt',
    })
    with urllib.request.urlopen(request, timeout=10) as response:
        raw = response.read(MAX_RECEIPT_BYTES + 1)
    if len(raw) > MAX_RECEIPT_BYTES:
        raise ValueError('private state receipt exceeds response budget')
    payload = json.loads(raw)
    if expected is not None:
        from rshelper.state_replication import _validate_receipt
        _validate_receipt(payload)
        if (not isinstance(expected, dict) or set(expected) != fields
                or payload['status'] not in ('applied', 'no_op')
                or any(payload[key] != value for key, value in expected.items())
                or type(expected['requested_revision']) is not int
                or payload['applied_revision'] != expected['requested_revision']
                or payload['applied_hash'] != expected['requested_hash']):
            raise ValueError('private state receipt does not match requested packet')
        return payload
    if (not isinstance(payload, dict) or not isinstance(payload.get('trades'), list)
            or type(payload.get('count')) is not int or payload['count'] < 0):
        raise ValueError('private state receipt has an invalid shape')
    return {'authenticated': True, 'private_shape_valid': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--expected-file', type=Path)
    args = parser.parse_args()
    expected = json.loads(args.expected_file.read_text()) if args.expected_file else None
    print(json.dumps(private_state_receipt(expected=expected)))
