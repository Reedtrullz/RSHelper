"""Alch-profit, flip-margin, and materials-processing scanner."""

import sys
from dataclasses import dataclass, field
from rshelper.market import (
    MAX_PRICE_RATIO,
    STALE_PRICE_AGE,
    ge_tax,
    price_issue,
    safe_int,
)
from rshelper.models import Item
from rshelper.analysis import analyze_timeseries, MarginAnalysis
from rshelper.signals import compute_rs_score_flip, compute_rs_score_alch
from rshelper.recipes import RECIPES, Recipe

MAX_CASTS_PER_HOUR = 1200  # 5-tick cast speed

@dataclass
class AlchScanner:
    nature_rune_cost: int = 147  # default GE price

    def scan(
        self,
        items: list[Item],
        *,
        members_only: bool = False,
        min_volume: int = 0,
    ) -> list[Item]:
        """Calculate profit and GP/hr for each item, return new Items sorted descending.

        Does not mutate the input list or its items.
        """
        results: list[Item] = []
        for item in items:
            if members_only and not item.members:
                continue
            if item.volume < min_volume:
                continue
            profit = item.alch_value - item.buy_price - self.nature_rune_cost
            if profit <= 0:
                continue
            if item.buy_limit <= 0:
                continue  # can.t buy = can.t alch
            # GP/hr capped by: alch speed, buy limit, and actual trade volume
            casts_per_hour = min(
                MAX_CASTS_PER_HOUR,
                item.buy_limit / 4,
                item.volume * 12,  # ponytail: 5-min volume → hourly
            )
            gp_per_hour = int(profit * casts_per_hour)
            result = Item(
                id=item.id, name=item.name, members=item.members,
                buy_limit=item.buy_limit, alch_value=item.alch_value,
                buy_price=item.buy_price, sell_price=item.sell_price,
                volume=item.volume, profit=profit, gp_per_hour=gp_per_hour,
            )
            results.append(result)
        results.sort(key=lambda i: i.gp_per_hour, reverse=True)
        compute_rs_score_alch(results)

        return results
def build_items_from_api(
    mapping: list[dict],
    latest: dict[str, dict],
    volume_5m: dict[str, dict],
) -> list[Item]:
    """Merge API responses into Item list, dropping stale/manipulated prices."""
    items: list[Item] = []
    skipped = {"stale": 0, "depth": 0, "ratio": 0}
    for entry in mapping:
        item_id = entry.get("id")
        if item_id is None:
            continue
        price = latest.get(str(item_id))
        if not isinstance(price, dict):
            continue  # skip items with no valid price data
        vol = volume_5m.get(str(item_id))
        if not isinstance(vol, dict):
            vol = {}
        issue = price_issue(price)
        if issue is not None:
            skipped[issue] = skipped.get(issue, 0) + 1
            continue
        buy_price = safe_int(price.get("high"))
        sell_price = safe_int(price.get("low"))
        volume = safe_int(vol.get("highPriceVolume")) + safe_int(vol.get("lowPriceVolume"))
        items.append(Item(
            id=item_id,
            name=entry.get("name", ""),
            members=entry.get("members", False),
            buy_limit=safe_int(entry.get("limit")),
            alch_value=safe_int(entry.get("highalch")),
            buy_price=buy_price,
            sell_price=sell_price,
            volume=volume,
        ))
    total = sum(skipped.values())
    if total:
        print(
            f"  Skipped {total} items with stale/manipulated prices "
            f"({skipped['stale']} stale, {skipped['depth']} no offer depth, "
            f"{skipped['ratio']} absurd spread)",
            file=sys.stderr,
        )
    return items

@dataclass
class FlipScanner:
    """Scan for flip margins.

    direction:
      "arbitrage"  — find low>high windows (buy at instant-buy/high, sell at instant-sell/low)
      "traditional" — standard GE flipping (buy at bid/low, sell at offer/high, minus tax)
    """
    direction: str = "arbitrage"
    ge_slots: int = 2  # number of GE slots (used at portfolio level, not per-item GP/hr)

    def __post_init__(self):
        if self.direction not in ("arbitrage", "traditional"):
            raise ValueError(f"direction must be 'arbitrage' or 'traditional', got '{self.direction}'")
        if self.ge_slots < 1:
            raise ValueError(f"ge_slots must be >= 1, got {self.ge_slots}")

    def scan(
        self,
        items: list[Item],
        *,
        members_only: bool = False,
        min_volume: int = 0,
        min_margin: int = 0,
    ) -> list[Item]:
        """Calculate flip margin and GP/hr, return sorted by gp_per_hour descending.

        GP/hr is per-item, independent of GE slot count. Slot allocation
        is a portfolio-level concern: pick the top (ge_slots // 2) items.
        """
        results: list[Item] = []
        for item in items:
            if members_only and not item.members:
                continue
            if item.volume < min_volume:
                continue
            if item.sell_price <= 0 or item.buy_price <= 0:
                continue

            # Arbitrage: buy at instant-buy(high), sell at instant-sell(low) — only finds low>high windows
            # Traditional: buy at bid(low), sell at offer(high) — standard GE flipping
            if self.direction == "arbitrage":
                margin = item.sell_price - item.buy_price
            else:  # traditional
                margin = item.buy_price - item.sell_price

            if margin < min_margin:
                continue
            if item.buy_limit <= 0:
                continue
            tax = ge_tax(item.sell_price if self.direction == "arbitrage" else item.buy_price)
            profit = margin - tax
            if profit <= 0:
                continue
            trades_per_hour = min(
                item.buy_limit / 4,
                item.volume * 12,
            )
            gp_per_hour = int(profit * trades_per_hour)
            result = Item(
                id=item.id, name=item.name, members=item.members,
                buy_limit=item.buy_limit, alch_value=item.alch_value,
                buy_price=item.buy_price, sell_price=item.sell_price,
                volume=item.volume, profit=profit, gp_per_hour=gp_per_hour,
            )
            results.append(result)
        results.sort(key=lambda i: i.gp_per_hour, reverse=True)
        max_vol = max((r.volume for r in results), default=1)
        
        for r in results:
            r.rs_score = compute_rs_score_flip(r, max_vol)
        return results

def trade_size(item: Item, capital: int) -> int:
    """Suggested buy quantity given capital (gp).

    Capped by: buy_limit, available capital, and hourly trade volume.
    Returns 0 for zero-volume (illiquid) items.
    """
    if item.buy_price <= 0 or capital <= 0:
        return 0
    by_limit = item.buy_limit
    by_capital = capital // item.buy_price
    by_volume = item.volume * 12  # 5-min volume -> hourly
    if by_volume == 0:
        return 0
    return min(by_limit, by_capital, by_volume)

class MarginScanner:
    """Scan top flip candidates for historical margin reliability."""

    def scan(
        self,
        lookup: dict[int, Item],  # item_id -> Item (name, buy_price, sell_price, etc)
        timeseries_data: dict[int, list[dict]],
        *,
        members_only: bool = False,
        direction: str = "arbitrage",
    ) -> list[MarginAnalysis]:
        """Analyze timeseries data for each item and return results sorted by expected GP/hr."""
        results: list[MarginAnalysis] = []
        for item_id, ts_data in timeseries_data.items():
            item = lookup.get(item_id)
            if item is None:
                continue
            if members_only and not item.members:
                continue
            analysis = analyze_timeseries(
                item_id, ts_data,
                direction=direction,
                current_buy=item.buy_price,
                current_sell=item.sell_price,
            )
            if analysis is None:
                continue

            # Compute current profit using same direction-aware logic as FlipScanner
            if direction == "arbitrage":
                margin = item.sell_price - item.buy_price
            else:
                margin = item.buy_price - item.sell_price
            tax = ge_tax(item.sell_price if direction == "arbitrage" else item.buy_price)
            current_profit = margin - tax

            # throughput = items per hour given market constraints
            trades_per_hour = min(item.buy_limit / 4, item.volume * 12)

            analysis.current_profit = max(0, current_profit)
            analysis.expected_gp_per_hour = int(analysis.confidence * max(0, current_profit) * trades_per_hour)

            results.append(analysis)

        results.sort(key=lambda a: a.expected_gp_per_hour, reverse=True)
        for a in results:
            a.rs_score = a.confidence * 100
        return results


@dataclass
class ProcessScanner:
    """Materials processing: buy inputs, process, sell output.

    The closest analog is AlchScanner — each recipe converts inputs into
    an output. Inputs are bought at their instant-buy price (no tax on
    buys); the output is sold at its instant-sell price with GE tax on
    that leg only. Throughput is capped by the action rate, the OUTPUT's
    buy limit / volume (the sell side consumes the output's 4h limit),
    and the limiting input's 4h buy-limit capacity (the min-ratio problem).
    """

    recipes: dict[int, Recipe] = field(default_factory=lambda: RECIPES)

    def scan(self, items: list[Item], *, members_only: bool = False,
             min_volume: int = 0, min_profit: int = 0,
             capital: int = 0) -> list[Item]:
        """Rank recipes by GP/hr. Returns new Items, never mutates input."""
        lookup = {i.id: i for i in items}
        results: list[Item] = []
        for recipe in self.recipes.values():
            output = lookup.get(recipe.output_id)
            if output is None:
                continue
            comps = [lookup.get(iid) for iid in recipe.inputs]
            if any(c is None for c in comps):
                continue
            comps = [c for c in comps if c is not None]  # type: ignore[assignment]
            if members_only and (output.members or any(c.members for c in comps)):
                continue
            if output.volume < min_volume:
                continue
            # Price sanity: skip if any component's price is unusable.
            if any(c.buy_price <= 0 or c.sell_price <= 0 for c in comps):
                continue
            if output.sell_price <= 0 or output.buy_price <= 0:
                continue

            input_cost = sum(c.buy_price * qty
                             for c, qty in zip(comps, recipe.inputs.values()))
            # Batch recipes (e.g. 15 shafts + 15 tips -> 15 arrows): cost is
            # per RUN; per-output-unit cost divides by outputs_per_run.
            per_unit_cost = input_cost / recipe.outputs_per_run
            output_gp = output.sell_price - ge_tax(output.sell_price)
            profit = int(output_gp - per_unit_cost - recipe.cost_per_unit)
            if profit <= 0 or profit < min_profit:
                continue

            # Throughput: the output's 4h buy limit / 4 (hourly) caps the
            # sell side; the market volume*12 caps absorb; the limiting
            # input's buy-limit capacity caps feed. min-ratio problem.
            # Batch: each run consumes the per-run input qty and produces
            # outputs_per_run units, so runs/hr = min(input feed // qty).
            output_rate = output.buy_limit / 4 if output.buy_limit > 0 else 0
            volume_rate = output.volume * 12
            runs_by_input = [
                (c.buy_limit / 4) // qty
                for c, qty in zip(comps, recipe.inputs.values())
                if c.buy_limit > 0
            ]
            input_capacity = min(runs_by_input) if runs_by_input else 0
            runs_per_hour = int(min(
                recipe.rate_per_hour, output_rate / recipe.outputs_per_run,
                volume_rate / recipe.outputs_per_run, input_capacity))
            outputs_per_hour = runs_per_hour * recipe.outputs_per_run
            if outputs_per_hour <= 0:
                continue

            # Capital cap: scale throughput by how many units the budget buys.
            if capital > 0 and input_cost > 0:
                by_capital = (capital // input_cost) * recipe.outputs_per_run
                outputs_per_hour = min(outputs_per_hour, by_capital)

            gp_per_hour = int(profit * outputs_per_hour)
            results.append(Item(
                id=output.id, name=output.name, members=output.members,
                buy_limit=output.buy_limit, alch_value=output.alch_value,
                buy_price=output.buy_price, sell_price=output.sell_price,
                volume=output.volume, profit=profit, gp_per_hour=gp_per_hour,
                input_cost=int(per_unit_cost), output_id=recipe.output_id,
            ))

        results.sort(key=lambda i: i.gp_per_hour, reverse=True)
        compute_rs_score_alch(results)
        return results
