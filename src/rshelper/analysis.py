"""Historical price analysis for margin confidence scoring."""

from dataclasses import dataclass
import math


@dataclass
class MarginAnalysis:
    """Result of analyzing an item's historical margins."""
    item_id: int
    avg_margin: float          # mean margin (gp) across windows
    margin_consistency: float  # fraction of windows where margin > 0 after tax
    current_vs_avg: float      # current_margin / avg_margin ratio
    margin_volatility: float   # CV of margins (stddev / |mean_buy|)
    avg_spread_pct: float      # avg margin / avg buy price as percentage
    avg_volume: float          # mean total volume per window
    confidence: float          # 0.0-1.0 composite = reliability * profitability
    reliability: float         # 0.0-1.0 margin pattern consistency
    profitability_score: float # 0.0-1.0 how profitable the margin is
    datapoints: int            # how many windows analyzed
    window_hours: float        # time span covered


def analyze_timeseries(
    item_id: int,
    datapoints: list[dict],
    current_buy: int,
    current_sell: int,
    tax_rate: float = 0.02,
) -> MarginAnalysis | None:
    """Analyze timeseries data to score margin reliability.

    datapoints: list of dicts from timeseries API, each with:
        avgHighPrice, avgLowPrice, highPriceVolume, lowPriceVolume, timestamp
    """
    if not datapoints or len(datapoints) < 6:
        return None

    margins: list[float] = []
    sell_prices: list[int] = []
    buy_prices: list[int] = []
    volumes: list[int] = []

    for dp in datapoints:
        high = dp.get("avgHighPrice")
        low = dp.get("avgLowPrice")
        if high is None or low is None:
            continue
        h = int(high)
        l = int(low)
        if h <= 0 or l <= 0:
            continue

        margin_raw = l - h  # following codebase convention: sell_price=low, buy_price=high
        tax = max(1, int(l * tax_rate))  # GE tax applies to all sales
        margin_after_tax = margin_raw - tax

        margins.append(margin_after_tax)
        sell_prices.append(l)
        buy_prices.append(h)

        vol_high = dp.get("highPriceVolume", 0) or 0
        vol_low = dp.get("lowPriceVolume", 0) or 0
        volumes.append(int(vol_high) + int(vol_low))

    if len(margins) < 6:
        return None

    avg_margin = sum(margins) / len(margins)
    positive_margins = sum(1 for m in margins if m > 0)
    margin_consistency = positive_margins / len(margins)

    avg_buy = sum(buy_prices) / len(buy_prices)

    # Current margin
    current_tax = max(1, int(current_sell * tax_rate))
    current_margin = current_sell - current_buy - current_tax
    current_vs_avg = (current_margin / avg_margin) if avg_margin != 0 else 0.0

    # Margin volatility (CV of margins, normalized by avg buy price)
    abs_mean_buy = abs(avg_buy) if avg_buy != 0 else 1
    margin_variance = sum((m - avg_margin) ** 2 for m in margins) / len(margins)
    margin_volatility = math.sqrt(margin_variance) / abs_mean_buy

    avg_spread_pct = (avg_margin / avg_buy * 100) if avg_buy > 0 else 0.0
    avg_volume = sum(volumes) / len(volumes)

    # Time span
    timestamps = [dp.get("timestamp", 0) for dp in datapoints if dp.get("timestamp")]
    if timestamps:
        window_hours = (max(timestamps) - min(timestamps)) / 3600
    else:
        window_hours = len(margins) * 5 / 60

    # Composite confidence score (0.0-1.0)
    vol_score = min(1.0, avg_volume / 50)
    volatility_score = max(0.0, 1.0 - margin_volatility * 20)
    spread_score = min(1.0, avg_spread_pct / 5.0)

    # Reliability: how consistent the margin pattern is (0-1)
    # Ignores profitability direction — a "reliable loser" still scores high here
    reliability = (
        0.40 * margin_consistency +
        0.20 * max(0.0, spread_score) +
        0.20 * vol_score +
        0.20 * volatility_score
    )

    # Profitability: shifted sigmoid — 0 at margin=0, rises toward 1 for positive margins
    # Scale factor: 250gp margin gives ~0.76 profitability, 500gp gives ~0.96
    try:
        raw_sigmoid = 1.0 / (1.0 + math.exp(-avg_margin / 125.0))
        profitability_score = max(0.0, 2.0 * raw_sigmoid - 1.0)
    except OverflowError:
        profitability_score = 1.0 if avg_margin > 0 else 0.0

    # Overall confidence = reliability * profitability
    # A "reliable loser" gets high reliability but confidence near 0
    confidence = max(0.0, min(1.0, reliability * profitability_score))

    return MarginAnalysis(
        item_id=item_id,
        avg_margin=avg_margin,
        margin_consistency=margin_consistency,
        current_vs_avg=current_vs_avg,
        margin_volatility=margin_volatility,
        avg_spread_pct=avg_spread_pct,
        avg_volume=avg_volume,
        confidence=confidence,
        reliability=reliability,
        profitability_score=profitability_score,
        datapoints=len(margins),
        window_hours=window_hours,
    )
