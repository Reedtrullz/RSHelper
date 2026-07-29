"""Tests for historical analysis engine."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from rshelper.analysis import analyze_timeseries


def _make_datapoints(prices: list[tuple[int, int]], base_ts=1700000000):
    """Helper: list of (avgHighPrice, avgLowPrice) -> timeseries datapoints."""
    return [
        {
            "timestamp": base_ts + i * 300,
            "avgHighPrice": high,
            "avgLowPrice": low,
            "highPriceVolume": 100,
            "lowPriceVolume": 100,
        }
        for i, (high, low) in enumerate(prices)
    ]


def test_consistent_margin():
    """Item with steady positive margins scores high consistency."""
    dp = _make_datapoints([(850, 1200)] * 50)
    result = analyze_timeseries(1, dp, current_buy=850, current_sell=1200)
    assert result is not None, "should return analysis"
    assert result.margin_consistency > 0.9, f"consistency {result.margin_consistency} should be >0.9"
    assert result.confidence > 0.5, f"confidence {result.confidence} should be >0.5"
    assert result.avg_margin > 0, f"avg_margin {result.avg_margin} should be positive"
    print("  PASSED test_consistent_margin")


def test_no_margin_item():
    """Item where buy >= sell should have low consistency."""
    dp = _make_datapoints([(1000, 900)] * 50)
    result = analyze_timeseries(1, dp, current_buy=1000, current_sell=900)
    assert result is not None
    assert result.margin_consistency < 0.1, f"consistency {result.margin_consistency} should be <0.1"
    print("  PASSED test_no_margin_item")


def test_too_few_datapoints():
    """Less than 6 datapoints returns None."""
    dp = _make_datapoints([(900, 1000)] * 3)
    result = analyze_timeseries(1, dp, current_buy=900, current_sell=1000)
    assert result is None, "should return None for <6 datapoints"
    print("  PASSED test_too_few_datapoints")


def test_null_prices_skipped():
    """Datapoints with None prices are skipped gracefully."""
    dp = _make_datapoints([(900, 1000)] * 10)
    dp[3]["avgHighPrice"] = None
    dp[7]["avgLowPrice"] = None
    result = analyze_timeseries(1, dp, current_buy=900, current_sell=1000)
    assert result is not None
    assert result.datapoints == 8, f"expected 8 valid datapoints, got {result.datapoints}"
    print("  PASSED test_null_prices_skipped")


def test_volatility_increases_with_variation():
    """Higher margin variation -> higher margin volatility."""
    # Stable margins: always ~80gp profit
    stable = _make_datapoints([(900, 1000)] * 50)
    # Volatile margins: alternates between ~80gp and ~180gp profit
    volatile = _make_datapoints([(900, 1000), (800, 1000)] * 25)
    r_stable = analyze_timeseries(1, stable, 900, 1000)
    r_volatile = analyze_timeseries(2, volatile, 900, 1000)
    assert r_stable.margin_volatility < r_volatile.margin_volatility, \
        f"stable margin_vol {r_stable.margin_volatility} should be < volatile margin_vol {r_volatile.margin_volatility}"
    print("  PASSED test_volatility_increases_with_variation")


def test_current_vs_avg_ratio():
    """current_vs_avg > 1 when current margin exceeds historical average."""
    dp = _make_datapoints([(950, 1000)] * 50)
    result = analyze_timeseries(1, dp, current_buy=900, current_sell=1100)
    assert result.current_vs_avg > 1.0, f"current_vs_avg {result.current_vs_avg} should be >1.0"
    print("  PASSED test_current_vs_avg_ratio")


def test_confidence_bounds():
    """Confidence score should be between 0 and 1."""
    dp = _make_datapoints([(900, 1000)] * 50)
    result = analyze_timeseries(1, dp, current_buy=900, current_sell=1000)
    assert 0.0 <= result.confidence <= 1.0, f"confidence {result.confidence} out of bounds"
    print("  PASSED test_confidence_bounds")



def test_negative_margin_confidence_nonnegative():
    """Confidence should never go below 0 even when margins are negative."""
    dp = _make_datapoints([(1000, 900)] * 50)  # consistently negative margin
    result = analyze_timeseries(1, dp, current_buy=1000, current_sell=900)
    assert result is not None
    assert result.confidence >= 0.0, f"confidence {result.confidence} should be >= 0"
    assert result.confidence <= 1.0, f"confidence {result.confidence} should be <= 1"
    print("  PASSED test_negative_margin_confidence_nonnegative")

def test_mixed_margin_consistency():
    """Item that flips between positive and negative margins."""
    dp = _make_datapoints([(900, 1000), (1000, 900)] * 25)  # 50% positive
    result = analyze_timeseries(1, dp, current_buy=950, current_sell=950)
    assert result is not None
    # consistency should be ~50% (25 out of 50 windows have positive margin after tax)
    assert 0.4 <= result.margin_consistency <= 0.6, \
        f"consistency {result.margin_consistency} should be ~0.5"
    print("  PASSED test_mixed_margin_consistency")

def test_margin_scanner_happy_path():
    """MarginScanner produces sorted results for items with valid timeseries."""
    from rshelper.scanner import MarginScanner
    from rshelper.models import Item

    scanner = MarginScanner()
    item = Item(id=1, name="Test", members=False, buy_limit=100,
                alch_value=1000, buy_price=900, sell_price=950, volume=200)
    lookup = {1: item}
    ts_data = {1: _make_datapoints([(900, 950)] * 50)}

    results = scanner.scan(lookup, ts_data)
    assert len(results) == 1, f"expected 1 result, got {len(results)}"
    assert results[0].item_id == 1
    assert 0 <= results[0].confidence <= 1
    print("  PASSED test_margin_scanner_happy_path")


def test_margin_scanner_missing_lookup():
    """Items not in lookup dict are skipped."""
    from rshelper.scanner import MarginScanner
    from rshelper.models import Item

    scanner = MarginScanner()
    item = Item(id=1, name="Test", members=False, buy_limit=100,
                alch_value=1000, buy_price=900, sell_price=950, volume=200)
    lookup = {1: item}
    ts_data = {1: _make_datapoints([(900, 950)] * 50),
               999: _make_datapoints([(100, 200)] * 50)}  # not in lookup

    results = scanner.scan(lookup, ts_data)
    assert len(results) == 1  # only item 1, not 999
    print("  PASSED test_margin_scanner_missing_lookup")


def test_margin_scanner_members_filter():
    """members_only=True filters out non-member items."""
    from rshelper.scanner import MarginScanner
    from rshelper.models import Item

    scanner = MarginScanner()
    member_item = Item(id=1, name="Member", members=True, buy_limit=100,
                       alch_value=1000, buy_price=900, sell_price=950, volume=200)
    f2p_item = Item(id=2, name="F2P", members=False, buy_limit=100,
                    alch_value=500, buy_price=400, sell_price=450, volume=200)
    lookup = {1: member_item, 2: f2p_item}
    ts_data = {
        1: _make_datapoints([(900, 950)] * 50),
        2: _make_datapoints([(400, 450)] * 50),
    }

    results = scanner.scan(lookup, ts_data, members_only=True)
    assert len(results) == 1
    assert results[0].item_id == 1
    print("  PASSED test_margin_scanner_members_filter")


def test_margin_scanner_insufficient_data():
    """Items with too few datapoints are excluded."""
    from rshelper.scanner import MarginScanner
    from rshelper.models import Item

    scanner = MarginScanner()
    item = Item(id=1, name="Test", members=False, buy_limit=100,
                alch_value=1000, buy_price=900, sell_price=950, volume=200)
    lookup = {1: item}
    ts_data = {1: _make_datapoints([(900, 950)] * 3)}  # only 3 datapoints

    results = scanner.scan(lookup, ts_data)
    assert len(results) == 0
    print("  PASSED test_margin_scanner_insufficient_data")



def test_reliable_loser_gets_low_confidence():
    """A consistently negative margin should get high reliability but low confidence."""
    # Consistently losing: margin ~ -80gp every window
    loser = _make_datapoints([(1000, 900)] * 50)
    # Consistently winning: margin ~ +80gp every window
    winner = _make_datapoints([(900, 1000)] * 50)

    r_loser = analyze_timeseries(1, loser, current_buy=1000, current_sell=900)
    r_winner = analyze_timeseries(2, winner, current_buy=900, current_sell=1000)

    # Both should have similar reliability (consistent pattern)
    assert r_loser.reliability > 0.3, f"loser reliability {r_loser.reliability} should be >0.3"
    assert r_winner.reliability > 0.3, f"winner reliability {r_winner.reliability} should be >0.3"

    # Loser profitability should be near 0
    assert r_loser.profitability_score < 0.4, \
        f"loser profitability {r_loser.profitability_score} should be <0.4 (losing money)"

    # Winner profitability should be notably higher than loser
    assert r_winner.profitability_score > r_loser.profitability_score, \
        f"winner profit {r_winner.profitability_score} should be > loser profit {r_loser.profitability_score}"

    # Loser confidence should be much lower than winner
    assert r_loser.confidence < r_winner.confidence, \
        f"loser confidence {r_loser.confidence} should be < winner confidence {r_winner.confidence}"

    print("  PASSED test_reliable_loser_gets_low_confidence")

def test_margin_scanner_sorted_by_confidence():
    """Results are sorted by confidence descending."""
    from rshelper.scanner import MarginScanner
    from rshelper.models import Item

    scanner = MarginScanner()
    # Item 1: consistently positive margin -> high confidence
    item1 = Item(id=1, name="Good", members=False, buy_limit=100,
                alch_value=1000, buy_price=900, sell_price=950, volume=200)
    # Item 2: consistently negative margin -> low confidence
    item2 = Item(id=2, name="Bad", members=False, buy_limit=100,
                alch_value=1000, buy_price=1000, sell_price=900, volume=200)
    lookup = {1: item1, 2: item2}
    ts_data = {
        1: _make_datapoints([(900, 950)] * 50),
        2: _make_datapoints([(1000, 900)] * 50),
    }

    results = scanner.scan(lookup, ts_data)
    assert len(results) == 2
    assert results[0].confidence >= results[1].confidence
    print("  PASSED test_margin_scanner_sorted_by_confidence")

if __name__ == "__main__":
    test_consistent_margin()
    test_no_margin_item()
    test_too_few_datapoints()
    test_null_prices_skipped()
    test_volatility_increases_with_variation()
    test_current_vs_avg_ratio()
    test_confidence_bounds()
    test_negative_margin_confidence_nonnegative()
    test_mixed_margin_consistency()
    test_reliable_loser_gets_low_confidence()
    test_margin_scanner_happy_path()
    test_margin_scanner_missing_lookup()
    test_margin_scanner_members_filter()
    test_margin_scanner_insufficient_data()
    test_margin_scanner_sorted_by_confidence()
    print("\nAll analysis tests passed.")