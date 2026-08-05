"""Tests for the materials-processing scanner and recipe table."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from rshelper.models import Item
from rshelper.recipes import RECIPES, Recipe
from rshelper.scanner import ProcessScanner
from rshelper.market import ge_tax


def _item(iid, name, buy, sell, limit=10000, volume=1000, members=False):
    return Item(id=iid, name=name, members=members, buy_limit=limit,
                alch_value=0, buy_price=buy, sell_price=sell, volume=volume)


def test_recipe_table_integrity():
    """Output ids are unique; inputs are non-empty with positive qty."""
    outputs = [r.output_id for r in RECIPES.values()]
    assert len(outputs) == len(set(outputs)), "output ids must be unique"
    assert len(RECIPES) >= 80, "expected a broad multi-skill recipe set"
    for r in RECIPES.values():
        assert isinstance(r, Recipe)
        assert r.inputs, "every recipe needs inputs"
        assert all(qty > 0 for qty in r.inputs.values())
        assert r.rate_per_hour > 0
        assert r.skill in ("smithing", "fletching", "crafting", "cooking",
                           "herblore", "construction", "runecrafting", "magic")
    # Every skill is represented
    from collections import Counter
    skills = Counter(r.skill for r in RECIPES.values())
    for skill in ("smithing", "fletching", "crafting", "cooking",
                  "herblore", "construction", "runecrafting", "magic"):
        assert skills[skill] >= 4, f"{skill} needs >= 4 recipes, got {skills[skill]}"
    # The classic chains are present
    assert 2353 in RECIPES  # steel bar
    assert 892 in RECIPES   # rune arrow (fletch)
    assert 573 in RECIPES   # air orb (blow)
    assert 1777 in RECIPES  # bowstring (spin)
    assert 385 in RECIPES   # shark (cooking)
    assert 139 in RECIPES   # prayer potion(3) (herblore)
    assert 8782 in RECIPES  # mahogany plank (construction)
    assert 560 in RECIPES   # death rune (runecrafting)
    print("  PASSED test_recipe_table_integrity")


def test_scan_skill_filter():
    """skill= filters to one skill; empty returns all."""
    scanner = ProcessScanner(recipes={
        2353: RECIPES[2353],  # smithing: steel bar
        385: RECIPES[385],    # cooking: shark
        8782: RECIPES[8782],  # construction: mahogany plank
    })
    items = [
        _item(2353, "Steel bar", 400, 576),
        _item(440, "Iron ore", 100, 90),
        _item(453, "Coal", 130, 120),
        _item(385, "Shark", 800, 1029),
        _item(383, "Raw shark", 700, 690),
        _item(8782, "Mahogany plank", 200, 1883),
        _item(6332, "Mahogany logs", 150, 140),
    ]
    all_r = scanner.scan(items)
    assert len(all_r) == 3, f"expected all 3 recipes, got {len(all_r)}"
    cook_r = scanner.scan(items, skill="cooking")
    assert [r.name for r in cook_r] == ["Shark"]
    smith_r = scanner.scan(items, skill="smithing")
    assert [r.name for r in smith_r] == ["Steel bar"]
    constr_r = scanner.scan(items, skill="construction")
    assert [r.name for r in constr_r] == ["Mahogany plank"]
    none_r = scanner.scan(items, skill="herblore")
    assert none_r == []
    print("  PASSED test_scan_skill_filter")


def test_fletch_recipe_batch_ratio():
    """Fletching arrows: 15 shafts + 15 feathers + 15 arrowtips -> 15 arrows."""
    scanner = ProcessScanner(recipes={892: RECIPES[892]})  # rune arrow
    items = [
        _item(892, "Rune arrow", 190, 200, limit=10000),
        _item(52, "Arrow shaft", 5, 4, limit=10000),
        _item(314, "Feather", 2, 1, limit=10000),
        _item(44, "Rune arrowtips", 100, 95, limit=10000),
    ]
    results = scanner.scan(items)
    assert len(results) == 1
    r = results[0]
    # input_cost per arrow = (15*5 + 15*2 + 15*100)/15 = 107
    assert r.input_cost == 107
    assert r.name == "Rune arrow"
    # profit per arrow = (200 - ge_tax(200)) - 107 = 196 - 107 = 89
    assert r.profit == 89
    print("  PASSED test_fletch_recipe_batch_ratio")


def test_process_scan_profit_steel_bar():
    """Steel bar: 1 iron ore (440) + 2 coal (453) -> 1 steel bar (2353).
    profit = (sell - tax) - input_cost."""
    scanner = ProcessScanner(recipes={2353: RECIPES[2353]})
    items = [
        _item(2353, "Steel bar", 400, 576),     # sell 576, tax 11
        _item(440, "Iron ore", 100, 90),
        _item(453, "Coal", 130, 120),
    ]
    results = scanner.scan(items)
    assert len(results) == 1
    r = results[0]
    assert r.name == "Steel bar"
    assert r.input_cost == 100 + 2 * 130  # 360
    assert r.profit == (576 - ge_tax(576)) - 360
    print("  PASSED test_process_scan_profit_steel_bar")


def test_process_scan_throughput_capped_by_input():
    """The limiting input's buy-limit capacity caps outputs/hour."""
    scanner = ProcessScanner(recipes={2353: RECIPES[2353]})
    items = [
        _item(2353, "Steel bar", 400, 576, limit=10000),
        _item(440, "Iron ore", 100, 90, limit=10000),
        _item(453, "Coal", 130, 120, limit=100),  # coal is scarce: 100/4=25/hr, /2 = 12.5
    ]
    results = scanner.scan(items)
    r = results[0]
    # output_rate = 10000/4 = 2500; volume_rate = 1000*12 = 12000;
    # input_capacity = min(2500, (100/4)//2 = 12) = 12; rate 1200
    # -> outputs_per_hour = 12
    assert r.gp_per_hour == r.profit * 12, \
        f"expected coal-limited 12/hr, got {r.gp_per_hour // r.profit}"
    print("  PASSED test_process_scan_throughput_capped_by_input")


def test_process_scan_skips_unprofitable():
    """A recipe whose output sells below input cost is skipped."""
    scanner = ProcessScanner(recipes={2353: RECIPES[2353]})
    items = [
        _item(2353, "Steel bar", 400, 300),  # sells below cost
        _item(440, "Iron ore", 100, 90),
        _item(453, "Coal", 130, 120),
    ]
    assert scanner.scan(items) == []
    print("  PASSED test_process_scan_skips_unprofitable")


def test_process_scan_skips_missing_component():
    """A recipe with a missing input item is skipped."""
    scanner = ProcessScanner(recipes={2353: RECIPES[2353]})
    items = [
        _item(2353, "Steel bar", 400, 576),
        _item(440, "Iron ore", 100, 90),
        # coal (453) missing
    ]
    assert scanner.scan(items) == []
    print("  PASSED test_process_scan_skips_missing_component")


def test_process_scan_members_filter():
    """members_only skips recipes with any member component."""
    scanner = ProcessScanner(recipes={1741: RECIPES[1741]})  # cowhide -> leather
    items = [
        _item(1741, "Leather", 150, 185, members=False),
        _item(1739, "Cowhide", 120, 110, members=True),
    ]
    assert scanner.scan(items, members_only=True) == []
    assert len(scanner.scan(items, members_only=False)) == 1
    print("  PASSED test_process_scan_members_filter")


def test_process_scan_capital_cap():
    """--capital caps throughput by how many units the budget buys."""
    scanner = ProcessScanner(recipes={2353: RECIPES[2353]})
    items = [
        _item(2353, "Steel bar", 400, 576, limit=10000),
        _item(440, "Iron ore", 100, 90),
        _item(453, "Coal", 130, 120),
    ]
    results = scanner.scan(items, capital=3600)  # 10 units of 360 input cost
    r = results[0]
    assert r.gp_per_hour == r.profit * 10, f"capital cap 10/hr, got {r.gp_per_hour // r.profit}"
    print("  PASSED test_process_scan_capital_cap")


def test_process_scan_sorted_by_gp_per_hour():
    """Results sort by gp_per_hour descending."""
    scanner = ProcessScanner(recipes={
        2353: RECIPES[2353],       # steel: profit ~205
        2351: RECIPES[2351],       # iron bar: 1 iron ore
    })
    items = [
        _item(2353, "Steel bar", 400, 576, limit=10000),
        _item(440, "Iron ore", 100, 90, limit=10000),
        _item(453, "Coal", 130, 120, limit=10000),
        _item(2351, "Iron bar", 200, 126, limit=10000),
    ]
    results = scanner.scan(items)
    assert len(results) == 2
    gps = [r.gp_per_hour for r in results]
    assert gps == sorted(gps, reverse=True)
    print("  PASSED test_process_scan_sorted_by_gp_per_hour")


def test_process_scan_does_not_mutate_input():
    """The scanner builds new Items; input Items are untouched."""
    scanner = ProcessScanner(recipes={2353: RECIPES[2353]})
    items = [
        _item(2353, "Steel bar", 400, 576),
        _item(440, "Iron ore", 100, 90),
        _item(453, "Coal", 130, 120),
    ]
    before = [(i.id, i.profit, i.gp_per_hour, i.input_cost) for i in items]
    scanner.scan(items)
    after = [(i.id, i.profit, i.gp_per_hour, i.input_cost) for i in items]
    assert before == after
    print("  PASSED test_process_scan_does_not_mutate_input")


if __name__ == "__main__":
    test_recipe_table_integrity()
    test_scan_skill_filter()
    test_fletch_recipe_batch_ratio()
    test_process_scan_profit_steel_bar()
    test_process_scan_throughput_capped_by_input()
    test_process_scan_skips_unprofitable()
    test_process_scan_skips_missing_component()
    test_process_scan_members_filter()
    test_process_scan_capital_cap()
    test_process_scan_sorted_by_gp_per_hour()
    test_process_scan_does_not_mutate_input()
    print("\nAll recipe tests passed.")
