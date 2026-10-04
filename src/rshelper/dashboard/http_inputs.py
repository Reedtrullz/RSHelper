"""Bounded dashboard input contracts; no state or provider access."""
import json
import math
from urllib.parse import parse_qs

MAX_BODY_BYTES = 65536
MAX_QUERY_BYTES = 4096
MAX_BATCH_IDS = 100


class HttpInputError(ValueError):
    def __init__(self, message, status=400, code='invalid_request'):
        super().__init__(message)
        self.status, self.code = status, code


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise HttpInputError('Duplicate JSON field')
        result[key] = value
    return result


def decode_object(raw):
    try:
        body = json.loads(raw, object_pairs_hook=_object,
            parse_constant=lambda value: (_ for _ in ()).throw(HttpInputError('Non-finite JSON number')))
        if not isinstance(body, dict): raise HttpInputError('JSON body must be an object')
        def check(value, depth=0):
            if depth > 64: raise HttpInputError('JSON nesting exceeds limit')
            if isinstance(value, float) and not math.isfinite(value):
                raise HttpInputError('Non-finite JSON number')
            if isinstance(value, dict):
                for child in value.values(): check(child, depth+1)
            elif isinstance(value, list):
                for child in value: check(child, depth+1)
        check(body)
        return body
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
        if isinstance(exc, HttpInputError): raise
        raise HttpInputError('Invalid JSON object') from exc


def positive_int(value, field, *, minimum=1):
    if type(value) is not int or value < minimum:
        raise HttpInputError(f'{field} must be an integer >= {minimum}')
    return value


def text(value, field, *, required=True, limit=256):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise HttpInputError(f'Invalid {field}')
    return value


def batch_ids(values):
    if not isinstance(values, list) or len(values) > MAX_BATCH_IDS:
        raise HttpInputError('IDs must be a list of at most 100 distinct positive integers')
    ids = [positive_int(value, 'ID') for value in values]
    if len(ids) != len(set(ids)): raise HttpInputError('Duplicate IDs')
    return ids


def validate_operation(path, body):
    def action(choices):
        if not isinstance(body.get('action'), str) or body['action'] not in choices:
            raise HttpInputError('Unknown action')
    if path == '/api/paper':
        action(('open', 'instant')); text(body.get('item'), 'item')
        positive_int(body.get('qty'), 'qty')
    elif path == '/api/watchlist':
        action(('add', 'remove', 'alerts')); positive_int(body.get('item_id'), 'item_id')
        for key in ('alert_above', 'alert_below'):
            if body.get(key) is not None: positive_int(body[key], key, minimum=0)
    elif path in ('/api/ge/collect', '/api/positions'):
        positive_int(body.get('position_id'), 'position_id')
        if path == '/api/positions':
            action(('close',))
            if body.get('qty') is not None: positive_int(body['qty'], 'qty')
    elif path in ('/api/trader', '/api/monitor'):
        action(('start', 'stop'))
    elif path == '/api/trades/delete':
        positive_int(body.get('trade_id'), 'trade_id')
    elif path == '/api/alerts/read':
        if 'all' in body and type(body['all']) is not bool: raise HttpInputError('all must be boolean')
        if body.get('ids') is not None: batch_ids(body['ids'])
    elif path == '/api/trades':
        for key in ('item_id', 'qty', 'buy_price', 'sell_price'):
            positive_int(body.get(key), key)
        text(body.get('name'), 'name')
        text(body.get('note', ''), 'note', required=False, limit=4096)
    return body


def parse_query(path):
    raw = path.partition('?')[2]
    if len(raw.encode('utf-8')) > MAX_QUERY_BYTES:
        raise HttpInputError('Query exceeds 4096-byte limit', 414, 'query_too_large')
    try: values = parse_qs(raw, keep_blank_values=True, max_num_fields=100)
    except ValueError as exc: raise HttpInputError('Too many query fields') from exc
    if any(len(rows) != 1 for rows in values.values()): raise HttpInputError('Duplicate query field')
    route = path.partition('?')[0]
    if route in ('/api/prices', '/api/confidence'):
        parts = values.get('ids', [''])[0].split(',')
        if parts == ['']: parts = []
        if any(not part.isascii() or not part.isdecimal() for part in parts):
            raise HttpInputError('IDs must be positive ASCII integers')
        # Check the count before integer conversion.
        if len(parts) > MAX_BATCH_IDS: raise HttpInputError('At most 100 IDs are allowed')
        try: batch_ids([int(part) for part in parts])
        except ValueError as exc: raise HttpInputError('Invalid IDs') from exc
    for field, low, high in (('points', 1, 1000), ('limit', 1, 200), ('ttl', 0, 60), ('id', 1, None)):
        if field in values:
            value = values[field][0]
            if not value.isascii() or not value.isdecimal(): raise HttpInputError(f'Invalid {field}')
            try: number = int(value)
            except ValueError as exc: raise HttpInputError(f'Invalid {field}') from exc
            if number < low or (high is not None and number > high): raise HttpInputError(f'Invalid {field}')
    if route == '/api/timeseries' and values.get('step', ['5m'])[0] not in ('5m', '1h', '6h', '24h'):
        raise HttpInputError('Invalid step')
    return values
