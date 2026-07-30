"""Tests for trade journal."""
import sys, os, json, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import rshelper.journal as jmod
# Isolate tests: use temp directory instead of production trades.json
_tmpdir = tempfile.TemporaryDirectory()
_test_dir = Path(_tmpdir.name)
jmod.TRADES_PATH = _test_dir / "trades.json"

from rshelper.journal import (log_trade, delete_trade, list_trades, compute_pnl,
                               Trade, PnLSummary, TRADES_PATH)

def _clean():
    if TRADES_PATH.exists():
        TRADES_PATH.unlink()
    TRADES_PATH.parent.mkdir(parents=True, exist_ok=True)

def test_log_trade():
    _clean()
    t = log_trade(1, "Nature rune", 1000, 100, 110, "test flip")
    assert t.id == 1
    assert t.name == "Nature rune"
    assert t.qty == 1000
    assert t.buy_price == 100
    assert t.sell_price == 110
    tax_per = min(5_000_000, max(1, int(110 * 0.02)))
    assert t.tax_paid == tax_per * 1000
    assert t.profit == (110 - 100) * 1000 - t.tax_paid
    assert t.note == "test flip"
    print("  PASSED test_log_trade")

def test_log_trade_auto_increment():
    _clean()
    # IDs are auto-generated, not passed in
    t1 = log_trade(10, "A", 1, 100, 200)
    t2 = log_trade(20, "B", 1, 100, 200)
    t3 = log_trade(30, "C", 1, 100, 200)
    assert t1.id == 1
    assert t2.id == 2
    assert t3.id == 3
    # Delete t2, next ID should still be 4 (monotonic, no reuse)
    delete_trade(2)
    t4 = log_trade(40, "D", 1, 100, 200)
    assert t4.id == 4
    print("  PASSED test_log_trade_auto_increment")

def test_log_trade_zero_profit():
    _clean()
    t = log_trade(1, "X", 1, 100, 100)
    assert t.profit < 0  # tax makes it negative
    assert t.tax_paid > 0
    print("  PASSED test_log_trade_zero_profit")

def test_log_trade_tax_cap():
    """Tax capped at 5M per item."""
    _clean()
    t = log_trade(1, "Expensive", 3, 100_000_000, 500_000_000)
    # Per-item tax: min(5M, 500M * 0.02) = min(5M, 10M) = 5M
    # Total: 5M * 3 = 15M
    assert t.tax_paid == 15_000_000
    print("  PASSED test_log_trade_tax_cap")

def test_delete_trade_exists():
    _clean()
    log_trade(1, "A", 1, 100, 200)
    assert delete_trade(1) is True
    assert len(list_trades()) == 0
    print("  PASSED test_delete_trade_exists")

def test_delete_trade_nonexistent():
    _clean()
    assert delete_trade(999) is False
    print("  PASSED test_delete_trade_nonexistent")

def test_list_trades_empty():
    _clean()
    assert len(list_trades()) == 0
    print("  PASSED test_list_trades_empty")

def test_list_trades_filtered_by_item():
    _clean()
    log_trade(1, "Nature rune", 1, 100, 200)
    log_trade(2, "Death rune", 1, 100, 200)
    log_trade(3, "Nature rune", 1, 100, 200)
    result = list_trades(item_name="Nature")
    assert len(result) == 2
    result2 = list_trades(item_name="Death")
    assert len(result2) == 1
    print("  PASSED test_list_trades_filtered_by_item")

def test_list_trades_filtered_by_date():
    _clean()
    log_trade(1, "A", 1, 100, 200)
    import time; time.sleep(0.01)
    log_trade(2, "B", 1, 100, 200)
    all_trades = list_trades()
    assert len(all_trades) == 2
    # Since yesterday should return both
    from datetime import date, timedelta
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    assert len(list_trades(since=yesterday)) == 2
    print("  PASSED test_list_trades_filtered_by_date")

def test_atomic_save_no_corruption():
    _clean()
    log_trade(1, "A", 1, 100, 200)
    assert TRADES_PATH.exists()
    data = json.loads(TRADES_PATH.read_text())
    assert "trades" in data
    assert len(data["trades"]) == 1
    # No .tmp file should remain
    assert not TRADES_PATH.with_suffix(".tmp").exists()
    print("  PASSED test_atomic_save_no_corruption")

def test_pnl_mixed_wins_losses():
    _clean()
    log_trade(1, "Winner", 1, 100, 200)   # profit
    log_trade(2, "Loser", 1, 200, 100)    # loss
    pnl = compute_pnl()
    assert pnl.trade_count == 2
    assert pnl.winning_trades + pnl.losing_trades == 2
    assert pnl.win_rate > 0 and pnl.win_rate < 100
    print("  PASSED test_pnl_mixed_wins_losses")

def test_pnl_empty_ledger():
    _clean()
    pnl = compute_pnl()
    assert pnl.trade_count == 0
    assert pnl.total_profit == 0
    assert pnl.best_trade is None
    print("  PASSED test_pnl_empty_ledger")

def test_pnl_gp_per_hour():
    _clean()
    log_trade(1, "A", 1, 100, 1000)
    log_trade(2, "B", 1, 100, 1000)
    # Simulate trades spanning 2 hours by patching timestamps
    trades_data = json.loads(TRADES_PATH.read_text())
    from datetime import datetime, timezone, timedelta
    t1 = datetime.now(timezone.utc) - timedelta(hours=2)
    t2 = datetime.now(timezone.utc)
    trades_data["trades"][0]["timestamp"] = t1.isoformat()
    trades_data["trades"][1]["timestamp"] = t2.isoformat()
    TRADES_PATH.write_text(json.dumps(trades_data))
    pnl = compute_pnl()
    assert pnl.active_gp_per_hour > 0
    print("  PASSED test_pnl_gp_per_hour")

def test_cli_trade_log_parse():
    import subprocess
    _clean()
    result = subprocess.run(
        [sys.executable, "-m", "rshelper", "trade", "log", "Nature rune", "100", "150", "200"],
        capture_output=True, text=True,
        cwd=os.path.join(os.path.dirname(__file__), ".."),
        env={**os.environ, "PYTHONPATH": "src"},
    )
    assert result.returncode == 0, result.stderr
    assert "Logged trade" in result.stdout
    print("  PASSED test_cli_trade_log_parse")

if __name__ == "__main__":
    test_log_trade()
    test_log_trade_auto_increment()
    test_log_trade_zero_profit()
    test_log_trade_tax_cap()
    test_delete_trade_exists()
    test_delete_trade_nonexistent()
    test_list_trades_empty()
    test_list_trades_filtered_by_item()
    test_list_trades_filtered_by_date()
    test_atomic_save_no_corruption()
    test_pnl_mixed_wins_losses()
    test_pnl_empty_ledger()
    test_pnl_gp_per_hour()
    test_cli_trade_log_parse()
    print("\nAll journal tests passed.")
