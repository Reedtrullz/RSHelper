"""Tests for the replay harness (scripts/replay.py)."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import replay


def _ts_item(item_id: int, n: int = 30, hi: int = 104, lo: int = 100,
             base_ts: int = 1_700_000_000) -> list[dict]:
    """A synthetic candle series: a dip (low drops ~5%) then recovery, so
    the dip+spread filters see a mean-reverting opportunity. The dip keeps
    the spread within [4%, 5%] so it passes max_entry_spread_pct."""
    out = []
    for i in range(n):
        # First 10 candles at normal price; candles 10-14 dip 5% (the low
        # falls below the trailing average); then recover.
        if 10 <= i < 15:
            c_lo = int(lo * 0.95)   # e.g. 100 -> 95
            c_hi = int(hi * 0.955)  # keep spread ~4.2% (99/95)
        else:
            c_lo, c_hi = lo, hi
        out.append({
            "timestamp": base_ts + i * 300,
            "avgHighPrice": c_hi,
            "avgLowPrice": c_lo,
            "highPriceVolume": 5000,
            "lowPriceVolume": 5000,
        })
    return out


def test_replay_baseline_generates_trades():
    """A dip+spread item should generate profitable trades under the
    validated defaults."""
    data = {1: _ts_item(1, n=60, hi=104, lo=100)}  # 4% spread, 4% dip vs 1h avg
    cfg = replay.ReplayConfig(dip_depth_pct=3.0, stop_loss_pct=-2.0,
                              stop_grace_minutes=20, min_spread_pct=4.0)
    r = replay.simulate(data, cfg)
    assert r["trades"] > 0, f"expected trades, got {r}"
    assert r["roi_pct"] > 0
    assert r["win_rate"] == 100.0
    print("  PASSED test_replay_baseline_generates_trades")


def test_replay_no_trades_without_dip():
    """An item that never dips below the entry filter produces no trades."""
    data = {1: _ts_item(1, n=30, hi=100, lo=99)}  # 1% spread < 4% filter
    cfg = replay.ReplayConfig(min_spread_pct=4.0)
    r = replay.simulate(data, cfg)
    assert r.get("trades", 0) == 0
    print("  PASSED test_replay_no_trades_without_dip")


def test_replay_grace_blocks_early_stop():
    """A crash during the stop-grace does NOT stop the position — the grace
    lets the dip revert (the ge_fill/take-profit then wins)."""
    # Normal 100/104. Dip (candles 10-14): low 96 / high 100 (4.2% spread,
    # ~3.5% dip). A crash to 88/91 hits at candle 13 — but the position is
    # only 15 min old (< the 20-min grace), so the stop does NOT fire and
    # the position survives to ge_fill/take-profit.
    candles = []
    base = 1_700_000_000
    for i in range(40):
        if 10 <= i < 14:
            c_lo, c_hi = 96, 100
        elif i >= 14:
            c_lo, c_hi = 88, 91  # crash mid-dip, within the grace window
        else:
            c_lo, c_hi = 100, 104
        candles.append({"timestamp": base + i * 300, "avgHighPrice": c_hi,
                        "avgLowPrice": c_lo, "highPriceVolume": 100000,
                        "lowPriceVolume": 100000})
    data = {1: candles}
    cfg = replay.ReplayConfig(dip_depth_pct=3.0, stop_loss_pct=-2.0,
                              stop_grace_minutes=20, min_spread_pct=4.0,
                              min_volume=100)
    r = replay.simulate(data, cfg)
    reasons = [t["reason"] for t in r.get("trade_list", [])]
    assert "stop_loss" not in reasons, \
        f"grace must block the early stop, got {reasons}"
    # The position still exits profitably (ge_fill or TP)
    assert any(t["profit"] > 0 for t in r.get("trade_list", [])), r
    print("  PASSED test_replay_grace_blocks_early_stop")


def test_replay_ge_fill_auto_collects():
    """A high-volume item's position auto-collects at the offer (ge_fill)
    when the fill completes but the offer is below the TP threshold."""
    # Normal 100/104. Dip (candles 10-14) drops low to 96, high to 100 —
    # spread 4.2%, dip ~3.5%, offer nets (100-96-2)/96 = 2.1% (< TP 3%) so
    # ge_fill (not TP) closes it once the huge volume completes the fill.
    candles = []
    base = 1_700_000_000
    for i in range(30):
        if 10 <= i < 15:
            c_lo, c_hi = 96, 100
        else:
            c_lo, c_hi = 100, 104
        candles.append({"timestamp": base + i * 300, "avgHighPrice": c_hi,
                        "avgLowPrice": c_lo, "highPriceVolume": 100000,
                        "lowPriceVolume": 100000})
    data = {1: candles}
    cfg = replay.ReplayConfig(dip_depth_pct=3.0, stop_loss_pct=-2.0,
                              stop_grace_minutes=20, min_spread_pct=4.0)
    r = replay.simulate(data, cfg)
    reasons = [t["reason"] for t in r.get("trade_list", [])]
    assert "ge_fill" in reasons, f"expected ge_fill, got {reasons}"
    print("  PASSED test_replay_ge_fill_auto_collects")


if __name__ == "__main__":
    test_replay_baseline_generates_trades()
    test_replay_no_trades_without_dip()
    test_replay_grace_blocks_early_stop()
    test_replay_ge_fill_auto_collects()
    print("\nAll replay tests passed.")
