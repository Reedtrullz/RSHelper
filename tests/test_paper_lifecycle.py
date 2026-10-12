from datetime import datetime,timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from rshelper.ge_offers import advance_paper_offer
from rshelper.market_data import MarketDataResult,market_payload
from rshelper.market_validation import validate_payload

POLICY = {'model_id':'paper-conservative-v1','participation_bps':100,'max_window_age_sec':600}

def offer():
    return {'schema_version':1,'stage':'buying','item_id':1,'direction':'traditional',
            'qty':20,'bought_qty':0,'sold_qty':0,'canceled_buy_qty':0,'canceled_sell_qty':0,
            'buy_price':91,'sell_price':None,'created_at':datetime.fromtimestamp(1500,timezone.utc).isoformat(),
            'stage_started_at':datetime.fromtimestamp(1500,timezone.utc).isoformat(),
            'last_window':None}

def market(window: int | None=1800,now=2100,volume=1000,source='wiki',stale=False):
    def wrapped(data,kind):
        return market_payload(MarketDataResult(data,source,'network',now,now,now,stale,kind,{source:1}))
    return {'latest':wrapped({'1':{'high':100,'low':90,'highTime':now,'lowTime':now}},'unknown'),
            '5m':wrapped({'1':{'avgHighPrice':100,'avgLowPrice':90,'highPriceVolume':volume,
                              'lowPriceVolume':volume,'window_timestamp':window}},
                          'executed-trades' if source=='wiki' else 'standing-orders')}

class PaperLifecycleTest(unittest.TestCase):
    def test_partial_buy_repeated_window_and_separate_sell_progression(self):
        before = offer()
        result = advance_paper_offer(before,market(),2100,POLICY)
        self.assertEqual(result['fill'],{'side':'buy','qty':10,'price':91,'tax_paid':0})
        self.assertEqual(result['offer']['bought_qty'],10)
        self.assertEqual(before,offer())
        repeated = advance_paper_offer(result['offer'],market(),2200,POLICY)
        self.assertIsNone(repeated['fill'])
        bought = advance_paper_offer(result['offer'],market(2100,2400),2400,POLICY)['offer']
        self.assertEqual(bought['stage'],'bought')
        self.assertEqual(bought['bought_qty'],20)
        bought.update(stage='selling',sell_price=100)
        first_sale = advance_paper_offer(bought,market(2400,2700),2700,POLICY)
        self.assertEqual(first_sale['fill'],{'side':'sell','qty':10,'price':100,'tax_paid':20})
        sold = advance_paper_offer(first_sale['offer'],market(2700,3000),3000,POLICY)['offer']
        self.assertEqual((sold['stage'],sold['sold_qty']),('collectable',20))

    def test_a_new_sell_stage_cannot_consume_prior_market_evidence(self):
        row = dict(offer(),stage='selling',bought_qty=20,sell_price=100,
                   stage_started_at=datetime.fromtimestamp(2000,timezone.utc).isoformat())
        self.assertIsNone(advance_paper_offer(row,market(),2100,POLICY)['fill'])

    def test_shared_side_allocation_cannot_repeat_full_capacity_per_offer(self):
        result = advance_paper_offer(offer(),market(),2100,POLICY,window_consumed_qty=9)
        self.assertEqual(result['fill']['qty'],1)
        exhausted=advance_paper_offer(offer(),market(),2100,POLICY,window_consumed_qty=10)
        self.assertIsNone(exhausted['fill'])
        self.assertEqual(exhausted['offer']['last_window'],1800)
        self.assertIsNone(advance_paper_offer(exhausted['offer'],market(),2100,POLICY,window_consumed_qty=0)['fill'])
        with self.assertRaises(ValueError):
            advance_paper_offer(offer(),market(),2100,POLICY,window_consumed_qty=-1)

    def test_legacy_unknown_and_invalid_clocks_never_fabricate_progress(self):
        row = {'schema_version':1,'stage':'legacy-unknown','bought_qty':None,'sold_qty':None}
        result = advance_paper_offer(row,market(),2100,POLICY)
        self.assertEqual(result['offer'],row)
        self.assertIsNone(result['fill'])
        for now in (True,-1,float('nan'),float('inf'),1e100):
            with self.subTest(now=now),self.assertRaises(ValueError):
                advance_paper_offer(offer(),market(),now,POLICY)

    def test_unknown_zero_proxy_or_stale_evidence_never_fills_with_elapsed_time(self):
        for snapshot in ({},market(volume=0),market(source='ge-tracker'),market(stale=True)):
            result = advance_paper_offer(offer(),snapshot,2100,POLICY)
            self.assertIsNone(result['fill'])
            self.assertEqual(result['offer']['bought_qty'],0)
            self.assertTrue(result['reason'])

    def test_old_incomplete_future_or_missing_windows_are_held(self):
        for window in (900,1499,2100,2400,None,True):
            with self.subTest(window=window):
                self.assertIsNone(advance_paper_offer(offer(),market(window),2100,POLICY)['fill'])

    def test_limit_prices_and_unusable_quotes_do_not_invent_fills(self):
        for change in ('too-expensive','bad-latest','missing-window-price'):
            snapshot = market()
            if change=='too-expensive':snapshot['5m']['1']['avgLowPrice']=92
            elif change=='bad-latest':snapshot['latest']['1']['high']=0
            else:snapshot['5m']['1'].pop('avgLowPrice')
            self.assertIsNone(advance_paper_offer(offer(),snapshot,2100,POLICY)['fill'])

    def test_invalid_policy_and_quantity_conservation_are_rejected(self):
        for policy in ({},dict(POLICY,participation_bps=True),dict(POLICY,participation_bps=101),
                       dict(POLICY,max_window_age_sec=3600)):
            with self.subTest(policy=policy),self.assertRaises(ValueError):
                advance_paper_offer(offer(),market(),2100,policy)
        for changes in ({'bought_qty':21},{'sold_qty':1},{'qty':True},{'canceled_buy_qty':21},
                        {'stage':'selling','bought_qty':20,'sell_price':None}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                advance_paper_offer(dict(offer(),**changes),market(),2100,POLICY)

    def test_api_window_timestamp_is_retained_without_inventing_legacy_evidence(self):
        row = {'avgHighPrice':100,'avgLowPrice':90,'highPriceVolume':1000,'lowPriceVolume':1000}
        response = validate_payload('5m',{'timestamp':1800,'data':{'1':row}},2100)
        self.assertEqual(response['data']['1']['window_timestamp'],1800)
        self.assertNotIn('window_timestamp',row)
        self.assertNotIn('window_timestamp',validate_payload('5m',{'1':row},2100)['data']['1'])
        cached = validate_payload('5m',response['data'],2200)['data']['1']
        self.assertEqual(cached['window_timestamp'],1800)

if __name__=='__main__':unittest.main()
