from __future__ import annotations

from dataclasses import dataclass
from typing import Any

TIMEFRAMES_HIGH_TO_LOW = ["4h", "1h", "15m", "5m", "3m"]
TIMEFRAME_LABELS = {"4h": "4H", "1h": "1H", "15m": "15m", "5m": "5m", "3m": "3m"}
TIMEFRAME_KEYS = {"4h": "tf_4h", "1h": "tf_1h", "15m": "tf_15m", "5m": "tf_5m", "3m": "tf_3m"}


@dataclass(frozen=True)
class Candle:
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def range(self) -> float:
        return max(self.high - self.low, 0.0)

    @property
    def direction(self) -> str:
        if self.close > self.open:
            return "UP"
        if self.close < self.open:
            return "DOWN"
        return "RANGE"


@dataclass(frozen=True)
class TimeframeAnalysis:
    timeframe: str
    candles: list[Candle]
    direction: str
    state: str
    velocity: list[float]
    acceleration: list[float]
    acceleration_area: list[float]
    divergence: dict[str, Any]
    range_state: dict[str, Any]
    zones: list[dict[str, Any]]


def parse_candles(rows: list[list[Any]]) -> list[Candle]:
    candles: list[Candle] = []
    for row in rows:
        try:
            candles.append(
                Candle(
                    open_time=int(row[0]),
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                    close_time=int(row[6]),
                )
            )
        except (IndexError, TypeError, ValueError):
            continue
    return candles


def format_price(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:,.2f}"
