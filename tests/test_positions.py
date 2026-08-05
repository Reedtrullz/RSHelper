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


def test_entry_offer_roundtrip():
    _clean()
    p = open_position(777, "Test", 5, 100, direction="traditional",
                      entry_sell=100, entry_offer=105)
    assert p.entry_offer == 105
    loaded = list_positions()[0]
    assert loaded.entry_offer == 105
    assert loaded.entry_sell == 100
    print("  PASSED test_entry_offer_roundtrip")


def test_unknown_fields_tolerated():
    """Rows with unknown fields (newer schema) load with defaults, no crash."""
    _clean()
    import json
    path = pmod.POSITIONS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"positions": [
        {"id": 1, "item_id": 9, "name": "X", "qty": 3, "buy_price": 50,
         "direction": "traditional", "opened_at": "2026-08-01T00:00:00Z",
         "note": "", "entry_sell": 50, "future_field": 42}
    ]}))
    loaded = list_positions()
    assert len(loaded) == 1
    assert loaded[0].item_id == 9
    assert loaded[0].entry_offer is None
    assert loaded[0].qty == 3
    print("  PASSED test_unknown_fields_tolerated")


def test_close_specific_position():
    """close_positions with position_id closes only that lot, not FIFO."""
    _clean()
    p1 = open_position(561, "Nature rune", 5, 90)
    open_position(561, "Nature rune", 5, 110)
    lots = close_positions(561, 3, 130, position_id=p1.id)
    assert len(lots) == 1
    assert lots[0]["position_id"] == p1.id
    assert lots[0]["buy_price"] == 90
    remaining = list_positions()
    assert len(remaining) == 2
    assert remaining[0].qty == 2  # p1 partially reduced
    assert remaining[1].qty == 5  # p2 untouched
    _clean()
    print("  PASSED test_close_specific_position")


def test_cross_process_open_no_lost_positions():
    """Concurrent opens from separate processes must not lose positions."""
    import subprocess
    import sys
    _clean()
    # The child must patch the module POSITIONS_PATH to the same temp file.
    code = (
        "import sys; sys.path.insert(0,'src');"
        "import rshelper.positions as p;"
        "p.POSITIONS_PATH = __import__('pathlib').Path(%r);"
        "p.open_position(561, 'Nature rune', 1, 100, profile='default')"
    ) % str(pmod.POSITIONS_PATH)
    procs = [subprocess.Popen([sys.executable, "-c", code], cwd=Path(__file__).resolve().parent.parent,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
             for _ in range(4)]
    for p in procs:
        p.wait(timeout=30)
    positions = list_positions()
    assert len(positions) == 4, f"lost positions: {len(positions)}"
    ids = [pos.id for pos in positions]
    assert len(ids) == len(set(ids)), f"colliding ids: {ids}"
    _clean()
    print("  PASSED test_cross_process_open_no_lost_positions")


if __name__ == "__main__":
    test_open_and_close_round_trip()
    test_close_fifo_across_lots()
    test_close_more_than_open_rejected()
    test_validation()
    test_tax_free_close_below_50()
    test_traditional_direction_stored()
    test_entry_offer_roundtrip()
    test_unknown_fields_tolerated()
    test_cross_process_open_no_lost_positions()
    print("\nAll tests passed.")
