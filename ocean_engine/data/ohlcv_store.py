"""Persistence helpers for OHLCV timeframe snapshots."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from ocean_engine.models.market import TimeframeData


def save_timeframe_data(symbol: str, timeframe_data: TimeframeData, data_dir: Path) -> Path:
    """Save one timeframe as JSON under ``{data_dir}/{symbol}``."""

    symbol_clean = symbol.upper().strip()
    timeframe = timeframe_data.timeframe
    target_dir = data_dir / symbol_clean
    target_dir.mkdir(parents=True, exist_ok=True)
    output_path = target_dir / f"{symbol_clean}_{timeframe}_futures.json"

    candles = [asdict(candle) for candle in timeframe_data.candles]
    first_open_time = candles[0]["open_time"] if candles else None
    last_close_time = candles[-1]["close_time"] if candles else None

    payload = {
        "symbol": symbol_clean,
        "timeframe": timeframe,
        "first_open_time": first_open_time,
        "last_close_time": last_close_time,
        "candles": candles,
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    return output_path


def save_all_timeframes(symbol: str, data: dict[str, TimeframeData], data_dir: Path) -> list[Path]:
    """Save all timeframe payloads and return generated file paths."""

    saved_paths: list[Path] = []
    for timeframe in sorted(data.keys()):
        saved_paths.append(save_timeframe_data(symbol=symbol, timeframe_data=data[timeframe], data_dir=data_dir))
    return saved_paths
