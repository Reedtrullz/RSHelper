import copy
import math
import time
from datetime import datetime,timezone

from rshelper import persistence,profile as profiles,state_identity,state_transaction

FILENAME='trade-reviews.json'

def authority_origin(activation):
    if not activation:raise ValueError('identified review authority required')
    if activation.get('financial_authority') is True:return activation['origin_uuid']
    if activation.get('paper_budget_origin'):return activation['paper_budget_origin']
    candidates=set(activation.get('replication_origins',[]))-{activation['origin_uuid']}
    if len(candidates)!=1:raise ValueError('review financial authority ambiguous')
    return next(iter(candidates))

def _entry(value):
    if not isinstance(value,dict) or set(value)!={'hypothesis','planned_exit','tags','review','deleted'}:
        raise ValueError('review fields differ')
    for key in ('hypothesis','planned_exit','review'):
        if not isinstance(value[key],str) or len(value[key].encode())>8192:raise ValueError('review text exceeds limit')
    tags=value['tags']
    if (not isinstance(tags,list) or len(tags)>20 or any(not isinstance(tag,str) or not tag or tag!=tag.strip() or any(ord(char)<32 for char in tag) or len(tag.encode())>64 for tag in tags)
            or len(set(tags))!=len(tags) or type(value['deleted']) is not bool):raise ValueError('invalid review tags or deletion marker')
    return value

def validate_store(store):
    if not isinstance(store,dict) or set(store)!={'schema_version','authority_origin','revision','entries'} or type(store['schema_version']) is not int or store['schema_version']!=1:
        raise ValueError('invalid review store')
    entries=store['entries'];revision=store['revision']
    if type(revision) is not int or revision<0 or not isinstance(entries,dict) or len(entries)!=revision or len(entries)>100000:
        raise ValueError('invalid review revision inventory')
    if store['authority_origin'] is not None:persistence.canonical_uuid(store['authority_origin'])
    if revision and store['authority_origin'] is None:raise ValueError('review authority is missing')
    ordinals=set()
    for operation,row in entries.items():
        persistence.canonical_uuid(operation)
        if not isinstance(row,dict) or set(row)!={'lot_uid','entry','revision','created_at','request_sha256'}:raise ValueError('invalid review receipt')
        persistence.canonical_uuid(row['lot_uid']);_entry(row['entry'])
        ordinal=row['revision']
        if type(ordinal) is not int or not 1<=ordinal<=revision or ordinal in ordinals:raise ValueError('invalid review ordinal')
        ordinals.add(ordinal)
        if not isinstance(row['created_at'],str) or len(row['created_at'])>64:raise ValueError('invalid review time')
        instant=datetime.fromisoformat(row['created_at'])
        if instant.utcoffset() is None or instant.astimezone(timezone.utc).isoformat()!=row['created_at']:
            raise ValueError('review time must be canonical UTC')
        expected=state_identity.request_hash({'lot_uid':row['lot_uid'],'entry':row['entry'],'expected_revision':ordinal-1})
        if row['request_sha256']!=expected:raise ValueError('review receipt fingerprint differs')
    return store

def require_successor(current,incoming):
    validate_store(current);validate_store(incoming)
    if current['revision'] and current['authority_origin']!=incoming['authority_origin']:
        raise ValueError('review authority differs')
    if any(incoming['entries'].get(operation)!=row for operation,row in current['entries'].items()):
        raise ValueError('review history cannot be discarded or rewritten')

def validate_peers(peers):
    from rshelper.state_replication import _information
    if (not isinstance(peers,dict) or set(peers)!={'schema_version','origins'} or type(peers['schema_version']) is not int or peers['schema_version']!=1 or not isinstance(peers['origins'],dict)):
        raise ValueError('invalid peer review inventory')
    for origin,information in peers['origins'].items():
        _information(information)
        if information['origin_uuid']!=origin:raise ValueError('peer source identity differs')
    return peers

def read_reviews(profile):
    root=profiles.resolve_config_path(FILENAME,profile).parent
    with state_transaction.profile_transaction(profile or 'default',root):
        current=persistence.read_state(root/FILENAME,'generic')
        if not current and not (root/FILENAME).exists():current={'schema_version':1,'authority_origin':None,'revision':0,'entries':{}}
        validate_store(current)
        peers=persistence.read_state(root/'peer-information.json','generic')
        if (root/'peer-information.json').exists():validate_peers(peers)
        candidates=[current]
        for origin,information in peers.get('origins',{}).items():
            value=information['files'].get(FILENAME)
            if value is not None:
                validate_store(value)
                if value['authority_origin']!=origin:raise ValueError('review source differs from authority')
                candidates.append(value)
        candidates.sort(key=lambda value:value['revision'])
        if candidates[-1]['revision'] and candidates[-1]['authority_origin']!=authority_origin(state_identity.activation_manifest(root/'identity-activation.json')):
            raise ValueError('review source differs from financial authority')
        for before,after in zip(candidates,candidates[1:]):require_successor(before,after)
        return copy.deepcopy(candidates[-1])

def latest_reviews(store):
    validate_store(store)
    latest={}
    for row in sorted(store['entries'].values(),key=lambda row:row['revision']):latest[row['lot_uid']]=row
    return latest

def append_review(profile,lot_uid,entry,*,operation_id,expected_revision,now=None):
    persistence.canonical_uuid(lot_uid);persistence.canonical_uuid(operation_id);_entry(entry)
    if type(expected_revision) is not int or expected_revision<0:raise ValueError('expected review revision required')
    now=time.time() if now is None else now
    if type(now) not in (int,float) or not math.isfinite(now) or now<0:raise ValueError('invalid review time')
    root=profiles.resolve_config_path(FILENAME,profile).parent
    request=state_identity.request_hash({'lot_uid':lot_uid,'entry':entry,'expected_revision':expected_revision})
    with state_transaction.profile_transaction(profile or 'default',root) as txn:
        manifest=state_identity.activation_manifest(root/'identity-activation.json')
        state_identity.require_financial_authority(manifest)
        store=read_reviews(profile)
        known=store['entries'].get(operation_id)
        if known:
            if known['request_sha256']!=request:raise ValueError('review operation reused with different request')
            return {'revision':known['revision'],'current_revision':store['revision'],'operation_id':operation_id,'retry':True}
        if store['revision']!=expected_revision:raise ValueError('review revision changed; reload')
        if store['authority_origin'] not in (None,manifest['origin_uuid']):raise ValueError('review authority differs')
        positions=persistence.read_state(root/'positions.json','positions')
        trades=persistence.read_state(root/'trades.json','trades')
        state_identity.validate_activated_store(positions,'positions',root/'positions.json')
        state_identity.validate_activated_store(trades,'trades',root/'trades.json')
        if not (any(row.get('lot_uid')==lot_uid for row in positions['positions']) or
                any(not row.get('tombstone') and row.get('closed_lot_uid')==lot_uid for row in trades['trades'])):
            raise ValueError('unknown stable lot identity')
        store['authority_origin']=manifest['origin_uuid'];store['revision']+=1
        store['entries'][operation_id]={'lot_uid':lot_uid,'entry':copy.deepcopy(entry),'revision':store['revision'],
            'created_at':datetime.fromtimestamp(now,timezone.utc).isoformat(),'request_sha256':request}
        validate_store(store);txn.stage(FILENAME,store);txn.commit(operation_id=operation_id)
        return {'revision':store['revision'],'current_revision':store['revision'],'operation_id':operation_id,'retry':False}

def review_queue(profile,trades=None,*,tag='',unreviewed=False,limit=50,note='',strategy=''):
    if not isinstance(tag,str) or len(tag.encode())>64 or type(unreviewed) is not bool or type(limit) is not int or not 1<=limit<=200:
        raise ValueError('invalid review queue filters')
    if not isinstance(note,str) or len(note.encode())>4096 or strategy not in ('','auto','manual'):raise ValueError('invalid legacy review filter')
    if trades is None:
        from rshelper.journal import list_trades
        trades=list_trades(profile=profile,note=note,strategy=strategy)
    store=read_reviews(profile);latest=latest_reviews(store);rows=[]
    for trade in trades:
        row=latest.get(trade.closed_lot_uid)
        entry=row['entry'] if row and not row['entry']['deleted'] else None
        reviewed=bool(entry and entry['review'].strip())
        if tag and (entry is None or tag not in entry['tags']):continue
        if unreviewed and reviewed:continue
        rows.append({'record_uuid':trade.record_uuid,'lot_uid':trade.closed_lot_uid,'profit':trade.profit,
                     'reviewed':reviewed,'annotation':entry,'attribution_known':trade.closed_lot_uid is not None})
    return {'revision':store['revision'],'trades':rows[:limit],'sample_count':len(rows),'lot_count':len({row['lot_uid'] for row in rows if row['lot_uid']}),'reviewed_count':sum(row['reviewed'] for row in rows),
            'missing_hypothesis_count':sum(not row['annotation'] or not row['annotation']['hypothesis'].strip() for row in rows),
            'filters':{'tag':tag,'unreviewed':unreviewed,'note':note,'strategy':strategy},'legacy_note_compatibility':'Exact note and strategy filters remain unchanged.'}

def review_detail(profile,lot_uid):
    persistence.canonical_uuid(lot_uid)
    store=read_reviews(profile)
    history=[{'operation_id':operation,**row} for operation,row in store['entries'].items() if row['lot_uid']==lot_uid]
    history.sort(key=lambda row:row['revision'])
    return {'lot_uid':lot_uid,'revision':store['revision'],'history':history[-50:],'history_count':len(history),
            'annotation':history[-1]['entry'] if history else None}
