import copy
import csv
import hashlib
import io
from datetime import datetime,timezone

from rshelper import persistence,profile as profiles,state_identity,state_transaction
from rshelper.trade_reviews import authority_origin

FILENAME='observed-offers.json'
FIELDS={'state','item_id','side','qty','limit_price','filled_qty','collected_qty','actual_gp','fees','observed_at','source','evidence','corrects'}
CSV_FIELDS=['offer_uuid','operation_id','expected_revision',*sorted(FIELDS)]

def validate_event(event):
    if not isinstance(event,dict) or set(event)!=FIELDS:raise ValueError('observed event fields differ')
    if event['state'] not in ('planned','placed','partial','canceled','collected') or event['side'] not in ('buy','sell'):
        raise ValueError('invalid observed offer state or side')
    for key in ('item_id','qty','limit_price','filled_qty','collected_qty','actual_gp','fees'):
        if type(event[key]) is not int or not 0<=event[key]<2**63:raise ValueError('bounded whole observed amounts required')
    if min(event['item_id'],event['qty'],event['limit_price'])<=0 or event['qty']*event['limit_price']>=2**63:
        raise ValueError('positive bounded observed order required')
    if not 0<=event['collected_qty']<=event['filled_qty']<=event['qty']:raise ValueError('observed quantities do not reconcile')
    if bool(event['filled_qty'])!=bool(event['actual_gp']) or event['fees']>event['actual_gp']:
        raise ValueError('observed fills require actual cumulative GP and bounded fees')
    if event['side']=='buy' and event['fees']:raise ValueError('buy receipts do not pay sell tax')
    if event['filled_qty'] and ((event['side']=='buy' and event['actual_gp']>event['filled_qty']*event['limit_price']) or (event['side']=='sell' and event['actual_gp']<event['filled_qty']*event['limit_price'])):
        raise ValueError('actual cumulative GP contradicts original offer price')
    if event['state'] in ('planned','placed') and any(event[key] for key in ('filled_qty','collected_qty','actual_gp','fees')):
        raise ValueError('unfilled order cannot contain actual fills')
    if event['state']=='partial' and not event['filled_qty']:raise ValueError('partial receipt requires a fill')
    if event['state']=='collected' and event['collected_qty']!=event['filled_qty']:raise ValueError('collection must reconcile all recorded fills')
    if event['state']!='collected' and event['collected_qty']:raise ValueError('only collection can contain collected units')
    if event['source'] not in ('manual','csv'):raise ValueError('observed source must be explicit manual or CSV evidence')
    if not isinstance(event['evidence'],str) or not event['evidence'].strip() or len(event['evidence'].encode())>4096:
        raise ValueError('bounded observed evidence required')
    if not isinstance(event['observed_at'],str) or len(event['observed_at'])>64:raise ValueError('invalid observation time')
    instant=datetime.fromisoformat(event['observed_at'])
    if instant.utcoffset() is None or instant.astimezone(timezone.utc).isoformat()!=event['observed_at']:
        raise ValueError('canonical UTC observation time required')
    if event['corrects'] is not None:persistence.canonical_uuid(event['corrects'])
    return event

def _transition(before,event):
    if before is None:
        if event['state']!='planned' or event['corrects'] is not None:raise ValueError('first observation must be planned')
        return
    previous=before['event']
    if any(previous[key]!=event[key] for key in ('item_id','side','qty','limit_price')):
        raise ValueError('offer identity and original reservation cannot change')
    if event['observed_at']<previous['observed_at']:raise ValueError('observation time moved backwards')
    if event['corrects'] is not None:
        if event['corrects']!=before['operation_id'] or event['state']!=previous['state']:
            raise ValueError('correction must name the latest receipt in the same phase')
        return
    allowed={'planned':('placed','canceled'),'placed':('partial','canceled'),
             'partial':('partial','canceled','collected'),'canceled':('collected',),'collected':()}
    if event['state'] not in allowed[previous['state']]:raise ValueError('invalid observed state transition')
    if previous['state']=='planned' and event['filled_qty']:raise ValueError('unplaced offer cannot have actual fills')
    if any(event[key]<previous[key] for key in ('filled_qty','actual_gp','fees')):raise ValueError('cumulative receipt moved backwards; append a correction')
    if previous['state']=='canceled' and any(event[key]!=previous[key] for key in ('filled_qty','actual_gp','fees')):
        raise ValueError('canceled offer cannot add fills during collection')
    if event['state']=='collected' and previous['state']!='canceled' and event['filled_qty']!=event['qty']:
        raise ValueError('cancel unfilled remainder before collection')

def empty_store():return {'schema_version':1,'authority_origin':None,'revision':0,'entries':{}}

def validate_store(store):
    if not isinstance(store,dict) or set(store)!={'schema_version','authority_origin','revision','entries'} or type(store['schema_version']) is not int or store['schema_version']!=1:
        raise ValueError('invalid observed store')
    revision=store['revision'];entries=store['entries']
    if type(revision) is not int or revision<0 or not isinstance(entries,dict) or len(entries)!=revision or revision>10000:
        raise ValueError('observed revision inventory exceeds bound')
    if store['authority_origin'] is not None:persistence.canonical_uuid(store['authority_origin'])
    if revision and store['authority_origin'] is None:raise ValueError('observed authority missing')
    for operation,row in entries.items():
        persistence.canonical_uuid(operation)
        if not isinstance(row,dict) or set(row)!={'offer_uuid','event','revision','request_sha256'}:raise ValueError('invalid observed receipt')
        persistence.canonical_uuid(row['offer_uuid']);validate_event(row['event'])
        if type(row['revision']) is not int or not 1<=row['revision']<=revision:raise ValueError('invalid observed ordinal')
        expected=state_identity.request_hash({'offer_uuid':row['offer_uuid'],'event':row['event'],'expected_revision':row['revision']-1})
        if row['request_sha256']!=expected:raise ValueError('observed request fingerprint differs')
    latest={}
    for ordinal,(operation,row) in enumerate(sorted(entries.items(),key=lambda pair:pair[1]['revision']),1):
        if row['revision']!=ordinal:raise ValueError('duplicate observed ordinal')
        _transition(latest.get(row['offer_uuid']),row['event'])
        latest[row['offer_uuid']]={**row,'operation_id':operation}
    return store

def latest_offers(store):
    validate_store(store);latest={}
    for operation,row in sorted(store['entries'].items(),key=lambda pair:pair[1]['revision']):
        latest[row['offer_uuid']]={**copy.deepcopy(row),'operation_id':operation}
    return latest

def require_successor(current,incoming):
    validate_store(current);validate_store(incoming)
    if current['revision'] and current['authority_origin']!=incoming['authority_origin']:raise ValueError('observed authority differs')
    if any(incoming['entries'].get(operation)!=row for operation,row in current['entries'].items()):
        raise ValueError('observed history cannot be discarded or rewritten')

def read_store(profile):
    root=profiles.resolve_config_path('',profile)
    with state_transaction.profile_transaction(profile or 'default',root):
        return _read_root(root)

def _read_root(root):
    store=persistence.read_state(root/FILENAME,'generic')
    activation=state_identity.activation_manifest(root/'identity-activation.json')
    if not (root/FILENAME).exists():
        if activation and activation.get('observed_offer_origin') is not None:raise ValueError('acknowledged observed ledger missing; backup recovery required')
        store=empty_store()
    validate_store(store)
    acknowledged=(activation or {}).get('observed_offer_origin')
    if acknowledged is not None and (acknowledged!=authority_origin(activation) or not store['revision']):
        raise ValueError('acknowledged observed authority or history differs')
    if store['revision'] and store['authority_origin']!=authority_origin(activation):raise ValueError('observed source differs from financial authority')
    return store

def _append(store,offer_uuid,event,operation_id,expected_revision,origin):
    persistence.canonical_uuid(offer_uuid);persistence.canonical_uuid(operation_id);validate_event(event)
    if type(expected_revision) is not int or expected_revision<0:raise ValueError('expected observed revision required')
    request=state_identity.request_hash({'offer_uuid':offer_uuid,'event':event,'expected_revision':expected_revision})
    known=store['entries'].get(operation_id)
    if known:
        if known['request_sha256']!=request:raise ValueError('observed operation reused with different request')
        return {'revision':known['revision'],'current_revision':store['revision'],'operation_id':operation_id,'retry':True}
    if store['revision']!=expected_revision:raise ValueError('observed revision changed; reload')
    if store['authority_origin'] not in (None,origin):raise ValueError('observed authority differs')
    _transition(latest_offers(store).get(offer_uuid),event)
    store['authority_origin']=origin;store['revision']+=1
    store['entries'][operation_id]={'offer_uuid':offer_uuid,'event':copy.deepcopy(event),'revision':store['revision'],'request_sha256':request}
    validate_store(store)
    return {'revision':store['revision'],'current_revision':store['revision'],'operation_id':operation_id,'retry':False}

def record_observation(profile,offer_uuid,event,*,operation_id,expected_revision):
    root=profiles.resolve_config_path('',profile)
    with state_transaction.profile_transaction(profile or 'default',root) as txn:
        activation=state_identity.activation_manifest(root/'identity-activation.json');state_identity.require_financial_authority(activation)
        if activation is None:raise ValueError('observed authority required')
        store=read_store(profile);result=_append(store,offer_uuid,event,operation_id,expected_revision,activation['origin_uuid'])
        if not result['retry']:
            txn.stage(FILENAME,store)
            txn.stage('identity-activation.json',{**activation,'observed_offer_origin':activation['origin_uuid']})
            txn.commit(operation_id=operation_id)
        return result

def summary(store,*,slot_limit=None):
    if slot_limit is not None and (type(slot_limit) is not int or slot_limit not in (3,8)):raise ValueError('observed slot capacity unknown/free/member only')
    rows=list(latest_offers(store).values());reserved=0;used=0;cash_flow=0;inventory={}
    placed={row['offer_uuid'] for row in store['entries'].values() if row['event']['state'] in ('placed','partial')}
    for row in rows:
        event=row['event'];phase=event['state'];side=event['side']
        if phase!='collected' and row['offer_uuid'] in placed:used+=1
        if phase in ('placed','partial'):
            remaining=event['qty']-event['filled_qty']
            if side=='buy':reserved+=remaining*event['limit_price']
            else:inventory[str(event['item_id'])]=inventory.get(str(event['item_id']),0)+remaining
        cash_flow+=-event['actual_gp'] if side=='buy' else event['actual_gp']-event['fees']
    if max(reserved,abs(cash_flow))>=2**63:raise ValueError('observed aggregate exceeds monetary bound')
    return {'lane':'observed-manual','revision':store['revision'],'offer_count':len(rows),'used_slots':used,
            'slot_limit':slot_limit,'available_slots':max(0,slot_limit-used) if slot_limit is not None else None,
            'reserved_cash':reserved,'reserved_inventory':inventory,'actual_cash_flow':cash_flow,
            'available_cash':None,'realized_profit':None,
            'unknown':['Game account balance and complete inventory not observed','Cash flow is not realized profit','Purchase-window history completeness unknown'],
            'offers':rows[:100],'total_offers':len(rows),'sensitivity':'private'}

def import_csv(profile,raw,*,known_items,apply=False,expected_import_hash=None,backup_path=None):
    from pathlib import Path
    from rshelper import backup
    if not isinstance(raw,bytes) or not 0<len(raw)<=65536 or type(apply) is not bool:raise ValueError('bounded observed CSV required')
    reader=csv.DictReader(io.StringIO(raw.decode('utf-8'),newline=''),strict=True)
    if reader.fieldnames!=CSV_FIELDS:raise ValueError('observed CSV header differs')
    requests=[]
    try:
        for row in reader:
            if set(row)!=set(CSV_FIELDS) or None in row.values() or len(requests)>=200:raise ValueError('observed CSV row inventory differs')
            offer=row.pop('offer_uuid');operation=row.pop('operation_id');revision=row.pop('expected_revision')
            for key in ('item_id','qty','limit_price','filled_qty','collected_qty','actual_gp','fees'):
                if not row[key].isascii() or not row[key].isdigit():raise ValueError('CSV amount must be nonnegative whole decimal')
                row[key]=int(row[key])
            if not revision.isascii() or not revision.isdigit():raise ValueError('CSV revision must be whole decimal')
            row['corrects']=row['corrects'] or None
            if row['source']!='csv':raise ValueError('CSV receipts must declare CSV provenance')
            validate_event(row);persistence.canonical_uuid(offer);persistence.canonical_uuid(operation)
            requests.append((offer,row,operation,int(revision)))
    except csv.Error as error:raise ValueError('invalid observed CSV') from error
    if not requests or len({request[2] for request in requests})!=len(requests):raise ValueError('nonempty unique CSV operation inventory required')
    root=profiles.resolve_config_path('',profile)
    with state_transaction.profile_transaction(profile or 'default',root) as txn:
        activation=state_identity.activation_manifest(root/'identity-activation.json')
        if activation is None:raise ValueError('identified CSV profile required')
        persistence.canonical_uuid(activation.get('profile_uuid'))
        if apply:state_identity.require_financial_authority(activation)
        current=read_store(profile);staged=copy.deepcopy(current)
        unknown=sorted({request[1]['item_id'] for request in requests}-set(known_items))
        receipts=[];conflicts=[]
        for index,(offer,event,operation,revision) in enumerate(requests,1):
            try:receipts.append(_append(staged,offer,event,operation,revision,authority_origin(activation)))
            except ValueError as error:
                conflicts.append({'row':index,'reason':str(error)})
                break
        import_hash=state_identity.request_hash({'profile_uuid':activation['profile_uuid'],'current':current,'csv_sha256':hashlib.sha256(raw).hexdigest()})
        result={'status':'preview','sensitivity':'private','valid':not unknown and not conflicts,'unknown_item_ids':unknown,'conflicts':conflicts,
                'profile_uuid':activation['profile_uuid'],'revision':current['revision'],'proposed_revision':staged['revision'],
                'import_hash':import_hash,'row_count':len(requests),'retry':not conflicts and all(receipt['retry'] for receipt in receipts)}
        if not apply:return result
        if unknown:raise ValueError('CSV contains unknown item IDs; refresh mapping and preview')
        if conflicts:raise ValueError('CSV conflicts with acknowledged history; correct and preview')
        if result['retry']:return {**result,'status':'applied'}
        if expected_import_hash!=import_hash or backup_path is None:raise ValueError('exact CSV preview hash and new pre-apply backup required')
        backup.export_profile(profile,Path(backup_path));backup._inspect(Path(backup_path))
        txn.stage(FILENAME,staged);txn.stage('identity-activation.json',{**activation,'observed_offer_origin':activation['origin_uuid']})
        txn.commit(operation_id=requests[-1][2])
        return {**result,'status':'applied','revision':staged['revision'],'backup':str(Path(backup_path).absolute())}
