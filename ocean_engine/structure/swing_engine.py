"""Deterministic swing pivot detection from OHLCV candles."""

from __future__ import annotations

from typing import Sequence

from ocean_engine.models.enums import Direction
from ocean_engine.models.market import Candle, Swing


def find_raw_pivots(candles: Sequence[Candle], pivot_left: int = 2, pivot_right: int = 2) -> list[Swing]:
    """Detect raw pivot highs and lows with complete left/right windows only."""

    if pivot_left < 1 or pivot_right < 1:
        raise ValueError("pivot_left and pivot_right must both be >= 1")
    if len(candles) < (pivot_left + pivot_right + 1):
        return []

    pivots: list[Swing] = []
    start = pivot_left
    end = len(candles) - pivot_right

    for index in range(start, end):
        current = candles[index]
        left_window = candles[index - pivot_left : index]
        right_window = candles[index + 1 : index + 1 + pivot_right]
        nearby = left_window + right_window

        left_highs = [candle.high for candle in left_window]
        right_highs = [candle.high for candle in right_window]
        left_lows = [candle.low for candle in left_window]
        right_lows = [candle.low for candle in right_window]

        is_pivot_high = current.high > max(left_highs) and current.high >= max(right_highs)
        is_pivot_low = current.low < min(left_lows) and current.low <= min(right_lows)

        if is_pivot_high and is_pivot_low:
            nearby_high = max(candle.high for candle in nearby)
            nearby_low = min(candle.low for candle in nearby)
            high_expansion = current.high - nearby_high
            low_expansion = nearby_low - current.low
            if high_expansion > low_expansion:
                is_pivot_low = False
            elif low_expansion > high_expansion:
                is_pivot_high = False
            else:
                continue

        if is_pivot_high:
            pivots.append(
                Swing(
                    index=index,
                    price=current.high,
                    direction=Direction.UP,
                    timestamp=current.close_time,
                )
            )
        elif is_pivot_low:
            pivots.append(
                Swing(
                    index=index,
                    price=current.low,
                    direction=Direction.DOWN,
                    timestamp=current.close_time,
                )
            )
    return pivots


def enforce_alternation(swings: list[Swing]) -> list[Swing]:
    """Collapse same-direction sequences so output alternates high/low pivots."""

    if not swings:
        return []

    ordered = sorted(swings, key=lambda swing: swing.index)
    alternating: list[Swing] = [ordered[0]]

    for swing in ordered[1:]:
        last = alternating[-1]
        if swing.direction != last.direction:
            alternating.append(swing)
            continue

        if swing.direction == Direction.UP and swing.price > last.price:
            alternating[-1] = swing
        elif swing.direction == Direction.DOWN and swing.price < last.price:
            alternating[-1] = swing
    return alternating


def detect_swings(candles: Sequence[Candle], pivot_left: int = 2, pivot_right: int = 2) -> list[Swing]:
    """Detect swings by finding pivots then enforcing directional alternation."""

    return enforce_alternation(find_raw_pivots(candles, pivot_left=pivot_left, pivot_right=pivot_right))
