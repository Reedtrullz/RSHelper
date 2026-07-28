"""Alch-profit scanner — core calculation engine."""

from dataclasses import dataclass
from rshelper.models import Item

MAX_CASTS_PER_HOUR = 1200  # 5-tick cast speed
MAX_CASTS_PER_4H = MAX_CASTS_PER_HOUR * 4  # 4800


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
        """Calculate profit and GP/hr for each item, return profitable ones sorted descending."""
        results: list[Item] = []
        for item in items:
            if members_only and not item.members:
                continue
            if item.volume < min_volume:
                continue
            item.profit = item.alch_value - item.buy_price - self.nature_rune_cost
            if item.profit <= 0:
                continue
            # GP/hr: capped by buy limit and volume
            max_casts_4h = min(item.buy_limit, MAX_CASTS_PER_4H)
            casts_per_hour = max_casts_4h / 4
            # Volume correction: if item trades too little to sustain the buy limit
            if item.volume < (6 * item.buy_limit) and item.volume < 28800:
                casts_per_hour = item.volume / 24
            item.gp_per_hour = int(item.profit * casts_per_hour)
            results.append(item)
        results.sort(key=lambda i: i.gp_per_hour, reverse=True)
        return results


def build_items_from_api(
    mapping: list[dict],
    latest: dict[str, dict],
    volume_5m: dict[str, dict],
) -> list[Item]:
    """Merge API responses into Item list."""
    items: list[Item] = []
    for entry in mapping:
        item_id = entry["id"]
        price = latest.get(str(item_id), {})
        vol = volume_5m.get(str(item_id), {})
        buy_price = price.get("high", 0)
        sell_price = price.get("low", 0)
        volume = vol.get("avgQuantity", 0) if isinstance(vol, dict) else 0
        # Skip items with no price data (not traded or untradeable)
        if buy_price <= 0:
            continue
        items.append(Item(
            id=item_id,
            name=entry.get("name", ""),
            members=entry.get("members", False),
            buy_limit=entry.get("limit", 0),
            alch_value=entry.get("highalch", 0),
            buy_price=buy_price,
            sell_price=sell_price,
            volume=int(volume),
        ))
    return items
