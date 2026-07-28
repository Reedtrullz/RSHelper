"""One focused test for the alch scanner."""

import sys
from pathlib import Path

# Ensure src/ is on the path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from rshelper.models import Item
from rshelper.scanner import AlchScanner


def test_alch_scanner_basic():
    items = [
        Item(id=1, name="Test item", members=False, buy_limit=100,
             alch_value=1000, buy_price=800, sell_price=750, volume=500),
        Item(id=2, name="Loss item", members=False, buy_limit=50,
             alch_value=100, buy_price=200, sell_price=190, volume=10),
    ]
    scanner = AlchScanner(nature_rune_cost=147)
    results = scanner.scan(items)
    assert len(results) == 1, f"Expected 1 profitable item, got {len(results)}"
    assert results[0].profit == 53, f"Expected profit 53, got {results[0].profit}"
    assert results[0].gp_per_hour > 0
    print("  PASSED")


if __name__ == "__main__":
    test_alch_scanner_basic()
    print("All tests passed.")
