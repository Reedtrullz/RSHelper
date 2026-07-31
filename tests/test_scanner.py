"""Tests for the alch scanner."""

import sys
import time
from pathlib import Path

# Ensure src/ is on the path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from rshelper.models import Item
from rshelper.scanner import AlchScanner, build_items_from_api


def test_alch_scanner_basic():
    """Profitable item returned, loss item filtered out."""
    items = [
        Item(id=1, name="Test item", members=False, buy_limit=100,
             alch_value=1000, buy_price=800, sell_price=750, volume=500),
        Item(id=2, name="Loss item", members=False, buy_limit=50,
             alch_value=100, buy_price=200, sell_price=190, volume=10),
    ]
    scanner = AlchScanner(nature_rune_cost=147)
    results = scanner.scan(items)
    assert len(results) == 1, f"Expected 1 profitable item, got {len(results)}"
    assert results[0].profit == 53, f"Expected profit 53, got {results[0].profit}"
    assert results[0].gp_per_hour > 0
    print("  PASSED test_alch_scanner_basic")


def test_scanner_does_not_mutate_input():
    """Scanner must not modify the original Item objects."""
    items = [
        Item(id=1, name="X", members=False, buy_limit=100,
             alch_value=1000, buy_price=800, sell_price=750, volume=500),
    ]
    original_profit = items[0].profit
    original_gp = items[0].gp_per_hour
    scanner = AlchScanner(nature_rune_cost=147)
    scanner.scan(items)
    assert items[0].profit == original_profit, "Scanner mutated input profit"
    assert items[0].gp_per_hour == original_gp, "Scanner mutated input gp_per_hour"
    print("  PASSED test_scanner_does_not_mutate_input")


def test_volume_caps_gp_per_hour():
    """GP/hr capped by min(buy_limit/4, volume*12, 1200)."""
    # volume=50 → hourly=600, buy_limit/4=250 → cap is 250
    items = [
        Item(id=1, name="Thin", members=False, buy_limit=1000,
             alch_value=1000, buy_price=500, sell_price=450, volume=50),
    ]
    scanner = AlchScanner(nature_rune_cost=147)
    results = scanner.scan(items)
    profit = 1000 - 500 - 147  # 353
    expected_gp = int(profit * 250)  # min(1000/4=250, 50*12=600, 1200)
    assert results[0].gp_per_hour == expected_gp, (
        f"Expected gp/hr {expected_gp}, got {results[0].gp_per_hour}"
    )
    print("  PASSED test_volume_caps_gp_per_hour")


def test_buy_limit_zero_excluded():
    """Items with buy_limit=0 should be excluded (can't buy = can't alch)."""
    items = [
        Item(id=1, name="NoLimit", members=False, buy_limit=0,
             alch_value=1000, buy_price=500, sell_price=450, volume=5000),
    ]
    scanner = AlchScanner(nature_rune_cost=147)
    results = scanner.scan(items)
    assert len(results) == 0, f"Expected 0 results for buy_limit=0, got {len(results)}"
    print("  PASSED test_buy_limit_zero_excluded")


def test_members_filter():
    """--members-only should exclude F2P items."""
    items = [
        Item(id=1, name="F2P item", members=False, buy_limit=100,
             alch_value=1000, buy_price=800, sell_price=750, volume=500),
        Item(id=2, name="P2P item", members=True, buy_limit=100,
             alch_value=1000, buy_price=800, sell_price=750, volume=500),
    ]
    scanner = AlchScanner(nature_rune_cost=147)
    results = scanner.scan(items, members_only=True)
    assert len(results) == 1
    assert results[0].name == "P2P item"
    print("  PASSED test_members_filter")


def test_min_volume_filter():
    """--min-volume should exclude low-volume items."""
    items = [
        Item(id=1, name="High vol", members=False, buy_limit=100,
             alch_value=1000, buy_price=800, sell_price=750, volume=500),
        Item(id=2, name="Low vol", members=False, buy_limit=100,
             alch_value=1000, buy_price=800, sell_price=750, volume=10),
    ]
    scanner = AlchScanner(nature_rune_cost=147)
    results = scanner.scan(items, min_volume=100)
    assert len(results) == 1
    assert results[0].name == "High vol"
    print("  PASSED test_min_volume_filter")


def test_sorted_by_gp_per_hour_descending():
    """Results should be sorted by gp_per_hour descending."""
    items = [
        Item(id=1, name="Low gp", members=False, buy_limit=100,
             alch_value=1200, buy_price=900, sell_price=850, volume=500),
        Item(id=2, name="High gp", members=False, buy_limit=100,
             alch_value=2000, buy_price=800, sell_price=750, volume=500),
    ]
    scanner = AlchScanner(nature_rune_cost=147)
    results = scanner.scan(items)
    assert len(results) == 2
    assert results[0].name == "High gp"
    assert results[0].gp_per_hour >= results[1].gp_per_hour
    print("  PASSED test_sorted_by_gp_per_hour_descending")


def test_build_items_from_api():
    """build_items_from_api merges mapping + latest + volume correctly."""
    mapping = [
        {"id": 1, "name": "Sword", "members": False, "limit": 100, "highalch": 1000},
        {"id": 2, "name": "Untradeable", "members": False, "limit": 0, "highalch": 0},
    ]
    now = int(time.time())
    latest = {
        "1": {"high": 800, "low": 750, "highTime": now - 60, "lowTime": now - 60},
        "2": {"high": 0, "low": 0, "highTime": now - 60, "lowTime": now - 60},
    }
    volume_5m = {"1": {"highPriceVolume": 300, "lowPriceVolume": 200}}
    items = build_items_from_api(mapping, latest, volume_5m)
    assert len(items) == 1  # untradeable filtered out
    assert items[0].name == "Sword"
    assert items[0].buy_price == 800
    assert items[0].volume == 500
    print("  PASSED test_build_items_from_api")


def test_build_items_skips_stale_and_manipulated_prices():
    """Stale, zero-depth, or absurdly spread prices never reach the scanners."""
    now = int(time.time())
    mapping = [
        {"id": i, "name": name, "members": False, "limit": 100, "highalch": 0}
        for i, name in enumerate(
            ("Fresh", "Stale", "NoTimes", "ZeroDepth", "WikiAbsurd", "TrackerAbsurd"), 1
        )
    ]
    latest = {
        # healthy item: kept
        "1": {"high": 100, "low": 95, "highTime": now - 60, "lowTime": now - 30},
        # one price leg 3 days old: skipped
        "2": {"high": 100, "low": 95, "highTime": now - 3 * 86400, "lowTime": now - 60},
        # no trade timestamps at all: skipped
        "3": {"high": 100, "low": 95},
        # fresh but zero offers on one side (GE Tracker shape): skipped
        "4": {"high": 100, "low": 95000, "highTime": now - 60, "lowTime": now - 30,
              "high_volume": 50, "low_volume": 0},
        # wiki shape, 1 gp buy vs 170k sell, both fresh: skipped by ratio
        "5": {"high": 1, "low": 170000, "highTime": now - 60, "lowTime": now - 30},
        # tracker shape, 1 gp buy vs 170k sell with depth: skipped by ratio
        "6": {"high": 1, "low": 170000, "highTime": now - 60, "lowTime": now - 30,
              "high_volume": 115, "low_volume": 10},
    }
    items = build_items_from_api(mapping, latest, {})
    assert [i.name for i in items] == ["Fresh"]
    assert items[0].buy_price == 100
    assert items[0].sell_price == 95
    print("  PASSED test_build_items_skips_stale_and_manipulated_prices")




def test_flip_scanner_arbitrage():
    """Arbitrage mode: margin = sell_price(low) - buy_price(high), finds low>high windows."""
    from rshelper.scanner import FlipScanner
    items = [
        Item(id=1, name="Arb item", members=False, buy_limit=100,
             alch_value=0, buy_price=900, sell_price=1000, volume=500),
        Item(id=2, name="No arb", members=False, buy_limit=100,
             alch_value=0, buy_price=1000, sell_price=900, volume=500),
    ]
    scanner = FlipScanner(direction="arbitrage")
    results = scanner.scan(items)
    assert len(results) == 1, f"Expected 1 arbitrage flip, got {len(results)}"
    assert results[0].name == "Arb item"
    assert results[0].profit > 0
    print("  PASSED test_flip_scanner_arbitrage")


def test_flip_scanner_traditional():
    """Traditional mode: margin = buy_price(high) - sell_price(low), standard GE flipping."""
    from rshelper.scanner import FlipScanner
    items = [
        Item(id=1, name="No flip", members=False, buy_limit=100,
             alch_value=0, buy_price=900, sell_price=1000, volume=500),
        Item(id=2, name="Trad flip", members=False, buy_limit=100,
             alch_value=0, buy_price=1000, sell_price=900, volume=500),
    ]
    scanner = FlipScanner(direction="traditional")
    results = scanner.scan(items)
    assert len(results) == 1, f"Expected 1 traditional flip, got {len(results)}"
    assert results[0].name == "Trad flip"
    assert results[0].profit > 0
    # Traditional: buy at low(900), sell at high(1000), margin=100, tax=20, profit=80
    assert results[0].profit == 80, f"Expected profit 80, got {results[0].profit}"
    print("  PASSED test_flip_scanner_traditional")


def test_flip_scanner_invalid_direction():
    """Invalid direction raises ValueError."""
    from rshelper.scanner import FlipScanner
    try:
        FlipScanner(direction="invalid")
        assert False, "Should have raised ValueError"
    except ValueError:
        pass
    print("  PASSED test_flip_scanner_invalid_direction")


def test_trade_size():
    """trade_size respects buy_limit, capital, and volume constraints."""
    from rshelper.scanner import trade_size
    from rshelper.models import Item

    item = Item(id=1, name="Test", members=False, buy_limit=10000,
                alch_value=0, buy_price=100, sell_price=120, volume=500)

    # volume = 500 * 12 = 6000/hr, buy_limit = 10000, capital//100 = 100000
    # min(10000, 100000, 6000) = 6000
    assert trade_size(item, 10_000_000) == 6000

    # Limited by capital: capital//100 = 100
    assert trade_size(item, 10_000) == 100

    # Limited by volume: volume 0 → returns 0 (illiquid item)
    no_vol = Item(id=2, name="NoVol", members=False, buy_limit=100,
                  alch_value=0, buy_price=100, sell_price=120, volume=0)
    assert trade_size(no_vol, 1_000_000) == 0

    # Zero capital = zero qty
    assert trade_size(item, 0) == 0
    print("  PASSED test_trade_size")

if __name__ == "__main__":
    test_alch_scanner_basic()
    test_scanner_does_not_mutate_input()
    test_volume_caps_gp_per_hour()
    test_buy_limit_zero_excluded()
    test_members_filter()
    test_min_volume_filter()
    test_sorted_by_gp_per_hour_descending()
    test_build_items_from_api()
    test_build_items_skips_stale_and_manipulated_prices()
    test_flip_scanner_arbitrage()
    test_flip_scanner_traditional()
    test_flip_scanner_invalid_direction()
    test_trade_size()
    print("\nAll tests passed.")
