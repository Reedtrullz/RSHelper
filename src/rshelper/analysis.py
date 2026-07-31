"""Historical price analysis for margin confidence scoring."""

from dataclasses import dataclass
import math
from rshelper.market import MAX_PRICE_RATIO, ge_tax


@dataclass
class MarginAnalysis:
    """Result of analyzing an item's historical margins."""
    item_id: int
    avg_margin: float          # mean margin (gp) across windows
    margin_consistency: float  # fraction of windows where margin > 0 after tax
    current_vs_avg: float      # current_margin / avg_margin ratio
    margin_volatility: float   # CV of margins (stddev / |mean_margin|)
    avg_spread_pct: float      # avg margin / avg buy price as percentage
    avg_volume: float          # mean total volume per window
    confidence: float          # 0.0-1.0 composite = reliability * profitability * recency
    reliability: float         # 0.0-1.0 margin pattern consistency
    profitability_score: float # 0.0-1.0 ROI-based profitability
    datapoints: int            # how many windows analyzed
    window_hours: float        # time span covered
    spread_score: float = 0.0      # normalized spread sub-score
    volume_score: float = 0.0      # normalized volume sub-score
    volatility_score: float = 0.0  # normalized volatility sub-score
    roi: float = 0.0               # avg_margin / avg_buy as a ratio
    margin_trend: float = 0.0    # recent vs early margin ratio (>0 improving, <0 declining)
    rs_score: float = 0.0        # 0-100 composite score (= confidence * 100)
    current_profit: int = 0        # current margin after tax per item
    expected_gp_per_hour: int = 0  # confidence * current_profit * throughput


def analyze_timeseries(
    item_id: int,
    datapoints: list[dict],
    current_buy: int,
    current_sell: int,
    direction: str = "arbitrage",
) -> MarginAnalysis | None:
    """Analyze timeseries data to score margin reliability.

    direction: "arbitrage" uses sell-low minus buy-high; "traditional"
              uses buy-high minus sell-low minus tax (standard flip direction).

    datapoints: list of dicts from timeseries API, each with:
        avgHighPrice, avgLowPrice, highPriceVolume, lowPriceVolume, timestamp
    """
    if not datapoints or len(datapoints) < 6:
        return None

    margins: list[float] = []
    sell_prices: list[int] = []
    buy_prices: list[int] = []
    volumes: list[int] = []
    timestamps: list[int] = []

    for dp in datapoints:
        high = dp.get("avgHighPrice")
        low = dp.get("avgLowPrice")
        if high is None or low is None:
            continue
        h = int(high)
        l = int(low)
        if h <= 0 or l <= 0:
            continue
        # Skip manipulated windows: >20x gap between buy and sell averages.
        if max(h, l) > MAX_PRICE_RATIO * min(h, l):
            continue

        if direction == "arbitrage":
            margin_raw = l - h
            sell_price_for_tax = l
        else:
            margin_raw = h - l
            sell_price_for_tax = h  # traditional: sell at h (offer price)
        tax = ge_tax(sell_price_for_tax)
        margin_after_tax = margin_raw - tax

        margins.append(margin_after_tax)
        sell_prices.append(l)
        buy_prices.append(h)

        vol_high = dp.get("highPriceVolume", 0) or 0
        vol_low = dp.get("lowPriceVolume", 0) or 0
        volumes.append(int(vol_high) + int(vol_low))

        ts = dp.get("timestamp")
        if ts is not None:
            timestamps.append(int(ts))

    if len(margins) < 6:
        return None

    avg_margin = sum(margins) / len(margins)
    positive_margins = sum(1 for m in margins if m > 0)
    margin_consistency = positive_margins / len(margins)

    avg_buy = sum(buy_prices) / len(buy_prices)

    # Current margin — direction-aware with 5M tax cap
    if direction == "arbitrage":
        current_tax = ge_tax(current_sell)
        current_margin = current_sell - current_buy - current_tax
    else:
        current_tax = ge_tax(current_buy)  # traditional: sell at buy_price (h)
        current_margin = current_buy - current_sell - current_tax
    current_vs_avg = (current_margin / avg_margin) if avg_margin != 0 else 0.0

    # Margin volatility = CV of margins (normalized by avg margin, not buy price)
    # Sample variance (N-1) for small windows
    n = len(margins)
    margin_variance = sum((m - avg_margin) ** 2 for m in margins) / (n - 1) if n > 1 else 0.0
    abs_mean_margin = abs(avg_margin) if avg_margin != 0 else 1
    margin_cv = math.sqrt(max(0, margin_variance)) / abs_mean_margin

    avg_spread_pct = (avg_margin / avg_buy * 100) if avg_buy > 0 else 0.0
    avg_volume = sum(volumes) / len(volumes)
    roi = (avg_margin / avg_buy) if avg_buy > 0 else 0.0

    # Margin trend: compare recent quarter of windows vs oldest quarter
    # Positive = margins improving, negative = declining
    quarter = max(1, n // 4)
    recent_avg = sum(margins[-quarter:]) / quarter
    early_avg = sum(margins[:quarter]) / quarter
    if abs_mean_margin > 0:
        margin_trend = (recent_avg - early_avg) / abs_mean_margin
    else:
        margin_trend = 0.0

    # Time span (timestamps collected in loop above)
    if timestamps:
        window_hours = (max(timestamps) - min(timestamps)) / 3600
    else:
        window_hours = len(margins) * 5 / 60

    # Sub-scores
    vol_score = min(1.0, avg_volume / 50)
    # margin_cv of 2.0 (200%) → volatility_score = 0
    volatility_score = max(0.0, 1.0 - margin_cv * 0.5)
    spread_score = min(1.0, avg_spread_pct / 5.0)

    # Reliability: how consistent the margin pattern is (0-1)
    # Ignores profitability direction — a "reliable loser" still scores high here
    reliability = (
        0.40 * margin_consistency +
        0.15 * max(0.0, spread_score) +
        0.20 * vol_score +
        0.25 * volatility_score
    )

    # Profitability: blend of historical and current ROI-based sigmoids
    # Historical ROI captures the long-term pattern
    # Current ROI captures the immediate opportunity size
    # ~0.2% ROI → 0.46 profitability, ~1% ROI → 0.99 profitability
    try:
        # Historical ROI profitability
        hist_scaled = roi * 500
        hist_raw = 1.0 / (1.0 + math.exp(-hist_scaled))
        hist_profit = max(0.0, 2.0 * hist_raw - 1.0)

        # Current ROI profitability
        current_roi = (current_margin / avg_buy) if avg_buy > 0 else 0.0
        curr_scaled = current_roi * 500
        curr_raw = 1.0 / (1.0 + math.exp(-curr_scaled))
        curr_profit = max(0.0, 2.0 * curr_raw - 1.0)

        # Blend: 60% historical pattern, 40% current opportunity
        profitability_score = 0.6 * hist_profit + 0.4 * curr_profit
        profitability_score = max(0.0, min(1.0, profitability_score))
    except OverflowError:
        profitability_score = 1.0 if avg_margin > 0 else 0.0
    # Recency modifier: current opportunity vs historical average
    # current_vs_avg < 1 → penalty; > 1 → bonus
    dampened_current = min(2.0, max(0.0, current_vs_avg))
    recency_modifier = 0.5 + 0.5 * dampened_current

    # Confidence = reliability * profitability * recency * trend
    trend_modifier = 1.0 + max(-0.5, min(0.5, margin_trend * 0.5))
    confidence = reliability * profitability_score * recency_modifier * trend_modifier
    confidence = max(0.0, min(1.0, confidence))

    return MarginAnalysis(
        item_id=item_id,
        avg_margin=avg_margin,
        margin_consistency=margin_consistency,
        current_vs_avg=current_vs_avg,
        margin_volatility=margin_cv,
        avg_spread_pct=avg_spread_pct,
        avg_volume=avg_volume,
        confidence=confidence,
        reliability=reliability,
        profitability_score=profitability_score,
        datapoints=len(margins),
        window_hours=window_hours,
        spread_score=spread_score,
        volume_score=vol_score,
        volatility_score=volatility_score,
        roi=roi,
        margin_trend=margin_trend,
    )
