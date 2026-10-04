"""Small endpoint-specific validation before providers can replace caches."""
import math
from rshelper.market import quote_time_issue

MAX_INTEGER = 2 ** 63 - 1  # Serialization/ranking engineering limit, not a game rule.


class MarketDataError(ValueError):
    pass


def _number(value, *, optional=False):
    if value is None:
        return optional
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and 0 <= value <= MAX_INTEGER and math.isfinite(value))


def _identifier(value):
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return 0 < value <= MAX_INTEGER
    return (isinstance(value, str) and 1 <= len(value) <= 19 and value.isascii()
            and value.isdigit() and str(int(value)) == value and 0 < int(value) <= MAX_INTEGER)


def _row(endpoint, row, now):
    if not isinstance(row, dict):
        return False
    if endpoint == 'mapping':
        return (_identifier(row.get('id')) and isinstance(row.get('name'), str)
                and bool(row['name'].strip())
                and isinstance(row.get('members', False), bool)
                and all(_number(row.get(key), optional=True) for key in ('limit', 'highalch', 'lowalch')))
    if endpoint == 'latest':
        if not all(key in row for key in ('high', 'low')):
            return False
        if not all(_number(row.get(key), optional=True) for key in ('high', 'low', 'high_volume', 'low_volume')):
            return False
        for key in ('highTime', 'lowTime'):
            value = row.get(key)
            if value is not None and quote_time_issue(value, now):
                return False
        return True
    if endpoint in ('5m', 'timeseries'):
        if not all(_number(row.get(key), optional=True) for key in
                   ('avgHighPrice', 'avgLowPrice', 'highPriceVolume', 'lowPriceVolume')):
            return False
        if not any(key in row for key in ('avgHighPrice', 'avgLowPrice', 'highPriceVolume', 'lowPriceVolume')):
            return False
        return endpoint != 'timeseries' or quote_time_issue(row.get('timestamp'), now) is None
    if endpoint == 'ge_tracker':
        return (_identifier(row.get('itemId'))
                and isinstance(row.get('name', ''), str)
                and isinstance(row.get('members', False), bool)
                and all(_number(row.get(key), optional=True) for key in
                        ('buying', 'selling', 'buyingQuantity', 'sellingQuantity', 'buyLimit', 'highAlch', 'lowAlch')))
    raise MarketDataError('unknown market endpoint')


def validate_payload(endpoint: str, payload: object, now: float) -> dict:
    data = payload.get('data', payload) if isinstance(payload, dict) else payload
    sequence = endpoint in ('mapping', 'timeseries', 'ge_tracker')
    expected = list if sequence else dict
    if not isinstance(data, expected):
        raise MarketDataError(f'{endpoint}: invalid root shape')
    valid = [] if sequence else {}
    rejected = 0
    rows = enumerate(data) if sequence else data.items()
    for key, row in rows:
        if (sequence or _identifier(key)) and _row(endpoint, row, now):
            if sequence:
                valid.append(row)
            else:
                valid[str(key)] = row
        else:
            rejected += 1
    return {'data': valid, 'rejected': rejected}
