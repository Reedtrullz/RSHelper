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


class MarketDict(dict):
    """Mapping view that retains acquisition evidence through existing consumers."""

    def copy(self):
        view = type(self)(self)
        view.market_data = getattr(self, 'market_data', None)
        return view


class MarketList(list):
    """Sequence view that retains acquisition evidence through existing consumers."""


def market_payload(result, *, sequence=False):
    """Expose data with evidence; raw legacy fixtures stay explicitly unknown."""
    if isinstance(result, (MarketDict, MarketList)):
        return result
    evidence = result if isinstance(result, MarketDataResult) else None
    data = evidence.data if evidence is not None else result
    if data is None:
        data = [] if sequence else {}
    if isinstance(data, dict):
        view = MarketDict(data)
    elif isinstance(data, list):
        view = MarketList(data)
    else:
        raise ValueError('market data must be a mapping or sequence')
    view.market_data = evidence
    return view


def provenance(value) -> dict:
    """No provider or timestamp is inferred from payload keys or file mtimes."""
    result = value if isinstance(value, MarketDataResult) else getattr(value, 'market_data', None)
    if not isinstance(result, MarketDataResult):
        return {'source':'unknown','delivery':'unknown','fetched_at':None,
                'last_attempt_at':None,'last_success_at':None,'stale':True,
                'volume_kind':'unknown','coverage':{}}
    return {'source':result.source,'delivery':result.delivery,
            'fetched_at':result.fetched_at,'last_attempt_at':result.last_attempt_at,
            'last_success_at':result.last_success_at,'stale':result.stale,
            'volume_kind':result.volume_kind,'coverage':dict(result.coverage)}


def executed_volume_supported(value) -> bool:
    meta = provenance(value)
    return (meta['source'] == 'wiki' and meta['volume_kind'] == 'executed-trades'
            and not meta['stale'])


def market_snapshot(mapping, latest, volume) -> dict:
    return {'mapping':provenance(mapping),'latest':provenance(latest),'5m':provenance(volume)}
