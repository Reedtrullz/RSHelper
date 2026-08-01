"""Signal detection engine for market events: DUMP, CRASH, SURGE, FLIP."""

import json
import os
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from rshelper.models import Item

from rshelper.profile import resolve_config_path
COOLDOWN_DIR = resolve_config_path("")
COOLDOWN_PATH = resolve_config_path("signal_cooldowns.json")
BASELINE_PATH = resolve_config_path("volume_baseline.json")

# Thresholds
DUMP_THRESHOLD = 0.10   # 10% below 5m average = DUMP
CRASH_THRESHOLD = 0.20  # 20% below 5m average = CRASH
SURGE_MULTIPLIER = 3.0  # 3x baseline volume = SURGE
SURGE_VOLUME_MIN = 100  # ignore tiny-volume noise
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
    fd, tmp = tempfile.mkstemp(dir=COOLDOWN_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.replace(tmp, COOLDOWN_PATH)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _cooldown_key(item_id: int, signal_type: str) -> str:
    return f"{item_id}:{signal_type}"


def _is_cooling(item_id: int, signal_type: str, cooldown_sec: int,
                  cooldowns: dict | None = None) -> bool:
    if cooldowns is None:
        cooldowns = _load_cooldowns()
    key = _cooldown_key(item_id, signal_type)
    last = cooldowns.get(key, 0)
    return (time.time() - last) < cooldown_sec


def _set_cooldown(item_id: int, signal_type: str,
                  cooldowns: dict | None = None) -> None:
    if cooldowns is None:
        cooldowns = _load_cooldowns()
    key = _cooldown_key(item_id, signal_type)
    cooldowns[key] = time.time()


def _persist_cooldowns(cooldowns: dict) -> None:
    """Best-effort cooldown save; a failure must not kill the scan cycle.

    Cooldowns are saved right after each signal fires so a later disk error
    cannot erase earlier cooldowns (which would re-fire the same alerts next
    cycle). A failed save is loud on stderr, never silent.
    """
    try:
        _save_cooldowns(cooldowns)
    except OSError as exc:
        print(f"[signals] warning: could not persist cooldowns: {exc}",
              file=sys.stderr)


def _load_baselines() -> dict[str, float]:
    COOLDOWN_DIR.mkdir(parents=True, exist_ok=True)
    try:
        if BASELINE_PATH.exists():
            return json.loads(BASELINE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _save_baselines(data: dict) -> None:
    COOLDOWN_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=COOLDOWN_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.replace(tmp, BASELINE_PATH)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _update_baseline(baselines: dict, item_id: int, current: int) -> float:
    """Rolling EMA baseline so a single snapshot has no 'normal' to compare."""
    key = str(item_id)
    prev = baselines.get(key)
    if prev is None or prev <= 0:
        baseline = float(current)
    else:
        # ponytail: alpha=0.3 spikes pull the baseline up fast, damping future
        # surges; make alpha configurable if surge sensitivity needs tuning
        baseline = 0.7 * prev + 0.3 * current
    baselines[key] = baseline
    return prev if (prev is not None and prev > 0) else 0.0


def detect_signals(
    items: list[Item],
    volume_5m: dict[str, dict],
    cooldown_sec: int = DEFAULT_COOLDOWN,
    flip_ids: set[int] | None = None,
) -> list[Signal]:
    """Scan items for DUMP, CRASH, SURGE, and FLIP signals.

    Uses 5-minute average prices from volume_5m as baseline for comparison.
    Returns only new signals (not currently on cooldown).

    flip_ids restricts FLIP detection to the given item ids (the monitor's
    scanned flip candidates, which carry an RS score). DUMP/CRASH/SURGE are
    always evaluated over the full item universe so market events on
    non-flip items are not silently missed. None keeps the historical
    behavior of scanning everything for every signal type.
    """
    signals: list[Signal] = []
    cooldowns = _load_cooldowns()  # load once for entire scan
    baselines = _load_baselines()

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
        # Real 5m averages/volumes are wiki-only; the GE Tracker fallback only
        # carries offer quantities, which would produce misleading signals.
        # FLIP is gated too: its liquidity test reads five_min_vol, which is
        # offer quantity on the fallback, not executed trade volume.
        has_real_5m = "avgHighPrice" in vol_data or "avgLowPrice" in vol_data

        # DUMP: sell price >10% below 5m average sell price, with some volume
        if has_real_5m and avg_low > 0 and five_min_vol >= 100:
            drop = (item.sell_price - avg_low) / avg_low
            if drop <= -CRASH_THRESHOLD:
                if not _is_cooling(item.id, "CRASH", cooldown_sec, cooldowns):
                    signals.append(Signal(
                        type="CRASH", item_id=item.id, name=item.name,
                        severity="HIGH", current_price=item.sell_price,
                        deviation=round(drop * 100, 1),
                        message=f"{item.name}: {drop*100:+.1f}% vs 5m avg (sell price)",
                    ))
                    _set_cooldown(item.id, "CRASH", cooldowns)
                    _persist_cooldowns(cooldowns)
            elif drop <= -DUMP_THRESHOLD:
                if not _is_cooling(item.id, "DUMP", cooldown_sec, cooldowns):
                    signals.append(Signal(
                        type="DUMP", item_id=item.id, name=item.name,
                        severity="MEDIUM", current_price=item.sell_price,
                        deviation=round(drop * 100, 1),
                        message=f"{item.name}: {drop*100:+.1f}% vs 5m avg (sell price)",
                    ))
                    _set_cooldown(item.id, "DUMP", cooldowns)
                    _persist_cooldowns(cooldowns)

        # SURGE: 5m volume > 3x the rolling baseline (persisted across scans).
        # A single snapshot has no 'normal', so the baseline seeds from the
        # first observation and adapts via EMA; SURGE needs monitor-style
        # polling history to be meaningful.
        if has_real_5m and five_min_vol >= SURGE_VOLUME_MIN:
            prev = _update_baseline(baselines, item.id, five_min_vol)
            surge_ok = prev > 0 and five_min_vol > prev * SURGE_MULTIPLIER
            if surge_ok and not _is_cooling(item.id, "SURGE", cooldown_sec, cooldowns):
                # deviation is a percentage like the other signal types
                # (e.g. 220.0 for 3.2x baseline), not a raw multiplier.
                signals.append(Signal(
                    type="SURGE", item_id=item.id, name=item.name,
                    severity="MEDIUM", current_price=item.buy_price,
                    deviation=round((five_min_vol / max(1.0, prev) - 1) * 100, 1),
                    message=f"{item.name}: {five_min_vol} volume (normal: ~{prev:.0f})",
                ))
                _set_cooldown(item.id, "SURGE", cooldowns)
                _persist_cooldowns(cooldowns)

        # FLIP: spread > 5% of buy price, with sufficient volume
        if (flip_ids is None or item.id in flip_ids) and has_real_5m \
                and item.buy_price > 0:
            spread_pct = (item.buy_price - item.sell_price) / item.buy_price
            if spread_pct >= FLIP_SPREAD_MIN and five_min_vol >= FLIP_VOLUME_MIN:
                # Severity based on RS Score
                if item.rs_score >= 70:
                    sev = "HIGH"
                elif item.rs_score >= 40:
                    sev = "MEDIUM"
                else:
                    sev = "LOW"
                if not _is_cooling(item.id, "FLIP", cooldown_sec, cooldowns):
                    signals.append(Signal(
                        type="FLIP", item_id=item.id, name=item.name,
                        severity=sev, current_price=item.buy_price,
                        deviation=round(spread_pct * 100, 1),
                        message=f"{item.name}: {spread_pct*100:.1f}% spread, RS={item.rs_score:.0f}",
                    ))
                    _set_cooldown(item.id, "FLIP", cooldowns)
                    _persist_cooldowns(cooldowns)

    _persist_cooldowns(cooldowns)  # final best-effort flush
    try:
        _save_baselines(baselines)
    except OSError as exc:
        print(f"[signals] warning: could not persist volume baselines: {exc}",
              file=sys.stderr)

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
    # Percentile rank is positional, so the input must be sorted by
    # gp_per_hour descending; sort defensively so a mis-ordered caller
    # cannot silently produce wrong scores.
    results.sort(key=lambda i: i.gp_per_hour, reverse=True)
    n = len(results)
    for i, item in enumerate(results):
        # Rank 0 = best (highest gp_per_hour), rank n-1 = worst
        percentile = (n - 1 - i) / max(1, n - 1) * 100 if n > 1 else 50.0
        item.rs_score = round(percentile, 1)
