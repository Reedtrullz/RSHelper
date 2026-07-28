"""Alch-profit and flip-margin scanner — core calculation engine."""

from typing import Any
from dataclasses import dataclass
from rshelper.models import Item
from rshelper.analysis import analyze_timeseries, MarginAnalysis

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

    def __post_init__(self):
        if self.direction not in ("arbitrage", "traditional"):
            raise ValueError(f"direction must be 'arbitrage' or 'traditional', got '{self.direction}'")

    def scan(
        self,
        items: list[Item],
        *,
        members_only: bool = False,
        min_volume: int = 0,
        min_margin: int = 0,
    ) -> list[Item]:
        """Calculate flip margin and GP/hr, return sorted by gp_per_hour descending."""
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
                tax = max(1, int(item.sell_price * 0.02))
            else:  # traditional
                margin = item.buy_price - item.sell_price
                tax = max(1, int(item.buy_price * 0.02))

            if margin < min_margin:
                continue
            if item.buy_limit <= 0:
                continue
            profit = margin - tax
            if profit <= 0:
                continue
            # ponytail: /2 for buy+sell round-trip; revisit if GE slots need modeling
            trades_per_hour = min(
                item.buy_limit / 4,
                item.volume * 12,
            )
            gp_per_hour = int(profit * trades_per_hour / 2)
            result = Item(
                id=item.id, name=item.name, members=item.members,
                buy_limit=item.buy_limit, alch_value=item.alch_value,
                buy_price=item.buy_price, sell_price=item.sell_price,
                volume=item.volume, profit=profit, gp_per_hour=gp_per_hour,
            )
            results.append(result)
        results.sort(key=lambda i: i.gp_per_hour, reverse=True)
        return results




class MarginScanner:
    """Scan top flip candidates for historical margin reliability."""

    def scan(
        self,
        lookup: dict[int, Item],  # item_id -> Item (name, buy_price, sell_price, etc)
        timeseries_data: dict[int, list[dict]],
        *,
        members_only: bool = False,
    ) -> list[MarginAnalysis]:
        """Analyze timeseries data for each item and return confidence-ranked results."""
        results: list[MarginAnalysis] = []
        for item_id, ts_data in timeseries_data.items():
            item = lookup.get(item_id)
            if item is None:
                continue
            if members_only and not item.members:
                continue
            analysis = analyze_timeseries(
                item_id, ts_data,
                current_buy=item.buy_price,
                current_sell=item.sell_price,
            )
            if analysis is not None:
                results.append(analysis)
        results.sort(key=lambda a: a.confidence, reverse=True)
        return results
