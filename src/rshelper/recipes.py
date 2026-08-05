"""Static processing recipes: output item -> inputs + process metadata.

The scanner buys the inputs at their instant-buy price, processes them,
and sells the output at its instant-sell price (GE tax on the sell leg
only). Item IDs are verified against the OSRS wiki mapping, and the
`rate_per_hour` / `cost_per_unit` values are calibrated to the OSRS Wiki
money-making guides (not guessed).

Recipe economics:
  input_cost = sum(input.buy_price * qty for each input)
  output_gp  = output.sell_price - ge_tax(output.sell_price)
  profit     = output_gp - input_cost/outputs_per_run - cost_per_unit
  gp_per_hour = profit * min(rate_per_hour, output.buy_limit/4,
                             output.volume*12, input_capacity)
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Recipe:
    output_id: int
    inputs: dict[int, int]   # {input_item_id: qty_per_run}
    skill: str               # "smithing" | "fletching" | "crafting" | "cooking"
                             # | "herblore" | "construction" | "runecrafting" | "magic"
    rate_per_hour: int       # action-rate cap (wiki-calibrated)
    cost_per_unit: int = 0   # non-GE process cost (e.g. sawmill fee)
    outputs_per_run: int = 1  # units produced per recipe run (batch: 15 arrows)


# ---------------------------------------------------------------------------
# SMITHING — ores -> bars. Wiki: ~775 bars/hr at the Edgeville furnace.
# ---------------------------------------------------------------------------
_SMELT = 775
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
# FLETCHING — arrow shafts + feathers + arrowtips -> arrows. Wiki: ~2,400
# arrows/hr. Full arrow = shaft + feather + tip (15 per batch).
# ---------------------------------------------------------------------------
_FLETCH = 2400
_FL = 314  # feather
FLETCHING: dict[int, Recipe] = {
    882: Recipe(882, {52: 15, _FL: 15, 39: 15}, "fletching", _FLETCH, outputs_per_run=15),  # bronze arrow
    884: Recipe(884, {52: 15, _FL: 15, 40: 15}, "fletching", _FLETCH, outputs_per_run=15),  # iron arrow
    886: Recipe(886, {52: 15, _FL: 15, 41: 15}, "fletching", _FLETCH, outputs_per_run=15),  # steel arrow
    888: Recipe(888, {52: 15, _FL: 15, 42: 15}, "fletching", _FLETCH, outputs_per_run=15),  # mithril arrow
    890: Recipe(890, {52: 15, _FL: 15, 43: 15}, "fletching", _FLETCH, outputs_per_run=15),  # adamant arrow
    892: Recipe(892, {52: 15, _FL: 15, 44: 15}, "fletching", _FLETCH, outputs_per_run=15),  # rune arrow
}

# ---------------------------------------------------------------------------
# CRAFTING — leather, jewelry, pottery, spinning. (Orbs are a Magic method:
# blowing molten glass is low-profit XP; the real money-maker is charging,
# which needs cosmic runes — see MAGIC below.)
# ---------------------------------------------------------------------------
CRAFTING: dict[int, Recipe] = {
    1741: Recipe(1741, {1739: 1}, "crafting", 1800),    # cowhide -> leather
    1743: Recipe(1743, {1739: 1}, "crafting", 1800),    # cowhide -> hard leather
    1745: Recipe(1745, {1753: 1}, "crafting", 1800),    # green dhide -> leather
    2505: Recipe(2505, {1751: 1}, "crafting", 1800),    # blue dhide -> leather
    2507: Recipe(2507, {1749: 1}, "crafting", 1800),    # red dhide -> leather
    2509: Recipe(2509, {1747: 1}, "crafting", 1800),    # black dhide -> leather
    # Jewelry: gold bar + gem -> ring (wiki: ~1,000/hr)
    1637: Recipe(1637, {2357: 1, 1607: 1}, "crafting", 1000),  # sapphire ring
    1639: Recipe(1639, {2357: 1, 1605: 1}, "crafting", 1000),  # emerald ring
    1641: Recipe(1641, {2357: 1, 1603: 1}, "crafting", 1000),  # ruby ring
    1643: Recipe(1643, {2357: 1, 1601: 1}, "crafting", 1000),  # diamond ring
    1675: Recipe(1675, {2357: 1, 1607: 1}, "crafting", 1000),  # sapphire amulet (u)
    1677: Recipe(1677, {2357: 1, 1605: 1}, "crafting", 1000),  # emerald amulet (u)
    1679: Recipe(1679, {2357: 1, 1603: 1}, "crafting", 1000),  # ruby amulet (u)
    1681: Recipe(1681, {2357: 1, 1601: 1}, "crafting", 1000),  # diamond amulet (u)
    1787: Recipe(1787, {1761: 1}, "crafting", 1500),  # soft clay -> unfired pot
    1931: Recipe(1931, {1787: 1}, "crafting", 1500),  # unfired pot -> pot
    1777: Recipe(1777, {1779: 1}, "crafting", 1000),  # flax -> bowstring
}

# ---------------------------------------------------------------------------
# MAGIC — charging unpowered orbs. Wiki: ~525 orbs/hr (21 trips x 25),
# each orb needs 3 cosmic runes. (The real "air orb" money-maker; blowing
# molten glass into an orb is a low-profit crafting XP method.)
# ---------------------------------------------------------------------------
_CHARGE = 525
MAGIC: dict[int, Recipe] = {
    573: Recipe(573, {567: 1, 564: 3}, "magic", _CHARGE),   # air orb
    571: Recipe(571, {567: 1, 564: 3}, "magic", _CHARGE),   # water orb
    575: Recipe(575, {567: 1, 564: 3}, "magic", _CHARGE),   # earth orb
    569: Recipe(569, {567: 1, 564: 3}, "magic", _CHARGE),   # fire orb
}

# ---------------------------------------------------------------------------
# COOKING — raw fish -> cooked. Wiki: ~1,000-1,300/hr (use 1100 avg).
# ---------------------------------------------------------------------------
_COOK = 1100
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
# HERBLORE — grimy -> clean (~2,000/hr); clean herb + secondary -> potion
# (~1,500/hr). Every potion needs a vial of water (227) as its base, plus
# the correct secondary (wiki-verified).
# ---------------------------------------------------------------------------
_HERB_CLEAN = 2000
_HERB_POT = 1500
_VOW = 227  # vial of water
HERBLORE: dict[int, Recipe] = {
    # Cleaning grimy herbs
    249: Recipe(249, {199: 1}, "herblore", _HERB_CLEAN),    # guam leaf
    251: Recipe(251, {201: 1}, "herblore", _HERB_CLEAN),    # marrentill
    253: Recipe(253, {203: 1}, "herblore", _HERB_CLEAN),    # tarromin
    255: Recipe(255, {205: 1}, "herblore", _HERB_CLEAN),    # harralander
    257: Recipe(257, {207: 1}, "herblore", _HERB_CLEAN),    # ranarr weed
    2998: Recipe(2998, {3049: 1}, "herblore", _HERB_CLEAN), # toadflax
    259: Recipe(259, {209: 1}, "herblore", _HERB_CLEAN),    # irit leaf
    261: Recipe(261, {211: 1}, "herblore", _HERB_CLEAN),    # avantoe
    263: Recipe(263, {213: 1}, "herblore", _HERB_CLEAN),    # kwuarm
    3000: Recipe(3000, {3051: 1}, "herblore", _HERB_CLEAN), # snapdragon
    269: Recipe(269, {219: 1}, "herblore", _HERB_CLEAN),    # torstol
    # Potions (vial of water + clean herb + secondary)
    121: Recipe(121, {_VOW: 1, 249: 1, 221: 1}, "herblore", _HERB_POT),      # attack: guam + eye of newt
    115: Recipe(115, {_VOW: 1, 253: 1, 225: 1}, "herblore", _HERB_POT),      # strength: tarromin + limpwurt
    133: Recipe(133, {_VOW: 1, 257: 1, 239: 1}, "herblore", _HERB_POT),      # defence: ranarr + white berries
    139: Recipe(139, {_VOW: 1, 257: 1, 231: 1}, "herblore", _HERB_POT),      # prayer: ranarr + snape grass
    145: Recipe(145, {_VOW: 1, 259: 1, 221: 1}, "herblore", _HERB_POT),      # super attack: irit + eye of newt
    157: Recipe(157, {_VOW: 1, 263: 1, 225: 1}, "herblore", _HERB_POT),      # super strength: kwuarm + limpwurt
    163: Recipe(163, {_VOW: 1, 265: 1, 239: 1}, "herblore", _HERB_POT),      # super defence: cadantine + white berries
    169: Recipe(169, {_VOW: 1, 267: 1, 245: 1}, "herblore", _HERB_POT),      # ranging: dwarf weed + wine of zamorak
    3042: Recipe(3042, {_VOW: 1, 2481: 1, 3138: 1}, "herblore", _HERB_POT),  # magic: lantadyme + potato cactus
    175: Recipe(175, {_VOW: 1, 251: 1, 235: 1}, "herblore", _HERB_POT),      # antipoison: marrentill + unicorn horn dust
    3010: Recipe(3010, {_VOW: 1, 255: 1, 1975: 1}, "herblore", _HERB_POT),   # energy: harralander + chocolate dust
    127: Recipe(127, {_VOW: 1, 255: 1, 223: 1}, "herblore", _HERB_POT),      # restore: harralander + red spiders' eggs
}

# ---------------------------------------------------------------------------
# CONSTRUCTION — logs -> planks at the Sawmill. Wiki: 1,500 gp fee per
# mahogany plank (100/250/500 for regular/oak/teak), ~2,800 planks/hr
# at max efficiency. Nails: 1 bar -> 15 nails (smithing at the anvil).
# ---------------------------------------------------------------------------
_CONSTR_PLANK = 2800
_CONSTR_NAIL = 800
CONSTRUCTION: dict[int, Recipe] = {
    960: Recipe(960, {1511: 1}, "construction", _CONSTR_PLANK, cost_per_unit=100),
    8778: Recipe(8778, {1521: 1}, "construction", _CONSTR_PLANK, cost_per_unit=250),
    8780: Recipe(8780, {6333: 1}, "construction", _CONSTR_PLANK, cost_per_unit=500),
    8782: Recipe(8782, {6332: 1}, "construction", _CONSTR_PLANK, cost_per_unit=1500),
    4819: Recipe(4819, {2349: 1}, "construction", _CONSTR_NAIL, outputs_per_run=15),
    4820: Recipe(4820, {2351: 1}, "construction", _CONSTR_NAIL, outputs_per_run=15),
    1539: Recipe(1539, {2353: 1}, "construction", _CONSTR_NAIL, outputs_per_run=15),
    4822: Recipe(4822, {2359: 1}, "construction", _CONSTR_NAIL, outputs_per_run=15),
    4823: Recipe(4823, {2361: 1}, "construction", _CONSTR_NAIL, outputs_per_run=15),
}

# ---------------------------------------------------------------------------
# RUNECRAFTING — essence -> runes. Wiki: ~4,000-6,000 runes/hr at high
# level through the Abyss (use 5000 avg; essence -> runes is 1:1 at low
# level but multiplies at high level — conservative 1:1 here).
# ---------------------------------------------------------------------------
_RC = 5000
RUNECRAFTING: dict[int, Recipe] = {
    556: Recipe(556, {1436: 1}, "runecrafting", _RC),   # air rune
    558: Recipe(558, {1436: 1}, "runecrafting", _RC),   # mind rune
    555: Recipe(555, {1436: 1}, "runecrafting", _RC),   # water rune
    557: Recipe(557, {1436: 1}, "runecrafting", _RC),   # earth rune
    554: Recipe(554, {1436: 1}, "runecrafting", _RC),   # fire rune
    559: Recipe(559, {1436: 1}, "runecrafting", _RC),   # body rune
    564: Recipe(564, {7936: 1}, "runecrafting", _RC),   # cosmic rune
    562: Recipe(562, {7936: 1}, "runecrafting", _RC),   # chaos rune
    561: Recipe(561, {7936: 1}, "runecrafting", _RC),   # nature rune
    563: Recipe(563, {7936: 1}, "runecrafting", _RC),   # law rune
    560: Recipe(560, {7936: 1}, "runecrafting", _RC),   # death rune
}

# ---------------------------------------------------------------------------
# AGGREGATE — all recipes, keyed by output item id
# ---------------------------------------------------------------------------
RECIPES: dict[int, Recipe] = {
    **SMITHING, **FLETCHING, **CRAFTING, **MAGIC, **COOKING,
    **HERBLORE, **CONSTRUCTION, **RUNECRAFTING,
}
