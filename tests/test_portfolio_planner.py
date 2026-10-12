import json
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from rshelper.market_data import MarketDataResult, market_payload
from rshelper.models import Item
from rshelper.portfolio_planner import MAX_PLAN_CANDIDATES, build_plan


class FakeCfg:
    capital = 1000
    trade_capital_frac = 0.5


def item(iid):
    return Item(iid, 'Item ' + str(iid), False, 100, 100, 100, 95, 1000)


def latest(now):
    return market_payload(MarketDataResult(
        {'2': {'high': 100, 'low': 95, 'highTime': now, 'lowTime': now}},
        'wiki', 'network', now, now, now, False, 'executed-trades', {'wiki': 1}))


def paper(budget=None, offers=None):
    windows = {str(i): {'limit': 100, 'purchased_qty': 0, 'reserved_qty': 0,
                        'available_qty': 100} for i in range(2, 6)}
    return {
        'budget': budget or {
            'bankroll': 1000, 'invested_cash': 100, 'reserved_cash': 0,
            'available_cash': 900, 'used_slots': 1, 'slot_limit': 8,
            'available_slots': 7, 'slot_overflow': 0, 'unknown': [],
            'purchase_windows': windows,
        },
        'offers': offers or {},
    }


class PortfolioPlannerTests(unittest.TestCase):
    def test_allocates_with_evidence_and_updates_simulated_budget(self):
        now = 1_000_000
        result = build_plan([item(2)], latest(now), FakeCfg(), paper(), now=now, top=5)
        self.assertTrue(result['proposal_only'])
        self.assertEqual(len(result['allocations']), 1)
        row = result['allocations'][0]
        self.assertEqual(row['item_id'], 2)
        self.assertGreater(row['qty'], 0)
        self.assertLessEqual(row['cost'], row['qty'] * row['buy_price'])
        self.assertEqual(row['evidence']['source'], 'wiki')
        self.assertEqual(result['simulated_budget']['available_cash'], 900 - row['cost'])
        self.assertEqual(result['simulated_budget']['available_slots'], 6)

    def test_abstains_when_quote_unavailable(self):
        now = 1_000_000
        result = build_plan([item(9)], latest(now), FakeCfg(), paper(), now=now, top=5)
        self.assertEqual(result['allocations'], [])
        self.assertEqual(result['abstentions'][0]['item_id'], 9)

    def test_abstains_on_stale_or_unknown_source(self):
        now = 1_000_000
        data = MarketDataResult(
            {'2': {'high': 100, 'low': 95, 'highTime': now, 'lowTime': now}},
            'wiki', 'network', now, now, now, True, 'executed-trades', {'wiki': 1})
        stale = market_payload(data)
        result = build_plan([item(2)], stale, FakeCfg(), paper(), now=now, top=5)
        self.assertEqual(result['allocations'], [])
        self.assertIn('evidence', result['abstentions'][0]['reason'])

        unknown_view = {'2': {'high': 100, 'low': 95, 'highTime': now, 'lowTime': now}}
        result = build_plan([item(2)], unknown_view, FakeCfg(), paper(), now=now, top=5)
        self.assertEqual(result['allocations'], [])

    def test_respects_top_and_consecutive_budget_deduction(self):
        now = 1_000_000
        items = [item(2 + i) for i in range(4)]
        quotes = {str(2 + i): {'high': 100, 'low': 95, 'highTime': now, 'lowTime': now} for i in range(4)}
        payload = market_payload(MarketDataResult(
            quotes, 'wiki', 'network', now, now, now, False, 'executed-trades', {'wiki': 4}))
        result = build_plan(items, payload, FakeCfg(), paper(), now=now, top=2)
        self.assertEqual(len(result['allocations']), 2)
        self.assertEqual(result['abstentions'], [])
        costs = [row['cost'] for row in result['allocations']]
        self.assertEqual(sum(costs), 900 - result['simulated_budget']['available_cash'])


    def test_frozen_inputs_reproduce_identically(self):
        now = 1_000_000
        inputs = ([item(2)], latest(now), FakeCfg(), paper())
        first = build_plan(*inputs, now=now, top=5)
        second = build_plan(*inputs, now=now, top=5)
        self.assertEqual(first, second)

    def test_invalid_top_rejected(self):
        now = 1_000_000
        with self.assertRaises(ValueError):
            build_plan([item(2)], latest(now), FakeCfg(), paper(), now=now, top=0)
        with self.assertRaises(ValueError):
            build_plan([item(2)], latest(now), FakeCfg(), paper(), now=now, top=MAX_PLAN_CANDIDATES + 1)


if __name__ == '__main__':
    unittest.main()
