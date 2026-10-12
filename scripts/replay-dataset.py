#!/usr/bin/env python3
"""Pin market-only candles and freeze selection before evaluating chronological holdout."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

from replay import ReplayConfig, _hash, load_data, simulate, validate_metadata
from rshelper.market_validation import normalize_candles
from rshelper.persistence import decode_json


def read_bytes(path):
    with Path(path).open('rb') as source:raw=source.read(64*1024*1024+1)
    if len(raw)>64*1024*1024:raise ValueError('dataset file exceeds 64 MiB')
    return raw


def read_json(path):
    return decode_json(read_bytes(path).decode('utf-8'))


def file_identity(path):
    raw=read_bytes(path)
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}


def inspect_data(data,metadata):
    normalized,coverage={},{}
    for iid,rows in data.items():
        if not isinstance(rows,list) or not rows:raise ValueError('nonempty candles required for every item')
        timestamps=[r.get('timestamp') for r in rows if isinstance(r,dict)]
        if len(timestamps)!=len(rows) or any(type(t) is not int or not 0<t<=253402300499 for t in timestamps):
            raise ValueError('invalid dataset timestamp')
        result=normalize_candles(rows,'5m',now=max(timestamps)+300)
        if any(result['coverage'][key] for key in ('rejected','conflicts','irregular_intervals')):
            raise ValueError('invalid, conflicting or irregular dataset candles')
        normalized[iid]=result['data'];coverage[str(iid)]=result['coverage']
    validate_metadata(metadata)
    return normalized,coverage


def pin_dataset(data_path,mapping_path,destination,*,source,train_end,validation_end):
    if not isinstance(source,dict) or set(source)!={'provider','url','fetched_at','selection_note'}:
        raise ValueError('explicit provider, URL, fetched_at and selection_note required')
    if source['provider'] not in ('wiki','synthetic','declared-unverified'):
        raise ValueError('unsupported source declaration')
    if not isinstance(source['selection_note'],str) or not 1<=len(source['selection_note'])<=2000:
        raise ValueError('bounded selection note required')
    if type(source['fetched_at']) not in (int,float) or not 0<source['fetched_at']<=253402300799:
        raise ValueError('invalid source fetch time')
    if source['url'] is not None and (not isinstance(source['url'],str) or len(source['url'])>2000 or not source['url'].startswith('https://')):
        raise ValueError('source URL must be HTTPS or null')
    if source['provider']=='wiki' and source['url'] is None:raise ValueError('Wiki source URL required')
    data,coverage=inspect_data(load_data(data_path),read_json(mapping_path))
    first=min(c['first_timestamp'] for c in coverage.values())
    end=max(c['last_timestamp'] for c in coverage.values())+300
    if any(type(t) is not int or (t-first)%300 for t in (train_end,validation_end)) or not first<train_end<validation_end<end:
        raise ValueError('chronological five-minute split boundaries required')
    splits={'train':[first,train_end],'validation':[train_end,validation_end],'holdout':[validation_end,end]}
    for lower,upper in splits.values():
        if any(sum(lower<=r['timestamp']<upper for r in rows)<2 for rows in data.values()):
            raise ValueError('each split requires at least two candles for every item')
    manifest={'schema_version':1,'source':source,'timestep':'5m','coverage':coverage,
              'splits':splits,'files':{'candles.json':file_identity(data_path),'mapping.json':file_identity(mapping_path)}}
    manifest['dataset_id']=_hash(manifest)
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=False)
    try:
        for name,path in (('candles.json',data_path),('mapping.json',mapping_path)):
            with (destination/name).open('xb') as output:output.write(read_bytes(path))
            if file_identity(destination/name)!=manifest['files'][name]:raise ValueError('input bytes changed during pinning')
        with (destination/'manifest.json').open('x') as output:json.dump(manifest,output,sort_keys=True,allow_nan=False)
    except BaseException:
        for name in ('candles.json','mapping.json','manifest.json'):(destination/name).unlink(missing_ok=True)
        destination.rmdir();raise
    return manifest


def load_dataset(path):
    path=Path(path);manifest=read_json(path/'manifest.json')
    if not isinstance(manifest,dict) or manifest.get('schema_version')!=1 or manifest.get('timestep')!='5m':
        raise ValueError('incompatible dataset manifest')
    body={key:value for key,value in manifest.items() if key!='dataset_id'}
    if manifest.get('dataset_id')!=_hash(body):raise ValueError('dataset manifest hash mismatch')
    if set(manifest.get('files',{}))!={'candles.json','mapping.json'}:raise ValueError('invalid dataset file inventory')
    for name,identity in manifest['files'].items():
        if file_identity(path/name)!=identity:raise ValueError('dataset file hash or bytes mismatch')
    data,coverage=inspect_data(load_data(path/'candles.json'),read_json(path/'mapping.json'))
    if coverage!=manifest.get('coverage'):raise ValueError('dataset coverage mismatch')
    expected=('train','validation','holdout')
    splits=manifest.get('splits',{})
    if set(splits)!=set(expected):raise ValueError('invalid split inventory')
    first=min(c['first_timestamp'] for c in coverage.values());end=max(c['last_timestamp'] for c in coverage.values())+300
    cursor=first
    for name in expected:
        bounds=splits[name]
        if not isinstance(bounds,list) or len(bounds)!=2 or any(type(t) is not int or (t-first)%300 for t in bounds) or bounds[0]!=cursor or bounds[1]<=cursor:
            raise ValueError('invalid chronological splits')
        cursor=bounds[1]
        if any(sum(bounds[0]<=r['timestamp']<bounds[1] for r in rows)<2 for rows in data.values()):
            raise ValueError('insufficient split samples')
    if cursor!=end:raise ValueError('split coverage mismatch')
    return manifest,data,read_json(path/'mapping.json')


def metrics(manifest,data,metadata,cfg,slots,split):
    lower,upper=manifest['splits'][split]
    rows={iid:[row for row in candles if lower<=row['timestamp']<upper] for iid,candles in data.items()}
    result=simulate(rows,cfg,metadata=metadata,slot_limit=slots,trace_limit=0)
    return {key:result[key] for key in ('config_hash','trades','total_profit','bankroll_return_pct','roi_pct',
        'roi_basis','max_drawdown','drawdown_basis','by_reason','candle_coverage','assumptions')}|{'open_offer_count':len(result['open_offers'])}


def select_parameters(path,configs,*,slot_limit):
    if type(slot_limit) is not int or slot_limit not in (3,8):raise ValueError('explicit 3 or 8 slots required')
    if not isinstance(configs,list) or not 1<=len(configs)<=64:raise ValueError('1..64 predeclared configurations required')
    configs=[ReplayConfig.from_trader_config(cfg) for cfg in configs]
    manifest,data,metadata=load_dataset(path)
    candidates=[{'config':asdict(cfg),'config_hash':_hash(asdict(cfg)),
        'train':metrics(manifest,data,metadata,cfg,slot_limit,'train'),
        'validation':metrics(manifest,data,metadata,cfg,slot_limit,'validation')} for cfg in configs]
    selected=min(candidates,key=lambda row:(-row['validation']['bankroll_return_pct'],row['config_hash']))
    selection={'schema_version':1,'dataset_id':manifest['dataset_id'],'slots':slot_limit,'candidates':candidates,
        'baseline_config':asdict(configs[0]),'selected_config':selected['config'],
        'objective':'validation realized bankroll return percent; hash breaks ties; open marked losses excluded'}
    selection['selection_hash']=_hash(selection)
    return selection


def evaluate_holdout(path,selection):
    manifest,data,metadata=load_dataset(path)
    if not isinstance(selection,dict) or selection.get('schema_version')!=1 or selection.get('dataset_id')!=manifest['dataset_id']:
        raise ValueError('selection must bind this dataset')
    body={key:value for key,value in selection.items() if key!='selection_hash'}
    if selection.get('selection_hash')!=_hash(body):raise ValueError('selection hash mismatch')
    configs=[ReplayConfig(**row['config']) for row in selection.get('candidates',[])]
    if select_parameters(path,configs,slot_limit=selection.get('slots'))!=selection:
        raise ValueError('selection does not reproduce from train/validation')
    selected=ReplayConfig(**selection['selected_config']);baseline=ReplayConfig(**selection['baseline_config'])
    return {'schema_version':1,'dataset_id':manifest['dataset_id'],'selection_hash':selection['selection_hash'],
        'manifest':manifest,'selected_config':asdict(selected),'baseline_config':asdict(baseline),
        'holdout':metrics(manifest,data,metadata,selected,selection['slots'],'holdout'),
        'baseline_holdout':metrics(manifest,data,metadata,baseline,selection['slots'],'holdout'),
        'validation_sensitivity':selection['candidates'],
        'limitations':['Every split starts with empty holdings and purchase history; no warmup carry.',
            'Completed candle averages and lagged volume are modeled observations, not actual poll execution.',
            'Realized collections exclude open marked losses; selection is not an estimate of total return.',
            'Declared provenance and chronological separation do not establish independent item/regime coverage.',
            'No automatic production retuning or profitability claim.']}


def main():
    parser=argparse.ArgumentParser(description=__doc__);commands=parser.add_subparsers(dest='command',required=True)
    pin=commands.add_parser('pin')
    for name in ('data','mapping','destination','provider','selection-note'):pin.add_argument('--'+name,required=True)
    pin.add_argument('--url');pin.add_argument('--fetched-at',required=True,type=float)
    pin.add_argument('--train-end',required=True,type=int);pin.add_argument('--validation-end',required=True,type=int)
    inspect=commands.add_parser('inspect');inspect.add_argument('--dataset',required=True)
    select=commands.add_parser('select');select.add_argument('--dataset',required=True);select.add_argument('--configs',required=True)
    select.add_argument('--slots',required=True,type=int,choices=(3,8))
    report=commands.add_parser('report');report.add_argument('--dataset',required=True);report.add_argument('--selection',required=True)
    windows=commands.add_parser('event-window')
    windows.add_argument('--dataset',required=True);windows.add_argument('--event-id',action='append',required=True)
    windows.add_argument('--selection-at',required=True,type=int);windows.add_argument('--selection-note',required=True)
    windows.add_argument('--retrospective',action='store_true');windows.add_argument('--item-id',type=int,action='append')
    args=parser.parse_args()
    try:
        if args.command=='pin':result=pin_dataset(args.data,args.mapping,args.destination,source={
            'provider':args.provider,'url':args.url,'fetched_at':args.fetched_at,'selection_note':args.selection_note},
            train_end=args.train_end,validation_end=args.validation_end)
        elif args.command=='inspect':result=load_dataset(args.dataset)[0]
        elif args.command=='select':
            raw=read_json(args.configs)
            if not isinstance(raw,list) or not 1<=len(raw)<=64:raise ValueError('1..64 configuration objects required')
            result=select_parameters(args.dataset,[ReplayConfig(**cfg) for cfg in raw],slot_limit=args.slots)
        elif args.command=='report':result=evaluate_holdout(args.dataset,read_json(args.selection))
        elif args.command=='event-window':
            from rshelper.event_annotations import reviewed_events,event_windows
            manifest,data,_=load_dataset(args.dataset)
            events={row['id']:row for row in reviewed_events()}
            if set(args.event_id)-set(events):raise ValueError('unsupported reviewed event selection')
            result=event_windows(data,[events[iid] for iid in args.event_id],dataset_id=manifest['dataset_id'],
                selection_at=args.selection_at,selection_note=args.selection_note,retrospective=args.retrospective,item_ids=args.item_id)
        else:
            raise ValueError('unknown dataset command')
        print(json.dumps(result,sort_keys=True,allow_nan=False));return 0
    except (OSError,ValueError,TypeError,KeyError) as error:
        print(str(error),file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())
