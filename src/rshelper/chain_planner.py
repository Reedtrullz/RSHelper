import json


MAX_INVENTORY_ENTRIES = 100
MAX_CHAIN_DEPTH = 2
MAX_CANDIDATES = 40


def plan_chains(recipes, prices, inventory_json: str,
                *, max_depth: int = MAX_CHAIN_DEPTH):
    if type(inventory_json) is not str or len(inventory_json) > 10_000:
        raise ValueError('inventory must be JSON text of at most 10,000 characters')
    try:
        raw = json.loads(inventory_json)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError('inventory is not valid JSON') from exc
    if not isinstance(raw, dict) or len(raw) > MAX_INVENTORY_ENTRIES:
        raise ValueError('inventory must be an object with at most 100 entries')
    inventory: dict[int, int] = {}
    for key, qty in raw.items():
        try:
            item_id, count = int(key), int(qty)
        except (TypeError, ValueError) as exc:
            raise ValueError('inventory item ids and quantities must be integers') from exc
        if str(item_id) != str(key).strip() or not 0 < item_id < 10**10 or count <= 0:
            raise ValueError('inventory ids must match keys and quantities be positive')
        inventory[item_id] = count

    depth = max(1, min(int(max_depth), MAX_CHAIN_DEPTH))
    from .recipes import recipe_breakdown

    def usable(recipe):
        output = prices.get(recipe.output_id)
        if output is None or output.sell_price <= 0 or any(
                (prices.get(iid) is None or prices[iid].buy_price <= 0)
                for iid in recipe.inputs):
            return None
        return recipe

    candidates = [recipe for recipe in sorted(recipes.values(), key=lambda r: r.output_id)
                  if usable(recipe)]
    rejections = []
    for recipe in sorted(recipes.values(), key=lambda r: r.output_id):
        if usable(recipe) is None:
            rejections.append({'output_id': recipe.output_id,
                               'rejected': 'quote unavailable or unusable'})
    rejections = rejections[:MAX_CANDIDATES]

    results = []
    for recipe in candidates:
        plan = _single_step(recipe, prices, inventory)
        if plan is not None:
            results.append(plan)
    if depth < 2:
        return results
    for first in candidates:
        first_outputs = _modeled_outputs(first, prices)
        if first_outputs is None:
            continue
        chained_inventory = {**inventory, first.output_id: first_outputs}
        for second in candidates:
            if second.output_id == first.output_id or first.output_id not in second.inputs:
                continue
            if second.output_id in first.inputs:
                rejections.append({'steps': [first.output_id, second.output_id],
                                   'rejected': 'cycle detected'})
                continue
            plan = _single_step(second, prices, chained_inventory,
                                chain_first=first, chain_outputs=first_outputs)
            if plan is not None:
                results.append(plan)
    return results + rejections


def _single_step(recipe, prices, inventory, *, chain_first=None, chain_outputs=0):
    from .recipes import recipe_breakdown
    lookup = dict(prices)
    econ = recipe_breakdown(recipe, lookup)
    if not econ['available']:
        return None
    shortfalls = {}
    owned_value = 0
    inputs_owned = {}
    for iid, qty in recipe.inputs.items():
        have = inventory.get(iid, 0)
        if chain_first is not None and iid == chain_first.output_id:
            have = chain_outputs
        owned = min(have, qty)
        if owned:
            inputs_owned[str(iid)] = owned
            owned_value += owned * prices[iid].buy_price
        need = qty - owned
        if need > 0:
            shortfalls[str(iid)] = need
    if chain_first is not None and chain_outputs <= 0:
        return None
    return {
        'depth': 2 if chain_first is not None else 1,
        'steps': [chain_first.output_id, recipe.output_id] if chain_first is not None else [recipe.output_id],
        'output_id': recipe.output_id,
        'profit_per_run': econ['profit_per_run'],
        'input_cost_per_run': econ['input_cost_per_run'],
        'owned_input_value': owned_value,
        'owned_input_value_disclosed': owned_value,
        'shortfalls': shortfalls,
        'inputs_owned': inputs_owned,
        'outputs_per_run': econ['outputs_per_run'],
        'model_runs_per_hour': econ['model_runs_per_hour'],
        'model_gp_per_hour': econ['model_gp_per_hour'],
        'xp_evidence': 'unavailable',
        'time_hours': None,
        'deterministic_limits': {'max_depth': MAX_CHAIN_DEPTH, 'max_candidates': MAX_CANDIDATES},
    }


def _modeled_outputs(recipe, prices):
    from .recipes import recipe_breakdown
    econ = recipe_breakdown(recipe, prices)
    if not econ['available']:
        return None
    return int(econ['model_runs_per_hour'] * econ['outputs_per_run'])
