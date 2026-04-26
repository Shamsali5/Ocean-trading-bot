"""Configuration primitives for deterministic ocean engine runners."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


@dataclass(slots=True)
class EngineConfig:
    """Runtime configuration for deterministic engine execution."""

    symbol: str = "BTCUSDT"
    timeframes: Sequence[str] = field(default_factory=lambda: ("4h", "1h", "15m", "5m", "3m"))
    max_candles: int = 500
