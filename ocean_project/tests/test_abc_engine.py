"""Tests for same-timeframe structural A-B-C candidate detection."""

from __future__ import annotations

from ocean_engine.models.enums import Direction, DivergenceDirection
from ocean_engine.models.market import ABCStructure, Leg, StructureState
from ocean_engine.divergence.abc_engine import find_abc_candidates, select_latest_abc_candidate


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
    return Leg(
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


def _structure(timeframe: str, legs: list[Leg]) -> StructureState:
    return StructureState(timeframe=timeframe, legs=legs)


def test_detects_bearish_up_down_up_abc() -> None:
    legs = [
        _leg(0, 6, Direction.UP, low=90.0, high=110.0),
        _leg(7, 12, Direction.DOWN, low=101.0, high=109.0),
        _leg(13, 20, Direction.UP, low=100.0, high=111.0),
    ]
    candidates = find_abc_candidates(_structure("1h", legs))
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.direction == DivergenceDirection.BEARISH
    assert candidate.timeframe == "1h"
    assert candidate.abc_valid is True


def test_detects_bullish_down_up_down_abc() -> None:
    legs = [
        _leg(0, 6, Direction.DOWN, low=90.0, high=110.0),
        _leg(7, 12, Direction.UP, low=91.0, high=100.0),
        _leg(13, 20, Direction.DOWN, low=89.9, high=101.0),
    ]
    candidates = find_abc_candidates(_structure("15m", legs))
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.direction == DivergenceDirection.BULLISH
    assert candidate.timeframe == "15m"
    assert candidate.abc_valid is True


def test_rejects_wrong_leg_sequence() -> None:
    legs = [
        _leg(0, 6, Direction.UP, low=90.0, high=110.0),
        _leg(7, 12, Direction.UP, low=99.0, high=115.0),
        _leg(13, 20, Direction.DOWN, low=100.0, high=114.0),
    ]
    candidates = find_abc_candidates(_structure("1h", legs))
    assert candidates == []


def test_rejects_invalid_b_reset_if_too_small_and_too_short() -> None:
    legs = [
        _leg(0, 10, Direction.UP, low=90.0, high=110.0),
        _leg(
            11,
            12,
            Direction.DOWN,
            low=109.95,
            high=110.0,
            start_price=110.0,
            end_price=109.95,
        ),
        _leg(13, 20, Direction.UP, low=100.0, high=111.0),
    ]
    candidates = find_abc_candidates(_structure("1h", legs), min_reset_pct=0.001, min_reset_bars=3)
    assert candidates == []


def test_accepts_c_near_retest_within_tolerance() -> None:
    legs = [
        _leg(0, 6, Direction.UP, low=90.0, high=110.0),
        _leg(7, 12, Direction.DOWN, low=102.0, high=109.0),
        _leg(13, 20, Direction.UP, low=101.0, high=109.95),
    ]
    candidates = find_abc_candidates(_structure("1h", legs), retest_tolerance_pct=0.001)
    assert len(candidates) == 1
    assert candidates[0].c_retest_valid is True


def test_rejects_c_that_does_not_retest_a_extreme() -> None:
    legs = [
        _leg(0, 6, Direction.DOWN, low=90.0, high=110.0),
        _leg(7, 12, Direction.UP, low=91.0, high=101.0),
        _leg(13, 20, Direction.DOWN, low=90.3, high=102.0),
    ]
    candidates = find_abc_candidates(_structure("1h", legs), retest_tolerance_pct=0.001)
    assert candidates == []


def test_select_latest_abc_candidate_chooses_latest_c_end_index() -> None:
    first = ABCStructure(
        timeframe="1h",
        a_index=0,
        b_index=1,
        c_index=2,
        direction=DivergenceDirection.BEARISH,
        abc_valid=True,
    )
    second = ABCStructure(
        timeframe="1h",
        a_index=3,
        b_index=4,
        c_index=8,
        direction=DivergenceDirection.BULLISH,
        abc_valid=True,
    )
    latest = select_latest_abc_candidate([first, second])
    assert latest is second


def test_same_timeframe_preserved_in_candidate() -> None:
    legs = [
        _leg(0, 6, Direction.UP, low=90.0, high=110.0),
        _leg(7, 12, Direction.DOWN, low=101.0, high=109.0),
        _leg(13, 20, Direction.UP, low=100.0, high=111.0),
    ]
    structure = _structure("5m", legs)
    candidate = find_abc_candidates(structure)[0]
    assert candidate.timeframe == "5m"
