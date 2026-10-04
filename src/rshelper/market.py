"""Shared GE market-data rules: tax, price sanity, manipulation guards.

Both the OSRS Wiki API (last-executed trade prices) and the GE Tracker
fallback (standing offer prices) feed the same merge point, so these rules
live here instead of being re-derived per source.
"""

import time
import math
from decimal import Decimal, InvalidOperation
from typing import Any

# ponytail: hardcoded thresholds. Add config knobs if a user ever
# legitimately trades items with >20x bid/ask gaps or >24h-old ticks.
STALE_PRICE_AGE = 24 * 3600
MAX_PRICE_RATIO = 20

GE_TAX_CAP = 5_000_000
FUTURE_QUOTE_TOLERANCE = 60  # Explicit engineering allowance for clock skew.


def safe_int(value: Any, default: int = 0) -> int:
    """Convert a value to int safely, handling strings and None."""
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    try:
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                if not math.isfinite(float(value)):
                    return default
                return int(Decimal(value))
        return int(value)
    except (ValueError, TypeError, OverflowError, InvalidOperation):
        return default


def quote_time_issue(timestamp: object, now: float, future_tolerance: float = FUTURE_QUOTE_TOLERANCE) -> str | None:
    """A quote may lead the local clock by at most the engineering skew limit."""
    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
        return "invalid"
    if (isinstance(timestamp, float) and not math.isfinite(timestamp)) or timestamp <= 0:
        return "invalid"
    if timestamp > now + future_tolerance:
        return "future"
    return None


def ge_tax(sell_price: int) -> int:
    """Per-item GE tax: 2% of the sale price, rounded down, capped at 5M.

    Wiki (Grand Exchange page): the 2% tax rounds down to the nearest whole
    number, so items sold below 50 coins have no tax obligation. Integer
    math avoids float rounding error.
    """
    if sell_price <= 0:
        return 0
    return min(GE_TAX_CAP, sell_price * 2 // 100)


def price_issue(price: dict, *, now: float | None = None) -> str | None:
    """Return a reason a latest-price entry is unusable, else None.

    Reasons: 'no data' (missing/zero prices), 'stale' (a price leg older
    than STALE_PRICE_AGE or without a timestamp), 'depth' (zero standing
    offer quantity on one side, GE Tracker only), 'ratio' (>20x gap between
    instant buy and instant sell, a price-manipulation artifact).
    """
    buy = safe_int(price.get("high"))
    sell = safe_int(price.get("low"))
    if buy <= 0 or sell <= 0:
        return "no data"
    high_time = price.get("highTime")
    low_time = price.get("lowTime")
    current = now if now is not None else time.time()
    for timestamp in (high_time, low_time):
        issue = quote_time_issue(timestamp, current)
        if issue:
            return "future" if issue == "future" else "stale"
    age = current - min(high_time, low_time)
    if age > STALE_PRICE_AGE:
        return "stale"
    if "high_volume" in price and (
        safe_int(price.get("high_volume")) <= 0 or safe_int(price.get("low_volume")) <= 0
    ):
        return "depth"
    if max(buy, sell) > MAX_PRICE_RATIO * min(buy, sell):
        return "ratio"
    return None
