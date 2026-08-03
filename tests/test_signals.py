"""Tests for signal detection engine and RS Score computation."""

import sys
import os
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from rshelper.models import Item
from rshelper.signals import (
    detect_signals, compute_rs_score_flip, compute_rs_score_alch,
    DUMP_THRESHOLD, CRASH_THRESHOLD, SURGE_MULTIPLIER,
)

import rshelper.signals as _s
_baseline_state = {}
_s._load_baselines = lambda: dict(_baseline_state)
_s._save_baselines = lambda data: _baseline_state.update(data)



# --- RS Score tests ---

def test_rs_score_flip_basic():
    """RS Score for a typical item falls in 0-100 range."""
    item = Item(id=1, name="Test", members=False, buy_limit=10000,
                alch_value=0, buy_price=100, sell_price=90,
                volume=500, profit=8, gp_per_hour=1000)
    score = compute_rs_score_flip(item, max_volume=1000)
    assert 0 <= score <= 100, f"RS Score {score} out of range"
    print("  PASSED test_rs_score_flip_basic")


def test_rs_score_flip_zero_volume():
    """Zero-volume item gets low volume component and neutral freshness."""
    item = Item(id=1, name="Dead", members=False, buy_limit=100,
                alch_value=0, buy_price=100, sell_price=90,
                volume=0, profit=8, gp_per_hour=100)
    score = compute_rs_score_flip(item, max_volume=1000)
    # 0 vol + spread 8% -> 5/5 = 1.0*30 + depth 100/10000=0.01*20 + neutral 5
    assert abs(score - 35.2) < 0.1, f"Zero vol item scored {score}, expected ~35.2"
    print("  PASSED test_rs_score_flip_zero_volume")


def test_rs_score_flip_freshness_from_age():
    """Freshness bonus is scored from real price age, not a constant."""
    item = Item(id=1, name="Test", members=False, buy_limit=10000,
                alch_value=0, buy_price=100, sell_price=90,
                volume=500, profit=8, gp_per_hour=1000)
    now = time.time()
    fresh = {"1": {"high": 100, "low": 90, "highTime": now - 60,
                   "lowTime": now - 60}}
    stale = {"1": {"high": 100, "low": 90, "highTime": now - 3600,
                   "lowTime": now - 3600}}
    score_fresh = compute_rs_score_flip(item, max_volume=1000,
                                        latest=fresh, now=now)
    score_stale = compute_rs_score_flip(item, max_volume=1000,
                                        latest=stale, now=now)
    assert score_fresh > score_stale, \
        f"fresh item ({score_fresh}) must score above stale ({score_stale})"
    # Fresh (<=5 min) gets the full 10 freshness points
    assert abs(score_fresh - (score_stale + 10)) < 1e-6
    print("  PASSED test_rs_score_flip_freshness_from_age")


def test_rs_score_alch_percentile():
    """Alch RS Score assigns percentile ranks."""
    items = [
        Item(id=1, name="A", members=False, buy_limit=100,
             alch_value=0, buy_price=100, sell_price=50, volume=10,
             profit=10, gp_per_hour=1000),
        Item(id=2, name="B", members=False, buy_limit=100,
             alch_value=0, buy_price=100, sell_price=50, volume=10,
             profit=20, gp_per_hour=500),
        Item(id=3, name="C", members=False, buy_limit=100,
             alch_value=0, buy_price=100, sell_price=50, volume=10,
             profit=5, gp_per_hour=100),
    ]
    compute_rs_score_alch(items)
    assert items[0].rs_score > items[1].rs_score > items[2].rs_score
    print("  PASSED test_rs_score_alch_percentile")


def test_rs_score_alch_sorts_unsorted_input():
    """Percentile ranks must be correct even for an unsorted input list."""
    items = [
        Item(id=3, name="C", members=False, buy_limit=100,
             alch_value=0, buy_price=100, sell_price=50, volume=10,
             profit=5, gp_per_hour=100),
        Item(id=1, name="A", members=False, buy_limit=100,
             alch_value=0, buy_price=100, sell_price=50, volume=10,
             profit=10, gp_per_hour=1000),
        Item(id=2, name="B", members=False, buy_limit=100,
             alch_value=0, buy_price=100, sell_price=50, volume=10,
             profit=20, gp_per_hour=500),
    ]
    compute_rs_score_alch(items)
    by_id = {i.id: i for i in items}
    assert by_id[1].rs_score > by_id[2].rs_score > by_id[3].rs_score, \
        "scores must follow gp_per_hour even when input was unsorted"
    print("  PASSED test_rs_score_alch_sorts_unsorted_input")



def _reset_cooldowns():
    """Clear all cooldowns and use in-memory state for test isolation."""
    import rshelper.signals as _s
    _orig_load = _s._load_cooldowns
    _orig_save = _s._save_cooldowns
    _state = {}
    _s._load_cooldowns = lambda: dict(_state)
    _s._save_cooldowns = lambda data: _state.update(data)
    return (_orig_load, _orig_save)

def _restore_cooldowns(orig):
    import rshelper.signals as _s
    _s._load_cooldowns, _s._save_cooldowns = orig

# --- Signal detection tests ---

def _make_item(item_id=1, name="Test", buy=100, sell=90, volume=100, buy_limit=100):
    return Item(id=item_id, name=name, members=False, buy_limit=buy_limit,
                alch_value=0, buy_price=buy, sell_price=sell,
                volume=volume, profit=0, gp_per_hour=0)


def _make_vol(avg_high=100, avg_low=90, high_vol=50, low_vol=50):
    return {"avgHighPrice": avg_high, "avgLowPrice": avg_low,
            "highPriceVolume": high_vol, "lowPriceVolume": low_vol}


def test_dump_detection():
    """Sell price >10% below 5m avg -> DUMP signal."""
    items = [_make_item(sell=80)]
    vol_5m = {"1": _make_vol(avg_low=90, high_vol=60, low_vol=60)}
    signals = detect_signals(items, vol_5m, cooldown_sec=0)
    dump_signals = [s for s in signals if s.type == "DUMP"]
    assert len(dump_signals) == 1
    print("  PASSED test_dump_detection")


def test_crash_detection():
    """Sell price >20% below 5m avg -> CRASH signal."""
    items = [_make_item(sell=70)]
    vol_5m = {"1": _make_vol(avg_low=90, high_vol=60, low_vol=60)}
    signals = detect_signals(items, vol_5m, cooldown_sec=0)
    crash_signals = [s for s in signals if s.type == "CRASH"]
    assert len(crash_signals) == 1
    print("  PASSED test_crash_detection")


def test_surge_detection():
    """5m volume >3x rolling baseline -> SURGE signal on a later scan."""
    _baseline_state.clear()
    item = _make_item(item_id=777, volume=100)
    items = [item]
    first = detect_signals(items, {"777": _make_vol(high_vol=50, low_vol=50)},
                           cooldown_sec=0)  # seeds baseline 100
    assert not [s for s in first if s.type == "SURGE"], \
        "First scan has no baseline, so no SURGE yet"
    signals = detect_signals(items, {"777": _make_vol(high_vol=200, low_vol=200)},
                             cooldown_sec=0)  # 400 > 3x100
    surge_signals = [s for s in signals if s.type == "SURGE"]
    assert len(surge_signals) == 1
    # deviation is a percentage like the other signal types: 400 vs 100
    # baseline is +300%, not a raw 4.0 multiplier
    assert surge_signals[0].deviation == 300.0, \
        f"expected +300% deviation, got {surge_signals[0].deviation}"
    print("  PASSED test_surge_detection")


def test_flip_detection():
    """Spread >5% + volume >500 -> FLIP signal."""
    item = _make_item(item_id=60, buy=100, sell=90, volume=600)
    item.rs_score = 50
    items = [item]
    vol_5m = {"60": _make_vol(high_vol=300, low_vol=300)}
    signals = detect_signals(items, vol_5m, cooldown_sec=0)
    flip_signals = [s for s in signals if s.type == "FLIP"]
    assert len(flip_signals) == 1
    assert flip_signals[0].severity == "MEDIUM"
    print("  PASSED test_flip_detection")


def test_flip_ids_restrict_flip_detection():
    """DUMP/CRASH must see the full universe; FLIP only fires for flip_ids."""
    items = [
        _make_item(item_id=1, name="A", buy=100, sell=70, volume=600),
        _make_item(item_id=2, name="B", buy=100, sell=84, volume=600),
    ]
    items[0].rs_score = 80
    items[1].rs_score = 80
    vol_5m = {"1": _make_vol(avg_low=95, high_vol=300, low_vol=300),
              "2": _make_vol(avg_low=95, high_vol=300, low_vol=300)}
    signals = detect_signals(items, vol_5m, cooldown_sec=0, flip_ids={2})
    flips = [s for s in signals if s.type == "FLIP"]
    assert [s.item_id for s in flips] == [2], \
        f"FLIP must be restricted to flip_ids, got {[s.item_id for s in flips]}"
    crashes = {s.item_id for s in signals if s.type == "CRASH"}
    dumps = {s.item_id for s in signals if s.type == "DUMP"}
    assert crashes == {1}, \
        "item 1 crashes even though it is not a flip candidate"
    assert dumps == {2}
    print("  PASSED test_flip_ids_restrict_flip_detection")


def test_cooldown_save_failure_does_not_kill_scan():
    """A failing cooldown save must not abort the scan or drop signals."""
    import rshelper.signals as _s
    orig = _reset_cooldowns()
    orig_save = _s._save_cooldowns

    def boom(data):
        raise OSError("disk full")

    _s._save_cooldowns = boom
    try:
        items = [_make_item(item_id=77, sell=70)]
        vol_5m = {"77": _make_vol(avg_low=90, high_vol=60, low_vol=60)}
        signals = detect_signals(items, vol_5m, cooldown_sec=0)
        assert len(signals) == 1, "signal must survive a cooldown save failure"
    finally:
        _s._save_cooldowns = orig_save
        _restore_cooldowns(orig)
    print("  PASSED test_cooldown_save_failure_does_not_kill_scan")


def test_no_signals_without_real_5m_data():
    """Tracker-shaped volume (no avg prices) must not produce signals."""
    item = _make_item(item_id=99, buy=100, sell=90, volume=600)
    item.rs_score = 50
    vol_5m = {"99": {"highPriceVolume": 300, "lowPriceVolume": 300}}
    signals = detect_signals([item], vol_5m, cooldown_sec=0)
    assert signals == []
    print("  PASSED test_no_signals_without_real_5m_data")


def test_concurrent_cooldown_save():
    """Concurrent signal scans must not race on the shared .tmp path."""
    import threading
    import tempfile
    from pathlib import Path
    import rshelper.signals as _s
    tmp = Path(tempfile.mkdtemp())
    old_dir, old_path = _s.COOLDOWN_DIR, _s.COOLDOWN_PATH
    _s.COOLDOWN_DIR = tmp
    _s.COOLDOWN_PATH = tmp / "signal_cooldowns.json"
    errors = []

    def writer():
        try:
            _s._save_cooldowns({"k": 1})
        except Exception as e:
            errors.append(e)

    try:
        threads = [threading.Thread(target=writer) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == [], f"race errors: {errors}"
        assert _s.COOLDOWN_PATH.exists()
    finally:
        _s.COOLDOWN_DIR, _s.COOLDOWN_PATH = old_dir, old_path
    print("  PASSED test_concurrent_cooldown_save")


def test_cooldown_suppression():
    """Same signal type for same item suppressed within cooldown."""
    orig = _reset_cooldowns()
    try:
        items = [_make_item(item_id=99, sell=70)]
        vol_5m = {"99": _make_vol(avg_low=90, high_vol=60, low_vol=60)}

        s1 = detect_signals(items, vol_5m, cooldown_sec=999)  # long cooldown
        crash1 = [s for s in s1 if s.type == "CRASH"]
        assert len(crash1) == 1, f"Expected 1 CRASH, got {len(crash1)}: {[s.type for s in s1]}"

        s2 = detect_signals(items, vol_5m, cooldown_sec=999)
        crash2 = [s for s in s2 if s.type == "CRASH"]
        assert len(crash2) == 0, "Signal should be suppressed by cooldown"
    finally:
        _restore_cooldowns(orig)
    print("  PASSED test_cooldown_suppression")

def test_cooldown_expiry():
    """Signal fires again after cooldown expires."""
    orig = _reset_cooldowns()
    try:
        items = [_make_item(item_id=98, sell=70)]
        vol_5m = {"98": _make_vol(avg_low=90, high_vol=60, low_vol=60)}

        s1 = detect_signals(items, vol_5m, cooldown_sec=0)
        crash1 = [s for s in s1 if s.type == "CRASH"]
        assert len(crash1) == 1

        s2 = detect_signals(items, vol_5m, cooldown_sec=0)
        crash2 = [s for s in s2 if s.type == "CRASH"]
        assert len(crash2) == 1, "Signal should fire again after 0 cooldown"
    finally:
        _restore_cooldowns(orig)
    print("  PASSED test_cooldown_expiry")


def test_no_false_positives():
    """Normal prices produce no signals."""
    items = [_make_item(item_id=70, buy=100, sell=99, volume=50)]
    vol_5m = {"70": _make_vol(avg_high=100, avg_low=99, high_vol=25, low_vol=25)}
    signals = detect_signals(items, vol_5m, cooldown_sec=0)
    assert len(signals) == 0, f"Expected 0 signals, got {len(signals)}"
    print("  PASSED test_no_false_positives")


def test_empty_input():
    """Empty items list produces empty signals."""
    signals = detect_signals([], {}, cooldown_sec=0)
    assert len(signals) == 0
    print("  PASSED test_empty_input")


def test_signal_serialization():
    """Signal fields are accessible and correctly typed."""
    from rshelper.signals import Signal
    s = Signal(
        type="DUMP", item_id=1, name="Test", severity="MEDIUM",
        current_price=100, deviation=-12.5,
        message="Test: -12.5% vs 5m avg",
    )
    d = {"type": s.type, "item_id": s.item_id, "name": s.name,
         "severity": s.severity, "current_price": s.current_price,
         "deviation": s.deviation, "message": s.message}
    assert d["type"] == "DUMP"
    assert d["deviation"] == -12.5
    print("  PASSED test_signal_serialization")


def test_signals_help():
    """rshelper signals --help exits 0."""
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "rshelper", "signals", "--help"],
        capture_output=True, text=True,
        cwd=os.path.join(os.path.dirname(__file__), ".."),
        env={**os.environ, "PYTHONPATH": "src"},
    )
    assert result.returncode == 0, f"signals --help failed: {result.stderr}"
    assert "signals" in result.stdout.lower()
    print("  PASSED test_signals_help")


def test_rs_score_in_margin_scanner():
    """MarginScanner results have rs_score set from confidence."""
    from rshelper.scanner import MarginScanner
    from rshelper.analysis import MarginAnalysis

    class MockAnalysis:
        item_id = 1
        confidence = 0.75
        expected_gp_per_hour = 1000
        rs_score = 0.0

    scanner = MarginScanner()
    import rshelper.scanner as smod
    original = smod.analyze_timeseries
    smod.analyze_timeseries = lambda *a, **kw: MockAnalysis()

    try:
        item = Item(id=1, name="Test", members=False, buy_limit=100,
                    alch_value=0, buy_price=100, sell_price=90,
                    volume=50, profit=0, gp_per_hour=0)
        lookup = {1: item}
        ts_data = {1: [{"avgHighPrice": 100, "avgLowPrice": 90}]}
        results = scanner.scan(lookup, ts_data)
        assert len(results) == 1
        assert results[0].rs_score == 75.0
    finally:
        smod.analyze_timeseries = original
    print("  PASSED test_rs_score_in_margin_scanner")


if __name__ == "__main__":
    test_rs_score_flip_basic()
    test_rs_score_flip_zero_volume()
    test_rs_score_flip_freshness_from_age()
    test_rs_score_alch_percentile()
    test_rs_score_alch_sorts_unsorted_input()
    test_dump_detection()
    test_crash_detection()
    test_surge_detection()
    test_flip_detection()
    test_flip_ids_restrict_flip_detection()
    test_cooldown_save_failure_does_not_kill_scan()
    test_no_signals_without_real_5m_data()
    test_concurrent_cooldown_save()
    test_cooldown_suppression()
    test_cooldown_expiry()
    test_no_false_positives()
    test_empty_input()
    test_signal_serialization()
    test_signals_help()
    test_rs_score_in_margin_scanner()
    print("\nAll signals tests passed.")
