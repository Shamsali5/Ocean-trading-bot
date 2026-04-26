"""Tests for deterministic leg construction from swing sequences."""

from __future__ import annotations

from ocean_engine.models.enums import Direction
from ocean_engine.models.market import Candle, Swing
from ocean_engine.structure.leg_engine import build_legs_from_swings, detect_legs, mark_active_leg


def _make_candles_from_closes(closes: list[float]) -> list[Candle]:
    candles: list[Candle] = []
    for idx, close in enumerate(closes):
        candles.append(
            Candle(
                open_time=idx * 60_000,
                open=close,
                high=close + 0.5,
                low=max(close - 0.5, 0.0001),
                close=close,
                volume=1.0,
                close_time=(idx + 1) * 60_000 - 1,
            )
        )
    return candles


def test_builds_bullish_leg_from_low_to_high_swing() -> None:
    candles = _make_candles_from_closes([100.0, 99.0, 98.0, 100.0, 102.0, 104.0, 105.0, 106.0, 107.0])
    swings = [
        Swing(index=2, price=98.0, direction=Direction.DOWN, timestamp=candles[2].close_time),
        Swing(index=8, price=107.0, direction=Direction.UP, timestamp=candles[8].close_time),
    ]

    legs = build_legs_from_swings(swings, candles, min_leg_bars=5, min_move_pct=0.001)

    assert len(legs) == 1
    leg = legs[0]
    assert leg.direction == Direction.UP
    assert leg.start_index == 2
    assert leg.end_index == 8
    assert leg.start_price == 98.0
    assert leg.end_price == 107.0


def test_builds_bearish_leg_from_high_to_low_swing() -> None:
    candles = _make_candles_from_closes([110.0, 111.0, 112.0, 109.0, 106.0, 103.0, 100.0, 98.0, 96.0])
    swings = [
        Swing(index=2, price=112.0, direction=Direction.UP, timestamp=candles[2].close_time),
        Swing(index=8, price=96.0, direction=Direction.DOWN, timestamp=candles[8].close_time),
    ]

    legs = build_legs_from_swings(swings, candles, min_leg_bars=5, min_move_pct=0.001)

    assert len(legs) == 1
    leg = legs[0]
    assert leg.direction == Direction.DOWN
    assert leg.start_index == 2
    assert leg.end_index == 8
    assert leg.start_price == 112.0
    assert leg.end_price == 96.0


def test_rejects_leg_with_too_few_bars() -> None:
    candles = _make_candles_from_closes([100.0, 99.0, 101.0, 102.0])
    swings = [
        Swing(index=1, price=99.0, direction=Direction.DOWN, timestamp=candles[1].close_time),
        Swing(index=3, price=102.0, direction=Direction.UP, timestamp=candles[3].close_time),
    ]

    legs = build_legs_from_swings(swings, candles, min_leg_bars=5, min_move_pct=0.001)

    assert legs == []


def test_rejects_leg_with_too_small_movement() -> None:
    candles = _make_candles_from_closes([100.0, 99.99, 100.02, 100.01, 100.03, 100.04, 100.05])
    swings = [
        Swing(index=1, price=99.99, direction=Direction.DOWN, timestamp=candles[1].close_time),
        Swing(index=6, price=100.05, direction=Direction.UP, timestamp=candles[6].close_time),
    ]

    legs = build_legs_from_swings(swings, candles, min_leg_bars=5, min_move_pct=0.001)

    assert legs == []


def test_marks_only_latest_leg_as_active() -> None:
    candles = _make_candles_from_closes([100.0 + float(i) for i in range(20)])
    first = build_legs_from_swings(
        [
            Swing(index=1, price=101.0, direction=Direction.UP, timestamp=candles[1].close_time),
            Swing(index=8, price=108.0, direction=Direction.DOWN, timestamp=candles[8].close_time),
        ],
        candles,
        min_leg_bars=5,
        min_move_pct=0.001,
    )[0]
    second = build_legs_from_swings(
        [
            Swing(index=9, price=109.0, direction=Direction.DOWN, timestamp=candles[9].close_time),
            Swing(index=16, price=116.0, direction=Direction.UP, timestamp=candles[16].close_time),
        ],
        candles,
        min_leg_bars=5,
        min_move_pct=0.001,
    )[0]

    marked = mark_active_leg([first, second])

    assert len(marked) == 2
    assert marked[0].is_active is False
    assert marked[1].is_active is True


def test_detect_legs_calls_swing_engine_when_swings_not_supplied(monkeypatch) -> None:
    candles = _make_candles_from_closes([100.0, 98.0, 96.0, 99.0, 103.0, 107.0, 110.0, 112.0, 114.0])
    fake_swings = [
        Swing(index=2, price=96.0, direction=Direction.DOWN, timestamp=candles[2].close_time),
        Swing(index=8, price=114.0, direction=Direction.UP, timestamp=candles[8].close_time),
    ]

    called: dict[str, bool] = {"value": False}

    def _fake_detect_swings(*args, **kwargs) -> list[Swing]:
        called["value"] = True
        return fake_swings

    monkeypatch.setattr("ocean_engine.structure.leg_engine.detect_swings", _fake_detect_swings)

    legs = detect_legs(candles, swings=None, pivot_left=2, pivot_right=2, min_leg_bars=5, min_move_pct=0.001)

    assert called["value"] is True
    assert len(legs) == 1
    assert legs[0].direction == Direction.UP
    assert legs[0].is_active is True
