from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from rshelper.budget import _budget_summary

def pending(qty=20,bought=5,canceled=0,stage='buying',lots=None):
    return {'offer':{'item_id':1,'stage':stage,'qty':qty,'bought_qty':bought,
                     'canceled_buy_qty':canceled,'buy_price':100},'lots':lots or []}

class BudgetSummaryTest(unittest.TestCase):
    def summary(self,positions=None,offers=None,purchases=None,limits=None,slots: int | None=3,complete=0,bankroll=10000):
        return _budget_summary(positions or [],offers or {},purchases or [],
                               bankroll=bankroll,slot_limit=slots,history_complete_after=complete,
                               now=20000,buy_limits=limits or {1:100})

    def test_manual_holdings_and_pending_auto_buy_share_cash_and_slots(self):
        rows = [{'qty':10,'buy_price':100,'lot_uid':'manual'}]
        result = self.summary(rows,{'auto':pending()})
        self.assertEqual(result['invested_cash'],1500)
        self.assertEqual(result['reserved_cash'],1500)
        self.assertEqual(result['available_cash'],7000)
        self.assertEqual(result['used_slots'],2)
        self.assertEqual(result['available_slots'],1)
        self.assertEqual(result['purchase_windows']['1']['reserved_qty'],15)

    def test_partial_buy_cancellation_releases_only_unfilled_capacity(self):
        initial = self.summary(offers={'auto':pending()})
        canceled = self.summary(offers={'auto':pending(canceled=15,stage='bought')})
        self.assertEqual(canceled['reserved_cash'],0)
        self.assertEqual(canceled['invested_cash'],500)
        self.assertEqual(canceled['available_cash']-initial['available_cash'],1500)
        self.assertEqual(canceled['purchase_windows']['1']['reserved_qty'],0)

    def test_confirmed_lot_and_offer_do_not_double_count_cost_or_slot(self):
        rows = [{'qty':20,'buy_price':100,'lot_uid':'confirmed'}]
        result = self.summary(rows,{'auto':pending(bought=20,stage='bought',lots=['confirmed'])})
        self.assertEqual(result['invested_cash'],2000)
        self.assertEqual(result['used_slots'],1)
        self.assertEqual(result['available_cash'],8000)

    def test_purchase_window_unknown_limits_and_exact_boundary_are_explicit(self):
        purchases = [{'item_id':1,'qty':30,'at':5600}, {'item_id':1,'qty':40,'at':5601}]
        result = self.summary(purchases=purchases,offers={'auto':pending()})
        self.assertEqual(result['purchase_windows']['1']['purchased_qty'],40)
        self.assertEqual(result['purchase_windows']['1']['available_qty'],45)
        unknown = self.summary(complete=20001,slots=None,limits={1:0})
        self.assertIsNone(unknown['available_slots'])
        self.assertIsNone(unknown['purchase_windows']['1']['available_qty'])
        self.assertIn('purchase history incomplete',unknown['unknown'])

    def test_legacy_overflow_and_negative_cash_remain_visible_without_liquidation(self):
        rows = [{'qty':10,'buy_price':100,'lot_uid':str(i)} for i in range(4)]
        result = self.summary(rows,bankroll=1000)
        self.assertEqual(result['used_slots'],4)
        self.assertEqual(result['slot_overflow'],1)
        self.assertEqual(result['available_cash'],0)
        self.assertEqual(result['cash_deficit'],3000)
        self.assertEqual(len(rows),4)

    def test_possible_linked_variants_cannot_bypass_the_shared_pool(self):
        purchases = [{'item_id':2,'qty':80,'at':19000}]
        result = self.summary(purchases=purchases,limits={1:100,2:100})
        self.assertEqual(result['purchase_windows']['1']['available_qty'],20)
        result = self.summary(purchases=purchases,offers={'auto':pending()},limits={1:100,2:100})
        self.assertEqual(result['purchase_windows']['1']['available_qty'],5)
        self.assertEqual(result['purchase_windows']['2']['available_qty'],5)
        self.assertIn('linked item groups unverified',' '.join(result['unknown']))
        unknown = self.summary(purchases=purchases,limits={1:100})
        self.assertIsNone(unknown['purchase_windows']['1']['available_qty'])

if __name__=='__main__':unittest.main()
