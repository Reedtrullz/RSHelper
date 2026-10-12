"""Static processing recipes: output item -> inputs + process metadata.

The scanner buys the inputs at their instant-buy price, processes them,
and sells the output at its instant-sell price (GE tax on each sell unit).
Legacy rates remain illustrative until a particular route is reviewed.

Recipe economics:
  input_cost = sum(input.buy_price * qty for each input)
  output_gp  = output.sell_price - ge_tax(output.sell_price)
  profit     = output_gp - input_cost/outputs_per_run - cost_per_unit
  Sell-throughput estimates are separate from input GE acquisition limits.
"""

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Recipe:
    output_id: int
    inputs: dict[int, int]   # {input_item_id: qty_per_run}
    skill: str               # "smithing" | "fletching" | "crafting" | "cooking"
                             # | "herblore" | "construction" | "runecrafting" | "magic"
    rate_per_hour: int       # illustrative legacy cap until rate_reviewed
    cost_per_unit: int = 0   # non-GE process cost (e.g. sawmill fee)
    outputs_per_run: int = 1  # units produced per recipe run (batch: 15 arrows)
    source_url: str | None = None
    reviewed_on: str | None = None
    rate_basis: str = 'runs-per-hour'
    rate_reviewed: bool = False
    yield_reviewed: bool = False
    success_probability: float | None = None
    requirements: dict | None = None


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
# RUNECRAFTING — essence -> runes. Wiki (99 RC reference): each essence
# crafts multiple runes (air 10x, mind 7x, water 5x, earth 4x, fire/body
# 3x, cosmic/chaos/nature/law/death 2x). Throughput ~3,350 essence/hr via
# the Abyss with the colossal pouch (50 trips x 67 essence).
# ---------------------------------------------------------------------------
_RC = 3350
RUNECRAFTING: dict[int, Recipe] = {
    556: Recipe(556, {1436: 1}, "runecrafting", _RC, outputs_per_run=10),  # air rune
    558: Recipe(558, {1436: 1}, "runecrafting", _RC, outputs_per_run=7),   # mind rune
    555: Recipe(555, {1436: 1}, "runecrafting", _RC, outputs_per_run=5),   # water rune
    557: Recipe(557, {1436: 1}, "runecrafting", _RC, outputs_per_run=4),   # earth rune
    554: Recipe(554, {1436: 1}, "runecrafting", _RC, outputs_per_run=3),   # fire rune
    559: Recipe(559, {1436: 1}, "runecrafting", _RC, outputs_per_run=3),   # body rune
    564: Recipe(564, {7936: 1}, "runecrafting", _RC, outputs_per_run=2),   # cosmic rune
    562: Recipe(562, {7936: 1}, "runecrafting", _RC, outputs_per_run=2),   # chaos rune
    561: Recipe(561, {7936: 1}, "runecrafting", _RC, outputs_per_run=2),   # nature rune
    563: Recipe(563, {7936: 1}, "runecrafting", _RC, outputs_per_run=2),   # law rune
    560: Recipe(560, {7936: 1}, "runecrafting", _RC, outputs_per_run=2),   # death rune
}

# ---------------------------------------------------------------------------
# AGGREGATE — all recipes, keyed by output item id
# ---------------------------------------------------------------------------
RECIPES: dict[int, Recipe] = {
    **SMITHING, **FLETCHING, **CRAFTING, **MAGIC, **COOKING,
    **HERBLORE, **CONSTRUCTION, **RUNECRAFTING,
}

for _iid,_level in {2349:1,2351:15,2353:30,2355:20,2357:40,2359:50,2361:70,2363:85}.items():
    RECIPES[_iid] = replace(RECIPES[_iid],source_url='https://oldschool.runescape.wiki/w/Smithing',
        reviewed_on='2026-10-12',yield_reviewed=True,success_probability=.5 if _iid==2351 else 1.0,
        requirements={'members':False,'level':_level,'unlocks':[]})
for _iid in (960,8778,8780,8782):
    RECIPES[_iid] = replace(RECIPES[_iid],source_url='https://oldschool.runescape.wiki/w/Sawmill',
        reviewed_on='2026-10-12',yield_reviewed=True,success_probability=1.0,
        requirements={'members':True,'level':0,'unlocks':[]})
for _iid in FLETCHING:
    RECIPES[_iid] = replace(RECIPES[_iid],rate_basis='outputs-per-hour')
RECIPES[892] = replace(RECIPES[892],source_url='https://oldschool.runescape.wiki/w/Rune_arrow',
    reviewed_on='2026-10-12',yield_reviewed=True,success_probability=1.0,
    requirements={'members':True,'level':75,'unlocks':[]})
for _iid in COOKING:
    RECIPES[_iid] = replace(RECIPES[_iid],source_url='https://oldschool.runescape.wiki/w/Cooking',
                          reviewed_on='2026-10-12',success_probability=None)
for _iid in HERBLORE:
    RECIPES[_iid] = replace(RECIPES[_iid],source_url='https://oldschool.runescape.wiki/w/Herblore',
                          reviewed_on='2026-10-12')
for _iid in RUNECRAFTING:
    RECIPES[_iid] = replace(RECIPES[_iid],source_url='https://oldschool.runescape.wiki/w/Runecraft',
                          reviewed_on='2026-10-12')


def recipe_breakdown(recipe, prices, account=None, *, capital=0):
    from rshelper.market import ge_tax
    requirements = recipe.requirements
    if account is not None and not isinstance(account,dict):
        raise ValueError('account context must be an object')
    account = account or {}
    if (account.get('members') is not None and type(account['members']) is not bool
            or not isinstance(account.get('levels',{}),dict)
            or len(account.get('levels',{}))>100
            or any(not isinstance(name,str) or not name or len(name)>100
                   or type(value) is not int or not 0<=value<=99 for name,value in account.get('levels',{}).items())
            or account.get('unlocks') is not None and (
                not isinstance(account['unlocks'],(list,dict))
                or len(account['unlocks'])>100
                or any(not isinstance(value,str) or not value or len(value)>100 for value in account['unlocks'])
                or isinstance(account['unlocks'],dict)
                    and any(type(value) is not bool for value in account['unlocks'].values()))):
        raise ValueError('invalid account membership, level or unlock facts')
    unknown,blocked = [],[]
    if requirements is None:
        unknown.append('requirements unverified')
    else:
        if requirements.get('members'):
            if account.get('members') is False:blocked.append('membership required')
            elif account.get('members') is not True:unknown.append('membership unknown')
        level = (account.get('levels') or {}).get(recipe.skill)
        required = requirements.get('level')
        if required is None:unknown.append('required level unverified')
        elif required > 0:
            if type(level) is not int:unknown.append('level unknown')
            elif level < required:blocked.append('level below requirement')
        for unlock in requirements.get('unlocks',[]):
            if account.get('unlocks') is None:unknown.append('unlock unknown: '+unlock)
            elif isinstance(account['unlocks'],dict):
                if unlock not in account['unlocks']:unknown.append('unlock unknown: '+unlock)
                elif not account['unlocks'][unlock]:blocked.append('unlock required: '+unlock)
            elif unlock not in account['unlocks']:blocked.append('unlock required: '+unlock)
    eligibility = 'ineligible' if blocked else 'unknown' if unknown else 'eligible'
    gaps = []
    if not recipe.source_url or not recipe.reviewed_on:gaps.append('source unreviewed')
    if not recipe.rate_reviewed:gaps.append('rate unverified')
    if not recipe.yield_reviewed:gaps.append('yield unverified')
    if recipe.success_probability is None:gaps.append('success probability unknown')
    output = prices.get(recipe.output_id)
    inputs = [(prices.get(iid),qty) for iid,qty in recipe.inputs.items()]
    factors = []
    result = {'available':False,'eligibility':eligibility,'eligibility_reasons':blocked+unknown,
        'skill':recipe.skill,
        'source_url':recipe.source_url,'reviewed_on':recipe.reviewed_on,'requirements':requirements,
        'rate_basis':recipe.rate_basis,'outputs_per_run':recipe.outputs_per_run,
        'success_probability':recipe.success_probability,'evidence_gaps':gaps,
        'gp_per_hour':None,'model_gp_per_hour':0,'limiting_factors':factors}
    if output is None or any(item is None for item,qty in inputs):
        factors.append('input or output quote unavailable')
        return result
    if output.sell_price <= 0 or any(item.buy_price <= 0 for item,qty in inputs):
        factors.append('quote unusable')
        return result
    if recipe.rate_basis not in ('runs-per-hour','outputs-per-hour'):
        raise ValueError('unsupported recipe rate units')
    input_cost = sum(item.buy_price*qty for item,qty in inputs)
    model_success = recipe.success_probability if recipe.success_probability is not None else 1.0
    expected_outputs = recipe.outputs_per_run*model_success
    if not 0 < model_success <= 1 or recipe.outputs_per_run <= 0:
        raise ValueError('invalid recipe yield')
    tax = ge_tax(output.sell_price)
    profit_run = expected_outputs*(output.sell_price-tax-recipe.cost_per_unit)-input_cost
    rate_runs = recipe.rate_per_hour/(recipe.outputs_per_run if recipe.rate_basis=='outputs-per-hour' else 1)
    input_caps = [(item.buy_limit/4)//qty if type(item.buy_limit) is int and item.buy_limit>0 else 0
                  for item,qty in inputs]
    if any(cap==0 for cap in input_caps):factors.append('input buy limit unknown')
    caps = {'action rate':rate_runs,'input acquisition':min(input_caps),
            'illustrative sell volume':max(0,output.volume)*12/expected_outputs}
    if capital > 0:caps['capital'] = capital//input_cost
    runs = min(caps.values())
    factors.extend(key for key,value in caps.items() if value==runs)
    model_profit = int(profit_run/expected_outputs)
    result.update(available=True,input_cost_per_run=input_cost,
        input_cost_per_output=input_cost/expected_outputs,process_fee_per_output=recipe.cost_per_unit,
        tax_per_output=tax,profit_per_run=profit_run,model_profit_per_output=model_profit,
        profit_per_output=model_profit if recipe.yield_reviewed and recipe.success_probability is not None else None,
        rate_runs_per_hour=rate_runs,model_runs_per_hour=runs,
        model_outputs_per_hour=runs*expected_outputs,model_gp_per_hour=int(profit_run*runs),
        model_success_probability=model_success,throughput_caps=caps,
        volume_quality=output.market_data.get('5m',{}).get('volume_kind','unknown'))
    volume_meta = output.market_data.get('5m',{})
    if result['volume_quality']!='executed-trades' or volume_meta.get('stale') is not False:
        gaps.append('executed sell-volume evidence unavailable')
    if not gaps and eligibility=='eligible':
        result['gp_per_hour'] = result['model_gp_per_hour']
    return result


def process_payload(item):
    economics = item.recipe_economics
    profit = economics.get('profit_per_output')
    cost = economics.get('input_cost_per_output',item.input_cost)
    roi = round(profit/cost*100,2) if profit is not None and cost else None
    return {'name':item.name,'item_id':item.id,'market_data':item.market_data,
            'input_cost':cost,'sell_price':item.sell_price,'profit':profit,
            'model_profit':item.profit,'roi':roi,'roi_pct':roi,
            'gp_per_hour':economics.get('gp_per_hour'),'model_gp_per_hour':item.gp_per_hour,
            'volume':item.volume,'buy_limit':item.buy_limit,'skill':economics.get('skill',''),
            'eligibility':economics.get('eligibility','unknown'),'recipe_economics':economics}
