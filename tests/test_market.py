"""Tests for shared market-data rules (tax + price sanity)."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from rshelper.market import ge_tax, price_issue


def test_ge_tax_no_minimum():
    """Tax is 2% rounded down; items below 50 gp pay no tax (wiki rule)."""
    assert ge_tax(0) == 0
    assert ge_tax(1) == 0
    assert ge_tax(49) == 0
    assert ge_tax(50) == 1
    assert ge_tax(100) == 2
    assert ge_tax(999) == 19
    print("  PASSED test_ge_tax_no_minimum")


def test_ge_tax_cap():
    assert ge_tax(5_000_000) == 100_000
    assert ge_tax(250_000_000) == 5_000_000
    print("  PASSED test_ge_tax_cap")


def test_price_issue_healthy():
    now = int(time.time())
    price = {"high": 100, "low": 95, "highTime": now - 60, "lowTime": now - 30}
    assert price_issue(price, now=now) is None
    print("  PASSED test_price_issue_healthy")


def test_price_issue_reasons():
    now = int(time.time())
    assert price_issue({"high": 0, "low": 95, "highTime": now, "lowTime": now},
                       now=now) == "no data"
    assert price_issue({"high": 100, "low": 95}, now=now) == "stale"
    assert price_issue({"high": 100, "low": 95,
                        "highTime": now - 3 * 86400, "lowTime": now}, now=now) == "stale"
    depth = {"high": 100, "low": 95000, "highTime": now - 60, "lowTime": now - 30,
             "high_volume": 50, "low_volume": 0}
    assert price_issue(depth, now=now) == "depth"
    ratio = {"high": 1, "low": 170000, "highTime": now - 60, "lowTime": now - 30}
    assert price_issue(ratio, now=now) == "ratio"
    print("  PASSED test_price_issue_reasons")


if __name__ == "__main__":
    test_ge_tax_no_minimum()
    test_ge_tax_cap()
    test_price_issue_healthy()
    test_price_issue_reasons()
    print("\nAll tests passed.")
