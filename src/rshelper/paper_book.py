import copy
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import math
import re
from uuid import UUID,uuid5
from typing import TypedDict

from rshelper import persistence, positions, state_identity, state_transaction
from rshelper.budget import _budget_summary
from rshelper.ge_offers import advance_paper_offer, new_paper_offer, cancel_paper_buy, paper_profit

FILENAME='paper-offers.json'

class PaperMutation(TypedDict):
    expected_revision: int
    operation_id: str
    now: float

class PaperState(TypedDict):
    revision: int
    budget: dict
    offers: dict
    offer_id: str | None
    operation_revision: int | None
    retry: bool
    pending_collections: dict[str,str]

class PaperProgress(PaperState):
    reason: str | None

POLICY={'model_id':'paper-conservative-v1','participation_bps':100,'max_window_age_sec':600}
MAX_RECORDS=100000
REQUEST_FIELDS={
    'initialize':{'bankroll','slot_limit'},'set-slots':{'slot_limit'},
    'reserve':{'item_id','name','qty','buy_price','buy_limit','direction','note','mode','client_ref','members'},
    'advance':{'offer_id'},'cancel-buy':{'offer_id'},'cancel-sale':{'offer_id'},'collect':{'offer_id'},
    'start-sale':{'offer_id','qty','sell_price','reason'},'adopt-holding':{'lot_uid','mode'},
    'finalize-collection':{'operation_id'},
    'queue-sales':{'item_id','qty','quotes','position_id','client_ref'},
}


def _clock(value):
    if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=253402300799:
        raise ValueError('invalid paper clock')
    return datetime.fromtimestamp(value,timezone.utc).timestamp()


def _hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def _root(profile):
    return positions._positions_path(profile).parent


def _authority(root):
    manifest=state_identity.activation_manifest(root/'identity-activation.json')
    state_identity.require_financial_authority(manifest)
    if manifest is None:raise ValueError('identified paper authority required')
    return manifest['origin_uuid']


def validate_book(book):
    fields={'schema_version','origin_uuid','revision','updated_at','bankroll','slot_limit',
            'history_complete_after','baseline_trades','baseline_lots','offers','purchases',
            'buy_limits','operations','policy','realized_profit','allocations','collections'}
    if not isinstance(book,dict) or set(book)!=fields or type(book['schema_version']) is not int or book['schema_version']!=1:
        raise ValueError('invalid paper book schema')
    persistence.canonical_uuid(book['origin_uuid'])
    if type(book['revision']) is not int or not 1<=book['revision']<2**63:
        raise ValueError('invalid paper revision')
    now=_clock(book['updated_at'])
    _clock(book['history_complete_after'])
    if type(book['realized_profit']) is not int or not -2**63<book['realized_profit']<2**63:
        raise ValueError('invalid paper realized cash')
    for key in ('baseline_trades','baseline_lots'):
        values=book[key]
        if not isinstance(values,list) or len(values)>MAX_RECORDS or len(set(values))!=len(values):
            raise ValueError('invalid paper financial baseline')
        for value in values:persistence.canonical_uuid(value)
    for key in ('offers','buy_limits','operations','allocations','collections'):
        if not isinstance(book[key],dict) or len(book[key])>MAX_RECORDS:
            raise ValueError('paper ledger exceeds record budget')
    if not isinstance(book['purchases'],list) or len(book['purchases'])>MAX_RECORDS:
        raise ValueError('paper purchase ledger exceeds record budget')
    for key,limit in book['buy_limits'].items():
        if type(key) is not str or not re.fullmatch('[1-9][0-9]{0,18}',key) or int(key)>=2**63:
            raise ValueError('invalid paper buy limit item')
        if type(limit) is not int or not 0<limit<2**63:raise ValueError('invalid paper buy limit')
    if book['policy']!=POLICY:raise ValueError('unsupported paper policy')
    covered=set()
    expected_purchases=[]
    expected_allocations={}
    window_totals={}
    window_caps={}
    for offer_id,record in book['offers'].items():
        persistence.canonical_uuid(offer_id)
        required={'offer','name','note','lots','fills','mode','purchase_basis','sale_reason'}
        if not isinstance(record,dict) or not required<=set(record) or set(record)-required-{'entry_config','exit_config'}:
            raise ValueError('invalid paper offer record')
        from rshelper.tuning import validate_config_evidence
        for field in ('entry_config','exit_config'):validate_config_evidence(record.get(field))
        if record['mode'] not in ('manual-hold','manual-roundtrip','auto') or record['purchase_basis'] not in ('paper-fills','legacy-recorded-holding','confirmed-held-remainder'):
            raise ValueError('invalid paper execution intent/evidence basis')
        if record['sale_reason'] not in (None,'manual','roundtrip','take_profit','stop_loss','spread_collapse','max_hold'):
            raise ValueError('invalid paper sale reason')
        if (record['offer']['stage'] in ('selling','collectable','collected'))!=(record['sale_reason'] is not None):
            raise ValueError('paper sale reason differs from stage')
        for key in ('name','note'):
            if type(record[key]) is not str or len(record[key])>1000:raise ValueError('invalid paper text')
        if not isinstance(record['lots'],list) or len(record['lots'])>1:
            raise ValueError('paper offer must own at most one financial lot')
        for lot in record['lots']:
            persistence.canonical_uuid(lot)
            if record['offer'].get('stage') not in ('collected','canceled'):
                if lot in covered:raise ValueError('financial lot already owns an active offer')
                covered.add(lot)
        advance_paper_offer(record['offer'],None,now,book['policy'])
        if not isinstance(record['fills'],list) or len(record['fills'])>MAX_RECORDS:
            raise ValueError('invalid paper fill ledger')
        bought=sold=0
        seen_windows=set()
        for fill in record['fills']:
            if not isinstance(fill,dict) or set(fill)!={'side','qty','price','tax_paid','window','at','executed_volume','observed_price'}:
                raise ValueError('invalid paper fill evidence')
            if fill['side'] not in ('buy','sell'):raise ValueError('invalid paper fill side')
            for key in ('qty','price','tax_paid','window'):
                if type(fill[key]) is not int or not (0 if key=='tax_paid' else 1)<=fill[key]<2**63:
                    raise ValueError('invalid paper fill quantity/price/window')
            if fill['window']%300 or not 300<=_clock(fill['at'])-fill['window']<=600 or fill['at']>now:
                raise ValueError('invalid paper fill instant')
            from rshelper.market import ge_tax
            expected=ge_tax(fill['price'])*fill['qty'] if fill['side']=='sell' else 0
            if fill['tax_paid']!=expected:raise ValueError('invalid paper fill tax')
            price=record['offer']['buy_price' if fill['side']=='buy' else 'sell_price']
            if fill['price']!=price:raise ValueError('paper fill price differs from pinned offer')
            volume=fill['executed_volume']
            observed=fill['observed_price']
            if (type(volume) is not int or not 0<volume<2**63 or type(observed) not in (int,float)
                    or not math.isfinite(observed) or not 0<observed<2**63
                    or fill['side']=='buy' and observed>price or fill['side']=='sell' and observed<price):
                raise ValueError('paper fill lacks supporting executed price/volume')
            window_key=(fill['side'],fill['window'])
            if window_key in seen_windows:raise ValueError('paper window counted twice')
            seen_windows.add(window_key)
            if fill['side']=='buy':
                bought+=fill['qty']
                expected_purchases.append({'item_id':record['offer']['item_id'],'qty':fill['qty'],
                                           'at':fill['at'],'offer_id':offer_id})
            else:sold+=fill['qty']
            leg='Low' if (fill['side']=='buy')==(record['offer']['direction']=='traditional') else 'High'
            allocation=str(fill['window'])+':'+str(record['offer']['item_id'])+':'+leg
            window_totals[allocation]=window_totals.get(allocation,0)+fill['qty']
            window_caps[allocation]=max(window_caps.get(allocation,0),volume*book['policy']['participation_bps']//10000)
            if now-fill['window']<=600:
                expected_allocations[allocation]=expected_allocations.get(allocation,0)+fill['qty']
        if record['purchase_basis']!='paper-fills':
            if bought or len(record['lots'])!=1:
                raise ValueError('legacy paper holding lacks baseline evidence')
            lot=record['lots'][0]
            if record['purchase_basis']=='legacy-recorded-holding' and lot not in book['baseline_lots']:
                raise ValueError('legacy paper holding lacks baseline evidence')
            if record['purchase_basis']=='confirmed-held-remainder' and not any(
                    previous['purchase_basis']=='paper-fills' and lot in previous['lots']
                    and previous['offer']['bought_qty']>=record['offer']['bought_qty']
                    for previous in book['offers'].values()):
                raise ValueError('paper remainder lacks original confirmed purchase')
        elif bought!=record['offer']['bought_qty']:
            raise ValueError('paper fill evidence does not conserve purchase quantity')
        if sold!=record['offer']['sold_qty']:
            raise ValueError('paper fill evidence does not conserve quantity')
    for operation,receipt in book['operations'].items():
        persistence.canonical_uuid(operation)
        if not isinstance(receipt,dict) or set(receipt)!={'request','request_hash','revision','offer_id'}:
            raise ValueError('invalid paper operation receipt')
        request=receipt['request']
        if (not isinstance(request,dict) or request.get('action') not in REQUEST_FIELDS
                or set(request)!={'action',*REQUEST_FIELDS[request['action']]}):
            raise ValueError('invalid paper operation request')
        if _hash(request)!=receipt['request_hash']:raise ValueError('paper operation request hash differs')
        if type(receipt['request_hash']) is not str or not re.fullmatch('[0-9a-f]{64}',receipt['request_hash']):
            raise ValueError('invalid paper request hash')
        if type(receipt['revision']) is not int or not 1<=receipt['revision']<=book['revision']:
            raise ValueError('invalid paper operation revision')
        if receipt['offer_id'] is not None and receipt['offer_id'] not in book['offers']:
            raise ValueError('paper operation offer missing')
    for allocation,qty in book['allocations'].items():
        if type(allocation) is not str or not re.fullmatch('[1-9][0-9]*:[1-9][0-9]*:(Low|High)',allocation):
            raise ValueError('invalid paper shared allocation')
        if type(qty) is not int or not 0<qty<2**63:raise ValueError('invalid paper shared allocation quantity')
    for purchase in book['purchases']:
        if not isinstance(purchase,dict) or set(purchase)!={'item_id','qty','at','offer_id'}:
            raise ValueError('invalid paper purchase evidence')
        if type(purchase['item_id']) is not int or not 0<purchase['item_id']<2**63:
            raise ValueError('invalid paper purchase item')
        if purchase['offer_id'] not in book['offers']:raise ValueError('paper purchase offer missing')
    if sorted(book['purchases'],key=_hash)!=sorted(expected_purchases,key=_hash):
        raise ValueError('paper purchase ledger differs from confirmed fills')
    if book['allocations']!=expected_allocations:raise ValueError('paper shared window ledger differs from confirmed fills')
    if any(qty>window_caps[key] for key,qty in window_totals.items()):
        raise ValueError('paper shared fill quantity exceeds evidenced participation cap')
    realized=0
    for offer_id,collection in book['collections'].items():
        if offer_id not in book['offers'] or not isinstance(collection,dict) or set(collection)!={'operation_id','status','profit','trade_uuids'}:
            raise ValueError('invalid paper collection receipt')
        persistence.canonical_uuid(collection['operation_id'])
        if collection['status'] not in ('pending','committed'):raise ValueError('invalid paper collection status')
        if type(collection['profit']) is not int or not -2**63<collection['profit']<2**63:
            raise ValueError('invalid paper collection profit')
        if not isinstance(collection['trade_uuids'],list) or len(collection['trade_uuids'])>1:
            raise ValueError('invalid paper collection financial proof')
        for trade in collection['trade_uuids']:persistence.canonical_uuid(trade)
        stage=book['offers'][offer_id]['offer']['stage']
        if (collection['status']=='pending' and (stage!='collectable' or collection['trade_uuids'])
                or collection['status']=='committed' and (stage!='collected' or len(collection['trade_uuids'])!=1)):
            raise ValueError('paper collection stage differs from receipt')
        if collection['status']=='committed':realized+=collection['profit']
    if book['realized_profit']!=realized:raise ValueError('paper cash differs from collection receipts')
    if (len(book['offers'])+len(book['operations'])+len(book['purchases'])+len(book['collections'])
            +sum(len(record['fills']) for record in book['offers'].values())>MAX_RECORDS):
        raise ValueError('paper ledger exceeds aggregate record budget')
    _budget_summary([],book['offers'],book['purchases'],bankroll=book['bankroll'],
        slot_limit=book['slot_limit'],history_complete_after=book['history_complete_after'],
        now=now,buy_limits={int(key):value for key,value in book['buy_limits'].items()})
    return book


def _read(root):
    book=persistence.read_state(root/FILENAME,'paper-book')
    if not book:raise ValueError('explicit paper budget initialization required')
    return book


def require_book_successor(current,incoming):
    validate_book(current)
    validate_book(incoming)
    if current['origin_uuid']!=incoming['origin_uuid']:raise ValueError('paper financial authority changed')
    if incoming['revision']<current['revision']:raise ValueError('older paper revision')
    if incoming['revision']==current['revision'] and incoming!=current:raise ValueError('conflicting paper revision')
    for key in ('bankroll','history_complete_after','baseline_lots','policy'):
        if current[key]!=incoming[key]:raise ValueError('paper baseline changed')
    if current['slot_limit']!=incoming['slot_limit']:
        request_hash=_hash({'action':'set-slots','slot_limit':incoming['slot_limit']})
        if not any(receipt['request_hash']==request_hash and receipt['revision']>current['revision']
                   for receipt in incoming['operations'].values()):
            raise ValueError('paper account capability changed without operation receipt')
    if not set(current['baseline_trades']).issubset(incoming['baseline_trades']):
        raise ValueError('paper financial baseline proof removed')
    for operation,receipt in current['operations'].items():
        if incoming['operations'].get(operation)!=receipt:raise ValueError('paper operation receipt changed')
    if Counter(map(_hash,current['purchases']))-Counter(map(_hash,incoming['purchases'])):
        raise ValueError('paper purchase evidence removed')
    for offer_id,record in current['offers'].items():
        peer=incoming['offers'].get(offer_id)
        if peer is None:raise ValueError('paper offer removed')
        for key in ('name','note','mode','purchase_basis'):
            if record[key]!=peer[key]:raise ValueError('paper offer metadata changed')
        for key in ('item_id','direction','qty','buy_price','created_at'):
            if record['offer'][key]!=peer['offer'][key]:raise ValueError('paper offer economics changed')
        if peer['fills'][:len(record['fills'])]!=record['fills']:raise ValueError('paper fill evidence changed')
        if record['offer']['sold_qty'] and peer['sale_reason']!=record['sale_reason']:
            raise ValueError('paper sale reason changed after a confirmed fill')
        if peer.get('entry_config')!=record.get('entry_config'):
            raise ValueError('paper entry configuration changed')
        if record['offer']['sold_qty'] and peer.get('exit_config')!=record.get('exit_config'):
            raise ValueError('paper exit configuration changed after fill')
        if record['lots'] and peer['lots']!=record['lots']:raise ValueError('paper financial lot changed')
        for key in ('bought_qty','sold_qty','canceled_buy_qty'):
            if peer['offer'][key]<record['offer'][key]:raise ValueError('paper quantity rewound')
        if record['offer']['stage'] in ('collected','canceled') and peer['offer']!=record['offer']:
            raise ValueError('completed paper offer changed')
    for offer_id,receipt in current['collections'].items():
        peer=incoming['collections'].get(offer_id)
        if (peer is None or peer['operation_id']!=receipt['operation_id'] or peer['profit']!=receipt['profit']
                or receipt['status']=='committed' and peer!=receipt):
            raise ValueError('paper collection receipt changed')


def verify_book_financial(book,position_store,trade_store,realizations,batches):
    validate_book(book)
    from rshelper.realization import verify_realization_snapshot
    verify_realization_snapshot(position_store,trade_store['trades'],realizations or {'operations':{}})
    rows={row.get('lot_uid'):row for row in position_store['positions']}
    trades={row.get('record_uuid'):row for row in trade_store['trades']}
    if not set(book['baseline_lots']).issubset(rows) or not set(book['baseline_trades']).issubset(trades):
        raise ValueError('paper baseline financial rows missing')
    for offer_id,record in book['offers'].items():
        offer=record['offer']
        collected=0
        collection=book['collections'].get(offer_id)
        if collection is not None:
            children=batches.get('batches',{}).get(collection['operation_id'],{}).get('operations',[])
            if len(children)!=1:raise ValueError('paper collection financial batch missing')
            intent=realizations.get('operations',{}).get(children[0])
            if (intent is None or not record['lots'] or intent['request']['lot_uid']!=record['lots'][0]
                    or intent['request']['qty']!=offer['sold_qty'] or intent['request']['sell_price']!=offer['sell_price']
                    or intent['request']['reason']!=record['sale_reason']
                    or intent['trade']['profit']!=collection['profit']):
                raise ValueError('paper collection financial evidence differs')
            if collection['status']=='committed' and (not intent['done'] or collection['trade_uuids']!=[intent['trade']['record_uuid']]):
                raise ValueError('paper collected financial receipt missing')
            if intent['done']:collected=offer['sold_qty']
        for lot in record['lots']:
            row=rows.get(lot)
            if (row is None or row['origin_uuid']!=book['origin_uuid'] or row['item_id']!=offer['item_id']
                    or row['buy_price']!=offer['buy_price'] or row['direction']!=offer['direction']
                    or offer['stage']!='collected' and (0 if row.get('tombstone',False) else row['qty'])!=offer['bought_qty']-collected):
                raise ValueError('paper financial holding differs from confirmed quantity')


def _summary(root,book,now,extra_limit=None):
    position_store=state_identity.validate_activated_store(persistence.read_state(root/'positions.json','positions'),
                                               'positions',root/'positions.json')
    rows=position_store['positions']
    limits={int(key):value for key,value in book['buy_limits'].items()}
    if extra_limit is not None:limits.update(extra_limit)
    result=_budget_summary(rows,book['offers'],book['purchases'],
            bankroll=max(0,book['bankroll']+book['realized_profit']),slot_limit=book['slot_limit'],
            history_complete_after=book['history_complete_after'],now=now,buy_limits=limits)
    result['realized_profit']=book['realized_profit']
    result['initial_bankroll']=book['bankroll']
    result['cash_deficit']+=max(0,-book['bankroll']-book['realized_profit'])
    known_lots=set(book['baseline_lots'])|{lot for record in book['offers'].values() for lot in record['lots']}
    known_trades=set(book['baseline_trades'])
    trades=persistence.read_state(root/'trades.json','trades')['trades']
    verify_book_financial(book,position_store,{'trades':trades},
        persistence.read_state(root/'realizations.json','generic'),
        persistence.read_state(root/'realization-batches.json','generic'))
    if (any(row.get('lot_uid') not in known_lots for row in rows)
            or any(row.get('record_uuid') not in known_trades for row in trades)):
        result['unknown'].append('unreconciled financial activity; paper budget recovery required')
    intents=persistence.read_state(root/'realizations.json','generic').get('operations',{})
    if any(collection['status']=='pending' for collection in book['collections'].values()) or any(not intent['done'] for intent in intents.values()):
        result['unknown'].append('unreconciled collection intent; paper budget recovery required')
    return result


def _response(root,book,now,receipt=None,retry=False) -> PaperState:
    return {'revision':book['revision'],'budget':_summary(root,book,now),
            'offers':copy.deepcopy(book['offers']),'offer_id':receipt['offer_id'] if receipt else None,
            'operation_revision':receipt['revision'] if receipt else None,'retry':retry,
            'pending_collections':{key:value['operation_id'] for key,value in book['collections'].items() if value['status']=='pending'}}


def _retry(book,operation_id,request):
    persistence.canonical_uuid(operation_id)
    receipt=book['operations'].get(operation_id)
    if receipt and receipt['request_hash']!=_hash(request):raise ValueError('operation reused with different paper request')
    return receipt


def _write(txn,book,operation_id,request,offer_id,now):
    if now<book['updated_at']:raise ValueError('paper clock moved backward')
    book['updated_at']=now
    book['allocations']={key:qty for key,qty in book['allocations'].items() if now-int(key.split(':')[0])<=600}
    book['revision']+=1
    book['operations'][operation_id]={'request':copy.deepcopy(request),'request_hash':_hash(request),'revision':book['revision'],'offer_id':offer_id}
    validate_book(book)
    txn.stage(FILENAME,book)
    txn.commit(operation_id=operation_id)
    return book['operations'][operation_id]


def initialize_budget(profile,*,bankroll,slot_limit,operation_id,now):
    now=_clock(now)
    persistence.canonical_uuid(operation_id)
    request={'action':'initialize','bankroll':bankroll,'slot_limit':slot_limit}
    root=_root(profile)
    with state_transaction.profile_transaction(profile or 'default',root) as txn:
        origin=_authority(root)
        if (root/FILENAME).exists():
            book=_read(root)
            receipt=_retry(book,operation_id,request)
            if receipt:return _response(root,book,now,receipt,True)
            raise ValueError('paper budget already initialized; baseline cannot be reset')
        activation=state_identity.activation_manifest(root/'identity-activation.json')
        if activation is None or activation.get('paper_budget_origin') is not None:
            raise ValueError('acknowledged paper budget missing; recover instead of resetting baseline')
        rows=persistence.read_state(root/'positions.json','positions')['positions']
        trades=persistence.read_state(root/'trades.json','trades')['trades']
        manifest=persistence.read_state(root/'identity-manifest.json','generic')
        historical=bool(rows or trades or any(key.startswith(('positions:','trades:')) for key in manifest.get('mappings',{})))
        historical=historical or any(proof['kind'] in ('positions','trades') for proof in manifest.get('native',{}).values())
        book={'schema_version':1,'origin_uuid':origin,'revision':0,'updated_at':now,
              'bankroll':bankroll,'slot_limit':slot_limit,'history_complete_after':now+14400 if historical else now,
              'baseline_trades':[row['record_uuid'] for row in trades],
              'baseline_lots':[row['lot_uid'] for row in rows], 'offers':{},'purchases':[],
              'buy_limits':{},'operations':{},'policy':dict(POLICY),'realized_profit':0,'allocations':{},'collections':{}}
        activation['paper_budget_origin']=origin
        txn.stage('identity-activation.json',activation)
        receipt=_write(txn,book,operation_id,request,None,now)
        return _response(root,book,now,receipt)


def budget_snapshot(profile,*,now) -> PaperState:
    now=_clock(now)
    root=_root(profile)
    with state_transaction.profile_transaction(profile or 'default',root):
        return _response(root,_read(root),now)


def operation_request(profile,operation_id):
    persistence.canonical_uuid(operation_id)
    root=_root(profile)
    with state_transaction.profile_transaction(profile or 'default',root):
        receipt=_read(root)['operations'].get(operation_id)
        return copy.deepcopy(receipt['request']) if receipt else None


def _mutation_book(root,expected_revision,operation_id,request):
    origin=_authority(root)
    book=_read(root)
    if book['origin_uuid']!=origin:raise ValueError('paper budget financial authority differs')
    receipt=_retry(book,operation_id,request)
    if receipt:return book,receipt
    if type(expected_revision) is not int or expected_revision!=book['revision']:
        raise ValueError('paper revision conflict; refresh before retrying')
    return book,None


def reserve_budget(profile,*,item_id,name,qty,buy_price,buy_limit,direction,note,expected_revision,operation_id,now,mode='manual-hold',client_ref='',members=None,trader_config=None):
    now=_clock(now)
    for value in (item_id,qty,buy_price,buy_limit):
        if type(value) is not int or not 0<value<2**63:raise ValueError('positive bounded item/quantity/price/buy limit required')
    if qty*buy_price>=2**63:raise ValueError('paper reservation exceeds monetary bounds')
    if direction not in ('traditional','arbitrage'):raise ValueError('invalid paper direction')
    if mode not in ('manual-hold','manual-roundtrip','auto'):raise ValueError('invalid paper execution intent')
    if members is not None and type(members) is not bool:raise ValueError('item membership must be known or unknown')
    for value in (name,note,client_ref):
        if type(value) is not str or len(value)>1000:raise ValueError('invalid paper text')
    request={'action':'reserve','item_id':item_id,'name':name,'qty':qty,'buy_price':buy_price,
             'buy_limit':buy_limit,'direction':direction,'note':note,'mode':mode,'client_ref':client_ref,'members':members}
    root=_root(profile)
    with state_transaction.profile_transaction(profile or 'default',root) as txn:
        book,receipt=_mutation_book(root,expected_revision,operation_id,request)
        if receipt:return _response(root,book,now,receipt,True)
        if (root/'trading_mode.json').exists():
            from rshelper.trading_mode import require_entries_running
            require_entries_running(root)
        budget=_summary(root,book,now,{item_id:buy_limit})
        from rshelper.budget import require_capacity
        require_capacity(budget,item_id=item_id,qty=qty,buy_price=buy_price,members=members)
        if (note=='auto')!=(mode=='auto'):raise ValueError('paper auto policy must preserve auto ownership')
        from rshelper.tuning import config_evidence
        book['offers'][operation_id]={'name':name,'note':note,'lots':[],'fills':[],'mode':mode,'purchase_basis':'paper-fills','sale_reason':None,
            'entry_config':config_evidence(profile,now=now,trader_config=trader_config),'exit_config':None,
            'offer':new_paper_offer(item_id,qty,buy_price,direction,now)}
        book['buy_limits'][str(item_id)]=buy_limit
        receipt=_write(txn,book,operation_id,request,operation_id,now)
        return _response(root,book,now,receipt)


def _publish_lot(txn,profile,record,offer_id,now):
    offer=record['offer']
    if offer['bought_qty'] and not record['lots']:
        request={'item_id':offer['item_id'],'name':record['name'],'qty':offer['bought_qty'],
                 'buy_price':offer['buy_price'],'direction':offer['direction'],'note':record['note'],
                 'entry_sell':None,'entry_offer':None}
        position,_=positions._stage_open_position(txn,profile,request,offer_id,
                             entry_config=record.get('entry_config'),
                             opened_at=datetime.fromtimestamp(now,timezone.utc).isoformat())
        record['lots']=[position.lot_uid]


def cancel_buy(profile,offer_id,*,expected_revision,operation_id,now):
    now=_clock(now)
    persistence.canonical_uuid(offer_id)
    request={'action':'cancel-buy','offer_id':offer_id}
    root=_root(profile)
    with state_transaction.profile_transaction(profile or 'default',root) as txn:
        book,receipt=_mutation_book(root,expected_revision,operation_id,request)
        if receipt:return _response(root,book,now,receipt,True)
        record=book['offers'].get(offer_id)
        if record is None or record['offer']['stage']!='buying':raise ValueError('buy cancellation requires an active buying offer')
        record['offer']=cancel_paper_buy(record['offer'],now)
        _publish_lot(txn,profile,record,offer_id,now)
        receipt=_write(txn,book,operation_id,request,offer_id,now)
        return _response(root,book,now,receipt)


def advance_offer(profile,offer_id,market_snapshot,*,expected_revision,operation_id,now) -> PaperProgress:
    now=_clock(now)
    persistence.canonical_uuid(offer_id)
    request={'action':'advance','offer_id':offer_id}
    root=_root(profile)
    with state_transaction.profile_transaction(profile or 'default',root) as txn:
        book,receipt=_mutation_book(root,expected_revision,operation_id,request)
        if receipt:return {**_response(root,book,now,receipt,True),'reason':None}
        record=book['offers'].get(offer_id)
        if record is None:raise ValueError('unknown paper offer')
        offer=record['offer']
        window=None
        from rshelper.market_data import MarketDataResult,market_payload
        if isinstance(market_snapshot,dict):
            frozen={}
            for endpoint in ('latest','5m'):
                source=market_snapshot.get(endpoint)
                if isinstance(source,dict):
                    payload={str(offer['item_id']):copy.deepcopy(source.get(str(offer['item_id'])))}
                    meta=getattr(source,'market_data',None)
                    frozen[endpoint]=market_payload(replace(meta,data=payload,coverage=dict(meta.coverage))
                                                    if isinstance(meta,MarketDataResult) else payload)
            market_snapshot=frozen
        if isinstance(market_snapshot,dict) and isinstance(market_snapshot.get('5m'),dict):
            candle=market_snapshot['5m'].get(str(offer['item_id']))
            if isinstance(candle,dict):window=candle.get('window_timestamp')
        side='buy' if offer['stage']=='buying' else 'sell'
        leg='Low' if (side=='buy')==(offer['direction']=='traditional') else 'High'
        allocation=str(window)+':'+str(offer['item_id'])+':'+leg
        result=advance_paper_offer(offer,market_snapshot,now,book['policy'],
                                  window_consumed_qty=book['allocations'].get(allocation,0))
        record['offer']=result['offer']
        fill=result['fill']
        if fill is not None:
            window=record['offer']['last_window']
            allocation=str(window)+':'+str(offer['item_id'])+':'+leg
            candle=market_snapshot['5m'][str(offer['item_id'])]
            record['fills'].append({**fill,'window':window,'at':now,
                                   'executed_volume':candle[leg.lower()+'PriceVolume'],
                                   'observed_price':candle['avg'+leg+'Price']})
            book['allocations'][allocation]=book['allocations'].get(allocation,0)+fill['qty']
            if fill['side']=='buy':
                book['purchases'].append({'item_id':offer['item_id'],'qty':fill['qty'],'at':now,'offer_id':offer_id})
            if record['offer']['stage']=='bought':_publish_lot(txn,profile,record,offer_id,now)
        receipt=_write(txn,book,operation_id,request,offer_id,now)
        return {**_response(root,book,now,receipt),'reason':result['reason']}


def start_sale(profile,offer_id,*,qty,sell_price,expected_revision,operation_id,now,reason='manual',trader_config=None):
    now=_clock(now)
    persistence.canonical_uuid(offer_id)
    if type(qty) is not int or not 0<qty<2**63 or type(sell_price) is not int or not 0<sell_price<2**63:
        raise ValueError('positive bounded sale quantity and price required')
    if reason not in ('manual','roundtrip','take_profit','stop_loss','spread_collapse','max_hold'):
        raise ValueError('invalid paper sale reason')
    request={'action':'start-sale','offer_id':offer_id,'qty':qty,'sell_price':sell_price,'reason':reason}
    root=_root(profile)
    with state_transaction.profile_transaction(profile or 'default',root) as txn:
        book,receipt=_mutation_book(root,expected_revision,operation_id,request)
        if receipt:return _response(root,book,now,receipt,True)
        record=book['offers'].get(offer_id)
        if record is None or record['offer']['stage']!='bought' or len(record['lots'])!=1:
            raise ValueError('sale requires a confirmed bought financial lot')
        rows=positions._load(profile)
        lot=next((row for row in rows if row.get('lot_uid')==record['lots'][0] and not row.get('tombstone',False)),None)
        from rshelper.tuning import config_evidence
        _stage_sale(record,lot,qty,sell_price,now,reason,config_evidence(profile,now=now,trader_config=trader_config))
        receipt=_write(txn,book,operation_id,request,offer_id,now)
        return _response(root,book,now,receipt)


def _stage_sale(record,lot,qty,sell_price,now,reason='manual',exit_config=None):
    offer=record['offer']
    if offer['stage']!='bought':raise ValueError('sale requires a bought holding')
    if qty>offer['bought_qty']:raise ValueError('sale quantity exceeds confirmed purchase')
    if sell_price*offer['bought_qty']>=2**63:raise ValueError('paper sale exceeds monetary bounds')
    if (lot is None or lot['qty']!=offer['bought_qty'] or lot['item_id']!=offer['item_id']
            or lot['buy_price']!=offer['buy_price'] or lot['direction']!=offer['direction']):
        raise ValueError('paper offer financial lot changed; reconciliation required')
    offer['sell_price']=sell_price
    offer['canceled_sell_qty']=offer['bought_qty']-qty
    offer['stage']='selling'
    record['sale_reason']=reason
    record['exit_config']=exit_config
    offer['stage_started_at']=datetime.fromtimestamp(now,timezone.utc).isoformat()


def queue_sales(profile,item_id,qty,quotes,*,expected_revision,operation_id,now,position_id=None,client_ref=''):
    now=_clock(now)
    if type(item_id) is not int or not 0<item_id<2**63 or type(qty) is not int or not 0<qty<2**63:
        raise ValueError('positive bounded item and sale quantity required')
    if position_id is not None and (type(position_id) is not int or not 0<position_id<2**63):
        raise ValueError('positive bounded position id required')
    if type(client_ref) is not str or len(client_ref)>1000:raise ValueError('invalid paper client reference')
    if (not isinstance(quotes,dict) or not quotes or set(quotes)-{'traditional','arbitrage'}
            or any(type(price) is not int or not 0<price<2**63 for price in quotes.values())):
        raise ValueError('positive bounded per-direction quote limits required')
    request={'action':'queue-sales','item_id':item_id,'qty':qty,'quotes':dict(quotes),'position_id':position_id,'client_ref':client_ref}
    root=_root(profile)
    with state_transaction.profile_transaction(profile or 'default',root) as txn:
        book,receipt=_mutation_book(root,expected_revision,operation_id,request)
        if receipt:return _response(root,book,now,receipt,True)
        rows=[row for row in positions._load(profile) if not row.get('tombstone',False)
              and row['item_id']==item_id and (position_id is None or row['id']==position_id)]
        rows.sort(key=lambda row:row['id'])
        if sum(row['qty'] for row in rows)<qty:raise ValueError('insufficient recorded holding quantity')
        active={lot:offer_id for offer_id,record in book['offers'].items()
                if record['offer']['stage'] not in ('collected','canceled') for lot in record['lots']}
        remaining=qty
        for row in rows:
            if remaining==0:break
            sell=quotes.get(row['direction'])
            if sell is None:raise ValueError('missing sale quote for holding direction')
            if row.get('note')=='auto':raise ValueError('holding belongs to auto-trader')
            take=min(remaining,row['qty'])
            offer_id=active.get(row['lot_uid'])
            if offer_id is None:
                offer_id=str(uuid5(UUID(operation_id),'sale-holding:'+row['lot_uid']))
                book['offers'][offer_id]=_holding_record(book,row,now,'manual-hold')
            record=book['offers'][offer_id]
            if record['mode']=='auto':raise ValueError('offer belongs to auto-trader')
            from rshelper.tuning import config_evidence
            _stage_sale(record,row,take,sell,now,exit_config=config_evidence(profile,now=now))
            remaining-=take
        receipt=_write(txn,book,operation_id,request,None,now)
        return _response(root,book,now,receipt)


def collect_offer(profile,offer_id,*,expected_revision,operation_id,now):
    from rshelper import realization
    from rshelper.market import ge_tax
    now=_clock(now)
    persistence.canonical_uuid(offer_id)
    request={'action':'collect','offer_id':offer_id}
    root=_root(profile)
    retry=False
    with state_transaction.profile_transaction(profile or 'default',root) as txn:
        book,receipt=_mutation_book(root,expected_revision,operation_id,request)
        record=book['offers'].get(offer_id)
        collection=book['collections'].get(offer_id)
        if receipt:
            retry=True
            if collection is None or collection['operation_id']!=operation_id:raise ValueError('paper collection operation differs')
            if collection['status']=='committed':return _response(root,book,now,receipt,True)
        elif (record is None or record['offer']['stage']!='collectable' or collection is not None
                or len(record['lots'])!=1):
            raise ValueError('collection requires an owned collectable offer')
        if record is None:raise ValueError('paper collection offer missing')
        offer=record['offer']
        realization.prepare_close_batch(profile,offer['item_id'],offer['sold_qty'],operation_id,
                {offer['direction']:offer['sell_price']},lot_uids=record['lots'],reason=record['sale_reason'],
                metadata={'note':'paper','strategy':'auto' if record['mode']=='auto' else 'manual',
                          'exit_config':record.get('exit_config')})
        if not receipt:
            profit=paper_profit(offer)
            book['collections'][offer_id]={'operation_id':operation_id,'status':'pending','profit':profit,'trade_uuids':[]}
            _write(txn,book,operation_id,request,offer_id,now)
    realization.realize_close_batch(profile,operation_id)
    with state_transaction.profile_transaction(profile or 'default',root) as txn:
        _authority(root)
        book=_read(root)
        collection=book['collections'][offer_id]
        if collection['operation_id']!=operation_id:raise ValueError('paper collection operation differs')
        if collection['status']=='committed':return _response(root,book,now,book['operations'][operation_id],True)
        batches=persistence.read_state(root/'realization-batches.json','generic')['batches']
        operations=batches[operation_id]['operations']
        intents=persistence.read_state(root/'realizations.json','generic')['operations']
        proof=[intents[child] for child in operations]
        if len(proof)!=1 or not all(intent['done'] for intent in proof):raise ValueError('paper collection financial publication incomplete')
        if sum(intent['trade']['profit'] for intent in proof)!=collection['profit']:
            raise ValueError('paper collection pinned economics differ')
        collection['status']='committed'
        collection['trade_uuids']=[intent['trade']['record_uuid'] for intent in proof]
        book['baseline_trades'].extend(collection['trade_uuids'])
        book['realized_profit']+=collection['profit']
        book['offers'][offer_id]['offer']['stage']='collected'
        book['offers'][offer_id]['offer']['stage_started_at']=datetime.fromtimestamp(now,timezone.utc).isoformat()
        final_operation=str(uuid5(UUID(operation_id),'paper-collection-finalization'))
        _write(txn,book,final_operation,{'action':'finalize-collection','operation_id':operation_id},offer_id,now)
        return _response(root,book,now,book['operations'][operation_id],retry)


def set_slot_limit(profile,slot_limit,*,expected_revision,operation_id,now):
    now=_clock(now)
    if slot_limit is not None and (type(slot_limit) is not int or slot_limit not in (3,8)):
        raise ValueError('account slot capacity must be unknown/free/member')
    request={'action':'set-slots','slot_limit':slot_limit}
    root=_root(profile)
    with state_transaction.profile_transaction(profile or 'default',root) as txn:
        book,receipt=_mutation_book(root,expected_revision,operation_id,request)
        if receipt:return _response(root,book,now,receipt,True)
        book['slot_limit']=slot_limit
        receipt=_write(txn,book,operation_id,request,None,now)
        return _response(root,book,now,receipt)


def adopt_holding(profile,lot_uid,*,expected_revision,operation_id,now,mode='manual-hold'):
    now=_clock(now)
    persistence.canonical_uuid(lot_uid)
    if mode not in ('manual-hold','auto'):raise ValueError('legacy holding requires an explicit hold/auto policy')
    request={'action':'adopt-holding','lot_uid':lot_uid,'mode':mode}
    root=_root(profile)
    with state_transaction.profile_transaction(profile or 'default',root) as txn:
        book,receipt=_mutation_book(root,expected_revision,operation_id,request)
        if receipt:return _response(root,book,now,receipt,True)
        if any(lot_uid in record['lots'] and record['offer']['stage'] not in ('collected','canceled') for record in book['offers'].values()):
            raise ValueError('holding already owns an active paper offer')
        row=next((row for row in positions._load(profile) if row.get('lot_uid')==lot_uid and not row.get('tombstone',False)),None)
        if row is None or row['origin_uuid']!=book['origin_uuid']:raise ValueError('legacy financial holding unavailable on its authority')
        book['offers'][operation_id]=_holding_record(book,row,now,mode)
        receipt=_write(txn,book,operation_id,request,operation_id,now)
        return _response(root,book,now,receipt)


def _holding_record(book,row,now,mode):
    if (row.get('note')=='auto')!=(mode=='auto'):
        raise ValueError('holding ownership must preserve the auto-trader policy')
    lot_uid=row['lot_uid']
    confirmed=any(record['purchase_basis']=='paper-fills' and lot_uid in record['lots'] for record in book['offers'].values())
    if lot_uid not in book['baseline_lots'] and not confirmed:raise ValueError('holding must belong to the declared baseline or a confirmed paper purchase')
    if row['origin_uuid']!=book['origin_uuid']:raise ValueError('holding belongs to another financial authority')
    instant=datetime.fromtimestamp(now,timezone.utc).isoformat()
    return {'name':row['name'],'note':row.get('note',''),
        'entry_config':row.get('entry_config'),'exit_config':None,
        'lots':[lot_uid],'fills':[],'mode':mode,'sale_reason':None,'purchase_basis':'confirmed-held-remainder' if confirmed else 'legacy-recorded-holding',
        'offer':{'schema_version':1,'stage':'bought','item_id':row['item_id'],'direction':row['direction'],
                 'qty':row['qty'],'bought_qty':row['qty'],'sold_qty':0,'canceled_buy_qty':0,'canceled_sell_qty':0,
                 'buy_price':row['buy_price'],'sell_price':None,'created_at':instant,
                 'stage_started_at':instant,'last_window':None}}


def cancel_sale(profile,offer_id,*,expected_revision,operation_id,now):
    now=_clock(now)
    persistence.canonical_uuid(offer_id)
    request={'action':'cancel-sale','offer_id':offer_id}
    root=_root(profile)
    with state_transaction.profile_transaction(profile or 'default',root) as txn:
        book,receipt=_mutation_book(root,expected_revision,operation_id,request)
        if receipt:return _response(root,book,now,receipt,True)
        record=book['offers'].get(offer_id)
        if record is None or record['offer']['stage']!='selling':raise ValueError('sale cancellation requires an active selling offer')
        offer=record['offer']
        offer['stage']='collectable' if offer['sold_qty'] else 'bought'
        offer['canceled_sell_qty']=offer['bought_qty']-offer['sold_qty'] if offer['sold_qty'] else 0
        if not offer['sold_qty']:
            offer['sell_price']=None
            record['sale_reason']=None
            record['exit_config']=None
        offer['stage_started_at']=datetime.fromtimestamp(now,timezone.utc).isoformat()
        receipt=_write(txn,book,operation_id,request,offer_id,now)
        return _response(root,book,now,receipt)
