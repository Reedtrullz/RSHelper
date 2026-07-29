"""Property-based invariant tests using fixed-seed random fuzzing."""

import math
import random
import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from rshelper.analysis import analyze_timeseries
from rshelper.scanner import trade_size
from rshelper.models import Item

random.seed(42)
N = 5000  # trials per invariant


def fake_ts(highs: list[int], lows: list[int], volumes: list[int] | None = None):
    """Build a list of timeseries dicts from parallel price arrays."""
    if volumes is None:
        volumes = [100] * len(highs)
    return [
        {
            "avgHighPrice": h, "avgLowPrice": l,
            "highPriceVolume": v // 2, "lowPriceVolume": v // 2,
            "timestamp": i * 300,
        }
        for i, (h, l, v) in enumerate(zip(highs, lows, volumes))
    ]


class TestProperties(unittest.TestCase):

    def test_confidence_in_bounds(self):
        for _ in range(N):
            highs = [random.randint(10, 2_000_000_000) for _ in range(12)]
            lows = [h - random.randint(-5000, 5000) for h in highs]
            lows = [max(1, l) for l in lows]
            ts = fake_ts(highs, lows)
            result = analyze_timeseries(1, ts, current_buy=highs[0], current_sell=lows[0])
            self.assertIsNotNone(result)
            self.assertGreaterEqual(result.confidence, 0.0)
            self.assertLessEqual(result.confidence, 1.0)
            self.assertGreaterEqual(result.reliability, 0.0)
            self.assertLessEqual(result.reliability, 1.0)
            self.assertGreaterEqual(result.profitability_score, 0.0)
            self.assertLessEqual(result.profitability_score, 1.0)

    def test_sub_scores_in_bounds(self):
        for _ in range(N):
            highs = [random.randint(10, 2_000_000_000) for _ in range(12)]
            lows = [h - random.randint(-5000, 5000) for h in highs]
            lows = [max(1, l) for l in lows]
            ts = fake_ts(highs, lows)
            result = analyze_timeseries(1, ts, current_buy=highs[0], current_sell=lows[0])
            self.assertIsNotNone(result)
            self.assertLessEqual(result.spread_score, 1.0)
            self.assertGreaterEqual(result.volume_score, 0.0)
            self.assertLessEqual(result.volume_score, 1.0)
            self.assertGreaterEqual(result.volatility_score, 0.0)
            self.assertLessEqual(result.volatility_score, 1.0)

    def test_margin_volatility_nonnegative(self):
        for _ in range(N):
            highs = [random.randint(10, 2_000_000_000) for _ in range(12)]
            lows = [h - random.randint(-5000, 5000) for h in highs]
            lows = [max(1, l) for l in lows]
            ts = fake_ts(highs, lows)
            result = analyze_timeseries(1, ts, current_buy=highs[0], current_sell=lows[0])
            self.assertIsNotNone(result)
            self.assertGreaterEqual(result.margin_volatility, 0.0)

    def test_trade_size_capped_by_limit(self):
        for _ in range(N):
            buy_limit = random.randint(1, 15000)
            buy_price = random.randint(1, 2_000_000_000)
            capital = random.randint(1, 2_000_000_000)
            item = Item(
                id=1, name="Test", members=False,
                buy_limit=buy_limit, alch_value=0,
                buy_price=buy_price, sell_price=buy_price - 1,
                volume=random.randint(0, 10000),
            )
            qty = trade_size(item, capital)
            self.assertLessEqual(qty, buy_limit,
                f"trade_size {qty} > buy_limit {buy_limit}")

    def test_trade_size_capped_by_capital(self):
        for _ in range(N):
            buy_price = random.randint(1, 2_000_000)
            capital = random.randint(1, 2_000_000_000)
            item = Item(
                id=1, name="Test", members=False,
                buy_limit=15000, alch_value=0,
                buy_price=buy_price, sell_price=buy_price - 1,
                volume=1000,
            )
            qty = trade_size(item, capital)
            self.assertLessEqual(qty * buy_price, capital,
                f"qty*buy_price {qty * buy_price} > capital {capital}")

    def test_trade_size_at_least_one(self):
        item = Item(
            id=1, name="Test", members=False,
            buy_limit=15000, alch_value=0,
            buy_price=100, sell_price=99,
            volume=1,
        )
        qty = trade_size(item, 1000)
        self.assertGreaterEqual(qty, 1)

    def test_direction_arbitrage_vs_traditional(self):
        """Same data, different directions → margins should differ."""
        highs = [200, 210, 205, 200, 210, 205, 200, 210]
        lows = [180, 185, 190, 180, 185, 190, 180, 185]
        ts = fake_ts(highs, lows)
        arb = analyze_timeseries(1, ts, current_buy=200, current_sell=180, direction="arbitrage")
        trad = analyze_timeseries(1, ts, current_buy=200, current_sell=180, direction="traditional")
        self.assertIsNotNone(arb)
        self.assertIsNotNone(trad)
        # Avg margins should have opposite signs (arb: low-high negative, trad: high-low positive)
        self.assertLess(arb.avg_margin, 0, f"Arbitrage margin {arb.avg_margin} should be negative")
        self.assertGreater(trad.avg_margin, 0, f"Traditional margin {trad.avg_margin} should be positive")

    def test_reliable_loser_zero_confidence(self):
        """A consistently negative margin should get near-zero confidence."""
        highs = [200] * 12
        lows = [180] * 12  # consistently negative margin
        ts = fake_ts(highs, lows)
        result = analyze_timeseries(1, ts, current_buy=200, current_sell=180)
        self.assertIsNotNone(result)
        # Reliability should be high (consistent pattern), confidence near zero (unprofitable)
        self.assertGreaterEqual(result.reliability, 0.35)
        self.assertAlmostEqual(result.confidence, 0.0, delta=0.15)


if __name__ == "__main__":
    unittest.main()
