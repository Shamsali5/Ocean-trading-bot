"""Tests for deterministic swing pivot detection and alternation."""

from __future__ import annotations

from ocean_engine.models.enums import Direction
from ocean_engine.models.market import Candle
from ocean_engine.structure.swing_engine import detect_swings, find_raw_pivots


def _make_candles(highs: list[float], lows: list[float]) -> list[Candle]:
    if len(highs) != len(lows):
        raise ValueError("high and low arrays must match length")
    candles: list[Candle] = []
    for idx, (high, low) in enumerate(zip(highs, lows)):
        candles.append(
            Candle(
                open_time=idx * 60_000,
                open=(high + low) / 2.0,
                high=high,
                low=low,
                close=(high + low) / 2.0,
                volume=1.0,
                close_time=(idx + 1) * 60_000 - 1,
            )
        )
    return candles


def test_detects_simple_pivot_high() -> None:
    candles = _make_candles(
        highs=[1.0, 2.0, 5.0, 2.0, 1.0],
        lows=[0.5, 1.0, 2.0, 1.0, 0.5],
    )
    swings = find_raw_pivots(candles, pivot_left=2, pivot_right=2)

    assert len(swings) == 1
    assert swings[0].index == 2
    assert swings[0].direction == Direction.UP
    assert swings[0].price == 5.0


def test_detects_simple_pivot_low() -> None:
    candles = _make_candles(
        highs=[3.0, 2.0, 1.5, 2.0, 3.0],
        lows=[2.0, 1.0, 0.2, 1.0, 2.0],
    )
    swings = find_raw_pivots(candles, pivot_left=2, pivot_right=2)

    assert len(swings) == 1
    assert swings[0].index == 2
    assert swings[0].direction == Direction.DOWN
    assert swings[0].price == 0.2


def test_ignores_incomplete_edge_windows() -> None:
    candles = _make_candles(
        highs=[5.0, 1.0, 1.0, 1.0, 5.0],
        lows=[0.5, 0.2, 0.2, 0.2, 0.5],
    )
    swings = find_raw_pivots(candles, pivot_left=2, pivot_right=2)

    assert swings == []


def test_duplicate_highs_keep_only_higher_high() -> None:
    candles = _make_candles(
        highs=[1.0, 2.0, 7.0, 2.0, 8.0, 2.0, 1.0],
        lows=[0.5, 1.0, 2.0, 1.0, 2.0, 1.0, 0.5],
    )
    swings = detect_swings(candles, pivot_left=1, pivot_right=1)

    assert len(swings) == 1
    assert swings[0].direction == Direction.UP
    assert swings[0].index == 4
    assert swings[0].price == 8.0


def test_duplicate_lows_keep_only_lower_low() -> None:
    candles = _make_candles(
        highs=[3.0, 2.0, 3.0, 2.0, 3.0, 2.0, 3.0],
        lows=[2.0, 1.0, 2.0, 0.5, 2.0, 1.0, 2.0],
    )
    swings = detect_swings(candles, pivot_left=1, pivot_right=1)

    assert len(swings) == 1
    assert swings[0].direction == Direction.DOWN
    assert swings[0].index == 3
    assert swings[0].price == 0.5


def test_detect_swings_enforces_alternating_sequence() -> None:
    candles = _make_candles(
        highs=[1.0, 2.0, 6.0, 2.0, 1.0, 2.0, 5.0, 2.0, 1.0],
        lows=[0.5, 1.0, 2.0, 0.2, 1.0, 1.0, 2.0, 0.3, 0.8],
    )
    swings = detect_swings(candles, pivot_left=1, pivot_right=1)

    assert len(swings) >= 3
    for left, right in zip(swings, swings[1:]):
        assert left.direction != right.direction
