"""Configuration loading from ~/.config/rshelper/config.toml."""


import tomllib
from dataclasses import dataclass, field
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
    trader: TraderConfig = field(default_factory=TraderConfig)


def load_config(profile: str | None = None) -> Config:
    """Load config from ~/.config/rshelper/config.toml, creating default if missing."""
    path = resolve_config_path("config.toml", profile)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        atomic_write_text(path, DEFAULT_CONFIG_TOML)
    raw = tomllib.loads(path.read_text())

    alch_raw = raw.get("alch", {})
    flip_raw = raw.get("flip", {})
    margin_raw = raw.get("margin", {})
    trader_raw = raw.get("trader", {})

    return Config(
        alch=AlchConfig(
            nature_rune_cost=alch_raw.get("nature_rune_cost", 0),
            members_only=alch_raw.get("members_only", False),
            min_volume=alch_raw.get("min_volume", 0),
            top=alch_raw.get("top", 50),
        ),
        flip=FlipConfig(
            direction=flip_raw.get("direction", "arbitrage"),
            members_only=flip_raw.get("members_only", False),
            min_volume=flip_raw.get("min_volume", 10),
            min_margin=flip_raw.get("min_margin", 0),
            top=flip_raw.get("top", 50),
        ),
        margin=MarginConfig(
            direction=margin_raw.get("direction", "arbitrage"),
            members_only=margin_raw.get("members_only", False),
            min_volume=margin_raw.get("min_volume", 10),
            min_margin=margin_raw.get("min_margin", 0),
            check=margin_raw.get("check", 20),
            top=margin_raw.get("top", 20),
        ),
        trader=TraderConfig(
            capital=trader_raw.get("capital", 1_000_000),
            trade_capital_frac=trader_raw.get("trade_capital_frac", 0.40),
            max_positions=trader_raw.get("max_positions", 3),
            min_volume=trader_raw.get("min_volume", 800),
            min_price=trader_raw.get("min_price", 25),
            max_spread_ratio=trader_raw.get("max_spread_ratio", 5.0),
            dip_depth_pct=trader_raw.get("dip_depth_pct", 2.5),
            max_dip_pct=trader_raw.get("max_dip_pct", 10.0),
            min_spread_pct=trader_raw.get("min_spread_pct", 3.5),
            max_entry_spread_pct=trader_raw.get("max_entry_spread_pct", 5.75),
            reentry_minutes=trader_raw.get("reentry_minutes", 30),
            stop_reentry_minutes=trader_raw.get("stop_reentry_minutes", 90),
            take_profit_pct=trader_raw.get("take_profit_pct", 3.0),
            stop_loss_pct=trader_raw.get("stop_loss_pct", -2.0),
            stop_grace_minutes=trader_raw.get("stop_grace_minutes", 20),
            max_hold_minutes=trader_raw.get("max_hold_minutes", 180),
            spread_collapse_exit_minutes=trader_raw.get(
                "spread_collapse_exit_minutes", 60),
            interval_sec=trader_raw.get("interval_sec", 120),
            artifact_min_low_vol=trader_raw.get("artifact_min_low_vol", 20),
            artifact_low_vol_frac=trader_raw.get("artifact_low_vol_frac", 0.10),
            artifact_outlier_pct=trader_raw.get("artifact_outlier_pct", 5.0),
            stop_slippage=trader_raw.get("stop_slippage", 0.97),
            stop_mark_blend=trader_raw.get("stop_mark_blend", 0.0),
        ),
    )
