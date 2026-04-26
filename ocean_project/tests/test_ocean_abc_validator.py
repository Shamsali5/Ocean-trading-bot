"""Tests for strict same-timeframe A-B-C validator."""

from __future__ import annotations

from ocean_framework_v12_audit import FrameworkAuditTrace
from ocean_abc_validator import validate_abc_for_timeframe
from ocean_engine.models.enums import Direction
from ocean_engine.models.market import Candle, Leg, StructureState, VAccPoint, VAccSeries


def _candle(open_: float, high: float, low: float, close: float, idx: int) -> Candle:
    candle = Candle(
        open_time=idx * 60_000,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=1.0,
        close_time=(idx + 1) * 60_000 - 1,
    )
    return candle


def _leg(
    start_index: int,
    end_index: int,
    direction: Direction,
    low: float,
    high: float,
    start_price: float | None = None,
    end_price: float | None = None,
) -> Leg:
    if start_price is None:
        start_price = low if direction == Direction.UP else high
    if end_price is None:
        end_price = high if direction == Direction.UP else low
    leg = Leg(
        start_index=start_index,
        end_index=end_index,
        direction=direction,
        high=high,
        low=low,
        start_price=start_price,
        end_price=end_price,
        start_time=start_index,
        end_time=end_index,
        is_active=False,
    )
    return leg


def _vacc(timeframe: str, points: int = 60) -> VAccSeries:
    return VAccSeries(
        timeframe=timeframe,
        points=[VAccPoint(timestamp=i, velocity=0.0, acceleration=0.0) for i in range(points)],
    )


def test_missing_b_segment_returns_invalid() -> None:
    candles = [_candle(100.0, 101.0, 99.5, 100.5, i) for i in range(20)]
    pivots = [
        _leg(0, 7, Direction.UP, low=95.0, high=110.0),
        _leg(8, 14, Direction.UP, low=100.0, high=112.0),
    ]
    result = validate_abc_for_timeframe(
        candles=candles,
        timeframe="15m",
        direction="BEARISH",
        pivots=pivots,
        vacc=_vacc("15m"),
    )
    assert result.valid is False
    assert result.reason == "Missing A/B/C segment."


def test_invalid_when_c_does_not_retest_a_extreme() -> None:
    candles = [_candle(100.0, 101.0, 99.5, 100.5, i) for i in range(30)]
    pivots = [
        _leg(0, 7, Direction.UP, low=95.0, high=110.0),
        _leg(8, 12, Direction.DOWN, low=104.0, high=109.0),
        _leg(13, 19, Direction.UP, low=103.0, high=108.0),
    ]
    result = validate_abc_for_timeframe(
        candles=candles,
        timeframe="15m",
        direction="BEARISH",
        pivots=pivots,
        vacc=_vacc("15m"),
    )
    assert result.valid is False
    assert result.c_test_valid is False


def test_invalid_on_mixed_timeframe_data() -> None:
    candles = [
        {"open": 100.0, "high": 101.0, "low": 99.5, "close": 100.5, "timeframe": "15m"}
        for _ in range(20)
    ]
    candles.append(
        {"open": 100.0, "high": 101.0, "low": 99.5, "close": 100.5, "timeframe": "5m"}
    )
    pivots = [
        _leg(0, 5, Direction.UP, low=95.0, high=110.0),
        _leg(6, 10, Direction.DOWN, low=102.0, high=109.0),
        _leg(11, 16, Direction.UP, low=101.0, high=111.0),
    ]
    result = validate_abc_for_timeframe(
        candles=candles,
        timeframe="15m",
        direction="BEARISH",
        pivots=pivots,
        vacc=_vacc("15m"),
    )
    assert result.valid is False
    assert result.same_timeframe_valid is False


def test_emits_required_audit_checks() -> None:
    candles = [_candle(100.0, 101.0, 99.5, 100.5, i) for i in range(30)]
    pivots = [
        _leg(0, 7, Direction.UP, low=95.0, high=110.0),
        _leg(8, 12, Direction.DOWN, low=102.0, high=109.0),
        _leg(13, 19, Direction.UP, low=101.0, high=111.0),
    ]
    trace = FrameworkAuditTrace(symbol="TEST", timestamp="2026-01-01T00:00:00Z")
    _ = validate_abc_for_timeframe(
        candles=candles,
        timeframe="15m",
        direction="BEARISH",
        pivots=pivots,
        vacc=_vacc("15m"),
        trace=trace,
    )
    names = {check.name for check in trace.checks}
    assert "A-B-C same timeframe" in names
    assert "Segment B reset valid" in names
    assert "Segment C retest/new extreme valid" in names
    assert "A-B-C valid" in names
