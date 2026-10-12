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
    if path=='/api/reviews':
        from rshelper.persistence import canonical_uuid
        fields={'queue':{'tag','unreviewed','note','strategy','limit'},'append':{'lot_uid','entry','expected_revision','operation_id'}}
        action(fields)
        if set(body)!={'action'}|fields[body['action']]:raise HttpInputError('Review action fields differ')
        if body['action']=='append':
            from rshelper.trade_reviews import _entry
            try:canonical_uuid(body['lot_uid']);canonical_uuid(body['operation_id']);_entry(body['entry'])
            except (ValueError,TypeError) as error:raise HttpInputError('Invalid review fields') from error
            positive_int(body['expected_revision'],'expected_revision',minimum=0)
        else:
            text(body['tag'],'tag',required=False,limit=64);text(body['note'],'note',required=False,limit=4096)
            if type(body['unreviewed']) is not bool or body['strategy'] not in ('','auto','manual'):raise HttpInputError('Invalid review filter')
            positive_int(body['limit'],'limit')
            if body['limit']>200:raise HttpInputError('Review limit exceeds 200')
    elif path == '/api/settings':
        from rshelper.persistence import canonical_uuid
        fields={'preview':{'candidate'},'apply':{'candidate','expected_revision','operation_id','backup_path'},
                'rollback':{'restore_operation_id','expected_revision','operation_id','backup_path'}}
        action(fields)
        if set(body)!={'action'}|fields[body['action']]:raise HttpInputError('Settings action fields differ')
        if 'candidate' in body:text(body['candidate'],'candidate',required=False,limit=65536)
        for key in ('operation_id','restore_operation_id'):
            if key in body:
                try:canonical_uuid(body[key])
                except ValueError as exc:raise HttpInputError('Invalid '+key) from exc
        if 'expected_revision' in body:
            text(body['expected_revision'],'expected_revision',limit=100)
            text(body['backup_path'],'backup_path',limit=4096)
    elif path == '/api/paper':
        from rshelper.persistence import canonical_uuid
        fields={'open':{'item','qty'},'roundtrip':{'item','qty'},
                'advance':{'offer_id'},'cancel-buy':{'offer_id'},'cancel-sale':{'offer_id'},
                'collect':{'offer_id'},'start-sale':{'offer_id','qty','sell_price'},
                'adopt':{'lot_uid'},'queue-sale':{'position_id','qty'}}
        action(fields)
        if set(body)!={'action','operation_id','expected_revision'}|fields[body['action']]:
            raise HttpInputError('Paper action fields differ')
        for key in ('operation_id','offer_id','lot_uid'):
            if key in body:
                try:canonical_uuid(body[key])
                except ValueError as exc:raise HttpInputError('Invalid '+key) from exc
        positive_int(body['expected_revision'],'expected_revision')
        if 'item' in body:text(body['item'],'item',limit=200)
        for key in ('qty','sell_price','position_id'):
            if key in body and not (key=='qty' and body['action']=='queue-sale' and body[key] is None):
                positive_int(body[key],key)
    elif path == '/api/watchlist':
        action(('add', 'remove', 'alerts')); positive_int(body.get('item_id'), 'item_id')
        for key in ('alert_above', 'alert_below'):
            if body.get(key) is not None: positive_int(body[key], key, minimum=0)
    elif path in ('/api/ge/collect', '/api/positions'):
        positive_int(body.get('position_id'), 'position_id')
        if path == '/api/positions':
            action(('close',))
            if body.get('qty') is not None: positive_int(body['qty'], 'qty')
            if body.get('operation_id') is not None:
                text(body['operation_id'], 'operation_id', limit=64)
    elif path == '/api/trader':
        action(('start','stop','mode'))
        if body['action'] == 'mode':
            if body.get('mode') not in ('running','entries-paused','draining'):
                raise HttpInputError('Unknown trading stance')
            positive_int(body.get('expected_revision'),'expected_revision',minimum=0)
            text(body.get('reason'),'reason',limit=500)
            text(body.get('operation_id'),'operation_id',limit=64)
            from rshelper.persistence import canonical_uuid
            try:
                canonical_uuid(body['operation_id'])
            except ValueError as error:
                raise HttpInputError('Invalid stance operation identity') from error
    elif path == '/api/monitor':
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
    if route=='/api/reviews':
        from rshelper.persistence import canonical_uuid
        if set(values)-{'lot_uid'}:raise HttpInputError('Unknown review query field')
        if 'lot_uid' in values:
            try:canonical_uuid(values['lot_uid'][0])
            except ValueError as error:raise HttpInputError('Invalid review lot identity') from error
    if route == '/api/state/receipt':
        from rshelper.persistence import canonical_uuid
        if set(values) != {'origin'}:
            raise HttpInputError('Exactly one origin UUID is required')
        try:
            canonical_uuid(values['origin'][0])
        except ValueError as exc:
            raise HttpInputError('Invalid origin UUID') from exc
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
