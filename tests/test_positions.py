"""Tests for open paper-trading positions."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import rshelper.positions as pmod
_tmpdir = tempfile.TemporaryDirectory()
pmod.POSITIONS_PATH = Path(_tmpdir.name) / "positions.json"

from rshelper.positions import (
    close_positions,
    list_positions,
    open_position,
    open_qty,
)


def _clean():
    if pmod.POSITIONS_PATH.exists():
        pmod.POSITIONS_PATH.unlink()
    pmod.POSITIONS_PATH.parent.mkdir(parents=True, exist_ok=True)


def test_open_and_close_round_trip():
    _clean()
    p = open_position(561, "Nature rune", 10, 100)
    assert p.qty == 10
    assert p.buy_price == 100
    assert p.direction == "arbitrage"
    lots = close_positions(561, 10, 120)
    assert len(lots) == 1
    lot = lots[0]
    # (120-100)*10 - ge_tax(120)=2 per item -> 200 - 20
    assert lot["profit"] == 180
    assert lot["tax_paid"] == 20
    assert list_positions() == []
    print("  PASSED test_open_and_close_round_trip")


def test_close_fifo_across_lots():
    _clean()
    open_position(561, "Nature rune", 5, 90)
    open_position(561, "Nature rune", 5, 110)
    lots = close_positions(561, 6, 130)
    assert [l["buy_price"] for l in lots] == [90, 110]
    assert [l["qty"] for l in lots] == [5, 1]
    remaining = list_positions()
    assert len(remaining) == 1
    assert remaining[0].qty == 4
    assert remaining[0].buy_price == 110
    print("  PASSED test_close_fifo_across_lots")


def test_close_more_than_open_rejected():
    _clean()
    open_position(561, "Nature rune", 3, 100)
    try:
        close_positions(561, 5, 120)
        assert False, "expected ValueError"
    except ValueError:
        pass
    assert open_qty(561) == 3
    print("  PASSED test_close_more_than_open_rejected")


def test_validation():
    _clean()
    for bad in [
        lambda: open_position(1, "X", 0, 100),
        lambda: open_position(1, "X", 1, 0),
        lambda: open_position(1, "X", 1, 100, direction="sideways"),
        lambda: close_positions(1, 0, 100),
        lambda: close_positions(1, 1, 0),
    ]:
        try:
            bad()
            assert False, "expected ValueError"
        except ValueError:
            pass
    print("  PASSED test_validation")


def test_tax_free_close_below_50():
    _clean()
    open_position(1, "Cheap", 10, 1)
    lots = close_positions(1, 10, 40)
    assert lots[0]["tax_paid"] == 0
    assert lots[0]["profit"] == (40 - 1) * 10
    print("  PASSED test_tax_free_close_below_50")


def test_traditional_direction_stored():
    _clean()
    p = open_position(561, "Nature rune", 2, 90, direction="traditional")
    assert p.direction == "traditional"
    lots = close_positions(561, 2, 130)
    assert lots[0]["profit"] == (130 - 90) * 2 - 2 * 2  # ge_tax(130)=2
    print("  PASSED test_traditional_direction_stored")


if __name__ == "__main__":
    test_open_and_close_round_trip()
    test_close_fifo_across_lots()
    test_close_more_than_open_rejected()
    test_validation()
    test_tax_free_close_below_50()
    test_traditional_direction_stored()
    print("\nAll tests passed.")
