"""Tests for strict standalone ocean carry engine."""

from __future__ import annotations

from ocean_carry_engine import assign_carry_timeframe, classify_carry_state
from ocean_engine.models.enums import Direction
from ocean_engine.models.market import Leg, RangeState, StructureState


def _structure(timeframe: str, active_direction: Direction, *, range_active: bool = False, legs: int = 3) -> StructureState:
    active_leg = Leg(
        start_index=0,
        end_index=legs,
        direction=active_direction,
        high=110.0,
        low=90.0,
        is_active=True,
    )
    return StructureState(
        timeframe=timeframe,
        active_leg=active_leg,
        legs=[active_leg for _ in range(legs)],
        range_state=RangeState(timeframe=timeframe, is_range=range_active, active=range_active),
    )


def test_assign_carry_timeframe_contract_mapping() -> None:
    assert assign_carry_timeframe("4h") == "1h"
    assert assign_carry_timeframe("1h") == "15m"
    assert assign_carry_timeframe("15m") == "5m"
    assert assign_carry_timeframe("5m") == "3m"


def test_classify_carry_state_fresh() -> None:
    context = _structure("15m", Direction.UP, range_active=False, legs=2)
    result = classify_carry_state(
        origin_timeframe="1h",
        direction=Direction.UP,
        lower_tf_context=context,
        opposite_divergence_result=False,
        opposite_impulse_result=False,
    )
    assert result.state in {"FRESH", "ACTIVE"}
    assert result.carry_finished is False


def test_classify_carry_state_exhausting_without_full_finish_when_no_continuation_failure() -> None:
    context = _structure("15m", Direction.UP, range_active=False, legs=3)
    result = classify_carry_state(
        origin_timeframe="1h",
        direction=Direction.UP,
        lower_tf_context=context,
        opposite_divergence_result=True,
        opposite_impulse_result=True,
    )
    assert result.state == "EXHAUSTING"
    assert result.carry_finished is False


def test_classify_carry_state_finished_requires_three_conditions() -> None:
    context = _structure("15m", Direction.DOWN, range_active=False, legs=3)
    result = classify_carry_state(
        origin_timeframe="1h",
        direction=Direction.UP,
        lower_tf_context=context,
        opposite_divergence_result=True,
        opposite_impulse_result=True,
    )
    assert result.state == "EXHAUSTING"
    assert result.carry_finished is True
    assert result.required_lower_cycle_complete == "YES"
