"""Run inside the owner container; emit a sanitized private-state receipt."""
import json
from pathlib import Path
import urllib.request

from rshelper.dashboard.owner_token import _read_token

MAX_RECEIPT_BYTES = 64 * 1024 * 1024


def private_state_receipt(credential=Path('/home/rshelper/.config/rshelper/owner.token'),
                          url='http://127.0.0.1:5555/api/trades'):
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
    if (not isinstance(payload, dict) or not isinstance(payload.get('trades'), list)
            or type(payload.get('count')) is not int or payload['count'] < 0):
        raise ValueError('private state receipt has an invalid shape')
    return {'authenticated': True, 'private_shape_valid': True}


if __name__ == '__main__':
    print(json.dumps(private_state_receipt()))
