"""Environment-backed configuration for deterministic data collection."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BINANCE_FUTURES_KLINES_URL = "https://fapi.binance.com/fapi/v1/klines"
DEFAULT_LIMITS: dict[str, int] = {
    "3m": 240,
    "5m": 240,
    "15m": 300,
    "1h": 300,
    "4h": 240,
}
POSITION_MODES = {"UNKNOWN", "FLAT", "LONG", "SHORT"}


def _parse_csv(value: str) -> list[str]:
    """Split comma-separated values while dropping blank items."""

    return [item.strip() for item in value.split(",") if item.strip()]


def _normalize_position_mode(value: str) -> str:
    """Normalize position mode into one of the allowed enum-like strings."""

    mode = value.strip().upper()
    if mode in POSITION_MODES:
        return mode
    return "UNKNOWN"


@dataclass(slots=True)
class VAccConfig:
    """Default settings for velocity/acceleration preprocessing."""

    period: int = 21
    smooth: int = 5


@dataclass(slots=True)
class SwingConfig:
    """Default settings for pivot and leg extraction."""

    pivot_left: int = 2
    pivot_right: int = 2
    min_leg_bars: int = 5
    range_min_legs: int = 3


@dataclass(slots=True)
class EngineConfig:
    """Runtime configuration loaded from environment variables."""

    symbols: list[str] = field(default_factory=lambda: ["BTCUSDT"])
    intervals: list[str] = field(default_factory=lambda: ["3m", "5m", "15m", "1h", "4h"])
    telegram_mode: str = "compact"
    run_every_half_hour: bool = False
    data_dir: Path = Path("ohlcv_data")
    results_dir: Path = Path("analysis_results")
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    request_timeout_seconds: int = 30
    binance_futures_klines_url: str = BINANCE_FUTURES_KLINES_URL
    candle_limits: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_LIMITS))
    vacc: VAccConfig = field(default_factory=VAccConfig)
    swing: SwingConfig = field(default_factory=SwingConfig)
    position_mode: str = "UNKNOWN"


@dataclass(slots=True)
class OceanConfig:
    """Flat runner configuration for deterministic pipeline orchestration."""

    symbols: list[str]
    intervals: list[str]
    candle_limits: dict[str, int]
    data_dir: Path
    results_dir: Path
    vacc_period: int
    vacc_smooth: int
    telegram_mode: str
    run_every_half_hour: bool
    position_mode: str


def from_env() -> EngineConfig:
    """Build an :class:`EngineConfig` from process environment variables."""

    symbols = _parse_csv(os.getenv("OCEAN_SYMBOLS", "BTCUSDT")) or ["BTCUSDT"]
    intervals = _parse_csv(os.getenv("OCEAN_INTERVALS", "3m,5m,15m,1h,4h")) or ["3m", "5m", "15m", "1h", "4h"]
    telegram_mode = os.getenv("OCEAN_TELEGRAM_MODE", "compact").strip().lower()
    run_every_half_hour = os.getenv("OCEAN_RUN_EVERY_HALF_HOUR", "0").strip() == "1"
    data_dir = Path(os.getenv("OCEAN_DATA_DIR", "ohlcv_data"))
    results_dir = Path(os.getenv("OCEAN_RESULTS_DIR", "analysis_results"))
    telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")
    position_mode = _normalize_position_mode(os.getenv("OCEAN_POSITION_MODE", "UNKNOWN"))

    return EngineConfig(
        symbols=symbols,
        intervals=intervals,
        telegram_mode=telegram_mode,
        run_every_half_hour=run_every_half_hour,
        data_dir=data_dir,
        results_dir=results_dir,
        telegram_bot_token=telegram_bot_token,
        telegram_chat_id=telegram_chat_id,
        position_mode=position_mode,
    )


def load_config() -> OceanConfig:
    """Load flat runner configuration from the environment-backed engine config."""

    engine = from_env()
    limits: dict[str, int] = {}
    for interval in engine.intervals:
        limits[interval] = engine.candle_limits.get(interval, DEFAULT_LIMITS.get(interval, 240))

    return OceanConfig(
        symbols=list(engine.symbols),
        intervals=list(engine.intervals),
        candle_limits=limits,
        data_dir=engine.data_dir,
        results_dir=engine.results_dir,
        vacc_period=engine.vacc.period,
        vacc_smooth=engine.vacc.smooth,
        telegram_mode=engine.telegram_mode,
        run_every_half_hour=engine.run_every_half_hour,
        position_mode=engine.position_mode,
    )
