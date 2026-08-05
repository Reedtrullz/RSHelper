"""Static processing recipes: output item -> inputs + process metadata.

The scanner buys the inputs at their instant-buy price, processes them,
and sells the output at its instant-sell price (GE tax on the sell leg
only). Item IDs are verified against the OSRS wiki mapping.

Recipe economics:
  input_cost = sum(input.buy_price * qty for each input)
  output_gp  = output.sell_price - ge_tax(output.sell_price)
  profit     = output_gp - input_cost - cost_per_unit
  gp_per_hour = profit * min(rate_per_hour, output.buy_limit/4,
                             output.volume*12, input_capacity)
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Recipe:
    output_id: int
    inputs: dict[int, int]   # {input_item_id: qty_per_run}
    process: str             # "smelt" | "craft" | "fletch" | "blow" | "spin"
    rate_per_hour: int       # action-rate cap (smelting ~1200/hr)
    cost_per_unit: int = 0   # non-GE process cost, default 0
    outputs_per_run: int = 1  # units produced per recipe run (batch: 15 arrows)


# Verified against the wiki mapping (ids 440=Iron ore, 453=Coal, etc.).
# Ores -> bars (smithing). Steel bar is the classic 1 iron + 2 coal chain.
RECIPES: dict[int, Recipe] = {
    # Bronze bar: 1 tin ore + 1 copper ore
    2349: Recipe(2349, {438: 1, 436: 1}, "smelt", 1200),
    # Iron bar: 1 iron ore
    2351: Recipe(2351, {440: 1}, "smelt", 1200),
    # Steel bar: 1 iron ore + 2 coal
    2353: Recipe(2353, {440: 1, 453: 2}, "smelt", 1200),
    # Silver bar: 1 silver ore
    2355: Recipe(2355, {442: 1}, "smelt", 1200),
    # Gold bar: 1 gold ore
    2357: Recipe(2357, {444: 1}, "smelt", 1200),
    # Mithril bar: 1 mithril ore + 4 coal
    2359: Recipe(2359, {447: 1, 453: 4}, "smelt", 1200),
    # Adamantite bar: 1 adamantite ore + 6 coal
    2361: Recipe(2361, {449: 1, 453: 6}, "smelt", 1200),
    # Runite bar: 1 runite ore + 8 coal
    2363: Recipe(2363, {451: 1, 453: 8}, "smelt", 1200),
    # Leather: 1 cowhide -> 1 leather (craft)
    1741: Recipe(1741, {1739: 1}, "craft", 1800),
    # Plain pizza: 1 pizza base + 1 tomato + 1 cheese (craft)
    2289: Recipe(2289, {2283: 1, 1982: 1, 1985: 1}, "craft", 1200),
    # Fletching arrows: 15 arrow shafts + 15 arrowtips -> 15 arrows (fletch)
    882: Recipe(882, {52: 15, 39: 15}, "fletch", 2000, outputs_per_run=15),  # bronze arrow
    884: Recipe(884, {52: 15, 40: 15}, "fletch", 2000, outputs_per_run=15),  # iron arrow
    886: Recipe(886, {52: 15, 41: 15}, "fletch", 2000, outputs_per_run=15),  # steel arrow
    888: Recipe(888, {52: 15, 42: 15}, "fletch", 2000, outputs_per_run=15),  # mithril arrow
    890: Recipe(890, {52: 15, 43: 15}, "fletch", 2000, outputs_per_run=15),  # adamant arrow
    892: Recipe(892, {52: 15, 44: 15}, "fletch", 2000, outputs_per_run=15),  # rune arrow
    # Glassblowing: 1 molten glass -> 1 orb (blow)
    573: Recipe(573, {1775: 1}, "blow", 1800),              # air orb
    571: Recipe(571, {1775: 1}, "blow", 1800),              # water orb
    575: Recipe(575, {1775: 1}, "blow", 1800),              # earth orb
    569: Recipe(569, {1775: 1}, "blow", 1800),              # fire orb
    # Spinning: 1 flax -> 1 bowstring (spin)
    1777: Recipe(1777, {1779: 1}, "spin", 1800),
    # Crafting jewelry: 1 gold bar + 1 gem -> 1 ring (craft)
    1637: Recipe(1637, {2357: 1, 1607: 1}, "craft", 1200),  # sapphire ring
    1639: Recipe(1639, {2357: 1, 1605: 1}, "craft", 1200),  # emerald ring
    1641: Recipe(1641, {2357: 1, 1603: 1}, "craft", 1200),  # ruby ring
    1643: Recipe(1643, {2357: 1, 1601: 1}, "craft", 1200),  # diamond ring
}
