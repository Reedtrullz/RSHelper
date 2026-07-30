"""Alch-profit and flip-margin scanner — core calculation engine."""

from typing import Any
from dataclasses import dataclass
from rshelper.models import Item
from rshelper.analysis import analyze_timeseries, MarginAnalysis
from rshelper.signals import compute_rs_score_flip, compute_rs_score_alch

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
def _safe_int(val: Any, default: int = 0) -> int:
    """Convert a value to int safely, handling strings and None."""
    if val is None:
        return default
    try:
        return int(float(val))  # float first handles "500.0" strings
    except (ValueError, TypeError):
        return default
def build_items_from_api(
    mapping: list[dict],
    latest: dict[str, dict],
    volume_5m: dict[str, dict],
) -> list[Item]:
    """Merge API responses into Item list."""
    items: list[Item] = []
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
        buy_price = _safe_int(price.get("high"))
        sell_price = _safe_int(price.get("low"))
        volume = _safe_int(vol.get("highPriceVolume")) + _safe_int(vol.get("lowPriceVolume"))
        # Skip items with no price data (not traded or untradeable)
        if buy_price <= 0:
            continue
        items.append(Item(
            id=item_id,
            name=entry.get("name", ""),
            members=entry.get("members", False),
            buy_limit=_safe_int(entry.get("limit")),
            alch_value=_safe_int(entry.get("highalch")),
            buy_price=buy_price,
            sell_price=sell_price,
            volume=volume,
        ))
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
                raw_tax = int(item.sell_price * 0.02)
            else:  # traditional
                margin = item.buy_price - item.sell_price
                raw_tax = int(item.buy_price * 0.02)
            tax = min(5_000_000, max(1, raw_tax))

            if margin < min_margin:
                continue
            if item.buy_limit <= 0:
                continue
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
                raw_tax = int(item.sell_price * 0.02)
                tax = min(5_000_000, max(1, raw_tax))
                margin = item.sell_price - item.buy_price
            else:
                raw_tax = int(item.buy_price * 0.02)
                tax = min(5_000_000, max(1, raw_tax))
                margin = item.buy_price - item.sell_price
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
