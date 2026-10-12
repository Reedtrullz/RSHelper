"""Grand Exchange offer simulation: fill progress, slots, collect."""

import time
import copy
import math
from datetime import datetime, timezone
from typing import TypedDict

from rshelper.market import ge_tax, price_issue, safe_int
from rshelper.market_data import executed_volume_supported, provenance
from rshelper.positions import list_positions

MAX_GE_SLOTS = 8


def new_paper_offer(item_id,qty,buy_price,direction,now):
    instant=datetime.fromtimestamp(now,timezone.utc).isoformat()
    return {'schema_version':1,'stage':'buying','item_id':item_id,'direction':direction,
            'qty':qty,'bought_qty':0,'sold_qty':0,'canceled_buy_qty':0,'canceled_sell_qty':0,
            'buy_price':buy_price,'sell_price':None,'created_at':instant,
            'stage_started_at':instant,'last_window':None}


def paper_profit(offer):
    return (offer['sell_price']-offer['buy_price']-ge_tax(offer['sell_price']))*offer['sold_qty']


def cancel_paper_buy(offer,now):
    if offer['stage']!='buying':raise ValueError('buy cancellation requires an active buying offer')
    updated=copy.deepcopy(offer)
    updated['canceled_buy_qty']=updated['qty']-updated['bought_qty']
    updated['stage']='bought' if updated['bought_qty'] else 'canceled'
    updated['stage_started_at']=datetime.fromtimestamp(now,timezone.utc).isoformat()
    return updated


class PaperAdvance(TypedDict):
    offer: dict[str,object]
    fill: dict[str,str | int] | None
    reason: str | None


def advance_paper_offer(offer, market_snapshot, now, policy, *, window_consumed_qty=0):
    if (not isinstance(policy,dict)
            or set(policy)!={'model_id','participation_bps','max_window_age_sec'}
            or policy['model_id']!='paper-conservative-v1'
            or type(policy['participation_bps']) is not int or not 1<=policy['participation_bps']<=100
            or type(policy['max_window_age_sec']) is not int or not 300<=policy['max_window_age_sec']<=600):
        raise ValueError('explicit bounded paper participation policy required')
    if type(now) not in (int,float) or not math.isfinite(now) or not 0<=now<=253402300799:
        raise ValueError('invalid paper clock')
    if type(window_consumed_qty) is not int or not 0<=window_consumed_qty<2**63:
        raise ValueError('invalid shared window allocation')
    if not isinstance(offer,dict) or type(offer.get('schema_version')) is not int or offer['schema_version']!=1:
        raise ValueError('unsupported paper offer')
    updated = copy.deepcopy(offer)
    result: PaperAdvance = {'offer':updated,'fill':None,'reason':None}
    if offer.get('stage')=='legacy-unknown':
        result['reason']='legacy stage evidence unknown; migration review required'
        return result
    fields = {'schema_version','stage','item_id','direction','qty','bought_qty','sold_qty',
              'canceled_buy_qty','canceled_sell_qty','buy_price','sell_price','created_at','stage_started_at','last_window'}
    if set(offer)!=fields or offer['stage'] not in ('buying','bought','selling','collectable','collected','canceled'):
        raise ValueError('invalid paper offer fields or stage')
    if offer['direction'] not in ('traditional','arbitrage'):
        raise ValueError('invalid paper direction')
    for key in ('item_id','qty','buy_price','bought_qty','sold_qty','canceled_buy_qty','canceled_sell_qty'):
        minimum = 1 if key in ('item_id','qty','buy_price') else 0
        if type(offer[key]) is not int or not minimum<=offer[key]<2**63:
            raise ValueError('invalid paper '+key)
    if offer['qty']*offer['buy_price']>=2**63:
        raise ValueError('paper reservation exceeds monetary bound')
    qty,bought,sold = offer['qty'],offer['bought_qty'],offer['sold_qty']
    canceled_buy,canceled_sell = offer['canceled_buy_qty'],offer['canceled_sell_qty']
    if bought+canceled_buy>qty or sold+canceled_sell>bought:
        raise ValueError('paper quantity conservation violated')
    stage = offer['stage']
    if (stage=='buying' and (sold or canceled_sell or bought+canceled_buy==qty)
            or stage in ('bought','selling','collectable','collected') and bought+canceled_buy!=qty
            or stage=='bought' and (sold or canceled_sell or bought==0)
            or stage=='selling' and sold+canceled_sell>=bought
            or stage in ('collectable','collected') and (sold==0 or sold+canceled_sell!=bought)
            or stage=='canceled' and (bought or sold or canceled_buy!=qty)):
        raise ValueError('paper stage inconsistent with quantities')
    if offer['sell_price'] is not None and (type(offer['sell_price']) is not int
            or not 0<offer['sell_price']<2**63 or offer['sell_price']*bought>=2**63):
        raise ValueError('invalid paper sell price')
    if stage in ('selling','collectable','collected') and offer['sell_price'] is None:
        raise ValueError('selling stage needs a pinned price')
    try:
        created = datetime.fromisoformat(offer['created_at'].replace('Z','+00:00'))
        if created.tzinfo is None:raise ValueError('UTC instant required')
        created_at = created.timestamp()
        started = datetime.fromisoformat(offer['stage_started_at'].replace('Z','+00:00'))
        if started.tzinfo is None or not 0<=created_at<=started.timestamp()<=now:
            raise ValueError('invalid stage instant')
        stage_started_at = started.timestamp()
    except (AttributeError,TypeError,ValueError,OverflowError) as exc:
        raise ValueError('invalid paper creation instant') from exc
    last_window = offer['last_window']
    if last_window is not None and (type(last_window) is not int or last_window<0 or last_window%300 or last_window>now):
        raise ValueError('invalid previous volume window')
    def hold(reason):
        result['reason']=reason
        return result
    if stage not in ('buying','selling'):return hold('stage requires an explicit owner action')
    if not isinstance(market_snapshot,dict):return hold('market evidence unavailable')
    latest,volume = market_snapshot.get('latest'),market_snapshot.get('5m')
    if not isinstance(latest,dict) or not isinstance(volume,dict) or not executed_volume_supported(volume):
        return hold('executed volume unavailable: zero, proxy, stale or unknown evidence')
    latest_meta = provenance(latest)
    if latest_meta['source']=='unknown' or latest_meta['stale']:
        return hold('fresh quote provenance unavailable')
    price = latest.get(str(offer['item_id']))
    if not isinstance(price,dict) or price_issue(price,now=now):return hold('usable exit/entry quote unavailable')
    candle = volume.get(str(offer['item_id']))
    if not isinstance(candle,dict):return hold('item volume unavailable')
    window = candle.get('window_timestamp')
    if (type(window) is not int or window<=0 or window%300 or window<stage_started_at
            or not 300<=now-window<=policy['max_window_age_sec']):
        return hold('completed fresh post-entry volume window unavailable')
    if last_window is not None and window<=last_window:return hold('volume window already considered')
    side = 'buy' if stage=='buying' else 'sell'
    low_side = (side=='buy')==(offer['direction']=='traditional')
    leg = 'Low' if low_side else 'High'
    observed_price = candle.get('avg'+leg+'Price')
    traded = candle.get(leg.lower()+'PriceVolume')
    if (isinstance(observed_price,bool) or not isinstance(observed_price,(int,float)) or not math.isfinite(observed_price)
            or not 0<observed_price<2**63 or type(traded) is not int or not 0<traded<2**63):
        return hold('side-specific executed price/volume unavailable')
    limit = offer['buy_price'] if side=='buy' else offer['sell_price']
    if not isinstance(limit,int):raise ValueError('paper limit required')
    if side=='buy' and observed_price>limit or side=='sell' and observed_price<limit:
        return hold('observed execution prices do not support the limit')
    remaining = qty-bought-canceled_buy if side=='buy' else bought-sold-canceled_sell
    fill_qty = min(remaining,max(0,traded*policy['participation_bps']//10000-window_consumed_qty))
    updated['last_window']=window
    if fill_qty==0:return hold('participation cap below one unit')
    key = 'bought_qty' if side=='buy' else 'sold_qty'
    updated[key]+=fill_qty
    if fill_qty==remaining:
        updated['stage']='bought' if side=='buy' else 'collectable'
        updated['stage_started_at']=datetime.fromtimestamp(now,timezone.utc).isoformat()
    result['fill']={'side':side,'qty':fill_qty,'price':limit,
                    'tax_paid':ge_tax(limit)*fill_qty if side=='sell' else 0}
    result['reason']='illustrative paper participation; no real queue/execution claim'
    return result


def resolve_icon_url(item_name: str, detail: bool = True) -> str:
    """OSRS wiki sprite URL from an item name.
    detail=True -> <Name>_detail.png (GE slot sprite).
    detail=False -> <Name>.png (inventory sprite).
    """
    from urllib.parse import quote
    suffix = "_detail" if detail else ""
    # The wiki stores files with URL-encoded names (apostrophes, &, etc.).
    base = quote(item_name.replace(" ", "_"), safe="")
    return "https://oldschool.runescape.wiki/images/" + base + suffix + ".png"


def _elapsed_minutes(opened_at: str, now: float) -> float:
    """Minutes since opened_at (UTC ISO string), clamped to >= 0."""
    try:
        opened = datetime.fromisoformat(opened_at)
        if opened.tzinfo is None:
            opened = opened.replace(tzinfo=timezone.utc)
        now_dt = datetime.fromtimestamp(now, tz=timezone.utc)
        return max(0.0, (now_dt - opened).total_seconds() / 60.0)
    except (ValueError, TypeError):
        return 0.0


def compute_fill_pct(qty: int, volume_5m: int, opened_at: str,
                     now: float | None = None) -> float:
    """0.0-1.0 fill progress, ease-out curve.

    rate = volume_5m / 5 units per minute; raw = elapsed_min * rate / qty;
    fill = 1 - (1 - min(raw, 1))^2. Zero/unknown volume falls back to a
    slow default: min(1.0, elapsed_min * (1/qty)).
    """
    if qty <= 0:
        return 0.0
    elapsed = _elapsed_minutes(opened_at, now if now is not None else time.time())
    if volume_5m > 0:
        rate = volume_5m / 5.0
        raw = min(1.0, elapsed * rate / qty)
        return 1.0 - (1.0 - raw) ** 2
    return min(1.0, elapsed * (1.0 / qty))


def _current_leg(price: dict, direction: str) -> int:
    """Exit leg for a position: offer (high) for traditional, bid (low) for arbitrage."""
    if direction == "traditional":
        return safe_int(price.get("high", 0))
    return safe_int(price.get("low", 0))


def _item_volume_5m(entry) -> int:
    """Total 5m trade volume from a cache entry (int or per-side dict).

    Handles BOTH key sets: the wiki cache uses highPriceVolume/lowPriceVolume;
    the GE Tracker fallback uses high_volume/low_volume (offer quantities).
    """
    if isinstance(entry, dict):
        if "highPriceVolume" in entry or "lowPriceVolume" in entry:
            return (safe_int(entry.get("highPriceVolume"))
                    + safe_int(entry.get("lowPriceVolume")))
        return (safe_int(entry.get("high_volume"))
                + safe_int(entry.get("low_volume")))
    return safe_int(entry)


def build_ge_slots(profile=None, latest=None, vol_5m=None, now=None, *, offset=0) -> dict:
    from rshelper import paper_book, state_identity, state_transaction
    if type(offset) is not int or not 0<=offset<=100000:raise ValueError('invalid paper page offset')
    now=time.time() if now is None else now
    latest={} if latest is None else latest
    root=paper_book._root(profile)
    with state_transaction.profile_transaction(profile or 'default',root):
        activation=state_identity.activation_manifest(root/'identity-activation.json')
        book=paper_book._read(root) if (root/paper_book.FILENAME).exists() or (activation or {}).get('paper_budget_origin') else None
        budget=paper_book._summary(root,book,now) if book is not None else None
        holdings=list_positions(profile)
        by_lot={position.lot_uid:position for position in holdings if position.lot_uid}
        records=[]
        covered=set()
        if book is not None:
            for offer_id,record in book['offers'].items():
                offer=record['offer']
                if offer['stage'] in ('collected','canceled'):continue
                covered.update(record['lots'])
                position=by_lot.get(record['lots'][0]) if record['lots'] else None
                records.append((offer_id,record,position))
        for position in holdings:
            if position.lot_uid not in covered:
                records.append((position.lot_uid or 'position:'+str(position.id),None,position))
        slots=[]
        total_value=0
        for index,(key,record,position) in enumerate(records):
            if record is not None:
                offer=record['offer']
                item_id,name,qty=offer['item_id'],record['name'],offer['qty']
                buy_price,direction,stage=offer['buy_price'],offer['direction'],offer['stage']
                automatic=record['mode']=='auto'
                selling=stage in ('selling','collectable')
                target=offer['bought_qty']-offer['canceled_sell_qty'] if selling else qty-offer['canceled_buy_qty']
                completed=offer['sold_qty'] if selling else offer['bought_qty']
                pinned=offer['sell_price'] if selling else buy_price
                invested_qty=offer['bought_qty']
                held=position.qty if position is not None else offer['bought_qty']
                opened_at=offer['created_at']
            else:
                if position is None:raise ValueError('paper projection lacks a holding')
                offer=None
                item_id,name,qty=position.item_id,position.name,position.qty
                buy_price,direction,stage=position.buy_price,position.direction,'legacy-unknown'
                automatic=position.note=='auto'
                selling=False
                target,completed,pinned=qty,0,buy_price
                invested_qty=held=qty
                opened_at=position.opened_at
            fill=completed/target if target>0 else 0
            total_value+=buy_price*invested_qty
            if not offset<=index<offset+50:continue
            price=latest.get(str(item_id))
            current=_current_leg(price,direction) if isinstance(price,dict) and price_issue(price,now=now) is None else None
            unrealized=(current-buy_price-ge_tax(current))*held if current is not None else None
            slots.append({
                'index':index,'slot_key':key,'offer_id':key if offer else None,
                'lot_uid':position.lot_uid if position is not None else None,
                'offer_type':'sell' if selling else 'buy' if stage=='buying' else 'hold',
                'item_id':item_id,'name':name,'qty':qty,'target_qty':target,'completed_qty':completed,
                'held_qty':held,'fill_pct':round(fill,4),'status':stage,'stage':stage,
                'fill_reason':'Persisted illustrative participation; separate sale and collection' if offer else 'Historical holding; purchase execution and offer stage unknown',
                'market_data':{'latest':provenance(latest)},
                'price':target*pinned,'price_each':pinned,'buy_price':buy_price,
                'current_price':current,'unrealized':unrealized,
                'unrealized_pct':round((current-buy_price-ge_tax(current))/buy_price*100,2) if current is not None else None,
                'icon_url':resolve_icon_url(name,False),'icon_url_detail':resolve_icon_url(name),
                'position_id':position.id if position is not None else None,
                'opened_at':opened_at,
                'age_minutes':round(_elapsed_minutes(opened_at,now),1),
                'can_collect':stage=='collectable' and not automatic,'auto':automatic,
                'entry_sell':position.entry_sell if position is not None else None,
                'entry_offer':position.entry_offer if position is not None else None,
                'spread_pct':round((position.entry_offer-buy_price)/buy_price*100,2) if position is not None and position.entry_offer else None,
                'exit_reason':None})
        capacity=book['slot_limit'] if book is not None else None
        return {'slots':slots,'total_count':len(records),'offset':offset,
                'next_offset':offset+50 if offset+50<len(records) else None,
                'empty_count':max(0,capacity-len(records)) if capacity is not None else None,
                'slot_limit':capacity,'total_value':total_value,'budget':budget,
                'initialized':book is not None,'revision':book['revision'] if book is not None else None,
                'unknown':budget['unknown'] if budget is not None else ['explicit paper budget and account capability required']}


def collect_offer(position_id: int, profile=None, latest=None,
                  operation_id: str | None = None) -> dict:
    from uuid import UUID,uuid5
    from rshelper import paper_book,realization
    root=paper_book._root(profile)
    now=time.time()
    if not (root/paper_book.FILENAME).exists():
        if operation_id is not None:
            summary=realization.batch_summary(profile,operation_id)
            realization.realize_close_batch(profile,operation_id)
            children=summary['operations']
            if not isinstance(children,list) or not children:raise ValueError('legacy collection children unavailable')
            return {'ok':True,'operation_id':operation_id,'replayed':True,
                    'name':children[0]['name'],'qty':sum(child['qty'] for child in children),
                    'sell_price':children[0]['sell_price'],
                    'profit':sum((child['sell_price']-child['buy_price']-ge_tax(child['sell_price']))*child['qty'] for child in children)}
        raise ValueError('historical stage unknown; initialize and adopt the holding before a paper sale')
    state=paper_book.budget_snapshot(profile,now=now)
    pinned=paper_book.operation_request(profile,operation_id) if operation_id is not None else None
    if pinned is not None:
        if pinned['action']!='collect':raise ValueError('operation belongs to another paper action')
        offer_id=pinned['offer_id']
    else:
        position=next((row for row in list_positions(profile) if row.id==position_id),None)
        if position is None:raise ValueError('recorded holding unavailable')
        matching=[key for key,record in state['offers'].items()
                  if position.lot_uid in record['lots'] and record['offer']['stage']=='collectable']
        if len(matching)!=1:raise ValueError('collection requires a collectable paper sale')
        offer_id=matching[0]
    record=state['offers'][offer_id]
    if record['mode']=='auto':raise ValueError('auto-trader owns this paper collection')
    offer=record['offer']
    operation_id=operation_id or str(uuid5(UUID(offer_id),'paper-ge-collection'))
    result=paper_book.collect_offer(profile,offer_id,expected_revision=state['revision'],
                                   operation_id=operation_id,now=now)
    return {'ok':True,'operation_id':operation_id,'replayed':result['retry'],
            'name':record['name'],'qty':offer['sold_qty'],'sell_price':offer['sell_price'],
            'profit':(offer['sell_price']-offer['buy_price']-ge_tax(offer['sell_price']))*offer['sold_qty']}


def close_market_price(position, latest: dict | None) -> int:
    latest={} if latest is None else latest
    price=latest.get(str(position.item_id))
    if not isinstance(price,dict) or price_issue(price):
        raise ValueError('usable current exit quote required; holding remains open')
    sell=_current_leg(price,position.direction)
    if sell<=0:raise ValueError('positive current exit quote required')
    return sell
