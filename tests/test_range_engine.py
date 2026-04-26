"""Tests for deterministic range (Zhongshu) detection from legs."""

from __future__ import annotations

from ocean_engine.models.enums import Direction
from ocean_engine.models.market import Leg
from ocean_engine.structure.range_engine import (
    calculate_leg_overlap,
    classify_price_location,
    detect_range_from_legs,
)


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


def test_no_range_if_fewer_than_three_legs() -> None:
    legs = [_leg(0, 5, 90.0, 110.0), _leg(6, 10, 92.0, 112.0, direction=Direction.DOWN)]
    state = detect_range_from_legs(legs, current_price=100.0, timeframe="1h")
    assert state.is_range is False
    assert state.active is False
    assert state.leg_count == 0


def test_no_range_if_three_legs_do_not_overlap() -> None:
    legs = [
        _leg(0, 5, 90.0, 95.0),
        _leg(6, 10, 100.0, 105.0, direction=Direction.DOWN),
        _leg(11, 15, 110.0, 120.0),
    ]
    state = detect_range_from_legs(legs, current_price=103.0, timeframe="1h")
    assert state.is_range is False
    assert state.active is False


def test_valid_range_if_three_legs_overlap() -> None:
    legs = [
        _leg(0, 5, 90.0, 120.0),
        _leg(6, 10, 95.0, 115.0, direction=Direction.DOWN),
        _leg(11, 15, 100.0, 118.0),
    ]
    state = detect_range_from_legs(legs, current_price=110.0, timeframe="1h")
    assert state.is_range is True
    assert state.active is True
    assert state.leg_count == 3


def test_correct_zd_zg_calculation() -> None:
    legs = [
        _leg(0, 5, 90.0, 120.0),
        _leg(6, 10, 97.0, 116.0, direction=Direction.DOWN),
        _leg(11, 15, 95.0, 118.0),
    ]
    overlap = calculate_leg_overlap(legs)
    assert overlap == (97.0, 116.0)

    state = detect_range_from_legs(legs, current_price=108.0, timeframe="1h")
    assert state.pivot_low == 97.0
    assert state.pivot_high == 116.0


def test_correct_outer_edges_and_midpoint() -> None:
    legs = [
        _leg(0, 5, 91.0, 125.0),
        _leg(6, 10, 94.0, 117.0, direction=Direction.DOWN),
        _leg(11, 15, 96.0, 121.0),
    ]
    state = detect_range_from_legs(legs, current_price=103.0, timeframe="1h")
    assert state.lower_edge == 91.0
    assert state.upper_edge == 125.0
    assert state.midpoint == 108.0


def test_price_location_lower_edge() -> None:
    assert classify_price_location(91.0, lower_edge=90.0, upper_edge=110.0) == "LOWER_EDGE"


def test_price_location_upper_edge() -> None:
    assert classify_price_location(109.0, lower_edge=90.0, upper_edge=110.0) == "UPPER_EDGE"


def test_price_location_mid() -> None:
    assert classify_price_location(100.0, lower_edge=90.0, upper_edge=110.0) == "MID"


def test_price_location_outside() -> None:
    assert classify_price_location(112.0, lower_edge=90.0, upper_edge=110.0) == "OUTSIDE"


def test_selects_most_recent_valid_range_when_multiple_exist() -> None:
    # Multiple windows ending at latest leg are valid; larger leg count should win.
    legs = [
        _leg(0, 5, 80.0, 120.0),
        _leg(6, 10, 90.0, 116.0, direction=Direction.DOWN),
        _leg(11, 15, 95.0, 112.0),
        _leg(16, 20, 97.0, 109.0, direction=Direction.DOWN),
    ]
    state = detect_range_from_legs(legs, current_price=103.0, timeframe="1h", min_legs=3, max_legs=4)
    assert state.is_range is True
    assert state.start_index == 0
    assert state.end_index == 20
    assert state.leg_count == 4
