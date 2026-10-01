"""Centralized configuration: .env + config/instruments.yaml -> typed Settings.

Read once at startup. Never reach into ``os.environ`` from anywhere else.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

import yaml
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"

DEMO_BASE = "https://gateway-api-demo.s2f.projectx.com"
LIVE_BASE = "https://api.topstepx.com"

# SignalR real-time market data hubs.
DEMO_RTC = "wss://gateway-rtc-demo.s2f.projectx.com/hubs/market"
LIVE_RTC = "wss://rtc.topstepx.com/hubs/market"


@dataclass(frozen=True)
class InstrumentSpec:
    """Static per-symbol contract metadata loaded from instruments.yaml."""

    symbol: str
    description: str
    contract_root: str
    tick_size: float
    tick_value: float
    point_value: float
    rth_open: str
    rth_close: str
    quarterly_months: list[str]
    exchange: str = "CME"

    @property
    def ticks_per_point(self) -> float:
        return 1.0 / self.tick_size


@dataclass(frozen=True)
class RiskCaps:
    """Hard risk limits sourced from .env, enforced by ``bot.risk.controls``."""

    daily_loss_limit: float
    trailing_drawdown: float
    max_contracts_per_trade: int
    max_trades_per_day: int
    max_consecutive_losses: int
    daily_profit_target: float = 0.0   # 0 = disabled; halt-flat when reached
    min_account_equity: float = 0.0    # 0 = disabled; absolute balance floor
                                       # (combine trailing-MLL floor across runs)


@dataclass(frozen=True)
class StrategyConfig:
    """Strategy + session parameters sourced from .env."""

    name: str                      # e.g. "mean_reversion"
    poll_interval_seconds: int
    lookback: int                  # bars for SMA / z-score
    z_entry: float                 # |z| threshold to enter
    stop_points: float             # hard stop distance in index points (fixed mode)
    target_points: float           # fixed take-profit distance in points (fixed mode)
    cooldown_seconds: int          # wait between trades
    min_hold_seconds: int          # minimum time in a position
    session_tz: str                # IANA tz, e.g. America/Chicago
    session_open: str              # "HH:MM" local to session_tz
    session_close: str             # "HH:MM"
    entry_end: str                 # "HH:MM" local; no NEW entries after this ("" = disabled)
    flatten_before_close_min: int  # minutes before close to force flat
    # --- upgrades ---
    trend_filter: bool             # block fading a strong trend
    trend_lookback: int            # bars for the long trend SMA
    trend_slope_thresh: float      # normalized per-bar slope = "strong" trend
    stop_mode: str                 # "fixed" | "atr"
    atr_period: int                # bars for ATR
    stop_atr_mult: float           # stop distance = mult * ATR (atr mode)
    target_atr_mult: float         # target distance = mult * ATR (atr mode)
    max_hold_seconds: int          # force exit after this long (0 = disabled)
    skip_first_minutes: int        # no new entries in first N min after open
    allow_long: bool
    allow_short: bool
    # --- Strategy 2: Opening Range Breakout + TTM Squeeze ---
    orb_minutes: int               # length of the opening range (minutes from open)
    orb_entry_end: str             # "HH:MM" local; no new ORB entries after this
    orb_target_r: float            # take-profit = R multiple of the stop risk
    orb_stop_mode: str             # "or_opposite" | "atr"
    orb_min_range: float           # skip if OR width (points) below this
    orb_max_range: float           # skip if OR width (points) above this
    orb_max_trades: int            # max ORB entries per day
    orb_require_squeeze: bool      # require a recently-fired squeeze
    orb_require_momentum: bool     # require aligned TTM momentum histogram
    bb_period: int
    bb_mult: float
    kc_period: int
    kc_mult: float
    mom_period: int
    # --- Strategy 3: VWAP-band mean reversion ---
    vwap_num_std: float            # band distance in std devs from VWAP
    vwap_require_rejection: bool   # require a wick-rejection bar at the band
    vwap_regime_filter: bool       # require range regime (ADX <= adx_max)
    adx_period: int
    adx_max: float                 # only fade when ADX <= this (range)
    vwap_stop_mode: str            # "band" | "atr"
    vwap_stop_buffer: float        # points beyond band for the stop (band mode)
    vwap_max_trades: int           # max VWAP-revert entries per day
    # --- Strategy 3B: VWAP +/-1 sigma band-rejection scalp ---
    vwap_scalp_num_std: float      # band distance in std devs (tighter; default 1.0)
    vwap_scalp_cooldown_seconds: int  # re-arm wait after an exit before re-entering
    vwap_scalp_max_trades: int     # max scalp entries per day (higher than reverter)
    vwap_scalp_adx_max: float      # scalp-specific ADX ceiling (looser than reverter)
    # --- Strategy 4: VWAP trend-pullback continuation ---
    vwap_trend_adx_min: float      # only trade with-trend when ADX >= this (trending)
    vwap_trend_target_r: float     # take-profit = R multiple of the stop risk
    vwap_trend_cooldown_seconds: int  # re-arm wait after an exit before re-entering
    vwap_trend_max_trades: int     # max trend-pullback entries per day
    # --- Strategy 5: rolling Donchian breakout (momentum) ---
    breakout_lookback: int         # bars for the Donchian channel (prior high/low)
    breakout_target_r: float       # take-profit = R multiple of the stop risk
    breakout_stop_mode: str        # "atr" | "channel"
    breakout_cooldown_seconds: int  # re-arm wait after an exit before re-entering
    breakout_max_trades: int       # max breakout entries per day
    breakout_require_squeeze: bool  # require a recently-fired TTM squeeze


@dataclass(frozen=True)
class Settings:
    username: str
    api_key: str
    env: str                       # "demo" | "live"
    base_url: str
    market_hub_url: str            # SignalR real-time quote hub
    account_id: Optional[int]
    symbol_root: str
    contract_id: Optional[str]     # if empty, broker resolves front month
    paper_mode: bool
    risk: RiskCaps
    strategy: StrategyConfig
    log_level: str
    log_dir: Path
    instruments: Dict[str, InstrumentSpec] = field(default_factory=dict)

    @property
    def instrument(self) -> InstrumentSpec:
        try:
            return self.instruments[self.symbol_root]
        except KeyError as exc:
            known = ", ".join(sorted(self.instruments)) or "(none loaded)"
            raise ValueError(
                f"SYMBOL_ROOT={self.symbol_root!r} not in config/instruments.yaml. "
                f"Known symbols: {known}"
            ) from exc


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Missing required env var {name}. Copy .env.example to .env and fill it in."
        )
    return value


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, str(default)).strip().lower()
    return raw in ("1", "true", "yes", "y", "on")


def _int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    return int(raw) if raw else default


def _float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    return float(raw) if raw else default


def _load_instruments(path: Path) -> Dict[str, InstrumentSpec]:
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: Dict[str, InstrumentSpec] = {}
    for symbol, spec in raw.items():
        out[symbol] = InstrumentSpec(
            symbol=symbol,
            description=spec.get("description", symbol),
            contract_root=spec["contract_root"],
            tick_size=float(spec["tick_size"]),
            tick_value=float(spec["tick_value"]),
            point_value=float(spec["point_value"]),
            rth_open=str(spec.get("rth_open", "08:30")),
            rth_close=str(spec.get("rth_close", "15:15")),
            quarterly_months=list(spec.get("quarterly_months", ["H", "M", "U", "Z"])),
            exchange=str(spec.get("exchange", "CME")),
        )
    return out


def load_settings() -> Settings:
    """Read .env and instruments.yaml. Call once at process start."""
    load_dotenv(REPO_ROOT / ".env")

    env = os.getenv("TSX_ENV", "demo").strip().lower()
    if env not in ("demo", "live"):
        raise ValueError(f"TSX_ENV must be 'demo' or 'live', got {env!r}")
    base_url = DEMO_BASE if env == "demo" else LIVE_BASE
    market_hub_url = DEMO_RTC if env == "demo" else LIVE_RTC

    account_raw = os.getenv("ACCOUNT_ID", "").strip()
    account_id = int(account_raw) if account_raw else None

    contract_id = os.getenv("CONTRACT_ID", "").strip() or None

    risk = RiskCaps(
        daily_loss_limit=_float("DAILY_LOSS_LIMIT", 1000.0),
        trailing_drawdown=_float("TRAILING_DRAWDOWN", 2000.0),
        max_contracts_per_trade=_int("MAX_CONTRACTS_PER_TRADE", 1),
        max_trades_per_day=_int("MAX_TRADES_PER_DAY", 10),
        max_consecutive_losses=_int("MAX_CONSECUTIVE_LOSSES", 3),
        daily_profit_target=_float("DAILY_PROFIT_TARGET", 0.0),
        min_account_equity=_float("MIN_ACCOUNT_EQUITY", 0.0),
    )

    strategy = StrategyConfig(
        name=os.getenv("STRATEGY", "mean_reversion").strip().lower(),
        poll_interval_seconds=_int("POLL_INTERVAL_SECONDS", 10),
        lookback=_int("MR_LOOKBACK", 50),
        z_entry=_float("MR_Z_ENTRY", 2.0),
        stop_points=_float("STOP_POINTS", 25.0),
        target_points=_float("TARGET_POINTS", 30.0),
        cooldown_seconds=_int("COOLDOWN_SECONDS", 60),
        min_hold_seconds=_int("MIN_HOLD_SECONDS", 30),
        session_tz=os.getenv("SESSION_TZ", "America/Chicago").strip(),
        session_open=os.getenv("SESSION_OPEN", "08:30").strip(),
        session_close=os.getenv("SESSION_CLOSE", "15:00").strip(),
        entry_end=os.getenv("ENTRY_END", "").strip(),
        flatten_before_close_min=_int("FLATTEN_BEFORE_CLOSE_MIN", 5),
        trend_filter=_bool("TREND_FILTER", True),
        trend_lookback=_int("TREND_LOOKBACK", 200),
        trend_slope_thresh=_float("TREND_SLOPE_THRESH", 0.00002),
        stop_mode=os.getenv("STOP_MODE", "fixed").strip().lower(),
        atr_period=_int("ATR_PERIOD", 14),
        stop_atr_mult=_float("STOP_ATR_MULT", 2.0),
        target_atr_mult=_float("TARGET_ATR_MULT", 2.0),
        max_hold_seconds=_int("MAX_HOLD_SECONDS", 0),
        skip_first_minutes=_int("SKIP_FIRST_MINUTES", 0),
        allow_long=_bool("ALLOW_LONG", True),
        allow_short=_bool("ALLOW_SHORT", True),
        orb_minutes=_int("ORB_MINUTES", 15),
        orb_entry_end=os.getenv("ORB_ENTRY_END", "10:30").strip(),
        orb_target_r=_float("ORB_TARGET_R", 2.0),
        orb_stop_mode=os.getenv("ORB_STOP_MODE", "or_opposite").strip().lower(),
        orb_min_range=_float("ORB_MIN_RANGE", 5.0),
        orb_max_range=_float("ORB_MAX_RANGE", 120.0),
        orb_max_trades=_int("ORB_MAX_TRADES", 2),
        orb_require_squeeze=_bool("ORB_REQUIRE_SQUEEZE", True),
        orb_require_momentum=_bool("ORB_REQUIRE_MOMENTUM", True),
        bb_period=_int("BB_PERIOD", 20),
        bb_mult=_float("BB_MULT", 2.0),
        kc_period=_int("KC_PERIOD", 20),
        kc_mult=_float("KC_MULT", 1.5),
        mom_period=_int("MOM_PERIOD", 20),
        vwap_num_std=_float("VWAP_NUM_STD", 2.0),
        vwap_require_rejection=_bool("VWAP_REQUIRE_REJECTION", True),
        vwap_regime_filter=_bool("VWAP_REGIME_FILTER", True),
        adx_period=_int("ADX_PERIOD", 14),
        adx_max=_float("ADX_MAX", 25.0),
        vwap_stop_mode=os.getenv("VWAP_STOP_MODE", "band").strip().lower(),
        vwap_stop_buffer=_float("VWAP_STOP_BUFFER", 5.0),
        vwap_max_trades=_int("VWAP_MAX_TRADES", 4),
        vwap_scalp_num_std=_float("VWAP_SCALP_NUM_STD", 1.0),
        vwap_scalp_cooldown_seconds=_int("VWAP_SCALP_COOLDOWN_SECONDS", 90),
        vwap_scalp_max_trades=_int("VWAP_SCALP_MAX_TRADES", 10),
        vwap_scalp_adx_max=_float("VWAP_SCALP_ADX_MAX", 30.0),
        vwap_trend_adx_min=_float("VWAP_TREND_ADX_MIN", 25.0),
        vwap_trend_target_r=_float("VWAP_TREND_TARGET_R", 1.5),
        vwap_trend_cooldown_seconds=_int("VWAP_TREND_COOLDOWN_SECONDS", 90),
        vwap_trend_max_trades=_int("VWAP_TREND_MAX_TRADES", 10),
        breakout_lookback=_int("BREAKOUT_LOOKBACK", 20),
        breakout_target_r=_float("BREAKOUT_TARGET_R", 2.0),
        breakout_stop_mode=os.getenv("BREAKOUT_STOP_MODE", "atr").strip().lower(),
        breakout_cooldown_seconds=_int("BREAKOUT_COOLDOWN_SECONDS", 60),
        breakout_max_trades=_int("BREAKOUT_MAX_TRADES", 10),
        breakout_require_squeeze=_bool("BREAKOUT_REQUIRE_SQUEEZE", False),
    )

    log_dir = REPO_ROOT / os.getenv("LOG_DIR", "logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    return Settings(
        username=_required("TSX_USERNAME"),
        api_key=_required("API_KEY"),
        env=env,
        base_url=base_url,
        market_hub_url=market_hub_url,
        account_id=account_id,
        symbol_root=os.getenv("SYMBOL_ROOT", "MNQ").strip(),
        contract_id=contract_id,
        paper_mode=_bool("PAPER_MODE", True),
        risk=risk,
        strategy=strategy,
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        log_dir=log_dir,
        instruments=_load_instruments(CONFIG_DIR / "instruments.yaml"),
    )
