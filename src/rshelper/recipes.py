"""Static processing recipes: output item -> inputs + process metadata.

The scanner buys the inputs at their instant-buy price, processes them,
and sells the output at its instant-sell price (GE tax on the sell leg
only). Item IDs are verified against the OSRS wiki mapping.

Recipe economics:
  input_cost = sum(input.buy_price * qty for each input)
  output_gp  = output.sell_price - ge_tax(output.sell_price)
  profit     = output_gp / outputs_per_run - input_cost/outputs_per_run - cost_per_unit
  gp_per_hour = profit * min(rate_per_hour, output.buy_limit/4,
                             output.volume*12, input_capacity)
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Recipe:
    output_id: int
    inputs: dict[int, int]   # {input_item_id: qty_per_run}
    skill: str               # "smithing" | "fletching" | "crafting" | "cooking"
                             # | "herblore" | "construction" | "runecrafting"
    rate_per_hour: int       # action-rate cap (smelting ~1200/hr)
    cost_per_unit: int = 0   # non-GE process cost, default 0
    outputs_per_run: int = 1  # units produced per recipe run (batch: 15 arrows)


# ---------------------------------------------------------------------------
# SMITHING — ores -> bars (1 run = 1 bar)
# ---------------------------------------------------------------------------
_SMELT = 1200
SMITHING: dict[int, Recipe] = {
    2349: Recipe(2349, {438: 1, 436: 1}, "smithing", _SMELT),          # bronze bar
    2351: Recipe(2351, {440: 1}, "smithing", _SMELT),                  # iron bar
    2353: Recipe(2353, {440: 1, 453: 2}, "smithing", _SMELT),          # steel bar
    2355: Recipe(2355, {442: 1}, "smithing", _SMELT),                  # silver bar
    2357: Recipe(2357, {444: 1}, "smithing", _SMELT),                  # gold bar
    2359: Recipe(2359, {447: 1, 453: 4}, "smithing", _SMELT),          # mithril bar
    2361: Recipe(2361, {449: 1, 453: 6}, "smithing", _SMELT),          # adamantite bar
    2363: Recipe(2363, {451: 1, 453: 8}, "smithing", _SMELT),          # runite bar
}

# ---------------------------------------------------------------------------
# FLETCHING — arrow shafts + arrowtips -> arrows (15 per run)
# ---------------------------------------------------------------------------
_FLETCH = 2000
FLETCHING: dict[int, Recipe] = {
    882: Recipe(882, {52: 15, 39: 15}, "fletching", _FLETCH, outputs_per_run=15),  # bronze arrow
    884: Recipe(884, {52: 15, 40: 15}, "fletching", _FLETCH, outputs_per_run=15),  # iron arrow
    886: Recipe(886, {52: 15, 41: 15}, "fletching", _FLETCH, outputs_per_run=15),  # steel arrow
    888: Recipe(888, {52: 15, 42: 15}, "fletching", _FLETCH, outputs_per_run=15),  # mithril arrow
    890: Recipe(890, {52: 15, 43: 15}, "fletching", _FLETCH, outputs_per_run=15),  # adamant arrow
    892: Recipe(892, {52: 15, 44: 15}, "fletching", _FLETCH, outputs_per_run=15),  # rune arrow
}

# ---------------------------------------------------------------------------
# CRAFTING — leather, glassblowing, jewelry, pottery
# ---------------------------------------------------------------------------
_CRAFT = 1200
CRAFTING: dict[int, Recipe] = {
    # Leather: cowhide -> leather
    1741: Recipe(1741, {1739: 1}, "crafting", 1800),
    # Hard leather: cowhide -> hard leather (needs 1 cowhide + craft)
    1743: Recipe(1743, {1739: 1}, "crafting", 1800),
    # Dragon leather: green/blue/red/black dragonhide -> leather
    1745: Recipe(1745, {1753: 1}, "crafting", 1800),  # green dragon leather
    2505: Recipe(2505, {1751: 1}, "crafting", 1800),  # blue dragon leather
    2507: Recipe(2507, {1749: 1}, "crafting", 1800),  # red dragon leather
    2509: Recipe(2509, {1747: 1}, "crafting", 1800),  # black dragon leather
    # Glassblowing: molten glass -> orb
    573: Recipe(573, {1775: 1}, "crafting", 1800),    # air orb
    571: Recipe(571, {1775: 1}, "crafting", 1800),    # water orb
    575: Recipe(575, {1775: 1}, "crafting", 1800),    # earth orb
    569: Recipe(569, {1775: 1}, "crafting", 1800),    # fire orb
    # Jewelry: gold bar + gem -> ring
    1637: Recipe(1637, {2357: 1, 1607: 1}, "crafting", _CRAFT),  # sapphire ring
    1639: Recipe(1639, {2357: 1, 1605: 1}, "crafting", _CRAFT),  # emerald ring
    1641: Recipe(1641, {2357: 1, 1603: 1}, "crafting", _CRAFT),  # ruby ring
    1643: Recipe(1643, {2357: 1, 1601: 1}, "crafting", _CRAFT),  # diamond ring
    # Jewelry: gold bar + gem -> amulet (u)
    1675: Recipe(1675, {2357: 1, 1607: 1}, "crafting", _CRAFT),  # sapphire amulet (u)
    1677: Recipe(1677, {2357: 1, 1605: 1}, "crafting", _CRAFT),  # emerald amulet (u)
    1679: Recipe(1679, {2357: 1, 1603: 1}, "crafting", _CRAFT),  # ruby amulet (u)
    1681: Recipe(1681, {2357: 1, 1601: 1}, "crafting", _CRAFT),  # diamond amulet (u)
    # Pottery: soft clay -> unfired pot -> pot
    1787: Recipe(1787, {1761: 1}, "crafting", 1500),  # unfired pot
    1931: Recipe(1931, {1787: 1}, "crafting", 1500),  # pot (fire unfired pot)
    # Spinning: flax -> bowstring
    1777: Recipe(1777, {1779: 1}, "crafting", 1800),
}

# ---------------------------------------------------------------------------
# COOKING — raw fish -> cooked fish (1 per run)
# ---------------------------------------------------------------------------
_COOK = 1800
COOKING: dict[int, Recipe] = {
    333: Recipe(333, {335: 1}, "cooking", _COOK),    # trout
    329: Recipe(329, {331: 1}, "cooking", _COOK),    # salmon
    379: Recipe(379, {377: 1}, "cooking", _COOK),    # lobster
    373: Recipe(373, {371: 1}, "cooking", _COOK),    # swordfish
    361: Recipe(361, {359: 1}, "cooking", _COOK),    # tuna
    385: Recipe(385, {383: 1}, "cooking", _COOK),    # shark
    7946: Recipe(7946, {7944: 1}, "cooking", _COOK), # monkfish
    3144: Recipe(3144, {3142: 1}, "cooking", _COOK), # cooked karambwan
    319: Recipe(319, {321: 1}, "cooking", _COOK),    # anchovies
    325: Recipe(325, {327: 1}, "cooking", _COOK),    # sardine
    347: Recipe(347, {345: 1}, "cooking", _COOK),    # herring
}

# ---------------------------------------------------------------------------
# HERBLORE — grimy herb -> clean herb; clean herb + secondary -> potion(3)
# ---------------------------------------------------------------------------
_HERB = 900
HERBLORE: dict[int, Recipe] = {
    # Cleaning grimy herbs
    249: Recipe(249, {199: 1}, "herblore", _HERB),    # guam leaf
    251: Recipe(251, {201: 1}, "herblore", _HERB),    # marrentill
    253: Recipe(253, {203: 1}, "herblore", _HERB),    # tarromin
    255: Recipe(255, {205: 1}, "herblore", _HERB),    # harralander
    257: Recipe(257, {207: 1}, "herblore", _HERB),    # ranarr weed
    2998: Recipe(2998, {3049: 1}, "herblore", _HERB), # toadflax
    259: Recipe(259, {209: 1}, "herblore", _HERB),    # irit leaf
    261: Recipe(261, {211: 1}, "herblore", _HERB),    # avantoe
    263: Recipe(263, {213: 1}, "herblore", _HERB),    # kwuarm
    3000: Recipe(3000, {3051: 1}, "herblore", _HERB), # snapdragon
    269: Recipe(269, {219: 1}, "herblore", _HERB),    # torstol
    # Potions: clean herb + secondary -> potion (3-dose)
    121: Recipe(121, {249: 1, 221: 1}, "herblore", _HERB),    # attack potion(3)
    115: Recipe(115, {251: 1, 225: 1}, "herblore", _HERB),    # strength potion(3)
    133: Recipe(133, {253: 1, 223: 1}, "herblore", _HERB),    # defence potion(3)
    139: Recipe(139, {257: 1, 239: 1}, "herblore", _HERB),    # prayer potion(3)
    145: Recipe(145, {2998: 1, 221: 1}, "herblore", _HERB),   # super attack(3)
    157: Recipe(157, {259: 1, 225: 1}, "herblore", _HERB),    # super strength(3)
    163: Recipe(163, {261: 1, 225: 1}, "herblore", _HERB),    # super defence(3)
    169: Recipe(169, {263: 1, 239: 1}, "herblore", _HERB),    # ranging potion(3)
    3042: Recipe(3042, {3000: 1, 2357: 1}, "herblore", _HERB),  # magic potion(3) (snapdragon + gold bar)
    175: Recipe(175, {253: 1, 223: 1}, "herblore", _HERB),    # antipoison(3) (tarromin + red spiders' eggs)
    3010: Recipe(3010, {249: 1, 221: 1}, "herblore", _HERB),  # energy potion(3) (guam + newt)
    127: Recipe(127, {253: 1, 225: 1}, "herblore", _HERB),    # restore potion(3) (harralander + limpwurt)
}

# ---------------------------------------------------------------------------
# CONSTRUCTION — logs -> planks; bar -> nails
# ---------------------------------------------------------------------------
_CONSTR = 600
CONSTRUCTION: dict[int, Recipe] = {
    960: Recipe(960, {1511: 1}, "construction", _CONSTR),       # regular plank (normal logs)
    8778: Recipe(8778, {1521: 1}, "construction", _CONSTR),     # oak plank
    8780: Recipe(8780, {6333: 1}, "construction", _CONSTR),     # teak plank
    8782: Recipe(8782, {6332: 1}, "construction", _CONSTR),     # mahogany plank
    4819: Recipe(4819, {2349: 1}, "construction", 800),         # bronze nails
    4820: Recipe(4820, {2351: 1}, "construction", 800),         # iron nails
    1539: Recipe(1539, {2353: 1}, "construction", 800),         # steel nails
    4822: Recipe(4822, {2359: 1}, "construction", 800),         # mithril nails
    4823: Recipe(4823, {2361: 1}, "construction", 800),         # adamantite nails
}

# ---------------------------------------------------------------------------
# RUNECRAFTING — essence -> runes (multi per run)
# ---------------------------------------------------------------------------
_RC = 1000
RUNECRAFTING: dict[int, Recipe] = {
    556: Recipe(556, {1436: 1}, "runecrafting", _RC),   # air rune (rune essence)
    558: Recipe(558, {1436: 1}, "runecrafting", _RC),   # mind rune
    555: Recipe(555, {1436: 1}, "runecrafting", _RC),   # water rune
    557: Recipe(557, {1436: 1}, "runecrafting", _RC),   # earth rune
    554: Recipe(554, {1436: 1}, "runecrafting", _RC),   # fire rune
    559: Recipe(559, {1436: 1}, "runecrafting", _RC),   # body rune
    564: Recipe(564, {7936: 1}, "runecrafting", _RC),   # cosmic rune (pure essence)
    562: Recipe(562, {7936: 1}, "runecrafting", _RC),   # chaos rune
    561: Recipe(561, {7936: 1}, "runecrafting", _RC),   # nature rune
    563: Recipe(563, {7936: 1}, "runecrafting", _RC),   # law rune
    560: Recipe(560, {7936: 1}, "runecrafting", _RC),   # death rune
}

# ---------------------------------------------------------------------------
# AGGREGATE — all recipes, keyed by output item id
# ---------------------------------------------------------------------------
RECIPES: dict[int, Recipe] = {
    **SMITHING, **FLETCHING, **CRAFTING, **COOKING,
    **HERBLORE, **CONSTRUCTION, **RUNECRAFTING,
}
