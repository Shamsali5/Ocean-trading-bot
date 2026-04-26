"""Tests for impulse and breakout acceptance validators."""

from __future__ import annotations

from ocean_framework_v12_audit import FrameworkAuditTrace
from ocean_impulse_acceptance import (
    BreakoutAcceptanceResult,
    ImpulseResult,
    validate_breakout_acceptance,
    validate_impulse_after_divergence,
)
from ocean_engine.models.enums import Direction
from ocean_engine.models.market import Candle, RangeState


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


def test_bullish_impulse_confirms_with_structural_break_and_follow_through() -> None:
    candles = [
        _candle(100.0, 100.4, 99.4, 99.6, 0),
        _candle(99.6, 99.8, 98.9, 99.1, 1),
        _candle(99.1, 99.3, 98.5, 98.7, 2),
        _candle(98.7, 101.0, 98.6, 100.9, 3),
        _candle(100.9, 101.8, 100.7, 101.6, 4),
    ]
    result = validate_impulse_after_divergence(
        candles=candles,
        timeframe="15m",
        direction="BULLISH",
        local_pivots={"start_index": 2, "minor_high": 100.0},
    )
    assert isinstance(result, ImpulseResult)
    assert result.confirmed is True
    assert result.grade in {"STRONG", "MODERATE"}
    assert result.trigger_price == candles[3].close


def test_bearish_impulse_rejected_when_immediately_erased() -> None:
    candles = [
        _candle(102.0, 102.6, 101.5, 102.4, 0),
        _candle(102.4, 103.0, 101.9, 102.8, 1),
        _candle(102.8, 103.1, 102.0, 102.9, 2),
        _candle(102.9, 103.0, 100.6, 100.8, 3),
        _candle(100.8, 102.7, 100.7, 102.5, 4),
    ]
    result = validate_impulse_after_divergence(
        candles=candles,
        timeframe="15m",
        direction="BEARISH",
        local_pivots={"start_index": 2, "minor_low": 101.2},
    )
    assert result.confirmed is False
    assert result.grade == "WEAK"
    assert result.immediately_erased is True


def test_breakout_acceptance_requires_full_acceptance_conditions() -> None:
    range_state = RangeState(
        timeframe="15m",
        is_range=True,
        active=True,
        upper_edge=100.0,
        lower_edge=90.0,
        breakout_direction=Direction.UP,
        breakout_confirmed=True,
        acceptance_confirmed=True,
        retest_held=False,
        first_break_index=2,
        first_accepted_close=100.6,
    )
    candles = [
        _candle(99.4, 99.9, 99.1, 99.6, 0),
        _candle(99.6, 100.2, 99.5, 100.1, 1),
        _candle(100.1, 100.9, 99.9, 100.6, 2),
        _candle(100.6, 101.1, 100.4, 100.9, 3),
    ]
    result = validate_breakout_acceptance(
        range_result=range_state,
        candles=candles,
        direction=Direction.UP,
    )
    assert isinstance(result, BreakoutAcceptanceResult)
    assert result.accepted is True
    assert result.boundary_broken is True
    assert result.immediate_reclaim is False


def test_breakout_acceptance_rejects_first_break_with_immediate_reclaim() -> None:
    range_state = RangeState(
        timeframe="15m",
        is_range=True,
        active=True,
        upper_edge=100.0,
        lower_edge=90.0,
        breakout_direction=Direction.UP,
        breakout_confirmed=True,
        acceptance_confirmed=False,
        retest_held=False,
        first_break_index=1,
        first_accepted_close=100.3,
    )
    candles = [
        _candle(99.4, 99.9, 99.1, 99.6, 0),
        _candle(99.6, 100.4, 99.5, 100.3, 1),
        _candle(100.3, 100.4, 99.7, 99.8, 2),
        _candle(99.8, 100.2, 99.6, 99.9, 3),
    ]
    result = validate_breakout_acceptance(
        range_result=range_state,
        candles=candles,
        direction=Direction.UP,
    )
    assert result.accepted is False
    assert result.immediate_reclaim is True


def test_impulse_validator_emits_trace_check() -> None:
    trace = FrameworkAuditTrace(symbol="TEST", timestamp="2026-01-01T00:00:00Z")
    _ = validate_impulse_after_divergence(
        candles=[],
        timeframe="5m",
        direction="BULLISH",
        trace=trace,
    )
    names = {check.name for check in trace.checks}
    assert "Trade-confirmed divergence requires impulse" in names

