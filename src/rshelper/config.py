"""Configuration loading from ~/.config/rshelper/config.toml."""


import tomllib
import math
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from rshelper.profile import atomic_write_text, resolve_config_path

CONFIG_DIR = Path.home() / ".config" / "rshelper"

DEFAULT_CONFIG_TOML = """\
# RSHelper configuration — edit defaults for your trading style.

[alch]
nature_rune_cost = 0        # 0 = auto-fetch from API
members_only = false
min_volume = 0
top = 50

[flip]
direction = "arbitrage"     # "arbitrage" or "traditional"
members_only = false
min_volume = 10
min_margin = 0
top = 50

[margin]
direction = "arbitrage"
members_only = false
min_volume = 10
min_margin = 0
check = 20
top = 20

[process]
members_only = false
min_volume = 0
min_profit = 0
top = 20
capital = 0

[trader]
capital = 1000000        # paper bankroll for sizing auto-trades
trade_capital_frac = 0.40  # fraction of bankroll per position (replay: 0.40
                         # adds +25% absolute profit at same 98.9% win / dd)
max_positions = 3        # concurrent auto positions
min_volume = 800         # 5m executed volume floor (fill plausibility)
min_price = 25           # skip sub-25gp items: 1gp tick > 2% stop distance
max_spread_ratio = 5.0   # max buy/sell gap for entries
dip_depth_pct = 2.5      # buy when sell is >=2.5% below the 5m average (replay: 2.5% doubles trade count vs 3% at same 99.5% win)
max_dip_pct = 10.0       # don't catch deeper freefalls than this
min_spread_pct = 3.5     # spread must exceed the 2% GE tax + buffer (replay: 3.5% unlocks the 3.5-4% band, +95% absolute profit at same risk)
max_entry_spread_pct = 5.75  # high/low gap cap (replay: 5.75 adds +34% profit at same 99.6% win / dd; 6.0+ brings the first losing item)
reentry_minutes = 30     # wait before re-entering an item after an auto close
stop_reentry_minutes = 90  # wait before re-entering an item after a stop-loss
take_profit_pct = 3.0    # close when net (after tax) >= this %
stop_loss_pct = -2.0     # close when the bid falls this % below the stop mark (replay: -1.5% stops too early)
stop_grace_minutes = 20  # stop-loss grace period after entry: a buy-the-dip
                         # entry needs time to revert before the stop arms
                         # (replay: grace=20 is the ROI sweet spot)
max_hold_minutes = 180   # force-close after this long
spread_collapse_exit_minutes = 60  # after this long, exit when the edge is gone
interval_sec = 120       # poll cycle (seconds); fast stops limit crash gaps
artifact_min_low_vol = 20  # below this, low-price volume is a thin print
artifact_low_vol_frac = 0.10  # low-price volume must be >= this share of the window
artifact_outlier_pct = 5.0  # bid more than this % below the 5m avg is an outlier
stop_slippage = 0.97      # stop-loss fill degradation (1.0 = fill at the bid)
# Stop-loss reference mark for dip entries. The entry bid can sit up to
# max_dip_pct below the 5m avgLowPrice, so a stop measured purely from the
# entry bid can fire on the very dip the strategy was designed to buy.
# 0.0 = stop from the entry bid (legacy behavior); 1.0 = stop from the 5m
# avgLowPrice at entry (full dip allowance). Values in between blend the
# two: mark = entry_bid + stop_mark_blend * (avg_low - entry_bid).
stop_mark_blend = 0.0    # 0.0 = legacy (stop from entry bid)
"""


@dataclass
class AlchConfig:
    nature_rune_cost: int = 0
    members_only: bool = False
    min_volume: int = 0
    top: int = 50


@dataclass
class FlipConfig:
    direction: str = "arbitrage"
    members_only: bool = False
    min_volume: int = 10
    min_margin: int = 0
    top: int = 50


@dataclass
class MarginConfig:
    direction: str = "arbitrage"
    members_only: bool = False
    min_volume: int = 10
    min_margin: int = 0
    check: int = 20
    top: int = 20


@dataclass
class ProcessConfig:
    members_only: bool = False
    min_volume: int = 0
    min_profit: int = 0
    top: int = 20
    capital: int = 0


@dataclass
class TraderConfig:
    capital: int = 1_000_000
    trade_capital_frac: float = 0.40
    max_positions: int = 3
    min_volume: int = 800
    min_price: int = 25
    max_spread_ratio: float = 5.0
    dip_depth_pct: float = 2.5
    max_dip_pct: float = 10.0
    min_spread_pct: float = 3.5
    max_entry_spread_pct: float = 5.75
    reentry_minutes: int = 30
    stop_reentry_minutes: int = 90
    take_profit_pct: float = 3.0
    stop_loss_pct: float = -2.0
    stop_grace_minutes: int = 20
    max_hold_minutes: int = 180
    spread_collapse_exit_minutes: int = 60
    interval_sec: int = 120
    artifact_min_low_vol: int = 20
    artifact_low_vol_frac: float = 0.10
    artifact_outlier_pct: float = 5.0
    stop_slippage: float = 0.97
    stop_mark_blend: float = 0.0


@dataclass
class Config:
    alch: AlchConfig = field(default_factory=AlchConfig)
    flip: FlipConfig = field(default_factory=FlipConfig)
    margin: MarginConfig = field(default_factory=MarginConfig)
    process: ProcessConfig = field(default_factory=ProcessConfig)
    trader: TraderConfig = field(default_factory=TraderConfig)


class ConfigError(ValueError):
    """Invalid configuration with a stable section/key diagnostic."""

    def __init__(self, section: str, key: str, reason: str):
        self.section = section
        self.key = key
        self.reason = reason
        super().__init__(f"[{section}].{key}: {reason}")


_SECTION_TYPES = {
    "alch": AlchConfig,
    "flip": FlipConfig,
    "margin": MarginConfig,
    "process": ProcessConfig,
    "trader": TraderConfig,
}
_MAX_CONFIG_INTEGER = (1 << 63) - 1
_MAX_RESULTS = 10_000
_MAX_COOLDOWN_MINUTES = 365 * 24 * 60
_INT_RANGES = {
    "alch": {
        "nature_rune_cost": (0, _MAX_CONFIG_INTEGER),
        "min_volume": (0, _MAX_CONFIG_INTEGER),
        "top": (1, _MAX_RESULTS),
    },
    "flip": {
        "min_volume": (0, _MAX_CONFIG_INTEGER),
        "min_margin": (0, _MAX_CONFIG_INTEGER),
        "top": (1, _MAX_RESULTS),
    },
    "margin": {
        "min_volume": (0, _MAX_CONFIG_INTEGER),
        "min_margin": (0, _MAX_CONFIG_INTEGER),
        "check": (1, _MAX_RESULTS),
        "top": (1, _MAX_RESULTS),
    },
    "process": {
        "min_volume": (0, _MAX_CONFIG_INTEGER),
        "min_profit": (0, _MAX_CONFIG_INTEGER),
        "top": (1, _MAX_RESULTS),
        "capital": (0, _MAX_CONFIG_INTEGER),
    },
    "trader": {
        "capital": (1, _MAX_CONFIG_INTEGER),
        "max_positions": (1, 8),
        "min_volume": (0, _MAX_CONFIG_INTEGER),
        "min_price": (10, _MAX_CONFIG_INTEGER),
        "reentry_minutes": (0, _MAX_COOLDOWN_MINUTES),
        "stop_reentry_minutes": (0, _MAX_COOLDOWN_MINUTES),
        "stop_grace_minutes": (0, _MAX_COOLDOWN_MINUTES),
        "max_hold_minutes": (1, _MAX_COOLDOWN_MINUTES),
        "spread_collapse_exit_minutes": (0, _MAX_COOLDOWN_MINUTES),
        "interval_sec": (1, 24 * 60 * 60),
        "artifact_min_low_vol": (0, _MAX_CONFIG_INTEGER),
    },
}
_FLOAT_RANGES = {
    "trader": {
        "trade_capital_frac": (0.0, 1.0, False, True),
        "max_spread_ratio": (1.0, 1000.0, True, True),
        "dip_depth_pct": (0.0, 100.0, False, False),
        "max_dip_pct": (0.0, 100.0, False, True),
        "min_spread_pct": (0.0, 100.0, True, True),
        "max_entry_spread_pct": (0.0, 100.0, False, True),
        "take_profit_pct": (0.0, 100.0, False, True),
        "stop_loss_pct": (-100.0, 0.0, False, False),
        "artifact_low_vol_frac": (0.0, 1.0, False, True),
        "artifact_outlier_pct": (0.0, 100.0, True, True),
        "stop_slippage": (0.0, 1.0, False, True),
        "stop_mark_blend": (0.0, 1.0, True, True),
    },
}


def _in_range(value: float, bounds: tuple[float, float, bool, bool]) -> bool:
    low, high, include_low, include_high = bounds
    return ((value >= low if include_low else value > low)
            and (value <= high if include_high else value < high))


def validate_config(config: Config) -> Config:
    """Check every effective setting before a command starts its work."""
    if type(config) is not Config:
        raise ConfigError("config", "object", "expected a Config instance")

    for section, config_type in _SECTION_TYPES.items():
        values = getattr(config, section)
        if type(values) is not config_type:
            raise ConfigError(section, "section",
                              f"expected {config_type.__name__} instance")
        for item in fields(config_type):
            key = item.name
            value = getattr(values, key)
            expected = item.type
            if expected is bool:
                valid_type = type(value) is bool
            elif expected is int:
                valid_type = type(value) is int
            elif expected is float:
                valid_type = type(value) in (int, float)
            elif expected is str:
                valid_type = type(value) is str
            else:
                valid_type = False
            if not valid_type:
                raise ConfigError(section, key,
                                  f"expected {expected.__name__}, got {type(value).__name__}")

            if expected is int:
                low, high = _INT_RANGES[section][key]
                if value < low or value > high:
                    raise ConfigError(section, key,
                                      f"must be between {low} and {high}")
            elif expected is float:
                try:
                    finite = math.isfinite(value)
                except OverflowError:
                    finite = False
                if not finite:
                    raise ConfigError(section, key, "must be finite")
                bounds = _FLOAT_RANGES[section][key]
                if not _in_range(value, bounds):
                    low, high, include_low, include_high = bounds
                    left = "[" if include_low else "("
                    right = "]" if include_high else ")"
                    raise ConfigError(section, key,
                                      f"must be in {left}{low}, {high}{right}")

    for section in ("flip", "margin"):
        direction = getattr(config, section).direction
        if direction not in ("arbitrage", "traditional"):
            raise ConfigError(section, "direction",
                              "must be 'arbitrage' or 'traditional'")

    trader = config.trader
    if trader.max_dip_pct <= trader.dip_depth_pct:
        raise ConfigError("trader", "max_dip_pct",
                          "must be greater than dip_depth_pct")
    if trader.max_entry_spread_pct < trader.min_spread_pct:
        raise ConfigError("trader", "max_entry_spread_pct",
                          "must be at least min_spread_pct")
    if trader.stop_reentry_minutes < trader.reentry_minutes:
        raise ConfigError("trader", "stop_reentry_minutes",
                          "must be at least reentry_minutes")
    if trader.stop_grace_minutes >= trader.max_hold_minutes:
        raise ConfigError("trader", "stop_grace_minutes",
                          "must be less than max_hold_minutes")
    if trader.spread_collapse_exit_minutes > trader.max_hold_minutes:
        raise ConfigError("trader", "spread_collapse_exit_minutes",
                          "must not exceed max_hold_minutes")
    if trader.interval_sec >= trader.max_hold_minutes * 60:
        raise ConfigError("trader", "interval_sec",
                          "must be shorter than max_hold_minutes")
    return config


def effective_config_dict(config: Config) -> dict:
    """Return the validated effective config in generated TOML section shape."""
    validate_config(config)
    return {section: asdict(getattr(config, section))
            for section in _SECTION_TYPES}


def _config_from_toml(raw: dict) -> Config:
    if not isinstance(raw, dict):
        raise ConfigError("config", "root", "must contain TOML tables")
    sections = {}
    for section, values in raw.items():
        config_type = _SECTION_TYPES.get(section)
        if config_type is None:
            raise ConfigError("config", str(section), "unknown configuration section")
        if not isinstance(values, dict):
            raise ConfigError(section, "section", "must be a TOML table")
        known = {item.name for item in fields(config_type)}
        for key in values:
            if key not in known:
                raise ConfigError(section, str(key), "unknown configuration key")
        sections[section] = config_type(**values)
    return Config(**sections)


def load_config(profile: str | None = None) -> Config:
    """Load, validate and return config before command-specific work begins."""
    path = resolve_config_path("config.toml", profile)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        atomic_write_text(path, DEFAULT_CONFIG_TOML)
    try:
        raw = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError("config", "toml", str(exc)) from exc
    return validate_config(_config_from_toml(raw))
