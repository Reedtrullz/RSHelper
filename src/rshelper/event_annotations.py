"""Reviewed context and private observations; never inputs to trading decisions."""
import copy
from datetime import datetime,timezone
import json
import re
from urllib.parse import urlsplit
from rshelper import persistence,profile
from rshelper.state_identity import request_hash

FILENAME='event-annotations.json'
MAX_RECORDS=500
MAX_BYTES=1024*1024
FIELDS={'id','start','end','type','item_ids','groups','class','title','uncertainty',
        'review_state','reviewed_at','reviewer','source_url'}

def _epoch(value):
    if type(value) is not int or not 0<value<=253402300799:raise ValueError('bounded UTC epoch seconds required')
    return value

def validate_annotation(row):
    if not isinstance(row,dict) or set(row)!=FIELDS:raise ValueError('annotation fields differ')
    if not isinstance(row['id'],str) or not re.fullmatch('[a-z0-9-]{1,80}',row['id']):raise ValueError('bounded event ID required')
    if _epoch(row['start'])>=_epoch(row['end']):raise ValueError('event interval must be nonempty and half-open')
    if row['type'] not in ('update','market-rule','availability','observation'):raise ValueError('unknown event type')
    if row['class'] not in ('reviewed-source','private-observation'):raise ValueError('unknown event class')
    for field,bound in (('title',500),('uncertainty',2000)):
        if not isinstance(row[field],str) or not 1<=len(row[field].encode())<=bound:raise ValueError('bounded event text required')
    for field in ('item_ids','groups'):
        if not isinstance(row[field],list) or len(row[field])>100:raise ValueError('bounded scope required')
    if any(type(i) is not int or i<=0 for i in row['item_ids']):raise ValueError('positive item scope required')
    if any(not isinstance(g,str) or not 1<=len(g.encode())<=128 for g in row['groups']):raise ValueError('bounded group scope required')
    if len(set(row['item_ids']))!=len(row['item_ids']) or len(set(row['groups']))!=len(row['groups']):raise ValueError('duplicate event scope')
    if row['review_state'] not in ('reviewed','unreviewed'):raise ValueError('unknown event review state')
    if row['review_state']=='reviewed':
        _epoch(row['reviewed_at'])
        if not isinstance(row['reviewer'],str) or not 1<=len(row['reviewer'].encode())<=128:raise ValueError('reviewer required')
        url=row['source_url'];parts=urlsplit(url) if isinstance(url,str) else None
        if not parts or parts.scheme!='https' or not parts.hostname or parts.username or parts.password or len(url)>2000:
            raise ValueError('primary HTTPS source URL required')
    elif any(row[field] is not None for field in ('reviewer','reviewed_at','source_url')):raise ValueError('unreviewed provenance must be unknown')
    if row['class']=='reviewed-source' and row['review_state']!='reviewed':raise ValueError('verified-source class requires review')
    return row

def reviewed_events():
    def day(value):return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp())
    seeds=[('ge-tax-introduced','2021-12-09','GE tax and item sink introduced','grand-exchange-tax--item-sink'),
           ('ge-tax-two-percent','2025-05-29','New GE offers use two percent tax','yama-cas--more')]
    return [validate_annotation({'id':iid,'start':day(date),'end':day(date)+86400,'type':'market-rule',
        'item_ids':[],'groups':[],'class':'reviewed-source','title':title,
        'uncertainty':'Publication date only; exact activation time and price effects are not established. Existing offers retained their prior rate in the 2025 update.',
        'review_state':'reviewed','reviewed_at':day('2026-10-12')+18*3600,'reviewer':'Codex primary-source review',
        'source_url':'https://secure.runescape.com/m=news/'+slug+'?oldschool=1'}) for iid,date,title,slug in seeds]

def validate_store(store):
    if not isinstance(store,dict) or set(store)!={'version','revision','records'} or type(store['version']) is not int or store['version']!=1:
        raise ValueError('annotation store version differs')
    if type(store['revision']) is not int or store['revision']<0 or not isinstance(store['records'],dict) or len(store['records'])>MAX_RECORDS:
        raise ValueError('annotation retention exceeds bounds')
    for iid,row in store['records'].items():
        if not isinstance(iid,str) or not re.fullmatch('[a-z0-9-]{1,80}',iid):raise ValueError('invalid annotation key')
        if row is not None and validate_annotation(row)['id']!=iid:raise ValueError('annotation identity differs')
    if len(json.dumps(store,ensure_ascii=False).encode())>MAX_BYTES:raise ValueError('annotation byte retention exceeded')
    return store

def read_annotations(selected_profile=None):
    path=profile.resolve_config_path(FILENAME,selected_profile)
    store=persistence.read_state(path,'generic') if path.exists() else {'version':1,'revision':0,'records':{}}
    return validate_store(store)

def write_annotation(selected_profile,iid,row,*,expected_revision):
    if not isinstance(iid,str) or not re.fullmatch('[a-z0-9-]{1,80}',iid):raise ValueError('bounded event ID required')
    if row is not None:validate_annotation(row)
    path=profile.resolve_config_path(FILENAME,selected_profile)
    with persistence.locked_state(path):
        activation=persistence.read_state(path.parent/'identity-activation.json','generic')
        if activation and activation.get('financial_authority') is not True:raise ValueError('write annotations on the source Mac')
        store=read_annotations(selected_profile)
        if type(expected_revision) is not int or expected_revision!=store['revision']:raise ValueError('annotation revision changed; reload')
        store={'version':1,'revision':store['revision']+1,'records':{**store['records'],iid:copy.deepcopy(row)}}
        validate_store(store);profile.atomic_write_json(path,store)
        return {'revision':store['revision'],'sensitivity':'private','advisory_only':True}

def all_events(selected_profile=None):
    store=read_annotations(selected_profile);rows={row['id']:row for row in reviewed_events()}
    rows.update(store['records'])
    return {'revision':store['revision'],'sensitivity':'private','events':[row for row in rows.values() if row is not None]}

def select_events(rows,start,end,*,item_id=None,groups=()):
    _epoch(start);_epoch(end)
    if start>=end:raise ValueError('selection interval is empty')
    return [copy.deepcopy(row) for row in rows if validate_annotation(row)['start']<end and row['end']>start
        and (not row['item_ids'] and not row['groups'] or item_id in row['item_ids'] or set(groups).intersection(row['groups']))]

def event_windows(data,events,*,dataset_id,selection_at,selection_note,retrospective=False,item_ids=None):
    _epoch(selection_at)
    if not isinstance(dataset_id,str) or not re.fullmatch('[0-9a-f]{64}',dataset_id):raise ValueError('pinned dataset required')
    if not isinstance(selection_note,str) or not 1<=len(selection_note.encode())<=2000:raise ValueError('explicit selection rationale required')
    if not isinstance(events,list) or not 1<=len(events)<=100 or type(retrospective) is not bool:raise ValueError('bounded event selection required')
    ids=sorted(data if item_ids is None else item_ids)
    if len(ids)>1000 or any(type(i) is not int or i<=0 for i in ids):raise ValueError('bounded explicit item selection required')
    if len(set(ids))!=len(ids) or len({event['id'] for event in events})!=len(events):raise ValueError('duplicate window selection')
    windows=[];hindsight=False;total_candles=0
    for event in events:
        validate_annotation(event)
        if event['class']!='reviewed-source':raise ValueError('private observations are excluded from event dataset exports')
        hindsight=hindsight or event['reviewed_at']>selection_at
        coverage={};candles={}
        for iid in ids:
            if not select_events([event],event['start'],event['end'],item_id=iid):continue
            rows=[]
            for row in data.get(iid,[]):
                if event['start']<=row['timestamp']<event['end']:
                    total_candles+=1
                    if total_candles>50000:raise ValueError('event window export exceeds 50000 candles')
                    rows.append(copy.deepcopy(row))
            stamps=[row['timestamp'] for row in rows]
            if stamps!=sorted(set(stamps)):raise ValueError('window candles must be unique and ordered')
            expected=max(0,(event['end']-1)//300-(event['start']+299)//300+1)
            coverage[str(iid)]={'count':len(rows),'expected':expected,'missing':max(0,expected-len(rows)),
                'gaps':sum(b-a>300 for a,b in zip(stamps,stamps[1:])),'first':stamps[0] if stamps else None,'last':stamps[-1] if stamps else None}
            candles[str(iid)]=rows
        windows.append({'event':copy.deepcopy(event),'coverage':coverage,'candles':candles})
    if hindsight and not retrospective:raise ValueError('review occurred after selection; explicit retrospective export required')
    result={'schema_version':1,'dataset_id':dataset_id,'selection_at':selection_at,'selection_note':selection_note,
        'hindsight':hindsight,'eligible_for_parameter_selection':not retrospective and not hindsight,
        'sensitivity':'private','windows':windows,
        'limitations':['Event timing is contextual, not causal evidence.','Window selection never changes default replay or production parameters.','Coverage counts include missing items and gaps; no return comparison is inferred.']}
    if len(json.dumps(result,ensure_ascii=False).encode())>8*1024*1024:raise ValueError('event window export exceeds 8 MiB')
    result['selection_hash']=request_hash(result);return result
