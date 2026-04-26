"""Tests for divergence detection from validated A-B-C structures."""

from __future__ import annotations

from ocean_engine.divergence.divergence_engine import (
    compare_segment_energy,
    detect_divergence_from_abc,
    detect_opposite_impulse,
    grade_divergence,
)
from ocean_engine.models.enums import Direction, DivergenceDirection, DivergenceGrade
from ocean_engine.models.market import ABCStructure, Candle, Leg, VAccPoint, VAccSeries


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


def _make_flat_candles(length: int = 40, close: float = 100.0) -> list[Candle]:
    return [_candle(close, close + 1.0, close - 1.0, close, i) for i in range(length)]


def _leg(
    start_index: int,
    end_index: int,
    direction: Direction,
    low: float,
    high: float,
) -> Leg:
    return Leg(
        start_index=start_index,
        end_index=end_index,
        direction=direction,
        high=high,
        low=low,
        start_price=low if direction == Direction.UP else high,
        end_price=high if direction == Direction.UP else low,
        start_time=start_index,
        end_time=end_index,
        is_active=False,
    )


def _abc(
    direction: DivergenceDirection,
    segment_a: Leg,
    segment_b: Leg,
    segment_c: Leg,
    abc_valid: bool = True,
) -> ABCStructure:
    return ABCStructure(
        timeframe="1h",
        a_index=segment_a.start_index,
        b_index=segment_b.start_index,
        c_index=segment_c.start_index,
        direction=direction,
        segment_a=segment_a,
        segment_b=segment_b,
        segment_c=segment_c,
        abc_valid=abc_valid,
        b_reset_valid=True,
        c_retest_valid=True,
    )


def _vacc_with_values(velocity: list[float], acceleration: list[float]) -> VAccSeries:
    points = [
        VAccPoint(timestamp=i, velocity=velocity[i], acceleration=acceleration[i])
        for i in range(len(velocity))
    ]
    return VAccSeries(timeframe="1h", points=points)


def test_invalid_abc_returns_no_divergence() -> None:
    a = _leg(0, 5, Direction.UP, low=90.0, high=110.0)
    b = _leg(6, 9, Direction.DOWN, low=95.0, high=108.0)
    c = _leg(10, 14, Direction.UP, low=96.0, high=111.0)
    abc = _abc(DivergenceDirection.BEARISH, a, b, c, abc_valid=False)
    state = detect_divergence_from_abc(abc, _make_flat_candles(), _vacc_with_values([0.0] * 50, [0.0] * 50))
    assert state.exists is False
    assert state.grade == DivergenceGrade.INVALID


def test_bearish_official_divergence_with_weaker_energy_and_impulse() -> None:
    a = _leg(2, 6, Direction.UP, low=90.0, high=110.0)
    b = _leg(7, 9, Direction.DOWN, low=98.0, high=109.0)
    c = _leg(10, 14, Direction.UP, low=97.0, high=111.0)
    abc = _abc(DivergenceDirection.BEARISH, a, b, c)

    velocity = [0.0] * 40
    acceleration = [0.0] * 40
    for idx, value in zip(range(2, 7), [2.0, 2.0, 2.0, 2.0, 2.0], strict=True):
        velocity[idx] = value
        acceleration[idx] = 0.4
    for idx, value in zip(range(10, 15), [0.8, 0.8, 0.8, 0.8, 0.8], strict=True):
        velocity[idx] = value
        acceleration[idx] = 0.1
    velocity[7] = 0.0
    velocity[8] = -0.2
    velocity[9] = 0.1

    vacc = _vacc_with_values(velocity, acceleration)

    candles = _make_flat_candles(length=25, close=100.0)
    candles[15] = _candle(106.0, 107.0, 99.0, 99.5, 15)
    candles[14] = _candle(105.5, 106.5, 104.0, 106.0, 14)

    state = detect_divergence_from_abc(abc, candles, vacc)
    assert state.exists is True
    assert state.direction == DivergenceDirection.BEARISH
    assert state.grade in {DivergenceGrade.STRONG, DivergenceGrade.ELITE}


def test_bullish_official_divergence_with_weaker_energy_and_impulse() -> None:
    a = _leg(2, 6, Direction.DOWN, low=90.0, high=110.0)
    b = _leg(7, 9, Direction.UP, low=91.0, high=102.0)
    c = _leg(10, 14, Direction.DOWN, low=89.8, high=103.0)
    abc = _abc(DivergenceDirection.BULLISH, a, b, c)

    velocity = [0.0] * 40
    acceleration = [0.0] * 40
    for idx in range(2, 7):
        velocity[idx] = -2.2
        acceleration[idx] = -0.5
    for idx in range(10, 15):
        velocity[idx] = -0.9
        acceleration[idx] = -0.15
    velocity[7] = 0.0
    velocity[8] = 0.2
    velocity[9] = -0.05

    vacc = _vacc_with_values(velocity, acceleration)

    candles = _make_flat_candles(length=25, close=100.0)
    candles[15] = _candle(94.0, 101.0, 93.0, 100.5, 15)
    candles[14] = _candle(95.0, 96.0, 93.8, 94.2, 14)

    state = detect_divergence_from_abc(abc, candles, vacc)
    assert state.exists is True
    assert state.direction == DivergenceDirection.BULLISH
    assert state.grade in {DivergenceGrade.STRONG, DivergenceGrade.ELITE}


def test_valid_abc_with_weaker_energy_but_no_impulse_is_weak_and_unofficial() -> None:
    a = _leg(2, 6, Direction.UP, low=90.0, high=110.0)
    b = _leg(7, 9, Direction.DOWN, low=98.0, high=109.0)
    c = _leg(10, 14, Direction.UP, low=97.0, high=111.0)
    abc = _abc(DivergenceDirection.BEARISH, a, b, c)

    velocity = [0.0] * 30
    acceleration = [0.0] * 30
    for idx in range(2, 7):
        velocity[idx] = 2.0
        acceleration[idx] = 0.4
    for idx in range(10, 15):
        velocity[idx] = 0.8
        acceleration[idx] = 0.1
    vacc = _vacc_with_values(velocity, acceleration)
    candles = _make_flat_candles(length=25, close=100.0)

    state = detect_divergence_from_abc(abc, candles, vacc)
    assert state.exists is False
    assert state.grade == DivergenceGrade.WEAK


def test_valid_abc_with_impulse_but_no_weakness_is_weak_and_unofficial() -> None:
    a = _leg(2, 6, Direction.UP, low=90.0, high=110.0)
    b = _leg(7, 9, Direction.DOWN, low=98.0, high=109.0)
    c = _leg(10, 14, Direction.UP, low=97.0, high=111.0)
    abc = _abc(DivergenceDirection.BEARISH, a, b, c)

    velocity = [0.0] * 30
    acceleration = [0.0] * 30
    for idx in range(2, 7):
        velocity[idx] = 1.0
        acceleration[idx] = 0.2
    for idx in range(10, 15):
        velocity[idx] = 1.0
        acceleration[idx] = 0.2
    vacc = _vacc_with_values(velocity, acceleration)

    candles = _make_flat_candles(length=25, close=100.0)
    candles[15] = _candle(106.0, 107.0, 99.0, 99.4, 15)
    candles[14] = _candle(105.5, 106.5, 104.0, 106.0, 14)

    state = detect_divergence_from_abc(abc, candles, vacc)
    assert state.exists is False
    assert state.grade == DivergenceGrade.WEAK


def test_grade_function_for_weakening_levels() -> None:
    assert grade_divergence(True, 3, True) == DivergenceGrade.ELITE
    assert grade_divergence(True, 2, True) == DivergenceGrade.STRONG
    assert grade_divergence(True, 1, True) == DivergenceGrade.MODERATE
    assert grade_divergence(True, 0, True) == DivergenceGrade.WEAK
    assert grade_divergence(True, 2, False) == DivergenceGrade.WEAK
    assert grade_divergence(False, 3, True) == DivergenceGrade.INVALID


def test_impulse_detection_rejects_weak_close_and_large_wick() -> None:
    a = _leg(2, 6, Direction.UP, low=90.0, high=110.0)
    b = _leg(7, 9, Direction.DOWN, low=98.0, high=109.0)
    c = _leg(10, 14, Direction.UP, low=97.0, high=111.0)
    abc = _abc(DivergenceDirection.BEARISH, a, b, c)

    candles = _make_flat_candles(length=25, close=100.0)
    candles[14] = _candle(105.0, 106.0, 103.0, 105.8, 14)
    candles[15] = _candle(105.2, 108.0, 104.8, 106.5, 15)

    assert detect_opposite_impulse(candles, abc, lookahead=5, body_multiplier=1.2) is False


def test_price_zone_uses_segment_c_extreme_area() -> None:
    a = _leg(2, 6, Direction.UP, low=90.0, high=110.0)
    b = _leg(7, 9, Direction.DOWN, low=98.0, high=109.0)
    c = _leg(10, 14, Direction.UP, low=97.0, high=111.5)
    abc = _abc(DivergenceDirection.BEARISH, a, b, c)

    velocity = [0.0] * 30
    acceleration = [0.0] * 30
    for idx in range(2, 7):
        velocity[idx] = 2.0
        acceleration[idx] = 0.4
    for idx in range(10, 15):
        velocity[idx] = 0.6
        acceleration[idx] = 0.1
    vacc = _vacc_with_values(velocity, acceleration)

    candles = _make_flat_candles(length=25, close=100.0)
    candles[15] = _candle(106.0, 107.0, 99.0, 99.4, 15)
    candles[14] = _candle(105.5, 106.5, 104.0, 106.0, 14)

    state = detect_divergence_from_abc(abc, candles, vacc)
    assert state.price_zone is not None
    assert "111." in state.price_zone


def test_compare_segment_energy_zero_axis_reset_counts_as_weakening() -> None:
    a = _leg(1, 3, Direction.UP, low=90.0, high=100.0)
    b = _leg(4, 6, Direction.DOWN, low=95.0, high=99.0)
    c = _leg(7, 9, Direction.UP, low=94.0, high=101.0)
    abc = _abc(DivergenceDirection.BEARISH, a, b, c)

    velocity = [0.0, 0.8, 0.7, 0.6, 0.0, -0.1, 0.05, 0.7, 0.7, 0.7, 0.0]
    acceleration = [0.0] * len(velocity)
    vacc = _vacc_with_values(velocity, acceleration)

    result = compare_segment_energy(abc, vacc)
    assert result["zero_axis_reset"] is True
    assert result["weakening_count"] >= 1
