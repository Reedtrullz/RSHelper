"""Small endpoint-specific validation before providers can replace caches."""
import math
import time
from rshelper.market import quote_time_issue

MAX_INTEGER = 2 ** 63 - 1  # Serialization/ranking engineering limit, not a game rule.


class MarketDataError(ValueError):
    pass

TIMESTEPS = {'5m':300,'1h':3600,'6h':21600,'24h':86400}

def normalize_candles(rows, timestep, *, now=None) -> dict:
    if not isinstance(timestep,str) or timestep not in TIMESTEPS or not isinstance(rows,list):
        raise MarketDataError('candles require a supported timestep and a sequence')
    seconds = TIMESTEPS[timestep]
    now = time.time() if now is None else now
    by_time, counts, conflicts = {}, {}, set()
    rejected = 0
    keys = ('timestamp','avgHighPrice','avgLowPrice','highPriceVolume','lowPriceVolume')
    for row in rows:
        if (not _row('timeseries',row,now) or type(row.get('timestamp')) is not int
                or row['timestamp'] > MAX_INTEGER):
            rejected += 1
            continue
        canonical = {key:row.get(key) for key in keys}
        timestamp = canonical['timestamp']
        counts[timestamp] = counts.get(timestamp,0) + 1
        if timestamp in by_time and by_time[timestamp] != canonical:
            conflicts.add(timestamp)
        else:
            by_time[timestamp] = canonical
    data = [by_time[timestamp] for timestamp in sorted(by_time) if timestamp not in conflicts]
    rejected += sum(counts[timestamp] for timestamp in conflicts)
    duplicates = sum(count-1 for timestamp,count in counts.items() if timestamp not in conflicts)
    times = [row['timestamp'] for row in data]
    intervals = [right-left for left,right in zip(times,times[1:])]
    span = times[-1]-times[0] if times else 0
    irregular = sum(delta % seconds != 0 for delta in intervals)
    expected = span//seconds+1 if times and not irregular else None
    coverage = {'timestep':timestep,'timestep_seconds':seconds,'samples':len(data),
                'first_timestamp':times[0] if times else None,'last_timestamp':times[-1] if times else None,
                'observed_span_seconds':span,'expected_windows':expected,
                'missing_windows':sum(max(0,delta//seconds-1) for delta in intervals),
                'gap_intervals':sum(delta > seconds for delta in intervals),
                'irregular_intervals':irregular,'rejected':rejected,'duplicates':duplicates,
                'conflicts':len(conflicts),'coverage_ratio':len(data)/expected if expected else None}
    return {'data':data,'coverage':coverage}


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
