"""Tests for the GE offer simulation (fill progress, slots, collect)."""

import sys
import json
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import rshelper.ge_offers as gmod
import rshelper.journal as jmod
import rshelper.positions as pmod
_tmpdir = tempfile.TemporaryDirectory()
pmod.POSITIONS_PATH = Path(_tmpdir.name) / "positions.json"
jmod.TRADES_PATH = Path(_tmpdir.name) / "trades.json"

from rshelper.ge_offers import (
    MAX_GE_SLOTS,
    build_ge_slots,
    collect_offer,
    compute_fill_pct,
    resolve_icon_url,
)
from rshelper.journal import list_trades
from rshelper.positions import list_positions, open_position


def _clean():
    for path in (pmod.POSITIONS_PATH, jmod.TRADES_PATH):
        if path.exists():
            path.unlink()
    for path in (pmod.POSITIONS_PATH, jmod.TRADES_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)


def _iso(now: float, minutes_ago: float) -> str:
    return datetime.fromtimestamp(now - minutes_ago * 60,
                                  tz=timezone.utc).isoformat()


def _seed(item_id: int, name: str, qty: int, buy_price: int,
          direction: str = "arbitrage", opened_at: str | None = None) -> None:
    """Write a position row directly (open_position has no opened_at kwarg)."""
    path = pmod.POSITIONS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = json.loads(path.read_text()).get("positions", []) if path.exists() else []
    rows.append({
        "id": max((r["id"] for r in rows), default=0) + 1,
        "item_id": item_id, "name": name, "qty": qty, "buy_price": buy_price,
        "direction": direction,
        "opened_at": opened_at or datetime.now(timezone.utc).isoformat(),
        "note": "", "entry_sell": None, "entry_offer": None,
    })
    path.write_text(json.dumps({"positions": rows}))


def _fresh_price(high: int, low: int, now: float) -> dict:
    return {"high": high, "low": low, "highTime": now, "lowTime": now,
            "high_volume": 1000, "low_volume": 1000}


def test_resolve_icon_url_detail():
    assert resolve_icon_url("Nature rune") == (
        "https://oldschool.runescape.wiki/images/Nature_rune_detail.png")
    print("  PASSED test_resolve_icon_url_detail")


def test_resolve_icon_url_inventory():
    assert resolve_icon_url("Nature rune", detail=False) == (
        "https://oldschool.runescape.wiki/images/Nature_rune.png")
    print("  PASSED test_resolve_icon_url_inventory")


def test_resolve_icon_url_special_chars():
    assert resolve_icon_url("3rd age longsword") == (
        "https://oldschool.runescape.wiki/images/3rd_age_longsword_detail.png")
    print("  PASSED test_resolve_icon_url_special_chars")


def test_fill_zero_volume_slow_default():
    now = 1_000_000.0
    fill = compute_fill_pct(100, 0, _iso(now, 10), now)
    assert abs(fill - 0.1) < 1e-9  # 10 min * (1/100) per minute
    print("  PASSED test_fill_zero_volume_slow_default")


def test_fill_high_volume_fast():
    now = 1_000_000.0
    fill = compute_fill_pct(100, 1000, _iso(now, 5), now)
    assert fill >= 0.95  # rate 200/min -> raw capped at 1 -> fill 1.0
    assert fill <= 1.0
    print("  PASSED test_fill_high_volume_fast")


def test_fill_low_volume_slow():
    now = 1_000_000.0
    fill = compute_fill_pct(1000, 10, _iso(now, 5), now)
    # raw = 5 * (10/5) / 1000 = 0.01 -> 1 - 0.99^2 = 0.0199
    assert abs(fill - 0.0199) < 1e-6
    print("  PASSED test_fill_low_volume_slow")


def test_fill_ease_out_shape():
    now = 1_000_000.0
    at_30s = compute_fill_pct(100, 100, _iso(now, 0.5), now)
    at_150s = compute_fill_pct(100, 100, _iso(now, 2.5), now)
    assert at_150s > 3 * at_30s  # tapering curve: 5x time > 3x fill
    print("  PASSED test_fill_ease_out_shape")


def test_fill_caps_at_one():
    now = 1_000_000.0
    assert compute_fill_pct(1, 1, _iso(now, 1000), now) == 1.0
    print("  PASSED test_fill_caps_at_one")


def test_fill_bad_opened_at():
    assert compute_fill_pct(100, 1000, "not-a-date", 1_000_000.0) == 0.0
    print("  PASSED test_fill_bad_opened_at")


def test_build_slots_empty():
    _clean()
    data = build_ge_slots()
    assert data == {"slots": [], "empty_count": MAX_GE_SLOTS,
                    "total_value": 0}
    print("  PASSED test_build_slots_empty")


def test_build_slot_shape():
    _clean()
    now = 1_000_000.0
    _seed(561, "Nature rune", 10, 100, direction="traditional",
          opened_at=_iso(now, 0))
    data = build_ge_slots(latest={"561": _fresh_price(120, 110, now)},
                          vol_5m={"561": 500}, now=now)
    assert len(data["slots"]) == 1
    assert data["empty_count"] == 7
    s = data["slots"][0]
    assert s["index"] == 0
    assert s["offer_type"] == "buy"
    assert s["item_id"] == 561
    assert s["name"] == "Nature rune"
    assert s["qty"] == 10
    assert s["fill_pct"] == 0.0
    assert s["status"] == "pending"
    assert s["price"] == 1000
    assert s["price_each"] == 100
    assert s["buy_price"] == 100
    assert s["current_price"] == 120
    assert s["unrealized"] == (120 - 100) * 10 - 2 * 10  # ge_tax(120)=2
    assert s["can_collect"] is False
    assert s["icon_url"].endswith("Nature_rune.png")
    assert s["icon_url_detail"].endswith("Nature_rune_detail.png")
    assert s["position_id"] == 1
    assert s["age_minutes"] == 0.0
    assert data["total_value"] == 1000
    print("  PASSED test_build_slot_shape")


def test_offer_type_mapping():
    _clean()
    open_position(561, "Nature rune", 1, 100, direction="traditional")
    open_position(562, "Fire rune", 1, 10, direction="arbitrage")
    slots = build_ge_slots()["slots"]
    assert slots[0]["offer_type"] == "buy"       # traditional -> buy offer
    assert slots[1]["offer_type"] == "sell"      # arbitrage -> sell offer
    print("  PASSED test_offer_type_mapping")


def test_max_eight_slots():
    _clean()
    for i in range(10):
        open_position(1000 + i, f"Item {i}", 1, 100)
    data = build_ge_slots()
    assert len(data["slots"]) == MAX_GE_SLOTS
    assert data["empty_count"] == 0
    print("  PASSED test_max_eight_slots")


def test_stale_price_slots():
    _clean()
    now = 1_000_000.0
    open_position(561, "Nature rune", 10, 100)
    stale = {"561": {"high": 120, "low": 110, "highTime": now - 25 * 3600,
                     "lowTime": now - 25 * 3600, "high_volume": 1,
                     "low_volume": 1}}
    s = build_ge_slots(latest=stale, now=now)["slots"][0]
    assert s["current_price"] is None
    assert s["unrealized"] is None
    assert s["unrealized_pct"] is None
    print("  PASSED test_stale_price_slots")


def test_slot_auto_flag():
    """Slots expose whether the position is auto-managed (no manual collect)."""
    _clean()
    now = 1_000_000.0
    open_position(561, "Nature rune", 10, 100, note="auto")
    open_position(562, "Fire rune", 1, 10, note="paper")
    slots = build_ge_slots(now=now)["slots"]
    auto = {s["item_id"]: s["auto"] for s in slots}
    assert auto[561] is True
    assert auto[562] is False
    print("  PASSED test_slot_auto_flag")


def test_slot_entry_fields():
    """Slots expose entry bid/offer and entry spread for the detail panel."""
    _clean()
    now = 1_000_000.0
    open_position(561, "Nature rune", 10, 100, direction="traditional",
                  entry_sell=100, entry_offer=104)
    s = build_ge_slots(now=now)["slots"][0]
    assert s["entry_sell"] == 100
    assert s["entry_offer"] == 104
    assert s["spread_pct"] == 4.0  # (104 - 100) / 100
    print("  PASSED test_slot_entry_fields")


def test_collect_closes_and_logs():
    _clean()
    p = open_position(561, "Nature rune", 10, 100, direction="traditional")
    r = collect_offer(p.id, latest={"561": _fresh_price(120, 110, time.time())})
    assert r == {"ok": True, "name": "Nature rune", "qty": 10,
                 "sell_price": 120, "profit": 180}  # (120-100)*10 - 2*10
    assert list_positions() == []
    trades = list_trades()
    assert len(trades) == 1
    assert trades[0].strategy == "ge_collect"
    assert trades[0].profit == 180
    print("  PASSED test_collect_closes_and_logs")


def test_collect_unknown_id():
    _clean()
    try:
        collect_offer(999)
        assert False, "expected ValueError"
    except ValueError:
        pass
    print("  PASSED test_collect_unknown_id")


def test_collect_no_price_fallback():
    _clean()
    p = open_position(561, "Nature rune", 10, 100)
    r = collect_offer(p.id, latest={})
    assert r["sell_price"] == 100  # falls back to buy_price
    assert r["profit"] == -20      # -ge_tax(100)=2 per item
    assert list_positions() == []
    print("  PASSED test_collect_no_price_fallback")


def test_collect_closes_specific_lot_not_fifo():
    """Collecting one of several lots must close THAT lot, not the oldest."""
    _clean()
    p1 = open_position(561, "Nature rune", 5, 90, direction="traditional")
    open_position(561, "Nature rune", 5, 110, direction="traditional")
    r = collect_offer(p1.id, latest={"561": _fresh_price(120, 110, time.time())})
    assert r["qty"] == 5
    assert r["profit"] == 140  # (120-90)*5 - 2*5
    remaining = list_positions()
    assert len(remaining) == 1
    assert remaining[0].buy_price == 110  # the OTHER lot is still open
    trades = list_trades()
    assert len(trades) == 1
    assert trades[0].buy_price == 90  # journaled the clicked lot's cost basis
    _clean()
    print("  PASSED test_collect_closes_specific_lot_not_fifo")


if __name__ == "__main__":
    test_resolve_icon_url_detail()
    test_resolve_icon_url_inventory()
    test_resolve_icon_url_special_chars()
    test_fill_zero_volume_slow_default()
    test_fill_high_volume_fast()
    test_fill_low_volume_slow()
    test_fill_ease_out_shape()
    test_fill_caps_at_one()
    test_fill_bad_opened_at()
    test_build_slots_empty()
    test_build_slot_shape()
    test_offer_type_mapping()
    test_max_eight_slots()
    test_stale_price_slots()
    test_slot_auto_flag()
    test_slot_entry_fields()
    test_collect_closes_and_logs()
    test_collect_unknown_id()
    test_collect_no_price_fallback()
    test_collect_closes_specific_lot_not_fifo()
    print("\nAll tests passed.")
