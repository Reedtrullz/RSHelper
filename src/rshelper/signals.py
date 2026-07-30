"""Signal detection engine for market events: DUMP, CRASH, SURGE, FLIP."""

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from rshelper.models import Item

from rshelper.profile import resolve_config_path
COOLDOWN_DIR = resolve_config_path("")
COOLDOWN_PATH = resolve_config_path("signal_cooldowns.json")

# Thresholds
DUMP_THRESHOLD = 0.10   # 10% below 5m average = DUMP
CRASH_THRESHOLD = 0.20  # 20% below 5m average = CRASH
SURGE_MULTIPLIER = 3.0  # 3x baseline volume = SURGE
FLIP_SPREAD_MIN = 0.05  # 5% spread of buy price
FLIP_VOLUME_MIN = 500   # minimum total volume for a FLIP signal
STALE_MINUTES = 30      # data older than this = STALE
DEFAULT_COOLDOWN = 15 * 60  # 15 minutes in seconds


@dataclass
class Signal:
    type: str       # "DUMP" | "CRASH" | "SURGE" | "FLIP" | "STALE"
    item_id: int
    name: str
    severity: str   # "HIGH" | "MEDIUM" | "LOW"
    current_price: int
    deviation: float  # percentage (e.g. -14.3 for 14.3% drop)
    message: str


def _load_cooldowns() -> dict:
    COOLDOWN_DIR.mkdir(parents=True, exist_ok=True)
    try:
        if COOLDOWN_PATH.exists():
            return json.loads(COOLDOWN_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _save_cooldowns(data: dict) -> None:
    COOLDOWN_DIR.mkdir(parents=True, exist_ok=True)
    tmp = COOLDOWN_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, COOLDOWN_PATH)


def _cooldown_key(item_id: int, signal_type: str) -> str:
    return f"{item_id}:{signal_type}"


def _is_cooling(item_id: int, signal_type: str, cooldown_sec: int) -> bool:
    cooldowns = _load_cooldowns()
    key = _cooldown_key(item_id, signal_type)
    last = cooldowns.get(key, 0)
    return (time.time() - last) < cooldown_sec


def _set_cooldown(item_id: int, signal_type: str) -> None:
    cooldowns = _load_cooldowns()
    key = _cooldown_key(item_id, signal_type)
    cooldowns[key] = time.time()
    _save_cooldowns(cooldowns)


def detect_signals(
    items: list[Item],
    volume_5m: dict[str, dict],
    cooldown_sec: int = DEFAULT_COOLDOWN,
) -> list[Signal]:
    """Scan items for DUMP, CRASH, SURGE, and FLIP signals.

    Uses 5-minute average prices from volume_5m as baseline for comparison.
    Returns only new signals (not currently on cooldown).
    """
    signals: list[Signal] = []

    for item in items:
        # Skip items without price data
        if item.buy_price <= 0 or item.sell_price <= 0:
            continue

        vol_data = volume_5m.get(str(item.id))
        if not isinstance(vol_data, dict):
            vol_data = {}

        avg_high = vol_data.get("avgHighPrice", item.buy_price) or item.buy_price
        avg_low = vol_data.get("avgLowPrice", item.sell_price) or item.sell_price
        five_min_vol = (vol_data.get("highPriceVolume", 0) or 0) + (vol_data.get("lowPriceVolume", 0) or 0)

        # DUMP: sell price >10% below 5m average sell price, with some volume
        if avg_low > 0 and five_min_vol >= 100:
            drop = (item.sell_price - avg_low) / avg_low
            if drop <= -CRASH_THRESHOLD:
                if not _is_cooling(item.id, "CRASH", cooldown_sec):
                    signals.append(Signal(
                        type="CRASH", item_id=item.id, name=item.name,
                        severity="HIGH", current_price=item.sell_price,
                        deviation=round(drop * 100, 1),
                        message=f"{item.name}: {drop*100:+.1f}% vs 5m avg (sell price)",
                    ))
                    _set_cooldown(item.id, "CRASH")
            elif drop <= -DUMP_THRESHOLD:
                if not _is_cooling(item.id, "DUMP", cooldown_sec):
                    signals.append(Signal(
                        type="DUMP", item_id=item.id, name=item.name,
                        severity="MEDIUM", current_price=item.sell_price,
                        deviation=round(drop * 100, 1),
                        message=f"{item.name}: {drop*100:+.1f}% vs 5m avg (sell price)",
                    ))
                    _set_cooldown(item.id, "DUMP")

        # SURGE: 5m volume > 3x normal. Use items average volume as baseline.
        # Normal is proxied by the item's volume field (which IS the 5m volume from /5m).
        # SURGE triggers when current 5m vol > 3x the stored average.
        item_vol = item.volume if item.volume > 0 else 1
        if five_min_vol > item_vol * SURGE_MULTIPLIER:
            if not _is_cooling(item.id, "SURGE", cooldown_sec):
                signals.append(Signal(
                    type="SURGE", item_id=item.id, name=item.name,
                    severity="MEDIUM", current_price=item.buy_price,
                    deviation=round(five_min_vol / max(1, item_vol), 1),
                    message=f"{item.name}: {five_min_vol} volume (normal: ~{item_vol})",
                ))
                _set_cooldown(item.id, "SURGE")

        # FLIP: spread > 5% of buy price, with sufficient volume
        if item.buy_price > 0:
            spread_pct = (item.buy_price - item.sell_price) / item.buy_price
            if spread_pct >= FLIP_SPREAD_MIN and five_min_vol >= FLIP_VOLUME_MIN:
                # Severity based on RS Score
                if item.rs_score >= 70:
                    sev = "HIGH"
                elif item.rs_score >= 40:
                    sev = "MEDIUM"
                else:
                    sev = "LOW"
                if not _is_cooling(item.id, "FLIP", cooldown_sec):
                    signals.append(Signal(
                        type="FLIP", item_id=item.id, name=item.name,
                        severity=sev, current_price=item.buy_price,
                        deviation=round(spread_pct * 100, 1),
                        message=f"{item.name}: {spread_pct*100:.1f}% spread, RS={item.rs_score:.0f}",
                    ))
                    _set_cooldown(item.id, "FLIP")

    # Sort: HIGH severity first, then by type
    severity_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    signals.sort(key=lambda s: (severity_order.get(s.severity, 3), s.type, s.name))
    return signals


def compute_rs_score_flip(item: Item, max_volume: int) -> float:
    """Compute RS Score (0-100) for a flip-scan Item.

    Volume (40%) + spread quality (30%) + market depth (20%) + freshness (10%).
    """
    # Volume score: relative to max in scan results
    vol_score = min(1.0, item.volume / max(1, max_volume)) if max_volume > 0 else 0.5

    # Spread quality: profit as % of buy price, normalized to 5% = full score
    if item.buy_price > 0:
        spread_pct = item.profit / item.buy_price * 100
        spread_score = min(1.0, spread_pct / 5.0)
    else:
        spread_score = 0.0

    # Market depth: higher buy limits = more stable market
    depth_score = min(1.0, item.buy_limit / 10000)

    # Freshness: constant 10% bonus (prices are live from API)
    rs = vol_score * 40 + spread_score * 30 + depth_score * 20 + 10
    return max(0.0, min(100.0, rs))


def compute_rs_score_alch(results: list[Item]) -> None:
    """Mutate results in-place: set rs_score to percentile rank of gp_per_hour."""
    if not results:
        return
    n = len(results)
    for i, item in enumerate(results):
        # Rank 0 = best (highest gp_per_hour), rank n-1 = worst
        percentile = (n - 1 - i) / max(1, n - 1) * 100 if n > 1 else 50.0
        item.rs_score = round(percentile, 1)
