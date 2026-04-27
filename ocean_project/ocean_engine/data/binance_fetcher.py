"""Binance Futures OHLCV fetch and conversion utilities."""

from __future__ import annotations

import os
from typing import Any

from ocean_engine.utils import http_client as requests

from ocean_engine.config import BINANCE_FUTURES_KLINES_URL
from ocean_engine.models.market import Candle, TimeframeData

REQUEST_TIMEOUT_SECONDS = int(os.getenv("OCEAN_REQUEST_TIMEOUT", "30"))


def fetch_futures_klines(symbol: str, interval: str, limit: int) -> list[list]:
    """Fetch raw Binance Futures kline rows for a symbol/timeframe."""

    params = {"symbol": symbol.upper().strip(), "interval": interval.strip(), "limit": int(limit)}
    try:
        response = requests.get(BINANCE_FUTURES_KLINES_URL, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(
            f"Failed to fetch klines from Binance for symbol={symbol}, interval={interval}, limit={limit}: {exc}"
        ) from exc

    payload: Any = response.json()
    if not isinstance(payload, list):
        raise ValueError(
            f"Invalid Binance kline payload for symbol={symbol}, interval={interval}: expected list, got {type(payload).__name__}"
        )

    for idx, row in enumerate(payload):
        if not isinstance(row, list):
            raise ValueError(f"Invalid kline row at index {idx}: expected list, got {type(row).__name__}")
        if len(row) < 7:
            raise ValueError(f"Invalid kline row at index {idx}: expected at least 7 items, got {len(row)}")
    return payload


def kline_to_candle(row: list) -> Candle:
    """Convert one Binance kline row into a typed :class:`Candle`."""

    if len(row) < 7:
        raise ValueError(f"Cannot convert kline row with fewer than 7 columns: {row}")
    try:
        return Candle(
            open_time=int(row[0]),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[5]),
            close_time=int(row[6]),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Unable to parse Binance kline row into Candle: {row}") from exc


def fetch_timeframe(symbol: str, interval: str, limit: int) -> TimeframeData:
    """Fetch and convert one timeframe into :class:`TimeframeData`."""

    raw_rows = fetch_futures_klines(symbol=symbol, interval=interval, limit=limit)
    candles = [kline_to_candle(row) for row in raw_rows]
    return TimeframeData(timeframe=interval, candles=candles)


def fetch_all_timeframes(symbol: str, intervals: list[str], limits: dict[str, int]) -> dict[str, TimeframeData]:
    """Fetch and convert all requested intervals for one symbol."""

    result: dict[str, TimeframeData] = {}
    for interval in intervals:
        if interval not in limits:
            raise KeyError(f"Missing candle limit for interval '{interval}'")
        result[interval] = fetch_timeframe(symbol=symbol, interval=interval, limit=limits[interval])
    return result
