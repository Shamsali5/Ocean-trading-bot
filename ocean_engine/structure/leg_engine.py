"""Directional leg construction from alternating swing pivots."""

from __future__ import annotations

from typing import Sequence

from ocean_engine.models.enums import Direction
from ocean_engine.models.market import Candle, Leg, Swing
from ocean_engine.structure.swing_engine import detect_swings


def build_legs_from_swings(
    swings: Sequence[Swing],
    candles: Sequence[Candle],
    min_leg_bars: int = 5,
    min_move_pct: float = 0.001,
) -> list[Leg]:
    """Build valid bullish/bearish legs from consecutive alternating swings."""

    if min_leg_bars < 1:
        raise ValueError("min_leg_bars must be >= 1")
    if min_move_pct < 0.0:
        raise ValueError("min_move_pct must be >= 0")
    if not swings:
        return []

    ordered = sorted(swings, key=lambda swing: swing.index)
    legs: list[Leg] = []

    for left, right in zip(ordered, ordered[1:]):
        if left.direction == right.direction:
            continue
        start_index = left.index
        end_index = right.index
        if start_index < 0 or end_index < 0 or start_index >= len(candles) or end_index >= len(candles):
            continue

        bar_count = end_index - start_index
        if bar_count < min_leg_bars:
            continue

        if left.direction == Direction.DOWN and right.direction == Direction.UP:
            direction = Direction.UP
            start_price = left.price
            end_price = right.price
        elif left.direction == Direction.UP and right.direction == Direction.DOWN:
            direction = Direction.DOWN
            start_price = left.price
            end_price = right.price
        else:
            continue

        if start_price <= 0.0:
            continue
        move_pct = abs(end_price - start_price) / start_price
        if move_pct < min_move_pct:
            continue

        span = candles[start_index : end_index + 1]
        high = max(candle.high for candle in span)
        low = min(candle.low for candle in span)

        legs.append(
            Leg(
                start_index=start_index,
                end_index=end_index,
                direction=direction,
                high=high,
                low=low,
                start_price=start_price,
                end_price=end_price,
                start_time=left.timestamp,
                end_time=right.timestamp,
                is_active=False,
            )
        )
    return legs


def mark_active_leg(legs: list[Leg]) -> list[Leg]:
    """Mark only the most recent leg as active."""

    if not legs:
        return legs
    for leg in legs:
        leg.is_active = False
    legs[-1].is_active = True
    return legs


def detect_legs(
    candles: Sequence[Candle],
    swings: Sequence[Swing] | None = None,
    pivot_left: int = 2,
    pivot_right: int = 2,
    min_leg_bars: int = 5,
    min_move_pct: float = 0.001,
) -> list[Leg]:
    """Detect valid legs from either supplied swings or detected swings."""

    working_swings = (
        list(swings)
        if swings is not None
        else detect_swings(candles, pivot_left=pivot_left, pivot_right=pivot_right)
    )
    legs = build_legs_from_swings(
        swings=working_swings,
        candles=candles,
        min_leg_bars=min_leg_bars,
        min_move_pct=min_move_pct,
    )
    return mark_active_leg(legs)
