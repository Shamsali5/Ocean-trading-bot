"""Tests for generic Type 3 breakout/range acceptance detection."""

from __future__ import annotations

from ocean_engine.models.enums import Direction
from ocean_engine.models.market import Candle, Leg, RangeState
from ocean_engine.structure.range_engine import detect_breakout_acceptance


def _leg(start: int, end: int, low: float, high: float, direction: Direction = Direction.UP) -> Leg:
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


def _candles_from_closes(closes: list[float]) -> list[Candle]:
    candles: list[Candle] = []
    for idx, close in enumerate(closes):
        candles.append(
            Candle(
                open_time=idx,
                open=close,
                high=close + 0.4,
                low=close - 0.4,
                close=close,
                volume=1.0,
                close_time=idx,
            )
        )
    return candles


def _active_range() -> RangeState:
    return RangeState(
        timeframe="15m",
        is_range=True,
        active=True,
        upper_edge=100.0,
        lower_edge=90.0,
        midpoint=95.0,
        price_location="MID",
        status="ACTIVE",
    )


def test_bullish_breakout_sets_broken_up_and_acceptance_confirmed() -> None:
    candles = _candles_from_closes([96.0, 99.0, 100.8, 101.2, 101.9])
    legs = [_leg(0, 4, 90.0, 100.0)]
    state = detect_breakout_acceptance(_active_range(), candles, legs, current_price=101.9)
    assert state.status == "BROKEN_UP"
    assert state.acceptance_confirmed is True
    assert state.breakout_direction == Direction.UP


def test_bearish_breakdown_sets_broken_down_and_acceptance_confirmed() -> None:
    candles = _candles_from_closes([94.0, 91.0, 89.5, 88.8, 88.0])
    legs = [_leg(0, 4, 90.0, 100.0, direction=Direction.DOWN)]
    state = detect_breakout_acceptance(_active_range(), candles, legs, current_price=88.0)
    assert state.status == "BROKEN_DOWN"
    assert state.acceptance_confirmed is True
    assert state.breakout_direction == Direction.DOWN


def test_wick_outside_without_close_does_not_confirm_breakout() -> None:
    candles = _candles_from_closes([96.0, 99.0, 100.0, 99.6, 99.8])
    # Add wick above upper edge on one candle while close remains inside.
    candles[2].high = 101.2
    legs = [_leg(0, 4, 90.0, 100.0)]
    state = detect_breakout_acceptance(_active_range(), candles, legs, current_price=99.8)
    assert state.breakout_confirmed is False
    assert state.acceptance_confirmed is False
    assert state.status == "ACTIVE"


def test_immediate_reclaim_sets_failed_break_statuses() -> None:
    bullish_candles = _candles_from_closes([99.0, 100.7, 99.7, 99.4])
    bullish = detect_breakout_acceptance(_active_range(), bullish_candles, [], current_price=99.4)
    assert bullish.status == "FAILED_BREAK_UP"
    assert bullish.acceptance_confirmed is False

    bearish_candles = _candles_from_closes([91.0, 89.3, 90.4, 90.8])
    bearish = detect_breakout_acceptance(_active_range(), bearish_candles, [], current_price=90.8)
    assert bearish.status == "FAILED_BREAK_DOWN"
    assert bearish.acceptance_confirmed is False


def test_retest_hold_outside_confirms_acceptance() -> None:
    candles = _candles_from_closes([98.0, 100.6, 100.05, 101.4])
    state = detect_breakout_acceptance(_active_range(), candles, [], current_price=101.4)
    assert state.breakout_confirmed is True
    assert state.retest_held is True
    assert state.acceptance_confirmed is True
    assert state.status == "BROKEN_UP"


def test_active_range_with_price_inside_remains_active() -> None:
    candles = _candles_from_closes([94.0, 95.0, 96.0, 97.0, 98.0])
    state = detect_breakout_acceptance(_active_range(), candles, [], current_price=98.0)
    assert state.status == "ACTIVE"
    assert state.breakout_confirmed is False


def test_midpoint_remains_mid_and_no_breakout() -> None:
    candles = _candles_from_closes([95.0, 95.2, 94.8, 95.1])
    range_state = _active_range()
    range_state.price_location = "MID"
    state = detect_breakout_acceptance(range_state, candles, [], current_price=95.1)
    assert state.price_location == "MID"
    assert state.status == "ACTIVE"
    assert state.breakout_confirmed is False
