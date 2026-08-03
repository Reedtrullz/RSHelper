"""Tests for the bank holdings aggregation."""

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import rshelper.bank as bmod
import rshelper.positions as pmod
_tmpdir = tempfile.TemporaryDirectory()
pmod.POSITIONS_PATH = Path(_tmpdir.name) / "positions.json"

from rshelper.bank import build_bank_items
from rshelper.market import ge_tax
from rshelper.positions import open_position


def _fresh_price(high: int, low: int, now: float) -> dict:
    return {"high": high, "low": low, "highTime": now, "lowTime": now,
            "high_volume": 1000, "low_volume": 1000}


def _clean():
    if pmod.POSITIONS_PATH.exists():
        pmod.POSITIONS_PATH.unlink()
    pmod.POSITIONS_PATH.parent.mkdir(parents=True, exist_ok=True)


def test_empty_bank():
    _clean()
    d = build_bank_items()
    assert d == {"items": [], "total_value": 0, "unrealized_pnl": 0,
                 "cost_basis": 0, "slot_count": 0}
    print("  PASSED test_empty_bank")


def test_aggregates_positions():
    _clean()
    open_position(561, "Nature rune", 3, 100, direction="traditional")
    open_position(561, "Nature rune", 2, 150, direction="traditional")
    d = build_bank_items()
    assert len(d["items"]) == 1
    it = d["items"][0]
    assert it["total_qty"] == 5
    assert it["avg_buy_price"] == 120   # (3*100 + 2*150) / 5
    assert it["cost_basis"] == 600
    assert it["position_count"] == 2
    assert d["slot_count"] == 1
    print("  PASSED test_aggregates_positions")


def test_weighted_average_rounding():
    _clean()
    open_position(561, "Nature rune", 1, 100)
    open_position(561, "Nature rune", 1, 199)
    it = build_bank_items()["items"][0]
    assert it["avg_buy_price"] == 150   # 299/2 rounds to 150
    print("  PASSED test_weighted_average_rounding")


def test_unrealized_traditional():
    _clean()
    now = 1_000_000.0
    open_position(561, "Nature rune", 10, 100, direction="traditional")
    d = build_bank_items(latest={"561": _fresh_price(130, 100, now)}, now=now)
    it = d["items"][0]
    assert it["current_price"] == 130   # traditional exits at offer/high
    assert it["total_value"] == 1300
    assert it["unrealized_pnl"] == 1300 - 1000 - ge_tax(130) * 10
    assert d["total_value"] == 1300
    assert d["unrealized_pnl"] == it["unrealized_pnl"]
    print("  PASSED test_unrealized_traditional")


def test_unrealized_arbitrage():
    _clean()
    now = 1_000_000.0
    open_position(561, "Nature rune", 10, 100, direction="arbitrage")
    it = build_bank_items(latest={"561": _fresh_price(130, 90, now)},
                          now=now)["items"][0]
    assert it["current_price"] == 90    # arbitrage exits at bid/low
    assert it["total_value"] == 900
    assert it["unrealized_pnl"] == 900 - 1000 - ge_tax(90) * 10
    print("  PASSED test_unrealized_arbitrage")


def test_sorted_by_total_value_desc():
    _clean()
    now = 1_000_000.0
    open_position(561, "Nature rune", 10, 100, direction="traditional")
    open_position(562, "Cannonball", 1000, 2, direction="traditional")
    items = build_bank_items(latest={"561": _fresh_price(130, 100, now),
                                     "562": _fresh_price(4, 3, now)},
                             now=now)["items"]
    assert items[0]["name"] == "Cannonball"  # 4000 > 1300
    assert items[1]["name"] == "Nature rune"
    print("  PASSED test_sorted_by_total_value_desc")


def test_latest_none():
    _clean()
    open_position(561, "Nature rune", 10, 100, direction="traditional")
    d = build_bank_items(latest=None)
    it = d["items"][0]
    assert it["current_price"] is None
    assert it["unrealized_pnl"] == 0
    assert it["unrealized_pct"] is None
    assert it["total_value"] == it["cost_basis"] == 1000
    assert d["unrealized_pnl"] == 0
    print("  PASSED test_latest_none")


def test_slot_count_distinct_items():
    _clean()
    open_position(561, "Nature rune", 1, 100)
    open_position(561, "Nature rune", 2, 100)
    open_position(562, "Fire rune", 5, 10)
    assert build_bank_items()["slot_count"] == 2
    print("  PASSED test_slot_count_distinct_items")


def test_icon_urls():
    _clean()
    open_position(561, "Nature rune", 1, 100)
    it = build_bank_items()["items"][0]
    assert it["icon_url"].endswith("Nature_rune.png")
    assert it["icon_url_detail"].endswith("Nature_rune_detail.png")
    print("  PASSED test_icon_urls")


def test_stale_price_no_mark():
    _clean()
    now = 1_000_000.0
    open_position(561, "Nature rune", 10, 100, direction="traditional")
    stale = {"561": {"high": 130, "low": 100, "highTime": now - 25 * 3600,
                     "lowTime": now - 25 * 3600, "high_volume": 1,
                     "low_volume": 1}}
    it = build_bank_items(latest=stale, now=now)["items"][0]
    assert it["current_price"] is None
    assert it["unrealized_pnl"] == 0
    print("  PASSED test_stale_price_no_mark")


def test_tax_uses_ge_tax():
    _clean()
    now = 1_000_000.0
    open_position(561, "Nature rune", 10, 100, direction="traditional")
    it = build_bank_items(latest={"561": _fresh_price(130, 100, now)},
                          now=now)["items"][0]
    gross = it["total_value"] - it["cost_basis"]
    assert gross - it["unrealized_pnl"] == ge_tax(130) * 10
    print("  PASSED test_tax_uses_ge_tax")


if __name__ == "__main__":
    test_empty_bank()
    test_aggregates_positions()
    test_weighted_average_rounding()
    test_unrealized_traditional()
    test_unrealized_arbitrage()
    test_sorted_by_total_value_desc()
    test_latest_none()
    test_slot_count_distinct_items()
    test_icon_urls()
    test_stale_price_no_mark()
    test_tax_uses_ge_tax()
    print("\nAll tests passed.")
