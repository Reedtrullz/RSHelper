"""Conditional arithmetic over frozen, explicitly scoped inventory and quotes."""
import copy
import re
from rshelper.market import ge_tax
from rshelper.state_identity import request_hash

DEFAULT_SPEC={'schema_version':1,'lane':'paper','price_leg':'direction','all_bps':0,
              'item_bps':{},'group_bps':{},'haircut_bps':0}

def _whole(value,low=0,high=2**63-1):
    if type(value) is not int or not low<=value<=high:raise ValueError('bounded whole scenario amount required')
    return value

def evaluate_scenario(holdings,cash,market_revision,specification):
    if not isinstance(holdings,list) or len(holdings)>1000:raise ValueError('scenario inventory exceeds bound')
    if not isinstance(cash,dict) or set(cash)!={'available','reserved'}:raise ValueError('declare available and reserved cash separately')
    for amount in cash.values():
        if amount is not None:_whole(amount)
    if not isinstance(market_revision,str) or not re.fullmatch('[0-9a-f]{64}',market_revision):raise ValueError('frozen market revision required')
    spec=specification
    if not isinstance(spec,dict) or set(spec)!=set(DEFAULT_SPEC) or type(spec['schema_version']) is not int or spec['schema_version']!=1:
        raise ValueError('scenario specification fields differ')
    if spec['lane'] not in ('paper','observed-manual') or spec['price_leg'] not in ('direction','high','low'):
        raise ValueError('explicit scenario lane and price leg required')
    _whole(spec['all_bps'],-10000,100000);_whole(spec['haircut_bps'],0,10000)
    for scopes in (spec['item_bps'],spec['group_bps']):
        if not isinstance(scopes,dict) or len(scopes)>1000:raise ValueError('bounded scenario shock scope required')
        for key,amount in scopes.items():
            if not isinstance(key,str) or not key or len(key.encode())>128:raise ValueError('bounded scenario scope label required')
            _whole(amount,-10000,100000)
    ids=set();groups=set()
    for row in holdings:
        if not isinstance(row,dict) or set(row)!={'item_id','qty','buy_price','direction','high','low','group'}:
            raise ValueError('scenario holding fields differ')
        for field in ('item_id','qty','buy_price'):_whole(row[field],1)
        if row['direction'] not in ('traditional','arbitrage'):raise ValueError('scenario direction unknown')
        if not isinstance(row['group'],str) or len(row['group'].encode())>128:raise ValueError('bounded manually declared group required')
        for field in ('high','low'):
            if row[field] is not None:_whole(row[field],1)
        ids.add(str(row['item_id']));groups.add(row['group'])
    if set(spec['item_bps'])-ids or set(spec['group_bps'])-(groups-{''}):raise ValueError('scenario scope has no declared holdings')
    rows=[];missing=set();concentration={};baseline=0;baseline_net=0;marked=0;modeled=0;cost=0
    for holding in holdings:
        item=holding['item_id'];qty=holding['qty'];cost+=holding['buy_price']*qty
        leg=spec['price_leg']
        if leg=='direction':leg='high' if holding['direction']=='traditional' else 'low'
        price=holding[leg]
        shock=spec['all_bps']+spec['item_bps'].get(str(item),0)+spec['group_bps'].get(holding['group'],0)
        _whole(shock,-10000,100000)
        row={**copy.deepcopy(holding),'price_leg':leg,'shock_bps':shock,'baseline_price':price,
             'shocked_price':None,'haircut_price':None,'after_tax_value':None}
        exposure=concentration.setdefault(item,{'item_id':item,'baseline_gross':0,'share_pct':None})
        if price is None:missing.add(item)
        else:
            stressed=price*(10000+shock)//10000
            haircut=stressed*(10000-spec['haircut_bps'])//10000
            net_value=(haircut-ge_tax(haircut))*qty
            row.update(shocked_price=stressed,haircut_price=haircut,after_tax_value=net_value)
            exposure['baseline_gross']+=price*qty
            baseline+=price*qty;baseline_net+=(price-ge_tax(price))*qty
            marked+=stressed*qty;modeled+=net_value
        rows.append(row)
    if max(cost,baseline,baseline_net,marked,modeled)>=2**63:raise ValueError('scenario aggregate exceeds monetary bound')
    complete=not missing
    cash_total=sum(cash.values()) if all(value is not None for value in cash.values()) else None
    if cash_total is not None:_whole(cash_total)
    base_equity=baseline_net+cash_total if complete and cash_total is not None else None
    equity=modeled+cash_total if complete and cash_total is not None else None
    if base_equity is not None:_whole(base_equity)
    if equity is not None:_whole(equity)
    if complete and baseline:
        for exposure in concentration.values():exposure['share_pct']=round(exposure['baseline_gross']/baseline*100,4)
    concentrations=[{**exposure,'known_baseline_gross':exposure['baseline_gross'],
        'baseline_gross':None if exposure['item_id'] in missing else exposure['baseline_gross']}
        for exposure in sorted(concentration.values(),key=lambda row:(-row['baseline_gross'],row['item_id']))]
    frozen={'holdings':copy.deepcopy(holdings),'cash':copy.deepcopy(cash),'market_revision':market_revision,'specification':copy.deepcopy(spec)}
    return {'schema_version':1,'lane':spec['lane'],'sensitivity':'private','input':frozen,'input_sha256':request_hash(frozen),
            'market_revision':market_revision,'cash':copy.deepcopy(cash),'cost_basis':cost,'coverage_complete':complete,
            'missing_item_ids':sorted(missing),'known_baseline_gross':baseline,'known_modeled_after_tax':modeled,
            'baseline_gross':baseline if complete else None,'baseline_after_tax':baseline_net if complete else None,
            'marked_value':marked if complete else None,'modeled_after_tax':modeled if complete else None,
            'baseline_equity':base_equity,'scenario_equity':equity,
            'equity_change_pct':round((equity-base_equity)/base_equity*100,4) if base_equity and equity is not None else None,
            'concentration':concentrations,
            'rows':rows,'assumptions':['Shocks are additive basis points; group membership is manually declared',
                'Prices and haircut fills round down per unit; GE sell tax applies per unit',
                'Available cash excludes reserved cash; both are unchanged by this scenario',
                'Conditional arithmetic; no probability, forecast, execution or liquidity guarantee']}
