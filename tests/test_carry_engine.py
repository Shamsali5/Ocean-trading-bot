"""Tests for deterministic carry engine mapping and state classification."""

from __future__ import annotations

from ocean_engine.models.enums import CarryState, Direction, DivergenceDirection
from ocean_engine.models.market import (
    CarryStatus,
    DivergenceAudit,
    DivergenceState,
    Leg,
    RangeState,
    StructureState,
)
from ocean_engine.trade.carry_engine import (
    build_carry_status,
    classify_carry_state,
    direction_from_divergence,
    get_carry_timeframe,
    is_carry_finished,
)


def _active_leg(direction: Direction) -> Leg:
    return Leg(
        start_index=0,
        end_index=8,
        direction=direction,
        low=90.0,
        high=110.0,
        start_price=90.0 if direction == Direction.UP else 110.0,
        end_price=110.0 if direction == Direction.UP else 90.0,
        start_time=0,
        end_time=8,
        is_active=True,
    )


def _structure(timeframe: str, active_leg: Leg | None = None, range_active: bool = False) -> StructureState:
    range_state = RangeState(timeframe=timeframe, active=range_active, is_range=range_active)
    return StructureState(
        timeframe=timeframe,
        active_leg=active_leg,
        range_state=range_state,
        legs=[active_leg] if active_leg is not None else [],
    )


def _divergence_state(
    timeframe: str,
    direction: DivergenceDirection,
    exists: bool = True,
    impulse: bool = False,
) -> DivergenceState:
    return DivergenceState(
        timeframe=timeframe,
        exists=exists,
        direction=direction,
        impulse_confirmed=impulse,
    )


def test_1h_origin_maps_to_15m_carry() -> None:
    assert get_carry_timeframe("1h") == "15m"


def test_15m_origin_maps_to_5m_carry() -> None:
    assert get_carry_timeframe("15m") == "5m"


def test_bullish_origin_maps_to_up_carry() -> None:
    assert direction_from_divergence(DivergenceDirection.BULLISH) == Direction.UP


def test_bearish_origin_maps_to_down_carry() -> None:
    assert direction_from_divergence(DivergenceDirection.BEARISH) == Direction.DOWN


def test_missing_carry_structure_gives_unclear() -> None:
    state = classify_carry_state(None, Direction.UP, None)
    assert state == CarryState.UNCLEAR


def test_matching_active_leg_gives_active_or_fresh() -> None:
    structure = _structure("15m", active_leg=_active_leg(Direction.UP), range_active=False)
    state = classify_carry_state(structure, Direction.UP, None)
    assert state in {CarryState.FRESH, CarryState.ACTIVE}


def test_active_range_gives_mature() -> None:
    structure = _structure("15m", active_leg=_active_leg(Direction.UP), range_active=True)
    state = classify_carry_state(structure, Direction.UP, None)
    assert state == CarryState.MATURE


def test_opposite_divergence_with_impulse_gives_exhausting_and_finished_true() -> None:
    structure = _structure("15m", active_leg=_active_leg(Direction.UP), range_active=False)
    carry_div = _divergence_state("15m", DivergenceDirection.BEARISH, exists=True, impulse=True)
    state = classify_carry_state(structure, Direction.UP, carry_div)
    assert state == CarryState.EXHAUSTING
    assert is_carry_finished(carry_div, Direction.UP) is True


def test_opposite_divergence_without_impulse_does_not_finish_carry() -> None:
    carry_div = _divergence_state("15m", DivergenceDirection.BEARISH, exists=True, impulse=False)
    assert is_carry_finished(carry_div, Direction.UP) is False


def test_build_carry_status_uses_only_carry_timeframe_divergence_row() -> None:
    structures = {
        "15m": _structure("15m", active_leg=_active_leg(Direction.UP), range_active=False),
    }
    audit = DivergenceAudit(
        tf_1h=_divergence_state("1h", DivergenceDirection.BEARISH, exists=True, impulse=True),
        tf_15m=_divergence_state("15m", DivergenceDirection.NONE, exists=False, impulse=False),
    )
    status = build_carry_status(
        origin_tf="1h",
        origin_direction=DivergenceDirection.BULLISH,
        structures=structures,
        divergence_audit=audit,
    )
    assert isinstance(status, CarryStatus)
    assert status.timeframe == "15m"
    assert status.opposite_divergence is False
    assert status.opposite_impulse is False
    assert status.finished is False
