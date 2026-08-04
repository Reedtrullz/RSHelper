"""Tests for the autonomous paper trader."""

import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from rshelper.models import Item
from rshelper.config import TraderConfig
import rshelper.trader as tmod
import rshelper.journal as jmod
import rshelper.positions as pmod

_tmpdir = tempfile.TemporaryDirectory()
jmod.TRADES_PATH = Path(_tmpdir.name) / "trades.json"
pmod.POSITIONS_PATH = Path(_tmpdir.name) / "positions.json"
tmod.EXITS_PATH = Path(_tmpdir.name) / "recent_exits.json"

from rshelper.trader import (
    exit_reason,
    select_candidates,
    size_position,
    run_cycle,
)


def _clean():
    tmod._RECENT_EXITS.clear()
    if tmod.EXITS_PATH.exists():
        tmod.EXITS_PATH.unlink()
    for path in (jmod.TRADES_PATH, pmod.POSITIONS_PATH):
        if path.exists():
            path.unlink()


def _cfg(**kw):
    defaults = dict(capital=1_000_000, trade_capital_frac=0.25, max_positions=3,
                    min_volume=800, min_price=25, max_spread_ratio=5.0,
                    dip_depth_pct=2.0, max_dip_pct=10.0, min_spread_pct=4.0,
                    max_entry_spread_pct=5.0,
                    reentry_minutes=30, stop_reentry_minutes=90,
                    take_profit_pct=3.0, stop_loss_pct=-1.5,
                    stop_grace_minutes=10,
                    max_hold_minutes=180, spread_collapse_exit_minutes=60,
                    min_exit_spread_pct=1.0, interval_sec=120,
                    stop_slippage=0.97, stop_mark_blend=0.0)
    defaults.update(kw)
    return TraderConfig(**defaults)


def _item(iid, name, high, low, volume, limit=10000):
    """high = offer (instant buy), low = bid (instant sell)."""
    profit = high - low - 1
    return Item(id=iid, name=name, members=False, buy_limit=limit, alch_value=0,
                buy_price=high, sell_price=low, volume=volume, profit=profit,
                gp_per_hour=profit * min(limit / 4, volume * 12))


def _latest(now, **prices):
    out = {}
    for iid, (high, low) in prices.items():
        out[str(iid)] = {"high": high, "low": low,
                         "highTime": now - 30, "lowTime": now - 30}
    return out


def test_select_candidates_filters():
    now = int(time.time())
    items = [
        _item(1, "Dipped", 100, 96, 1000),     # 4.2% spread, 4% below avg
        _item(2, "Thin", 100, 96, 50),         # too little volume
        _item(3, "WideSpread", 106, 96, 1000), # 10.4% spread: spread cap
        _item(9, "NoDip", 103, 99, 1000),      # 4% spread, 1% dip: dip guard
        _item(4, "Stale", 100, 96, 1000),      # old timestamp
        _item(5, "NoBaseline", 100, 96, 1000), # no avgLowPrice
        _item(6, "WideGap", 106, 90, 1000),    # 17.8% high/low gap
        _item(7, "Freefall", 100, 80, 1000),   # 20% below average
        _item(8, "ThinSpread", 101, 100, 1000),  # 1% spread < min spread
        _item(10, "TooCheap", 26, 24, 1000),   # bid below min_price 25
    ]
    latest = _latest(now, **{"1": (100, 96), "2": (100, 96), "3": (106, 96),
                             "9": (103, 99), "5": (100, 96)})
    latest["4"] = {"high": 100, "low": 96, "highTime": now - 400, "lowTime": now - 400}
    vol_5m = {"1": {"avgLowPrice": 100}, "2": {"avgLowPrice": 100},
              "3": {"avgLowPrice": 100}, "4": {"avgLowPrice": 100},
              "9": {"avgLowPrice": 100}, "6": {"avgLowPrice": 100},
              "7": {"avgLowPrice": 100}, "8": {"avgLowPrice": 100},
              "10": {"avgLowPrice": 30}}
    cfg = _cfg()
    candidates = select_candidates(items, latest, vol_5m, cfg, now=now)
    assert [c.id for c in candidates] == [1], \
        f"expected only item 1, got {[c.id for c in candidates]}"
    print("  PASSED test_select_candidates_filters")


def test_exit_reason():
    now = time.time()
    cfg = _cfg(stop_grace_minutes=0)  # bypass grace: test stop mechanics
    from rshelper.positions import Position
    p = Position(id=1, item_id=1, name="X", qty=10, buy_price=97,
                 direction="traditional",
                 opened_at=(datetime.now(timezone.utc)).isoformat())
    # take profit: offer 102 -> (102-97-2)/97 = +3.1% >= +3.0%
    assert exit_reason(p, _latest(now, **{"1": (102, 97)}), cfg, now=now) == "take_profit"
    # hold: offer 100 -> (100-97-2)/97 = +1.0% < +3.0%; bid == entry bid
    assert exit_reason(p, _latest(now, **{"1": (100, 97)}), cfg, now=now) is None
    # stop loss: bid 94 -> -3.1% from entry bid 97; stop is -1.5%
    assert exit_reason(p, _latest(now, **{"1": (100, 94)}), cfg, now=now) == "stop_loss"
    # bid 96 -> -1.0% from entry bid 97: within -1.5% stop -> hold
    assert exit_reason(p, _latest(now, **{"1": (100, 96)}), cfg, now=now) is None
    # stale price -> hold
    stale = {"1": {"high": 102, "low": 97, "highTime": now - 500, "lowTime": now - 500}}
    assert exit_reason(p, stale, cfg, now=now) is None
    # max hold
    old = Position(id=2, item_id=1, name="X", qty=10, buy_price=97,
                   direction="traditional",
                   opened_at=(datetime.now(timezone.utc) - timedelta(hours=5)).isoformat())
    assert exit_reason(old, _latest(now, **{"1": (102, 97)}), cfg, now=now) == "max_hold"
    # max hold fires even without any price data (dead item)
    assert exit_reason(old, {}, cfg, now=now) == "max_hold"
    print("  PASSED test_exit_reason")


def test_candidate_edge_ranking():
    """Candidates rank by expected edge (dip x net spread), not raw volume."""
    _clean()
    now = int(time.time())
    items = [
        _item(1, "BigShallow", 100, 96, 5000),  # dip ~4%
        _item(2, "SmallDeep", 100, 96, 900),    # dip ~9.9%
    ]
    latest = _latest(now, **{"1": (100, 96), "2": (100, 96)})
    vol_5m = {"1": {"avgLowPrice": 99.1}, "2": {"avgLowPrice": 106.6}}
    cfg = _cfg()
    cands = select_candidates(items, latest, vol_5m, cfg, now=now)
    assert [c.id for c in cands] == [2, 1], \
        f"edge ranking expected [2, 1], got {[c.id for c in cands]}"
    print("  PASSED test_candidate_edge_ranking")


def test_thin_dip_skipped_volume_backed_accepted():
    """Dip entries need low-price volume support (no print-only bids)."""
    now = int(time.time())
    items = [
        _item(1, "RealDip", 100, 96, 1000),    # dip, volume-backed
        _item(2, "PrintDip", 100, 96, 1000),   # dip, thin low print
        _item(3, "NoVolData", 100, 96, 1000),  # fallback: no volume fields
    ]
    latest = _latest(now, **{"1": (100, 96), "2": (100, 96), "3": (100, 96)})
    vol_5m = {
        "1": {"avgLowPrice": 100, "lowPriceVolume": 500, "highPriceVolume": 500},
        "2": {"avgLowPrice": 100, "lowPriceVolume": 10, "highPriceVolume": 1000},
        "3": {"avgLowPrice": 100},
    }
    cfg = _cfg()
    candidates = select_candidates(items, latest, vol_5m, cfg, now=now)
    assert sorted(c.id for c in candidates) == [1, 3], \
        f"thin print must be skipped, got {[c.id for c in candidates]}"
    # 10 low-volume units is still thin even when the absolute floor is low.
    cfg2 = _cfg(artifact_min_low_vol=1)
    candidates2 = select_candidates(items, latest, vol_5m, cfg2, now=now)
    assert 2 not in [c.id for c in candidates2]  # 10 < 10% of 1010
    print("  PASSED test_thin_dip_skipped_volume_backed_accepted")


def test_stop_on_thin_print_fills_at_window_avg():
    """A stop fired by a thin crash print fills at the 5m window average."""
    _clean()
    from unittest import mock
    from rshelper.positions import open_position
    now = int(time.time())
    open_position(1, "Dipped", 100, 97, note="auto", entry_sell=97,
                  direction="traditional")
    latest = _latest(now, **{"1": (100, 80)})  # -17% print
    vol_5m = {"1": {"avgLowPrice": 100, "lowPriceVolume": 5,
                    "highPriceVolume": 5000}}
    with mock.patch("rshelper.cli._fetch_bootstrap",
                    return_value=([], latest, vol_5m, [])):
        result = run_cycle(_cfg(stop_grace_minutes=0))
    assert len(result["closed"]) == 1
    assert result["closed"][0]["reason"] == "stop_loss"
    assert result["closed"][0]["fill_guard"] is True
    trade = jmod.list_trades()[0]
    assert trade.sell_price == 97, "fill must cap at the entry bid"
    assert trade.quote_sell == 80, "the raw print is still reported"
    assert trade.fill_guard is True
    print("  PASSED test_stop_on_thin_print_fills_at_window_avg")


def test_stop_on_real_crash_keeps_print_fill():
    """A crash with volume at the low keeps the print fill with slippage."""
    _clean()
    from unittest import mock
    from rshelper.positions import open_position
    now = int(time.time())
    open_position(1, "Dipped", 100, 97, note="auto", entry_sell=97,
                  direction="traditional")
    latest = _latest(now, **{"1": (100, 80)})
    vol_5m = {"1": {"avgLowPrice": 82, "lowPriceVolume": 2000,
                    "highPriceVolume": 3000}}
    with mock.patch("rshelper.cli._fetch_bootstrap",
                    return_value=([], latest, vol_5m, [])):
        result = run_cycle(_cfg(stop_grace_minutes=0))
    assert len(result["closed"]) == 1
    assert result["closed"][0]["fill_guard"] is False
    trade = jmod.list_trades()[0]
    assert trade.sell_price == int(80 * tmod.STOP_SLIPPAGE)
    assert trade.fill_guard is False
    print("  PASSED test_stop_on_real_crash_keeps_print_fill")


def test_stop_normal_decline_not_guarded():
    """A normal -2% stop is not an outlier: slippage fill as before."""
    _clean()
    from unittest import mock
    from rshelper.positions import open_position
    now = int(time.time())
    open_position(1, "Dipped", 100, 97, note="auto", entry_sell=97,
                  direction="traditional")
    latest = _latest(now, **{"1": (100, 94)})  # -3.1%: normal stop
    vol_5m = {"1": {"avgLowPrice": 95, "lowPriceVolume": 5,
                    "highPriceVolume": 5000}}  # thin but not an outlier
    with mock.patch("rshelper.cli._fetch_bootstrap",
                    return_value=([], latest, vol_5m, [])):
        result = run_cycle(_cfg(stop_grace_minutes=0))
    assert len(result["closed"]) == 1
    assert result["closed"][0]["fill_guard"] is False
    trade = jmod.list_trades()[0]
    assert trade.sell_price == int(94 * tmod.STOP_SLIPPAGE)
    print("  PASSED test_stop_normal_decline_not_guarded")


def test_spread_collapse_exit():
    """After the collapse window, an idling position exits; TP/SL/max_hold
    take precedence."""
    _clean()
    from rshelper.positions import open_position
    cfg = _cfg(spread_collapse_exit_minutes=60, min_exit_spread_pct=1.0)
    now = time.time()
    open_position(1, "X", 10, 97, note="auto", direction="traditional",
                  entry_sell=97, entry_offer=100)
    pos = pmod._load()
    pos[0]["opened_at"] = (datetime.now(timezone.utc) -
                           timedelta(minutes=90)).isoformat()
    pmod._save(pos)
    p = pmod.list_positions()[0]
    # Time-based exit: 90 min old (>= 60m window) exits even with a healthy
    # spread — idling positions sell at the better of offer/bid instead of
    # riding to max_hold and booking the tax.
    assert exit_reason(p, _latest(now, **{"1": (100, 97)}), cfg, now=now) == \
        "spread_collapse"
    # young position (< 60m): holds even with a collapsed spread (edge may
    # re-widen, and the stop/TP own the extremes)
    open_position(2, "Y", 10, 97, note="auto", direction="traditional",
                  entry_sell=97, entry_offer=100)
    p2 = [pp for pp in pmod.list_positions() if pp.item_id == 2][0]
    assert exit_reason(p2, _latest(now, **{"2": (98, 97)}), cfg, now=now) is None
    # max_hold still takes precedence over the collapse exit
    pos2 = pmod._load()
    for row in pos2:
        if row["item_id"] == 1:
            row["opened_at"] = (datetime.now(timezone.utc) -
                                timedelta(hours=5)).isoformat()
    pmod._save(pos2)
    p1 = [pp for pp in pmod.list_positions() if pp.item_id == 1][0]
    assert exit_reason(p1, _latest(now, **{"1": (98, 97)}), cfg, now=now) == \
        "max_hold"
    print("  PASSED test_spread_collapse_exit")


def test_run_cycle_spread_collapse_closes_at_bid():
    _clean()
    from unittest import mock
    from rshelper.positions import open_position
    open_position(1, "X", 10, 97, note="auto", direction="traditional",
                  entry_sell=97, entry_offer=100)
    pos = pmod._load()
    pos[0]["opened_at"] = (datetime.now(timezone.utc) -
                           timedelta(minutes=90)).isoformat()
    pmod._save(pos)
    now = int(time.time())
    # Spread collapsed; the offer (98) is the better fill than the bid (97).
    latest = _latest(now, **{"1": (98, 97)})
    with mock.patch("rshelper.cli._fetch_bootstrap",
                    return_value=([], latest, {}, [])):
        result = run_cycle(_cfg())
    assert len(result["closed"]) == 1
    assert result["closed"][0]["reason"] == "spread_collapse"
    assert result["closed"][0]["sell_price"] == 98  # sold at the offer (better)
    trade = jmod.list_trades()[0]
    assert trade.exit_reason == "spread_collapse"
    assert trade.sell_price == 98
    assert trade.entry_spread_pct == round((100 - 97) / 97 * 100, 2)
    print("  PASSED test_run_cycle_spread_collapse_closes_at_bid")


def test_size_position_caps():
    cfg = _cfg(capital=1_000_000, trade_capital_frac=0.25)  # 250k per trade
    entry = _item(1, "X", 1050, 1000, 10000, limit=200)
    assert size_position(cfg, 0, entry) == 200  # buy limit binds
    entry2 = _item(2, "X", 1050, 1000, 10000, limit=100000)
    assert size_position(cfg, 0, entry2) == 250  # budget binds (250k // 1000)
    entry3 = _item(3, "X", 1050, 1000, 100, limit=100000)  # thin market
    assert size_position(cfg, 0, entry3) == 10  # 10% of volume binds
    # bankroll already used up
    assert size_position(cfg, 1_000_000, entry2) == 0
    print("  PASSED test_size_position_caps")


def test_run_cycle_opens_and_closes(monkeypatch_cleanup=None):
    _clean()
    from unittest import mock
    now = int(time.time())
    items = [_item(1, "Dipped", 100, 96, 10000, limit=5000)]
    latest = _latest(now, **{"1": (100, 97)})
    vol_5m = {"1": {"avgLowPrice": 100}}
    cfg = _cfg()
    with mock.patch("rshelper.cli._fetch_bootstrap",
                    return_value=([], latest, vol_5m, items)):
        result = run_cycle(cfg)
    assert len(result["opened"]) == 1, result
    positions = pmod.list_positions()
    assert len(positions) == 1 and positions[0].note == "auto"
    assert positions[0].direction == "traditional"
    assert positions[0].buy_price == 96  # entered at the bid
    # next cycle: offer 103 -> (103-97-2)/97 = +4.1% -> take profit at offer
    latest2 = _latest(now, **{"1": (103, 97)})
    with mock.patch("rshelper.cli._fetch_bootstrap",
                    return_value=([], latest2, vol_5m, items)):
        result2 = run_cycle(cfg)
    assert len(result2["closed"]) == 1
    assert result2["closed"][0]["reason"] == "take_profit"
    assert len(jmod.list_trades()) == 1
    trade = jmod.list_trades()[0]
    assert trade.strategy == "auto"
    assert trade.exit_reason == "take_profit"
    assert isinstance(trade.hold_minutes, float)
    assert trade.sell_price == 103  # sold at the offer
    assert trade.quote_sell == 103
    assert pmod.list_positions() == []
    print("  PASSED test_run_cycle_opens_and_closes")


def test_spread_does_not_insta_stop_and_stop_records_slippage():
    _clean()
    from unittest import mock
    from rshelper.positions import open_position
    now = int(time.time())
    # Bought at the bid 97; a flat quote (bid still 97) must hold the
    # position instead of stopping out on the entry spread.
    open_position(1, "Dipped", 100, 97, note="auto", entry_sell=97,
                  direction="traditional")
    latest = _latest(now, **{"1": (100, 97)})  # unchanged -> hold
    with mock.patch("rshelper.cli._fetch_bootstrap",
                    return_value=([], latest, {}, [])):
        result = run_cycle(_cfg())
    assert result["closed"] == [], "flat quote after entry must hold"
    # A real 2%+ drop of the bid below the entry bid (97 -> 94) triggers it.
    latest = _latest(now, **{"1": (100, 94)})
    with mock.patch("rshelper.cli._fetch_bootstrap",
                    return_value=([], latest, {}, [])):
        result = run_cycle(_cfg(stop_grace_minutes=0))
    assert len(result["closed"]) == 1
    assert result["closed"][0]["reason"] == "stop_loss"
    trade = jmod.list_trades()[0]
    assert trade.exit_reason == "stop_loss"
    assert trade.quote_sell == 94
    assert trade.sell_price == int(94 * tmod.STOP_SLIPPAGE)  # slippage
    print("  PASSED test_spread_does_not_insta_stop_and_stop_records_slippage")


def test_stop_loss_legacy_position_uses_buy_mark():
    """Legacy arbitrage positions stop from the entry mark (buy fallback)."""
    _clean()
    from unittest import mock
    from rshelper.positions import open_position
    now = int(time.time())
    open_position(1, "Legacy", 100, 100, note="auto")  # arbitrage (default)
    latest = _latest(now, **{"1": (100, 98)})  # -2% from buy -> stop
    with mock.patch("rshelper.cli._fetch_bootstrap",
                    return_value=([], latest, {}, [])):
        result = run_cycle(_cfg())
    assert len(result["closed"]) == 1
    assert result["closed"][0]["reason"] == "stop_loss"
    trade = jmod.list_trades()[0]
    assert trade.exit_reason == "stop_loss"
    assert trade.quote_sell == 98
    assert trade.sell_price == int(98 * tmod.STOP_SLIPPAGE)
    print("  PASSED test_stop_loss_legacy_position_uses_buy_mark")


def test_stop_mark_blend_gives_dip_allowance():
    """stop_mark_blend moves the stop reference toward the 5m avg low."""
    _clean()
    from rshelper.positions import open_position
    now = time.time()
    # Entry bid 97, avg_low 100 (a ~3% dip). With stop_mark_blend=0.5 the
    # stop mark is 98.5. Legacy (blend 0): bid 97.2 is -0.8% from entry bid
    # 97 -> hold; blend 0.5: bid 97.2 is -1.32% from mark 98.5 -> also hold.
    # The key difference: bid 96.8 is -0.2% from entry bid (legacy holds)
    # but -1.73% from mark 98.5 (blend stops — the position has drifted
    # meaningfully below the window average, not just the entry print).
    open_position(1, "Dipped", 100, 97, note="auto", entry_sell=97,
                  direction="traditional")
    # Legacy blend 0: bid 96.8 is -0.2% from entry bid -> hold
    cfg0 = _cfg(stop_mark_blend=0.0, stop_loss_pct=-1.5)
    assert exit_reason(pmod.list_positions()[0],
                       _latest(now, **{"1": (100, 96)}), cfg0, now=now,
                       avg_low=100) is None
    # Blend 0.5: bid 96.8 is -1.73% from mark 98.5 -> stop
    cfg = _cfg(stop_mark_blend=0.5, stop_loss_pct=-1.5, stop_grace_minutes=0)
    assert exit_reason(pmod.list_positions()[0],
                       _latest(now, **{"1": (100, 96)}), cfg, now=now,
                       avg_low=100) == "stop_loss"
    # Blend 0.5: bid 98 (above entry bid, below avg) -> +1.5% from mark -> hold
    assert exit_reason(pmod.list_positions()[0],
                       _latest(now, **{"1": (100, 98)}), cfg, now=now,
                       avg_low=100) is None
    print("  PASSED test_stop_mark_blend_gives_dip_allowance")


def test_stop_mark_blend_zero_is_legacy():
    """stop_mark_blend=0.0 keeps the legacy stop-from-entry-bid behavior."""
    _clean()
    from rshelper.positions import open_position
    now = time.time()
    open_position(1, "Dipped", 100, 97, note="auto", entry_sell=97,
                  direction="traditional")
    cfg = _cfg(stop_mark_blend=0.0, stop_loss_pct=-1.5)
    # bid 96 -> -1.0% from entry bid 97 -> within -1.5% -> hold
    assert exit_reason(pmod.list_positions()[0],
                       _latest(now, **{"1": (100, 96)}), cfg, now=now) is None
    print("  PASSED test_stop_mark_blend_zero_is_legacy")


def test_stop_slippage_configurable():
    """stop_slippage config knob controls stop fill degradation."""
    _clean()
    from unittest import mock
    from rshelper.positions import open_position
    now = int(time.time())
    open_position(1, "Dipped", 100, 97, note="auto", entry_sell=97,
                  direction="traditional")
    latest = _latest(now, **{"1": (100, 94)})
    with mock.patch("rshelper.cli._fetch_bootstrap",
                    return_value=([], latest, {}, [])):
        result = run_cycle(_cfg(stop_slippage=0.99, stop_grace_minutes=0))
    trade = jmod.list_trades()[0]
    assert trade.sell_price == int(94 * 0.99)
    print("  PASSED test_stop_slippage_configurable")


def test_candidate_confidence_tiebreaker():
    """Confidence model breaks ties between equal edges."""
    _clean()
    now = int(time.time())
    items = [
        _item(1, "A", 100, 96, 5000),   # same dip/spread as B
        _item(2, "B", 100, 96, 900),    # lower volume
        _item(3, "C", 100, 96, 3000),   # same dip/spread as A, mid volume
    ]
    latest = _latest(now, **{"1": (100, 96), "2": (100, 96), "3": (100, 96)})
    vol_5m = {"1": {"avgLowPrice": 99}, "2": {"avgLowPrice": 99},
              "3": {"avgLowPrice": 99}}
    cfg = _cfg()
    # Without confidence: volume breaks ties (A 5000 > C 3000 > B 900)
    no_conf = select_candidates(items, latest, vol_5m, cfg, now=now)
    assert [c.id for c in no_conf] == [1, 3, 2]
    # With confidence: item 3 (mid volume) has the highest confidence and
    # outranks item 1 despite lower volume.
    conf = {1: 0.3, 2: 0.1, 3: 0.9}
    with_conf = select_candidates(items, latest, vol_5m, cfg, now=now,
                                  confidence=conf)
    assert [c.id for c in with_conf] == [3, 1, 2]
    print("  PASSED test_candidate_confidence_tiebreaker")


def test_auto_ge_fill_closes_at_offer():
    """A filled auto buy-offer closes itself at the offer (no manual click)."""
    _clean()
    from unittest import mock
    from rshelper.positions import open_position
    now = int(time.time())
    # Position opened 10 min ago on a liquid item: fill completes fast.
    open_position(1, "Dipped", 100, 97, note="auto", direction="traditional",
                  entry_sell=97, entry_offer=100)
    pos = pmod._load()
    pos[0]["opened_at"] = (datetime.now(timezone.utc) -
                           timedelta(minutes=10)).isoformat()
    pmod._save(pos)
    # No TP/SL/collapse/max_hold: offer 100 (net +1.0% < +3.0% TP), bid ==
    # entry bid 97 (no stop). But the simulated GE fill is complete (1000
    # units/min for qty 100 over 10 min), so the trader closes it at the offer.
    latest = _latest(now, **{"1": (100, 97)})
    vol_5m = {"1": {"avgLowPrice": 100, "highPriceVolume": 5000,
                    "lowPriceVolume": 5000}}
    with mock.patch("rshelper.cli._fetch_bootstrap",
                    return_value=([], latest, vol_5m, [])):
        result = run_cycle(_cfg())
    assert len(result["closed"]) == 1, result
    assert result["closed"][0]["reason"] == "ge_fill"
    assert result["closed"][0]["sell_price"] == 100  # sold at the offer
    trade = jmod.list_trades()[0]
    assert trade.exit_reason == "ge_fill"
    assert trade.sell_price == 100
    assert pmod.list_positions() == []
    print("  PASSED test_auto_ge_fill_closes_at_offer")


def test_manual_position_not_auto_closed_by_ge_fill():
    """Manual paper positions are not closed by the trader's ge_fill path."""
    _clean()
    from unittest import mock
    from rshelper.positions import open_position
    now = int(time.time())
    open_position(1, "Manual", 100, 97, note="paper", direction="traditional")
    pos = pmod._load()
    pos[0]["opened_at"] = (datetime.now(timezone.utc) -
                           timedelta(minutes=10)).isoformat()
    pmod._save(pos)
    latest = _latest(now, **{"1": (100, 97)})
    vol_5m = {"1": {"avgLowPrice": 100, "highPriceVolume": 5000,
                    "lowPriceVolume": 5000}}
    with mock.patch("rshelper.cli._fetch_bootstrap",
                    return_value=([], latest, vol_5m, [])):
        result = run_cycle(_cfg())
    assert result["closed"] == [], result  # manual positions untouched
    assert len(pmod.list_positions()) == 1
    print("  PASSED test_manual_position_not_auto_closed_by_ge_fill")


def test_ge_fill_skips_when_offer_collapsed():
    """ge_fill must not fire when the offer no longer nets profit over the
    entry bid — a filled close at a collapsed offer would lock in a loss."""
    _clean()
    from unittest import mock
    from rshelper.positions import open_position
    now = int(time.time())
    open_position(1, "Dipped", 100, 97, note="auto", direction="traditional",
                  entry_sell=97, entry_offer=100)
    pos = pmod._load()
    pos[0]["opened_at"] = (datetime.now(timezone.utc) -
                           timedelta(minutes=10)).isoformat()
    pmod._save(pos)
    # Fill is complete, but the offer has collapsed to 96 (< entry bid 97)
    # while the bid 96.5 stays within the -1.5% stop (mark 97 -> -0.5%):
    # ge_fill must NOT close (would sell below entry) and neither does the
    # stop — the position holds for the spread-collapse logic.
    latest = _latest(now, **{"1": (96, 96.5)})
    vol_5m = {"1": {"avgLowPrice": 100, "highPriceVolume": 5000,
                    "lowPriceVolume": 5000}}
    with mock.patch("rshelper.cli._fetch_bootstrap",
                    return_value=([], latest, vol_5m, [])):
        result = run_cycle(_cfg())
    assert result["closed"] == [], result
    assert len(pmod.list_positions()) == 1
    print("  PASSED test_ge_fill_skips_when_offer_collapsed")


def test_ge_fill_requires_net_profit_after_tax():
    """ge_fill must require net profit AFTER the 2% sell tax, not just a
    gross offer above the entry bid. Offer 98 vs buy 97 is gross +1% but
    net -1% (tax 1.96 -> 1), so it must NOT auto-collect."""
    _clean()
    from unittest import mock
    from rshelper.positions import open_position
    now = int(time.time())
    open_position(1, "Dipped", 100, 97, note="auto", direction="traditional",
                  entry_sell=97, entry_offer=100)
    pos = pmod._load()
    pos[0]["opened_at"] = (datetime.now(timezone.utc) -
                           timedelta(minutes=10)).isoformat()
    pmod._save(pos)
    # Offer 98 > bid 97 (gross +1%) but net of 2% tax it's a loss; bid 97
    # is flat vs entry (no stop). ge_fill must NOT fire.
    latest = _latest(now, **{"1": (98, 97)})
    vol_5m = {"1": {"avgLowPrice": 100, "highPriceVolume": 5000,
                    "lowPriceVolume": 5000}}
    with mock.patch("rshelper.cli._fetch_bootstrap",
                    return_value=([], latest, vol_5m, [])):
        result = run_cycle(_cfg())
    assert result["closed"] == [], result
    assert len(pmod.list_positions()) == 1
    # Offer 100: net (100 - 97 - 2)/97 = +1.03% > 0 -> ge_fill fires.
    latest_ok = _latest(now, **{"1": (100, 97)})
    with mock.patch("rshelper.cli._fetch_bootstrap",
                    return_value=([], latest_ok, vol_5m, [])):
        result_ok = run_cycle(_cfg())
    assert len(result_ok["closed"]) == 1
    assert result_ok["closed"][0]["reason"] == "ge_fill"
    print("  PASSED test_ge_fill_requires_net_profit_after_tax")


def test_no_auto_open_on_item_with_manual_position():
    """The trader must not open an auto position on an item that already has
    a manual position — stacking splits the GE slot and bank stack."""
    _clean()
    from unittest import mock
    from rshelper.positions import open_position
    now = int(time.time())
    # A manual position exists for item 1.
    open_position(1, "Dipped", 50, 97, note="paper", direction="traditional")
    # Item 1 is also a valid dip candidate.
    items = [_item(1, "Dipped", 100, 96, 10000, limit=5000)]
    latest = _latest(now, **{"1": (100, 97)})
    vol_5m = {"1": {"avgLowPrice": 100}}
    with mock.patch("rshelper.cli._fetch_bootstrap",
                    return_value=([], latest, vol_5m, items)):
        result = run_cycle(_cfg())
    assert result["opened"] == [], result  # must NOT stack auto on manual
    positions = pmod.list_positions()
    assert len(positions) == 1
    assert positions[0].note == "paper"  # the manual one survives untouched
    print("  PASSED test_no_auto_open_on_item_with_manual_position")


def test_spread_collapse_unfilled_sells_at_bid():
    """A spread-collapse exit sells at the better of offer vs bid — never
    throws away the spread by dumping at the bid."""
    _clean()
    from unittest import mock
    from rshelper.positions import open_position
    open_position(1, "X", 10, 97, note="auto", direction="traditional",
                  entry_sell=97, entry_offer=100)
    pos = pmod._load()
    pos[0]["opened_at"] = (datetime.now(timezone.utc) -
                           timedelta(minutes=90)).isoformat()
    pmod._save(pos)
    now = int(time.time())
    # Offer 98 (better than bid 97) -> sell at 98.
    latest = _latest(now, **{"1": (98, 97)})
    with mock.patch("rshelper.cli._fetch_bootstrap",
                    return_value=([], latest, {}, [])):
        result = run_cycle(_cfg())
    assert len(result["closed"]) == 1
    assert result["closed"][0]["reason"] == "spread_collapse"
    assert result["closed"][0]["sell_price"] == 98  # sold at the offer
    trade = jmod.list_trades()[0]
    assert trade.sell_price == 98
    print("  PASSED test_spread_collapse_unfilled_sells_at_bid")


def test_time_exit_sells_at_offer_when_net_positive():
    """A 60m+ idling position exits at the offer when it nets a profit —
    converts 'ride to max_hold and book tax' into a small win."""
    _clean()
    from unittest import mock
    from rshelper.positions import open_position
    open_position(1, "X", 10, 97, note="auto", direction="traditional",
                  entry_sell=97, entry_offer=100)
    pos = pmod._load()
    pos[0]["opened_at"] = (datetime.now(timezone.utc) -
                           timedelta(minutes=90)).isoformat()
    pmod._save(pos)
    now = int(time.time())
    # Offer 100 nets +1.03% (> 0), bid 97 (flat): the time exit sells at
    # the offer, not the bid.
    latest = _latest(now, **{"1": (100, 97)})
    with mock.patch("rshelper.cli._fetch_bootstrap",
                    return_value=([], latest, {}, [])):
        result = run_cycle(_cfg())
    assert len(result["closed"]) == 1
    assert result["closed"][0]["reason"] == "spread_collapse"
    assert result["closed"][0]["sell_price"] == 100  # sold at the offer
    trade = jmod.list_trades()[0]
    assert trade.sell_price == 100
    assert trade.profit > 0
    print("  PASSED test_time_exit_sells_at_offer_when_net_positive")


def test_stop_grace_period_blocks_early_stop():
    """The stop-loss does not arm during stop_grace_minutes after entry —
    a buy-the-dip entry needs time to revert (51% of stops fired within
    10 min). TP and max_hold still fire during the grace."""
    _clean()
    from unittest import mock
    from rshelper.positions import open_position
    now = int(time.time())
    open_position(1, "Dipped", 100, 97, note="auto", entry_sell=97,
                  direction="traditional")
    # Fresh position (age 0), bid crashed to 94 (-3.1% < -1.5% stop): with
    # the 10-min grace the stop must NOT fire.
    latest = _latest(now, **{"1": (100, 94)})
    with mock.patch("rshelper.cli._fetch_bootstrap",
                    return_value=([], latest, {}, [])):
        result = run_cycle(_cfg())
    assert result["closed"] == [], result
    assert len(pmod.list_positions()) == 1
    # Age the position past the grace: the stop now fires.
    pos = pmod._load()
    pos[0]["opened_at"] = (datetime.now(timezone.utc) -
                           timedelta(minutes=15)).isoformat()
    pmod._save(pos)
    with mock.patch("rshelper.cli._fetch_bootstrap",
                    return_value=([], latest, {}, [])):
        result2 = run_cycle(_cfg())
    assert len(result2["closed"]) == 1
    assert result2["closed"][0]["reason"] == "stop_loss"
    print("  PASSED test_stop_grace_period_blocks_early_stop")


def test_reentry_cooldown():
    _clean()
    from unittest import mock
    now = int(time.time())
    items = [_item(1, "Dipped", 100, 96, 10000, limit=5000)]
    latest = _latest(now, **{"1": (100, 97)})
    vol_5m = {"1": {"avgLowPrice": 100}}
    cfg = _cfg()
    with mock.patch("rshelper.cli._fetch_bootstrap",
                    return_value=([], latest, vol_5m, items)):
        run_cycle(cfg)  # opens position 1
    # price hits take profit -> closes and starts the cooldown
    latest2 = _latest(now, **{"1": (103, 97)})
    with mock.patch("rshelper.cli._fetch_bootstrap",
                    return_value=([], latest2, vol_5m, items)):
        result = run_cycle(cfg)
    assert len(result["closed"]) == 1
    # dip returns immediately, but the item is on cooldown
    with mock.patch("rshelper.cli._fetch_bootstrap",
                    return_value=([], latest, vol_5m, items)):
        result3 = run_cycle(cfg)
    assert result3["opened"] == [], result3
    assert pmod.list_positions() == []
    print("  PASSED test_reentry_cooldown")


def test_stop_loss_cooldown_is_longer():
    """A stop-loss exit blocks re-entry for stop_reentry_minutes, not 30."""
    _clean()
    now = int(time.time())
    items = [_item(1, "Dipped", 100, 96, 10000, limit=5000)]
    latest = _latest(now, **{"1": (100, 97)})
    vol_5m = {"1": {"avgLowPrice": 100}}
    cfg = _cfg(stop_grace_minutes=0)  # bypass grace: test cooldown timing
    from unittest import mock
    with mock.patch("rshelper.cli._fetch_bootstrap",
                    return_value=([], latest, vol_5m, items)):
        run_cycle(cfg)  # opens position 1
    # bid falls 2% below entry -> stop loss
    latest_sl = _latest(now, **{"1": (100, 94)})
    with mock.patch("rshelper.cli._fetch_bootstrap",
                    return_value=([], latest_sl, vol_5m, items)):
        result = run_cycle(cfg)
    assert len(result["closed"]) == 1
    assert result["closed"][0]["reason"] == "stop_loss"
    # Use select_candidates with an explicit clock: 40 min after the stop,
    # the normal 30m cooldown has expired but the 90m stop cooldown has not.
    t40 = now + 40 * 60
    latest_ok = _latest(t40, **{"1": (100, 97)})
    assert select_candidates(items, latest_ok, vol_5m, cfg, now=t40) == [], \
        "stop-loss cooldown must block re-entry at 40 min"
    # At 100 min both cooldowns have expired, so the item is eligible again.
    t100 = now + 100 * 60
    latest_ok2 = _latest(t100, **{"1": (100, 97)})
    assert [c.id for c in select_candidates(items, latest_ok2, vol_5m, cfg,
                                            now=t100)] == [1], \
        "item must become eligible after the stop cooldown expires"
    # For contrast, a take-profit exit is eligible again after 40 min.
    _clean()
    with mock.patch("rshelper.cli._fetch_bootstrap",
                    return_value=([], latest, vol_5m, items)):
        run_cycle(cfg)  # opens position 1
    latest_tp = _latest(now, **{"1": (103, 97)})
    with mock.patch("rshelper.cli._fetch_bootstrap",
                    return_value=([], latest_tp, vol_5m, items)):
        result_tp = run_cycle(cfg)
    assert result_tp["closed"][0]["reason"] == "take_profit"
    t40b = now + 40 * 60
    assert [c.id for c in select_candidates(items, _latest(t40b, **{"1": (100, 97)}),
                                            vol_5m, cfg, now=t40b)] == [1], \
        "take-profit cooldown (30m) must expire by 40 min"
    print("  PASSED test_stop_loss_cooldown_is_longer")


def test_stop_cooldown_survives_restart():
    """A daemon restart must not erase the stop-loss re-entry cooldown."""
    _clean()
    from unittest import mock
    now = int(time.time())
    items = [_item(1, "Dipped", 100, 96, 10000, limit=5000)]
    latest = _latest(now, **{"1": (100, 97)})
    vol_5m = {"1": {"avgLowPrice": 100}}
    cfg = _cfg(stop_grace_minutes=0)  # bypass grace: test restart persistence
    with mock.patch("rshelper.cli._fetch_bootstrap",
                    return_value=([], latest, vol_5m, items)):
        run_cycle(cfg)  # opens position 1
    latest_sl = _latest(now, **{"1": (100, 94)})
    with mock.patch("rshelper.cli._fetch_bootstrap",
                    return_value=([], latest_sl, vol_5m, items)):
        result = run_cycle(cfg)
    assert len(result["closed"]) == 1
    assert result["closed"][0]["reason"] == "stop_loss"
    assert tmod.EXITS_PATH.exists(), "exit cooldown must be persisted"
    tmod._RECENT_EXITS.clear()  # simulate a daemon restart
    with mock.patch("rshelper.cli._fetch_bootstrap",
                    return_value=([], latest, vol_5m, items)):
        result2 = run_cycle(cfg)
    assert result2["opened"] == [], result2  # still on the stop cooldown
    print("  PASSED test_stop_cooldown_survives_restart")


def test_trader_daemon_guards_and_pnl():
    import json
    import os
    from unittest import mock
    old_pid, old_state = tmod.PID_PATH, tmod.STATE_PATH
    with tempfile.TemporaryDirectory() as tmp:
        tmod.PID_PATH = Path(tmp) / "trader.pid"
        tmod.STATE_PATH = Path(tmp) / "trader_state.json"
        try:
            # a live pid blocks a second instance
            tmod.PID_PATH.write_text(str(os.getpid()))
            try:
                with mock.patch.object(tmod, "run_cycle", return_value={}):
                    tmod.run_trader(_cfg(), once=True)
                assert False, "expected SystemExit for a live second instance"
            except SystemExit:
                pass
            # a dead pid allows start; one cycle runs and P&L accumulates
            tmod.PID_PATH.write_text("99999999")
            with mock.patch.object(tmod, "run_cycle", return_value={
                    "candidates": 1, "opened": [], "closed": [],
                    "closed_pnl": 250}):
                result = tmod.run_trader(_cfg(), once=True)
            assert result["closed_pnl"] == 250
            state = json.loads(tmod.STATE_PATH.read_text())
            assert state["realized_pnl"] == 250
            assert state["cycles"] == 1
            assert state["running"] is False  # set false on clean exit
            assert not tmod.PID_PATH.exists()  # cleaned up on exit
        finally:
            tmod.PID_PATH, tmod.STATE_PATH = old_pid, old_state
    print("  PASSED test_trader_daemon_guards_and_pnl")


def test_max_hold_flat_close():
    _clean()
    from unittest import mock
    from rshelper.positions import open_position
    from datetime import timedelta
    open_position(1, "Dead item", 10, 97, note="auto", direction="traditional")
    pos = pmod._load()
    pos[0]["opened_at"] = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
    pmod._save(pos)
    with mock.patch("rshelper.cli._fetch_bootstrap",
                    return_value=([], {}, {}, [])):
        result = run_cycle(_cfg())
    assert len(result["closed"]) == 1
    assert result["closed"][0]["reason"] == "max_hold"
    trades = jmod.list_trades()
    assert len(trades) == 1
    assert trades[0].sell_price == 97  # flat close at the buy price
    assert trades[0].quote_sell is None  # no fresh quote on expiry
    assert trades[0].strategy == "auto"
    assert pmod.list_positions() == []
    print("  PASSED test_max_hold_flat_close")


def test_max_hold_stale_bid_close():
    """Max-hold marks to the last known bid; flat close only with no data."""
    _clean()
    from unittest import mock
    from rshelper.positions import open_position
    open_position(1, "Stale", 10, 97, note="auto", direction="traditional")
    pos = pmod._load()
    pos[0]["opened_at"] = (datetime.now(timezone.utc) -
                           timedelta(hours=5)).isoformat()
    pmod._save(pos)
    now = int(time.time())
    stale = {"1": {"high": 100, "low": 90,
                   "highTime": now - 3600, "lowTime": now - 3600}}
    with mock.patch("rshelper.cli._fetch_bootstrap",
                    return_value=([], stale, {}, [])):
        result = run_cycle(_cfg())
    assert len(result["closed"]) == 1
    assert result["closed"][0]["reason"] == "max_hold"
    assert result["closed"][0]["sell_price"] == 90  # marked to stale bid
    assert result["closed"][0]["quote_sell"] == 90
    trade = jmod.list_trades()[0]
    assert trade.sell_price == 90
    print("  PASSED test_max_hold_stale_bid_close")


def test_recent_exits_pruned():
    """Exits older than the longest cooldown are pruned on load and persist."""
    _clean()
    import json
    now = time.time()
    tmod._RECENT_EXITS.clear()
    tmod._RECENT_EXITS[1] = (now - 3 * 3600, "take_profit")  # stale
    tmod._RECENT_EXITS[2] = (now - 60, "stop_loss")          # fresh
    tmod._persist_recent_exits()
    data = json.loads(tmod.EXITS_PATH.read_text())
    assert set(data) == {"2"}, f"stale exits must be pruned, got {set(data)}"
    tmod._RECENT_EXITS.clear()
    tmod._load_recent_exits()
    assert set(tmod._RECENT_EXITS) == {2}
    # in-memory entries that expired while the daemon ran are pruned too
    tmod._RECENT_EXITS[3] = (now - 5 * 3600, "take_profit")
    tmod._load_recent_exits()
    assert set(tmod._RECENT_EXITS) == {2}, \
        f"expired in-memory exits must be pruned, got {set(tmod._RECENT_EXITS)}"
    print("  PASSED test_recent_exits_pruned")


def test_status_journal_pnl():
    """Status exposes all-time journal P&L, not just the per-run counter."""
    import json
    import os
    old_pid, old_state = tmod.PID_PATH, tmod.STATE_PATH
    old_trades = jmod.TRADES_PATH
    with tempfile.TemporaryDirectory() as tmp:
        tmod.PID_PATH = Path(tmp) / "trader.pid"
        tmod.STATE_PATH = Path(tmp) / "trader_state.json"
        jmod.TRADES_PATH = Path(tmp) / "trades.json"
        try:
            jmod.log_trade(1, "A", 10, 100, 105, strategy="auto",
                           exit_reason="take_profit")  # profit 30
            tmod._write_state({"running": True, "profile": "default",
                               "realized_pnl": 0, "cycles": 1, "errors": 0,
                               "last_cycle_iso": None, "started_iso": None,
                               "last_result": None, "exits_by_reason": {}})
            tmod.PID_PATH.write_text(str(os.getpid()))
            status = tmod.trader_status()
            assert status["journal_realized_pnl"] == 30, status
            assert status["journal_auto_trades"] == 1
            assert status["running"] is True
        finally:
            tmod.PID_PATH, tmod.STATE_PATH = old_pid, old_state
            jmod.TRADES_PATH = old_trades
    print("  PASSED test_status_journal_pnl")


def test_trader_config_validation():
    old_pid, old_state = tmod.PID_PATH, tmod.STATE_PATH
    with tempfile.TemporaryDirectory() as tmp:
        tmod.PID_PATH = Path(tmp) / "trader.pid"
        tmod.STATE_PATH = Path(tmp) / "trader_state.json"
        try:
            for kw in ({"stop_loss_pct": 0}, {"take_profit_pct": 0},
                       {"capital": 0}, {"max_positions": 0},
                       {"artifact_min_low_vol": -1},
                       {"artifact_low_vol_frac": 0},
                       {"artifact_low_vol_frac": 1.5},
                       {"artifact_outlier_pct": -1},
                       {"stop_slippage": 0}, {"stop_slippage": 1.5},
                       {"stop_mark_blend": -0.1}, {"stop_mark_blend": 1.1}):
                try:
                    tmod.run_trader(_cfg(**kw), once=True)
                    assert False, f"expected ValueError for {kw}"
                except ValueError:
                    pass
        finally:
            tmod.PID_PATH, tmod.STATE_PATH = old_pid, old_state
    print("  PASSED test_trader_config_validation")


def test_status_staleness():
    """Status snapshots expose age and a stale flag."""
    import json
    old_pid, old_state = tmod.PID_PATH, tmod.STATE_PATH
    with tempfile.TemporaryDirectory() as tmp:
        tmod.PID_PATH = Path(tmp) / "trader.pid"
        tmod.STATE_PATH = Path(tmp) / "trader_state.json"
        try:
            now = time.time()
            fresh = {"running": True, "last_cycle_iso":
                     datetime.fromtimestamp(now - 60, timezone.utc).isoformat()}
            stale = {"running": True, "last_cycle_iso":
                     datetime.fromtimestamp(now - 3600, timezone.utc).isoformat()}
            base_fresh = tmod._status_base(fresh)
            base_stale = tmod._status_base(stale)
            assert base_fresh["stale"] is False, base_fresh
            assert 55 <= base_fresh["last_cycle_age_sec"] <= 65
            assert base_stale["stale"] is True, base_stale
            assert base_stale["last_cycle_age_sec"] > 3500
            # no cycle timestamp -> age None, not stale
            base_none = tmod._status_base({"running": True})
            assert base_none["last_cycle_age_sec"] is None
            assert base_none["stale"] is False
        finally:
            tmod.PID_PATH, tmod.STATE_PATH = old_pid, old_state
    print("  PASSED test_status_staleness")


def test_sync_script_changed_detection():
    """Sync helper only stages files whose content changed."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "sync_state", Path(__file__).resolve().parent.parent /
        "scripts" / "sync-and-push-state.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src"
        dst = Path(tmp) / "dst"
        src.mkdir(); dst.mkdir()
        (src / "trades.json").write_text('{"trades": []}')
        (dst / "trades.json").write_text('{"trades": []}')
        assert mod._files_differ(src, dst, "trades.json") is False
        (src / "trades.json").write_text('{"trades": [1]}')
        assert mod._files_differ(src, dst, "trades.json") is True
        assert mod._files_differ(src, dst, "missing.json") is False
    print("  PASSED test_sync_script_changed_detection")


def test_sync_script_reports_commit_failure():
    """A failed state commit must surface as an error, not fake success."""
    import contextlib
    import importlib.util
    import io
    from unittest import mock
    spec = importlib.util.spec_from_file_location(
        "sync_state_commit_fail", Path(__file__).resolve().parent.parent /
        "scripts" / "sync-and-push-state.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.SRC = Path(_tmpdir.name) / "sync_src"
    mod.DEST = Path(_tmpdir.name) / "sync_dst"
    mod.SRC.mkdir(exist_ok=True)
    mod.DEST.mkdir(exist_ok=True)
    (mod.SRC / "trades.json").write_text('{"trades": [2]}')
    fake = mock.Mock(side_effect=[
        mock.Mock(returncode=0),  # git add
        mock.Mock(returncode=1, stderr="signing failed"),  # git commit
    ])
    with mock.patch.object(mod.subprocess, "run", fake), \
            contextlib.redirect_stderr(io.StringIO()) as err:
        rc = mod.main()
    assert rc == 1
    assert "commit failed: signing failed" in err.getvalue()
    assert fake.call_count == 2  # push must not run after a failed commit
    print("  PASSED test_sync_script_reports_commit_failure")


def test_sync_script_falls_back_unsigned_on_1password():
    """A 1Password signing failure must not block the state sync (fall back
    to an unsigned commit so the live site doesn't go stale)."""
    import contextlib
    import importlib.util
    import io
    from unittest import mock
    spec = importlib.util.spec_from_file_location(
        "sync_state_1p_fallback", Path(__file__).resolve().parent.parent /
        "scripts" / "sync-and-push-state.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.SRC = Path(_tmpdir.name) / "sync_src_1p"
    mod.DEST = Path(_tmpdir.name) / "sync_dst_1p"
    mod.SRC.mkdir(exist_ok=True)
    mod.DEST.mkdir(exist_ok=True)
    (mod.SRC / "trades.json").write_text('{"trades": [3]}')
    fake = mock.Mock(side_effect=[
        mock.Mock(returncode=0),  # git add
        mock.Mock(returncode=1, stderr="1Password: failed to fill whole buffer"),
        mock.Mock(returncode=0),  # git commit --no-gpg-sign
        mock.Mock(returncode=0),  # git push
    ])
    with mock.patch.object(mod.subprocess, "run", fake), \
            contextlib.redirect_stderr(io.StringIO()) as err:
        rc = mod.main()
    assert rc == 0, f"sync should succeed via unsigned fallback, rc={rc}"
    assert "retrying unsigned" in err.getvalue()
    assert "1Password" in err.getvalue()
    # git add + signed commit + unsigned commit + push
    assert fake.call_count == 4
    # the unsigned commit must pass --no-gpg-sign
    commit_calls = [c for c in fake.call_args_list if "commit" in c.args[0]]
    assert any("--no-gpg-sign" in c.args[0] for c in commit_calls)
    print("  PASSED test_sync_script_falls_back_unsigned_on_1password")


def test_sync_script_ignores_snapshot_subdirs():
    """A subdirectory inside snapshots must not abort the state sync."""
    import importlib.util
    from unittest import mock
    spec = importlib.util.spec_from_file_location(
        "sync_state_subdir", Path(__file__).resolve().parent.parent /
        "scripts" / "sync-and-push-state.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src"
        dst = Path(tmp) / "dst"
        (src / "snapshots" / "subdir").mkdir(parents=True)
        (src / "snapshots" / "flip-2026-08-01.json").write_text("{}")
        mod.SRC, mod.DEST = src, dst

        def fake_git(*args, **kw):
            import subprocess
            return subprocess.CompletedProcess(args, 0, "", "")

        with mock.patch.object(mod.subprocess, "run", side_effect=fake_git):
            rc = mod.main()
        assert rc == 0, f"sync must not crash on a snapshot subdir, rc={rc}"
        assert (dst / "snapshots" / "flip-2026-08-01.json").exists()
    print("  PASSED test_sync_script_ignores_snapshot_subdirs")


if __name__ == "__main__":
    test_select_candidates_filters()
    test_exit_reason()
    test_size_position_caps()
    test_run_cycle_opens_and_closes()
    test_spread_does_not_insta_stop_and_stop_records_slippage()
    test_stop_loss_legacy_position_uses_buy_mark()
    test_reentry_cooldown()
    test_stop_loss_cooldown_is_longer()
    test_stop_cooldown_survives_restart()
    test_trader_daemon_guards_and_pnl()
    test_max_hold_flat_close()
    test_trader_config_validation()
    test_status_staleness()
    test_sync_script_changed_detection()
    test_sync_script_reports_commit_failure()
    test_sync_script_falls_back_unsigned_on_1password()
    test_sync_script_ignores_snapshot_subdirs()
    test_candidate_edge_ranking()
    test_spread_collapse_exit()
    test_run_cycle_spread_collapse_closes_at_bid()
    test_max_hold_stale_bid_close()
    test_recent_exits_pruned()
    test_status_journal_pnl()
    test_thin_dip_skipped_volume_backed_accepted()
    test_stop_on_thin_print_fills_at_window_avg()
    test_stop_on_real_crash_keeps_print_fill()
    test_stop_normal_decline_not_guarded()
    test_stop_mark_blend_gives_dip_allowance()
    test_stop_mark_blend_zero_is_legacy()
    test_stop_slippage_configurable()
    test_candidate_confidence_tiebreaker()
    test_auto_ge_fill_closes_at_offer()
    test_manual_position_not_auto_closed_by_ge_fill()
    test_ge_fill_skips_when_offer_collapsed()
    test_ge_fill_requires_net_profit_after_tax()
    test_no_auto_open_on_item_with_manual_position()
    test_spread_collapse_unfilled_sells_at_bid()
    test_time_exit_sells_at_offer_when_net_positive()
    test_stop_grace_period_blocks_early_stop()
    print("\nAll tests passed.")
