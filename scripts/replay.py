#!/usr/bin/env python3
"""Replay shared paper decisions on explicitly selected five-minute data."""
from __future__ import annotations
import argparse
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tomllib
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from rshelper import trader, paper_book
from rshelper.budget import _budget_summary, require_capacity
from rshelper.config import Config, TraderConfig, validate_config, _config_from_toml
from rshelper.ge_offers import advance_paper_offer, new_paper_offer, cancel_paper_buy, paper_profit
from rshelper.market import ge_tax, safe_int
from rshelper.market_data import MarketDataResult, market_payload
from rshelper.market_validation import normalize_candles
from rshelper.models import Item
from rshelper.positions import Position
from rshelper.persistence import decode_json

@dataclass
class ReplayConfig(TraderConfig):
    @classmethod
    def from_trader_config(cls,effective):
        copied=cls(**asdict(effective))
        validate_config(Config(trader=TraderConfig(**asdict(copied))))
        return copied

    @classmethod
    def historical_baseline(cls):
        return cls(min_spread_pct=4.0,max_entry_spread_pct=5.0,dip_depth_pct=2.0,
                   stop_loss_pct=-1.5,stop_grace_minutes=10,trade_capital_frac=0.25)

def _candle_iso(ts):
    return datetime.fromtimestamp(ts,timezone.utc).isoformat()

def _hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def candle_observations(items,metadata):
    indices={iid:{c['timestamp']:i for i,c in enumerate(rows)} for iid,rows in items.items()}
    for timestamp in sorted({c['timestamp'] for rows in items.values() for c in rows}):
        now=timestamp+300
        latest,volume,candidates={},{},[]
        for iid in sorted(items):
            index=indices[iid].get(timestamp)
            if index is None:continue
            current=items[iid][index]
            high,low=safe_int(current['avgHighPrice']),safe_int(current['avgLowPrice'])
            latest[str(iid)]={'high':high,'low':low,'highTime':now,'lowTime':now}
            previous=items[iid][index-1] if index else None
            if previous is None or previous['timestamp']!=timestamp-300:continue
            volume[str(iid)]={**previous,'window_timestamp':previous['timestamp']}
            meta=metadata.get(str(iid),{})
            candidates.append(Item(iid,meta.get('name','Item '+str(iid)),meta.get('members'),
                meta.get('limit') or 0,0,high,low,
                safe_int(previous['highPriceVolume'])+safe_int(previous['lowPriceVolume'])))
        def wrap(data,kind):
            return market_payload(MarketDataResult(data,'wiki','historical-model',now,now,now,False,kind,{'wiki':len(data)}))
        yield {'now':now,'latest':wrap(latest,'unknown'),'5m':wrap(volume,'executed-trades'),'items':candidates}

def validate_metadata(metadata):
    if not isinstance(metadata,dict):raise ValueError('explicit item metadata mapping required')
    for key,value in metadata.items():
        if not isinstance(key,str) or not key.isdecimal() or str(int(key))!=key or int(key)<=0 or not isinstance(value,dict):
            raise ValueError('mapping requires canonical positive item IDs and metadata objects')
        if value.get('members') is not None and type(value['members']) is not bool:raise ValueError('invalid item membership')
        if value.get('limit') is not None and (type(value['limit']) is not int or not 0<value['limit']<2**63):raise ValueError('invalid item buy limit')
        if 'name' in value and (type(value['name']) is not str or not value['name'] or len(value['name'])>1000):raise ValueError('invalid item name')


def simulate(timeseries,cfg,capital=None,max_positions=None,*,metadata=None,slot_limit=None,observations=None,trace_limit=1000):
    cfg=ReplayConfig.from_trader_config(cfg)
    cfg=replace(cfg,capital=cfg.capital if capital is None else capital,
                max_positions=cfg.max_positions if max_positions is None else max_positions)
    validate_config(Config(trader=TraderConfig(**asdict(cfg))))
    if type(trace_limit) is not int or not 0<=trace_limit<=10000:raise ValueError('trace limit must be 0..10000')
    items,coverage={},{}
    for iid,candles in sorted(timeseries.items(),key=lambda row:int(row[0])):
        if not isinstance(candles,list):raise ValueError('replay candles must be a list')
        horizon=max((safe_int(row.get('timestamp')) for row in candles if isinstance(row,dict)),default=0)+300
        if not 0<horizon<=253402300799:raise ValueError('replay timestamp exceeds supported UTC clock')
        normalized=normalize_candles(candles,'5m',now=horizon)
        coverage[str(iid)]=normalized['coverage']
        if normalized['coverage']['irregular_intervals']:raise ValueError('replay data does not use five-minute candle intervals')
        if not normalized['data']:raise ValueError(f'replay item {iid} has no usable five-minute candles')
        items[int(iid)]=normalized['data']
    if not items:raise ValueError('explicit usable timeseries required')
    metadata={} if metadata is None else metadata
    validate_metadata(metadata)
    limits={}
    records,holdings,purchases,allocations,recent_exits={},{},[],{},{}
    trades,trace=[],[]
    trace_count=0
    def event(kind,now,**data):
        nonlocal trace_count
        trace_count+=1
        if len(trace)<trace_limit:trace.append({'kind':kind,'at':now,**data})
    def budget(now,extra=None):
        realized=sum(t['profit'] for t in trades)
        result=_budget_summary(list(holdings.values()),records,purchases,
            bankroll=cfg.capital+realized,slot_limit=slot_limit,
            history_complete_after=0,now=now,buy_limits={**limits,**(extra or {})})
        return {**result,'realized_profit':realized,'initial_bankroll':cfg.capital}
    previous_now=None
    stream=candle_observations(items,metadata) if observations is None else observations
    for snapshot in stream:
        now=snapshot['now']
        if previous_now is not None and now<=previous_now:raise ValueError('replay clock must strictly advance')
        previous_now=now
        latest,volume=snapshot['latest'],snapshot['5m']
        if not isinstance(latest,dict) or not isinstance(volume,dict):raise ValueError('replay snapshot requires keyed quote and volume data')
        candidates=trader.select_candidates(snapshot['items'],latest,volume,cfg,now=now,recent_exits=recent_exits)
        event('ranking',now,item_ids=[item.id for item in candidates])
        for offer_id,record in records.items():
            offer=record['offer']
            if offer['stage'] in ('collected','canceled'):continue
            if offer['stage']=='buying' and now-datetime.fromisoformat(offer['created_at']).timestamp()>=cfg.max_hold_minutes*60:
                offer=record['offer']=cancel_paper_buy(offer,now)
                event('cancel-buy',now,offer_id=offer_id,bought_qty=offer['bought_qty'])
            if offer['stage'] in ('buying','selling'):
                candle=volume.get(str(offer['item_id']),{})
                leg='Low' if (offer['stage']=='buying')==(offer['direction']=='traditional') else 'High'
                key=str(candle.get('window_timestamp'))+':'+str(offer['item_id'])+':'+leg
                result=advance_paper_offer(offer,snapshot,now,paper_book.POLICY,window_consumed_qty=allocations.get(key,0))
                offer=record['offer']=result['offer']
                fill=result['fill']
                if fill is not None:
                    allocations[key]=allocations.get(key,0)+fill['qty']
                    record['fills'].append(fill)
                    if fill['side']=='buy':purchases.append({'item_id':offer['item_id'],'qty':fill['qty'],'at':now})
                    event('fill',now,offer_id=offer_id,**fill)
            if offer['stage']=='bought':
                if offer_id not in holdings:
                    holdings[offer_id]={'lot_uid':offer_id,'item_id':offer['item_id'],'qty':offer['bought_qty'],
                        'buy_price':offer['buy_price'],'direction':offer['direction'],'opened_at':_candle_iso(now)}
                    record['lots']=[offer_id]
                    event('bought',now,offer_id=offer_id,qty=offer['bought_qty'])
                lot=holdings[offer_id]
                position=Position(0,lot['item_id'],record['name'],lot['qty'],lot['buy_price'],lot['direction'],lot['opened_at'])
                quote=latest.get(str(position.item_id))
                if not isinstance(quote,dict) or trader.price_issue(quote,now=now) or not trader._fresh(quote,trader.EXIT_MAX_AGE,now):continue
                candle=volume.get(str(position.item_id),{})
                reason=trader.exit_reason(position,latest,cfg,now=now,avg_low=candle.get('avgLowPrice'))
                if reason is not None:
                    sell=trader.paper_sale_price(position,quote,volume,cfg,reason)
                    if sell>0:
                        paper_book._stage_sale(record,lot,position.qty,sell,now,reason)
                        event('sale',now,offer_id=offer_id,reason=reason,sell=sell)
            if offer['stage']=='collectable':
                lot=holdings.pop(offer_id)
                profit=paper_profit(offer)
                trade={'item_id':offer['item_id'],'qty':offer['sold_qty'],'buy':offer['buy_price'],
                    'sell':offer['sell_price'],'tax_paid':ge_tax(offer['sell_price'])*offer['sold_qty'],
                    'profit':profit,'reason':record['sale_reason'],
                    'hold_minutes':(now-datetime.fromisoformat(lot['opened_at']).timestamp())/60}
                trades.append(trade)
                recent_exits[offer['item_id']]=(now,record['sale_reason'])
                offer['stage']='collected';offer['stage_started_at']=_candle_iso(now)
                event('collected',now,offer_id=offer_id,**trade)
        occupied={r['offer']['item_id'] for r in records.values() if r['offer']['stage'] not in ('collected','canceled')}
        for candidate in candidates:
            current=budget(now)
            if len(occupied)>=cfg.max_positions:break
            if candidate.id in occupied:continue
            qty=min(trader.size_position(cfg,current['invested_cash']+current['reserved_cash'],candidate),current['available_cash']//candidate.sell_price)
            if qty<=0:
                event('held',now,item_id=candidate.id,reason='known sizing/buy-limit capacity unavailable or exhausted');continue
            try:require_capacity(budget(now,{candidate.id:candidate.buy_limit}),item_id=candidate.id,qty=qty,buy_price=candidate.sell_price,members=candidate.members)
            except ValueError as exc:
                event('held',now,item_id=candidate.id,reason=str(exc));continue
            offer_id=str(len(records)+1)
            limits[candidate.id]=candidate.buy_limit
            records[offer_id]={'name':candidate.name,'lots':[],'fills':[],'sale_reason':None,'exit_config':None,
                'offer':new_paper_offer(candidate.id,qty,candidate.sell_price,'traditional',now)}
            occupied.add(candidate.id)
            event('queued',now,offer_id=offer_id,item_id=candidate.id,qty=qty,buy=candidate.sell_price)
        event('budget',now,**budget(now))
    final=budget(previous_now if previous_now is not None else 0)
    total=sum(t['profit'] for t in trades);cost=sum(t['buy']*t['qty'] for t in trades)
    winners=[t for t in trades if t['profit']>0];losers=[t for t in trades if t['profit']<0]
    cumulative=peak=drawdown=0
    for trade in trades:
        cumulative+=trade['profit'];peak=max(peak,cumulative);drawdown=max(drawdown,peak-cumulative)
    by_reason={}
    for trade in trades:
        summary=by_reason.setdefault(trade['reason'],{'n':0,'profit':0})
        summary['n']+=1;summary['profit']+=trade['profit']
    return {'trades':len(trades),'trade_list':trades,'total_profit':total,
        'roi_pct':round(total/cost*100,2) if cost else 0,'roi_basis':'realized turnover; excludes uncollected offers',
        'bankroll_return_pct':round(total/cfg.capital*100,4),
        'win_rate':round(len(winners)/len(trades)*100,1) if trades else 0,
        'avg_win':round(sum(t['profit'] for t in winners)/len(winners)) if winners else 0,
        'avg_loss':round(sum(t['profit'] for t in losers)/len(losers)) if losers else 0,
        'profit_factor':round(sum(t['profit'] for t in winners)/abs(sum(t['profit'] for t in losers)),2) if losers else None,
        'max_drawdown':drawdown,'drawdown_basis':'realized collections only; excludes open marked losses',
        'by_reason':by_reason,'budget':final,'open_offers':{key:row['offer'] for key,row in records.items() if row['offer']['stage'] not in ('collected','canceled')},
        'trace':trace,'trace_count':trace_count,'trace_truncated':trace_count>len(trace),'candle_coverage':coverage,
        'config':asdict(cfg),'config_hash':_hash(asdict(cfg)),'metadata_hash':_hash(metadata),
        'assumptions':{'model':paper_book.POLICY,'slots':slot_limit,'initial_holdings':0,'purchase_history':'empty simulation',
            'quote_model':'completed current candle average','volume_model':'previous contiguous completed candle',
            'cadence_seconds':300,'no_final_liquidation':True}}

def load_data(path):
    selected=Path(path)
    if selected.stat().st_size>64*1024*1024:raise ValueError('replay input exceeds 64 MiB')
    raw=decode_json(selected.read_text())
    if not isinstance(raw,dict) or not raw:raise ValueError('nonempty keyed replay data required')
    if any(not key.isdecimal() or str(int(key))!=key or int(key)<=0 for key in raw):
        raise ValueError('replay data requires canonical positive decimal item IDs')
    return {int(key):value for key,value in raw.items()}


def selected_config(selection,path=None):
    if selection not in ('runtime-defaults','historical-baseline'):raise ValueError('explicit replay config selection required')
    cfg=ReplayConfig() if selection=='runtime-defaults' else ReplayConfig.historical_baseline()
    if path is not None:
        if selection!='runtime-defaults':raise ValueError('explicit TOML applies only to runtime-defaults selection')
        selected=Path(path)
        if selected.stat().st_size>65536:raise ValueError('config exceeds 64 KiB')
        cfg=ReplayConfig.from_trader_config(validate_config(_config_from_toml(tomllib.loads(selected.read_text()))).trader)
    return cfg

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',required=True)
    parser.add_argument('--mapping',required=True)
    parser.add_argument('--config',required=True,choices=('runtime-defaults','historical-baseline'))
    parser.add_argument('--config-file')
    parser.add_argument('--slots',required=True,type=int,choices=(3,8))
    parser.add_argument('--items')
    parser.add_argument('--json',action='store_true')
    args=parser.parse_args()
    try:
        cfg=selected_config(args.config,args.config_file)
        data=load_data(args.data)
        mapping=Path(args.mapping)
        if mapping.stat().st_size>64*1024*1024:raise ValueError('mapping exceeds 64 MiB')
        metadata=decode_json(mapping.read_text())
        if args.items:
            wanted={int(value) for value in args.items.split(',')};data={key:value for key,value in data.items() if key in wanted}
        result=simulate(data,cfg,metadata=metadata,slot_limit=args.slots)
    except (OSError,ValueError,TypeError) as exc:
        print(str(exc),file=sys.stderr);return 1
    print(json.dumps(result,sort_keys=True,allow_nan=False) if args.json else
          f"trades={result['trades']} realized={result['total_profit']}gp open_offers={len(result['open_offers'])} max_drawdown={result['max_drawdown']}")
    return 0

if __name__=='__main__':raise SystemExit(main())
