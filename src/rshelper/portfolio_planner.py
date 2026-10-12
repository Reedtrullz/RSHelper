import json
import math
import time


MAX_PLAN_CANDIDATES = 50


def build_plan(candidates, latest, cfg, paper_state, *, now=None, top=None):
    if now is None:
        now = time.time()
    if type(now) not in (int, float) or not math.isfinite(now) or now < 0:
        raise ValueError('invalid planner clock')
    if top is not None and (type(top) is not int or not 0 < top <= MAX_PLAN_CANDIDATES):
        raise ValueError('top must be 1..50')
    from .trader import ENTRY_MAX_AGE, _fresh, price_issue, size_position
    from .market_data import provenance
    budget = paper_state.get('budget')
    if not isinstance(budget, dict):
        raise ValueError('paper budget snapshot required; initialize trade budget first')
    evidence = provenance(latest)
    allocations = []
    abstentions = []
    occupied = set()
    for record in paper_state.get('offers', {}).values():
        offer = record.get('offer', {})
        if offer.get('stage') not in ('collected', 'canceled'):
            occupied.add(offer.get('item_id'))
    unknown = list(budget.get('unknown', []))
    invested = budget['invested_cash'] + budget['reserved_cash']
    available_cash = budget['available_cash']
    available_slots = budget['available_slots']
    for item in candidates:
        if top is not None and len(allocations) >= top:
            break
        if evidence['source'] == 'unknown' or evidence['stale']:
            abstentions.append({'item_id': item.id, 'reason': 'market evidence unknown or stale'})
            continue
        if available_slots is not None and available_slots < 1:
            abstentions.append({'item_id': item.id, 'reason': 'no paper slot capacity'})
            continue
        if item.id in occupied:
            abstentions.append({'item_id': item.id, 'reason': 'item already has an open paper cycle'})
            continue
        quote = latest.get(str(item.id))
        if not isinstance(quote, dict) or price_issue(quote, now=now) or not _fresh(quote, ENTRY_MAX_AGE, now):
            abstentions.append({'item_id': item.id, 'reason': 'quote unavailable, stale or failed price sanity'})
            continue
        buy = quote.get('low')
        if type(buy) is not int or buy <= 0:
            abstentions.append({'item_id': item.id, 'reason': 'buyable price unavailable'})
            continue
        qty = min(size_position(cfg, invested, item), available_cash // buy)
        if qty <= 0:
            abstentions.append({'item_id': item.id, 'reason': 'known sizing or cash capacity unavailable'})
            continue
        window = budget.get('purchase_windows', {}).get(str(item.id))
        available_qty = window.get('available_qty') if isinstance(window, dict) else None
        if available_qty is None:
            abstentions.append({'item_id': item.id, 'reason': 'buy-limit window unknown'})
            continue
        if available_qty < qty:
            qty = available_qty
        if qty <= 0:
            abstentions.append({'item_id': item.id, 'reason': 'shared purchase limit exhausted'})
            continue
        planned_cost = qty * buy
        if planned_cost > available_cash:
            abstentions.append({'item_id': item.id, 'reason': 'shared paper cash exhausted'})
            continue
        allocations.append({
            'item_id': item.id,
            'name': item.name,
            'qty': qty,
            'buy_price': buy,
            'cost': planned_cost,
            'evidence': {key: evidence.get(key) for key in
                         ('source', 'delivery', 'stale', 'fetched_at', 'last_success_at')},
        })
        invested += planned_cost
        available_cash -= planned_cost
        if available_slots is not None:
            available_slots -= 1
    result = {
        'proposal_only': True,
        'allocations': allocations,
        'abstentions': abstentions,
        'simulated_budget': {
            'invested_cash': invested,
            'available_cash': available_cash,
            'available_slots': available_slots,
        },
        'unknown': unknown,
        'modeled_count': len(allocations),
    }
    return json.loads(json.dumps(result, allow_nan=False))
