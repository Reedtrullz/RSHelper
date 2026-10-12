import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from rshelper.chain_planner import plan_chains
from rshelper.models import Item
from rshelper.recipes import Recipe, RECIPES


def item(i, name, buy, sell):
    return Item(id=i, name=name, members=False, buy_limit=10000, alch_value=0,
                buy_price=buy, sell_price=sell, volume=1000)


class ChainPlannerTest(unittest.TestCase):
    def test_owned_inputs_fund_chain_step(self):
        prices = {
            1761: item(1761, "Soft clay", 2, 1),
            1787: item(1787, "Unfired pot", 3, 2),
            1931: item(1931, "Pot", 6, 5),
        }
        plans = plan_chains(RECIPES, prices, "{}")
        chain = [p for p in plans if p.get("steps") == [1787, 1931]]
        self.assertEqual(len(chain), 1)
        self.assertEqual(chain[0]["owned_input_value"], 3)
        self.assertEqual(chain[0]["shortfalls"], {})

    def test_cycles_are_rejected(self):
        recipes = {
            2: Recipe(2, {1: 1}, "smithing", 10),
            1: Recipe(1, {2: 1}, "smithing", 10),
        }
        prices = {1: item(1, "A", 2, 3), 2: item(2, "B", 2, 3)}
        results = plan_chains(recipes, prices, "{}")
        cycles = [r for r in results if r.get("rejected") == "cycle detected"]
        self.assertEqual(len(cycles), 2)

    def test_missing_quotes_are_rejected_with_reason(self):
        recipes = {2: Recipe(2, {1: 1}, "smithing", 10)}
        prices = {2: item(2, "B", 2, 3)}
        results = plan_chains(recipes, prices, "{}")
        self.assertEqual(results[0].get("rejected"), "quote unavailable or unusable")

    def test_invalid_inventory_is_rejected(self):
        with self.assertRaises(ValueError):
            plan_chains(RECIPES, {}, "not-json")


if __name__ == "__main__":
    unittest.main()
