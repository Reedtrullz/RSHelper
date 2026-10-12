"""Quote-independent item identity and bounded full-catalog discovery."""
from rshelper.market import ge_tax,price_issue,safe_int
from rshelper.market_data import provenance


def search_catalog(query,mapping,*,limit=50):
    if not isinstance(query,str) or len(query)>200:raise ValueError('item query must be at most 200 characters')
    if type(limit) is not int or not 1<=limit<=50:raise ValueError('catalog limit must be 1..50')
    query=query.strip().casefold()
    rows=[entry for entry in mapping if query in str(entry.get('name','')).casefold() or query==str(entry.get('id'))]
    rows.sort(key=lambda row:(0 if query==str(row['id']) else 1 if query==row['name'].casefold() else 2,
                              row['name'].casefold(),row['id']))
    return [{key:row.get(key) for key in ('id','name','members','limit','highalch')} for row in rows[:limit]]


def resolve_item(query,mapping):
    if not isinstance(query,str) or not query.strip() or len(query)>200:raise ValueError('nonempty bounded item query required')
    query=query.strip().casefold()
    identifiers=[row for row in mapping if str(row.get('id'))==query]
    exact=[row for row in mapping if str(row.get('name','')).casefold()==query]
    matches=identifiers or exact or [row for row in mapping if query in str(row.get('name','')).casefold()]
    if len(matches)!=1:raise ValueError('item match is ambiguous; choose an ID' if matches else 'item not found')
    return matches[0]


def item_details(query,mapping,latest,*,now=None):
    entry=resolve_item(query,mapping)
    price=latest.get(str(entry['id']))
    evidence=provenance(latest)
    reason=price_issue(price,now=now) if isinstance(price,dict) else 'no quote'
    if reason is None and (evidence['source']=='unknown' or evidence['stale']):reason='quote provenance is unknown or stale'
    usable=reason is None
    buy=safe_int(price.get('high')) if usable else None
    sell=safe_int(price.get('low')) if usable else None
    tax=ge_tax(sell) if usable else None
    net=sell-buy-tax if usable else None
    return {'id':entry['id'],'name':entry['name'],'members':entry.get('members'),
        'buy_limit':entry.get('limit'),'alch_value':entry.get('highalch'),
        'quote':{'usable':usable,'reason':reason,'buy_price':buy,'sell_price':sell,'tax':tax,'net_profit':net,
            'margin_pct':(sell-buy)/buy*100 if usable and buy else None,
            'roi_pct':net/buy*100 if usable and buy else None,
            'buy_time':price.get('highTime') if isinstance(price,dict) else None,
            'sell_time':price.get('lowTime') if isinstance(price,dict) else None},
        'market_data':{'mapping':provenance(mapping),'latest':evidence}}
