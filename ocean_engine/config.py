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


def _parse_csv(value: str) -> list[str]:
    """Split comma-separated values while dropping blank items."""

    return [item.strip() for item in value.split(",") if item.strip()]


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

    return EngineConfig(
        symbols=symbols,
        intervals=intervals,
        telegram_mode=telegram_mode,
        run_every_half_hour=run_every_half_hour,
        data_dir=data_dir,
        results_dir=results_dir,
        telegram_bot_token=telegram_bot_token,
        telegram_chat_id=telegram_chat_id,
    )
