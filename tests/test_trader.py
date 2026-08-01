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

from rshelper.trader import (
    exit_reason,
    select_candidates,
    size_position,
    run_cycle,
)


def _clean():
    tmod._RECENT_EXITS.clear()
    for path in (jmod.TRADES_PATH, pmod.POSITIONS_PATH):
        if path.exists():
            path.unlink()


def _cfg(**kw):
    defaults = dict(capital=1_000_000, trade_capital_frac=0.25, max_positions=3,
                    min_volume=800, max_spread_ratio=5.0, dip_depth_pct=2.0,
                    max_dip_pct=10.0, min_spread_pct=3.0,
                    max_entry_spread_pct=5.0,
                    reentry_minutes=30,
                    take_profit_pct=2.0, stop_loss_pct=-2.0,
                    max_hold_minutes=180, interval_sec=300)
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
        _item(1, "Dipped", 100, 97, 1000),     # 3% spread, 3% below avg
        _item(2, "Thin", 100, 97, 50),         # too little volume
        _item(3, "WideSpread", 106, 97, 1000), # 9.3% spread: spread cap
        _item(9, "NoDip", 103, 99, 1000),      # 4% spread, 1% dip: dip guard
        _item(4, "Stale", 100, 97, 1000),      # old timestamp
        _item(5, "NoBaseline", 100, 97, 1000), # no avgLowPrice
        _item(6, "WideGap", 106, 90, 1000),    # 17.8% high/low gap
        _item(7, "Freefall", 100, 80, 1000),   # 20% below average
        _item(8, "ThinSpread", 101, 100, 1000),  # 1% spread < min spread
    ]
    latest = _latest(now, **{"1": (100, 97), "2": (100, 97), "3": (106, 97),
                             "9": (103, 99), "5": (100, 97)})
    latest["4"] = {"high": 100, "low": 97, "highTime": now - 400, "lowTime": now - 400}
    vol_5m = {"1": {"avgLowPrice": 100}, "2": {"avgLowPrice": 100},
              "3": {"avgLowPrice": 100}, "4": {"avgLowPrice": 100},
              "9": {"avgLowPrice": 100}, "6": {"avgLowPrice": 100},
              "7": {"avgLowPrice": 100}, "8": {"avgLowPrice": 100}}
    cfg = _cfg()
    candidates = select_candidates(items, latest, vol_5m, cfg, now=now)
    assert [c.id for c in candidates] == [1], \
        f"expected only item 1, got {[c.id for c in candidates]}"
    print("  PASSED test_select_candidates_filters")


def test_exit_reason():
    now = time.time()
    cfg = _cfg()
    from rshelper.positions import Position
    p = Position(id=1, item_id=1, name="X", qty=10, buy_price=97,
                 direction="traditional",
                 opened_at=(datetime.now(timezone.utc)).isoformat())
    # take profit: offer 102 -> (102-97-2)/97 = +3.1% >= +2%
    assert exit_reason(p, _latest(now, **{"1": (102, 97)}), cfg, now=now) == "take_profit"
    # hold: offer 100 -> (100-97-2)/97 = +1.0% < +2%; bid == entry bid
    assert exit_reason(p, _latest(now, **{"1": (100, 97)}), cfg, now=now) is None
    # stop loss: bid 94 -> -3.1% from entry bid 97
    assert exit_reason(p, _latest(now, **{"1": (100, 94)}), cfg, now=now) == "stop_loss"
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
    items = [_item(1, "Dipped", 100, 97, 10000, limit=5000)]
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
    assert positions[0].buy_price == 97  # entered at the bid
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
        result = run_cycle(_cfg())
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


def test_reentry_cooldown():
    _clean()
    from unittest import mock
    now = int(time.time())
    items = [_item(1, "Dipped", 100, 97, 10000, limit=5000)]
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


def test_trader_config_validation():
    old_pid, old_state = tmod.PID_PATH, tmod.STATE_PATH
    with tempfile.TemporaryDirectory() as tmp:
        tmod.PID_PATH = Path(tmp) / "trader.pid"
        tmod.STATE_PATH = Path(tmp) / "trader_state.json"
        try:
            for kw in ({"stop_loss_pct": 0}, {"take_profit_pct": 0},
                       {"capital": 0}, {"max_positions": 0}):
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


if __name__ == "__main__":
    test_select_candidates_filters()
    test_exit_reason()
    test_size_position_caps()
    test_run_cycle_opens_and_closes()
    test_spread_does_not_insta_stop_and_stop_records_slippage()
    test_stop_loss_legacy_position_uses_buy_mark()
    test_reentry_cooldown()
    test_trader_daemon_guards_and_pnl()
    test_max_hold_flat_close()
    test_trader_config_validation()
    test_status_staleness()
    test_sync_script_changed_detection()
    print("\nAll tests passed.")
