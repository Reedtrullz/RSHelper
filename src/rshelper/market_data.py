"""Typed provenance attached to market data at acquisition boundaries."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MarketDataResult:
    """Market payload plus explicit source, delivery, freshness and coverage."""

    data: Any
    source: str
    delivery: str
    fetched_at: float | None
    last_attempt_at: float | None
    last_success_at: float | None
    stale: bool
    volume_kind: str
    coverage: dict[str, int]
