"""Tests for divergence detection from validated A-B-C structures."""

from __future__ import annotations

from ocean_abc_validator import ABCValidationResult
from ocean_engine.divergence.divergence_engine import (
    compare_segment_energy,
    compare_vacc_energy_a_vs_c,
    detect_divergence_from_abc,
    detect_opposite_impulse,
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


def _abc_result(
    *,
    valid: bool = True,
    direction: str = "BEARISH",
    b_reset_valid: bool = True,
    c_test_valid: bool = True,
) -> ABCValidationResult:
    return ABCValidationResult(
        timeframe="1h",
        direction=direction,
        valid=valid,
        segment_a=type("Seg", (), {"start_index": 2, "end_index": 6, "high": 110.0, "low": 90.0})(),
        segment_b=type("Seg", (), {"start_index": 7, "end_index": 9, "high": 109.0, "low": 98.0})(),
        segment_c=type("Seg", (), {"start_index": 10, "end_index": 14, "high": 111.5, "low": 97.0})(),
        b_reset_valid=b_reset_valid,
        c_test_valid=c_test_valid,
        same_timeframe_valid=True,
        reason="test",
    )


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
    candles[16] = _candle(99.5, 100.0, 98.5, 98.9, 16)
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
    candles[16] = _candle(100.5, 102.0, 100.1, 101.3, 16)
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
    # Add a strong post-C impulse candle so classifier can isolate missing carry/quality.
    candles[15] = _candle(106.0, 107.0, 99.0, 99.4, 15)
    candles[14] = _candle(105.5, 106.5, 104.0, 106.0, 14)

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
    # Keep B segment away from zero so zero-axis reset is not counted as weakening.
    for idx in range(7, 10):
        velocity[idx] = 0.6
        acceleration[idx] = 0.05
    vacc = _vacc_with_values(velocity, acceleration)

    candles = _make_flat_candles(length=25, close=100.0)
    candles[15] = _candle(106.0, 107.0, 99.0, 99.4, 15)
    candles[14] = _candle(105.5, 106.5, 104.0, 106.0, 14)

    state = detect_divergence_from_abc(abc, candles, vacc)
    assert state.exists is False
    assert state.grade == DivergenceGrade.WEAK


def test_divergence_wait_when_impulse_is_weak_warning_only() -> None:
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
    # Trigger impulse then immediate erase to force weak impulse warning.
    candles[14] = _candle(105.5, 106.5, 104.0, 106.0, 14)
    candles[15] = _candle(106.0, 107.0, 99.0, 99.4, 15)
    candles[16] = _candle(99.4, 106.2, 99.2, 105.8, 16)

    state = detect_divergence_from_abc(abc, candles, vacc)
    assert state.exists is False
    assert state.grade == DivergenceGrade.WEAK
    assert state.impulse_confirmed is False


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


def test_official_divergence_includes_event_price_and_time_metadata() -> None:
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
    candles[14] = _candle(105.5, 111.8, 104.0, 111.5, 14)
    candles[15] = _candle(111.2, 111.6, 103.0, 103.2, 15)

    state = detect_divergence_from_abc(abc, candles, vacc)
    assert state.divergence_price is not None
    assert state.divergence_price == candles[14].close
    assert state.divergence_time_utc
    assert state.divergence_time_utc.startswith("1970-01-01T")
    assert state.impulse_confirmed is True
    assert state.impulse_price is not None
    assert state.impulse_price == candles[15].close
    assert state.impulse_time_utc
    assert state.impulse_time_utc.startswith("1970-01-01T")


def test_compare_segment_energy_zero_axis_reset_counts_as_weakening() -> None:
    a = _leg(1, 3, Direction.UP, low=90.0, high=100.0)
    b = _leg(4, 6, Direction.DOWN, low=95.0, high=99.0)
    c = _leg(7, 9, Direction.UP, low=94.0, high=101.0)
    abc = _abc(DivergenceDirection.BEARISH, a, b, c)

    velocity = [0.0, 0.8, 0.7, 0.6, 0.0, -0.1, 0.05, 0.7, 0.7, 0.7, 0.0]
    acceleration = [0.0] * len(velocity)
    vacc = _vacc_with_values(velocity, acceleration)

    result = compare_segment_energy(abc, vacc)
    assert result["zero_axis_reset"] is False
    assert result["weakening_count"] == 0


def test_compare_vacc_energy_a_vs_c_requires_valid_abc_first() -> None:
    abc_result = type(
        "ABCResult",
        (),
        {
            "timeframe": "1h",
            "direction": "BEARISH",
            "valid": False,
            "segment_a": None,
            "segment_b": None,
            "segment_c": None,
        },
    )()
    vacc = _vacc_with_values([0.0] * 20, [0.0] * 20)
    result = compare_vacc_energy_a_vs_c([], abc_result, vacc)
    assert result.valid_energy_weakening is False
    assert "A-B-C invalid" in result.reason


def test_compare_vacc_energy_a_vs_c_needs_two_core_weakenings() -> None:
    abc_result = type(
        "ABCResult",
        (),
        {
            "timeframe": "1h",
            "direction": "BEARISH",
            "valid": True,
            "segment_a": type("Seg", (), {"start_index": 2, "end_index": 6})(),
            "segment_b": type("Seg", (), {"start_index": 7, "end_index": 9})(),
            "segment_c": type("Seg", (), {"start_index": 10, "end_index": 14})(),
        },
    )()
    velocity = [0.0] * 25
    acceleration = [0.0] * 25
    for idx in range(2, 7):
        velocity[idx] = 2.0
        acceleration[idx] = 0.4
    for idx in range(10, 15):
        velocity[idx] = 1.0
        acceleration[idx] = 0.15
    velocity[7] = 0.6
    velocity[8] = 0.7
    velocity[9] = 0.6
    vacc = _vacc_with_values(velocity, acceleration)
    result = compare_vacc_energy_a_vs_c([], abc_result, vacc)
    assert result.vel_weaker is True
    assert result.acc_weaker is True
    assert result.valid_energy_weakening is True


def test_compare_vacc_energy_single_component_is_not_valid_weakening() -> None:
    abc_result = type(
        "ABCResult",
        (),
        {
            "timeframe": "1h",
            "direction": "BEARISH",
            "valid": True,
            "segment_a": type("Seg", (), {"start_index": 2, "end_index": 6})(),
            "segment_b": type("Seg", (), {"start_index": 7, "end_index": 9})(),
            "segment_c": type("Seg", (), {"start_index": 10, "end_index": 14})(),
        },
    )()
    velocity = [0.0] * 25
    acceleration = [0.0] * 25
    for idx in range(2, 7):
        velocity[idx] = 2.0
        acceleration[idx] = 0.4
    for idx in range(10, 15):
        velocity[idx] = 1.5
        acceleration[idx] = 0.42
    velocity[7] = 0.8
    velocity[8] = 0.7
    velocity[9] = 0.75
    vacc = _vacc_with_values(velocity, acceleration)
    result = compare_vacc_energy_a_vs_c([], abc_result, vacc)
    assert result.vel_weaker is True
    assert result.acc_weaker is False
    assert result.acc_area_weaker is False
    assert result.valid_energy_weakening is False


def test_detect_divergence_invalid_when_validator_fails_even_if_abc_candidate_true() -> None:
    a = _leg(2, 6, Direction.UP, low=90.0, high=110.0)
    b = _leg(7, 9, Direction.DOWN, low=98.0, high=109.0)
    c = _leg(10, 14, Direction.UP, low=97.0, high=111.0)
    abc = _abc(DivergenceDirection.BEARISH, a, b, c, abc_valid=True)

    vacc = _vacc_with_values([0.0] * 30, [0.0] * 30)
    candles = _make_flat_candles(length=25, close=100.0)
    state = detect_divergence_from_abc(
        abc,
        candles,
        vacc,
        abc_validation=_abc_result(valid=False),
    )
    assert state.exists is False
    assert state.grade == DivergenceGrade.INVALID
    assert state.direction == DivergenceDirection.NONE


def test_detect_divergence_requires_valid_energy_weakening_even_with_impulse() -> None:
    a = _leg(2, 6, Direction.UP, low=90.0, high=110.0)
    b = _leg(7, 9, Direction.DOWN, low=98.0, high=109.0)
    c = _leg(10, 14, Direction.UP, low=97.0, high=111.0)
    abc = _abc(DivergenceDirection.BEARISH, a, b, c)

    velocity = [0.0] * 25
    acceleration = [0.0] * 25
    for idx in range(2, 7):
        velocity[idx] = 2.0
        acceleration[idx] = 0.4
    for idx in range(10, 15):
        velocity[idx] = 1.8
        acceleration[idx] = 0.4
    velocity[7] = 0.9
    velocity[8] = 0.8
    velocity[9] = 0.85
    vacc = _vacc_with_values(velocity, acceleration)

    candles = _make_flat_candles(length=25, close=100.0)
    candles[15] = _candle(106.0, 107.0, 99.0, 99.4, 15)
    candles[16] = _candle(99.4, 100.1, 98.8, 99.0, 16)
    candles[14] = _candle(105.5, 106.5, 104.0, 106.0, 14)

    state = detect_divergence_from_abc(abc, candles, vacc)
    assert state.impulse_confirmed is True
    assert state.exists is False


def test_compare_vacc_energy_single_component_is_not_valid_weakening() -> None:
    abc_result = type(
        "ABCResult",
        (),
        {
            "timeframe": "1h",
            "direction": "BEARISH",
            "valid": True,
            "segment_a": type("Seg", (), {"start_index": 2, "end_index": 6})(),
            "segment_b": type("Seg", (), {"start_index": 7, "end_index": 9})(),
            "segment_c": type("Seg", (), {"start_index": 10, "end_index": 14})(),
        },
    )()
    velocity = [0.0] * 25
    acceleration = [0.0] * 25
    for idx in range(2, 7):
        velocity[idx] = 2.0
        acceleration[idx] = 0.25
    for idx in range(10, 15):
        velocity[idx] = 1.0
        acceleration[idx] = 0.25
    # Keep B above zero: no reset, and acceleration-area equal.
    velocity[7] = 0.4
    velocity[8] = 0.5
    velocity[9] = 0.4
    vacc = _vacc_with_values(velocity, acceleration)
    result = compare_vacc_energy_a_vs_c([], abc_result, vacc)
    assert result.vel_weaker is True
    assert result.acc_weaker is False
    assert result.acc_area_weaker is False
    assert result.valid_energy_weakening is False
