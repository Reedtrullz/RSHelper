import math


def _budget_summary(positions, offers, purchases, *, bankroll, slot_limit,
                    history_complete_after, now, buy_limits):
    if type(bankroll) is not int or not 0<=bankroll<2**63:
        raise ValueError('explicit bounded paper bankroll required')
    if slot_limit is not None and (type(slot_limit) is not int or slot_limit not in (3,8)):
        raise ValueError('account slots must be known free/member capacity or unknown')
    if (type(now) not in (int,float) or not math.isfinite(now) or now<0
            or type(history_complete_after) not in (int,float)
            or not math.isfinite(history_complete_after) or history_complete_after<0):
        raise ValueError('invalid budget clock/history boundary')
    holdings = [row for row in positions if not row.get('tombstone',False)]
    active = [record for record in offers.values() if record['offer']['stage'] not in ('collected','canceled')]
    covered_lots = {lot for record in active for lot in record['lots']}
    used_slots = len(active)+sum(row.get('lot_uid') not in covered_lots for row in holdings)
    invested = sum(row['qty']*row['buy_price'] for row in holdings)
    reserved = 0
    reserved_qty = {}
    for record in active:
        order = record['offer']
        if not record['lots']:invested+=order['bought_qty']*order['buy_price']
        if order['stage']=='buying':
            qty = order['qty']-order['bought_qty']-order['canceled_buy_qty']
            reserved+=qty*order['buy_price']
            reserved_qty[order['item_id']]=reserved_qty.get(order['item_id'],0)+qty
    unknown = []
    if slot_limit is None:unknown.append('account slot capacity unknown')
    if now<history_complete_after:unknown.append('purchase history incomplete')
    purchased = {}
    for entry in purchases:
        if (type(entry['at']) not in (int,float) or not math.isfinite(entry['at'])
                or not 0<=entry['at']<=now or type(entry['qty']) is not int or not 0<entry['qty']<2**63):
            raise ValueError('invalid purchase evidence')
        if now-14400<entry['at']<=now:
            purchased[entry['item_id']]=purchased.get(entry['item_id'],0)+entry['qty']
    windows = {}
    involved = set(reserved_qty)|set(purchased)
    pool_limits = [buy_limits.get(item_id) for item_id in involved]
    pool_known = all(type(limit) is int and 0<limit<2**63 for limit in pool_limits)
    pool_floor=min(pool_limits) if pool_known and pool_limits else None
    pool_used,pool_reserved = sum(purchased.values()),sum(reserved_qty.values())
    if involved:unknown.append('linked item groups unverified: conservative shared purchase pool')
    for item_id in sorted(set(buy_limits)|set(reserved_qty)|set(purchased)):
        limit = buy_limits.get(item_id)
        known = type(limit) is int and 0<limit<2**63 and pool_known and now>=history_complete_after
        if not known and now>=history_complete_after:unknown.append('item buy limit unknown: '+str(item_id))
        used,pending = purchased.get(item_id,0),reserved_qty.get(item_id,0)
        effective_limit = min(limit,pool_floor) if known and pool_floor is not None else limit if known else None
        windows[str(item_id)]={'limit':limit,'purchased_qty':used,'reserved_qty':pending,
                              'effective_pool_limit':effective_limit,
                              'pool_purchased_qty':pool_used,'pool_reserved_qty':pool_reserved,
                              'available_qty':max(0,effective_limit-pool_used-pool_reserved) if known else None,
                              'model':'conservative-global-pool-rolling-four-hours'}
    cash = bankroll-invested-reserved
    if not 0<=invested<2**63 or not 0<=reserved<2**63:
        raise ValueError('budget exceeds monetary bounds')
    return {'bankroll':bankroll,'invested_cash':invested,'reserved_cash':reserved,
            'available_cash':max(0,cash),'cash_deficit':max(0,-cash),'used_slots':used_slots,
            'slot_limit':slot_limit,'available_slots':max(0,slot_limit-used_slots) if slot_limit is not None else None,
            'slot_overflow':max(0,used_slots-slot_limit) if slot_limit is not None else None,
            'slot_model':'one-slot-per-open-cycle-conservative','purchase_windows':windows,'unknown':unknown}
