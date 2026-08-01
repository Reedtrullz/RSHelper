"""Configuration loading from ~/.config/rshelper/config.toml."""


import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from rshelper.profile import resolve_config_path

CONFIG_DIR = Path.home() / ".config" / "rshelper"
CONFIG_PATH = CONFIG_DIR / "config.toml"

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
trade_capital_frac = 0.25  # fraction of bankroll per position
max_positions = 3        # concurrent auto positions
min_volume = 500         # 5m executed volume floor
max_spread_ratio = 5.0   # max buy/sell gap for entries
dip_depth_pct = 2.0      # buy when sell is >=2% below the 5m average
take_profit_pct = 1.5    # close when unrealized >= this %
stop_loss_pct = -1.5     # close when unrealized <= this %
max_hold_minutes = 240   # force-close after this long
interval_sec = 300       # poll cycle
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
    trade_capital_frac: float = 0.25
    max_positions: int = 3
    min_volume: int = 500
    max_spread_ratio: float = 5.0
    dip_depth_pct: float = 2.0
    take_profit_pct: float = 1.5
    stop_loss_pct: float = -1.5
    max_hold_minutes: int = 240
    interval_sec: int = 300


@dataclass
class Config:
    alch: AlchConfig = field(default_factory=AlchConfig)
    flip: FlipConfig = field(default_factory=FlipConfig)
    margin: MarginConfig = field(default_factory=MarginConfig)
    trader: TraderConfig = field(default_factory=TraderConfig)


def _ensure_config_exists() -> Path:
    """Create default config.toml if missing. Returns the config path."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(DEFAULT_CONFIG_TOML)
    return CONFIG_PATH


def load_config(profile: str | None = None) -> Config:
    """Load config from ~/.config/rshelper/config.toml, creating default if missing."""
    path = resolve_config_path("config.toml", profile)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(DEFAULT_CONFIG_TOML)
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
            trade_capital_frac=trader_raw.get("trade_capital_frac", 0.25),
            max_positions=trader_raw.get("max_positions", 3),
            min_volume=trader_raw.get("min_volume", 500),
            max_spread_ratio=trader_raw.get("max_spread_ratio", 5.0),
            dip_depth_pct=trader_raw.get("dip_depth_pct", 2.0),
            take_profit_pct=trader_raw.get("take_profit_pct", 1.5),
            stop_loss_pct=trader_raw.get("stop_loss_pct", -1.5),
            max_hold_minutes=trader_raw.get("max_hold_minutes", 240),
            interval_sec=trader_raw.get("interval_sec", 300),
        ),
    )
