"""Tests for strict standalone ocean range engine."""

from __future__ import annotations

from ocean_range_engine import classify_range_location, detect_valid_range
from ocean_engine.models.enums import Direction
from ocean_engine.models.market import Candle, Leg


def _candle(open_: float, high: float, low: float, close: float, idx: int) -> Candle:
    return Candle(
        open_time=idx * 60_000,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=1.0,
        close_time=(idx + 1) * 60_000 - 1,
    )


def _leg(start: int, end: int, low: float, high: float, direction: Direction) -> Leg:
    return Leg(
        start_index=start,
        end_index=end,
        direction=direction,
        high=high,
        low=low,
        start_price=low if direction == Direction.UP else high,
        end_price=high if direction == Direction.UP else low,
        start_time=start,
        end_time=end,
        is_active=False,
    )


def test_detect_valid_range_requires_three_parts() -> None:
    swings = [
        _leg(0, 3, 90.0, 110.0, Direction.UP),
        _leg(4, 7, 94.0, 108.0, Direction.DOWN),
    ]
    result = detect_valid_range(candles=[], timeframe="15m", swings=swings)
    assert result.valid is False
    assert result.parts_count == 2


def test_detect_valid_range_detects_overlap_range() -> None:
    swings = [
        _leg(0, 3, 90.0, 110.0, Direction.UP),
        _leg(4, 7, 94.0, 108.0, Direction.DOWN),
        _leg(8, 11, 95.0, 109.0, Direction.UP),
        _leg(12, 15, 96.0, 107.0, Direction.DOWN),
    ]
    candles = [
        _candle(99.0, 100.0, 98.5, 99.5, 0),
        _candle(99.5, 100.3, 99.0, 100.1, 1),
    ]
    result = detect_valid_range(candles=candles, timeframe="15m", swings=swings)
    assert result.valid is True
    assert result.upper_edge is not None
    assert result.lower_edge is not None
    assert result.midpoint is not None
    assert result.repeated_overlap is True


def test_detect_valid_range_invalid_when_continuation_outside_sustained() -> None:
    swings = [
        _leg(0, 3, 90.0, 110.0, Direction.UP),
        _leg(4, 7, 94.0, 108.0, Direction.DOWN),
        _leg(8, 11, 95.0, 109.0, Direction.UP),
    ]
    candles = [
        _candle(109.8, 111.0, 109.6, 110.6, 0),
        _candle(110.6, 111.3, 110.2, 110.9, 1),
        _candle(110.9, 111.5, 110.7, 111.1, 2),
    ]
    result = detect_valid_range(candles=candles, timeframe="15m", swings=swings)
    assert result.valid is False
    assert "sustained continuation outside" in result.reason.lower()


def test_classify_range_location_midpoint() -> None:
    swings = [
        _leg(0, 3, 90.0, 110.0, Direction.UP),
        _leg(4, 7, 94.0, 108.0, Direction.DOWN),
        _leg(8, 11, 95.0, 109.0, Direction.UP),
    ]
    candles = [_candle(99.0, 100.0, 98.5, 99.8, 0)]
    result = detect_valid_range(candles=candles, timeframe="15m", swings=swings)
    assert result.valid is True
    location = classify_range_location(result.midpoint, result)
    assert location == "MID"
