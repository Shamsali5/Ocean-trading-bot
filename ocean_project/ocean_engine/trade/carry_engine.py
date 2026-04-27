"""Carry timeframe and lifecycle classification from divergence origin."""

from __future__ import annotations

from ocean_carry_engine import (
    assign_carry_timeframe,
    classify_carry_state as strict_classify_carry_state,
)
from ocean_engine.models.enums import CarryState, Direction, DivergenceDirection
from ocean_engine.models.market import CarryStatus, DivergenceAudit, DivergenceState, StructureState

TIMEFRAME_TO_AUDIT_FIELD = {
    "4h": "tf_4h",
    "1h": "tf_1h",
    "15m": "tf_15m",
    "5m": "tf_5m",
    "3m": "tf_3m",
}


def get_carry_timeframe(origin_tf: str) -> str | None:
    """Map origin timeframe to its next lower carry timeframe."""

    return assign_carry_timeframe(origin_tf)


def direction_from_divergence(divergence_direction: DivergenceDirection) -> Direction:
    """Map divergence direction into carry direction."""

    if divergence_direction == DivergenceDirection.BULLISH:
        return Direction.UP
    if divergence_direction == DivergenceDirection.BEARISH:
        return Direction.DOWN
    return Direction.UNCLEAR


def classify_carry_state(
    carry_structure: StructureState | None,
    carry_direction: Direction,
    carry_divergence: DivergenceState | None = None,
    origin_timeframe: str | None = None,
    trace: object | None = None,
) -> CarryState:
    """Classify current carry lifecycle state for the mapped carry timeframe."""

    opposite_divergence = _is_opposite_divergence(carry_divergence, carry_direction)
    opposite_impulse = bool(opposite_divergence and carry_divergence and carry_divergence.impulse_confirmed)
    strict_origin = (origin_timeframe or "").strip() or _infer_origin_timeframe(carry_structure)
    strict = strict_classify_carry_state(
        origin_timeframe=strict_origin,
        direction=carry_direction,
        lower_tf_context=carry_structure,
        opposite_divergence_result=opposite_divergence,
        opposite_impulse_result=opposite_impulse,
        trace=trace,
    )
    return _carry_state_from_text(strict.state)


def is_carry_finished(
    carry_divergence: DivergenceState | None,
    carry_direction: Direction,
    *,
    continuation_failed: bool,
) -> bool:
    """Determine whether carry is finished by strict opposite conditions."""

    if not _is_official_divergence(carry_divergence):
        return False
    if not continuation_failed:
        return False
    if carry_direction == Direction.UP and carry_divergence.direction == DivergenceDirection.BEARISH:
        return True
    if carry_direction == Direction.DOWN and carry_divergence.direction == DivergenceDirection.BULLISH:
        return True
    return False


def build_carry_status(
    origin_tf: str,
    origin_direction: DivergenceDirection,
    structures: dict[str, StructureState],
    divergence_audit: DivergenceAudit,
    trace: object | None = None,
) -> CarryStatus:
    """Build carry status from origin timeframe, mapped carry row, and structure."""

    carry_tf = get_carry_timeframe(origin_tf)
    carry_direction = direction_from_divergence(origin_direction)
    if carry_tf is None:
        return CarryStatus(
            timeframe="",
            direction=carry_direction,
            state=CarryState.UNCLEAR,
            cycle_complete="UNCLEAR",
            summary=f"No lower carry timeframe for origin {origin_tf}.",
        )

    carry_structure = structures.get(carry_tf)
    carry_divergence = _get_divergence_row(divergence_audit, carry_tf)

    opposite_divergence = _is_opposite_divergence(carry_divergence, carry_direction)
    opposite_impulse = bool(opposite_divergence and carry_divergence and carry_divergence.impulse_confirmed)
    strict = strict_classify_carry_state(
        origin_timeframe=origin_tf,
        direction=carry_direction,
        lower_tf_context=carry_structure,
        opposite_divergence_result=opposite_divergence,
        opposite_impulse_result=opposite_impulse,
        trace=trace,
    )
    state = _carry_state_from_text(strict.state)
    finished = bool(strict.carry_finished)

    cycle_complete = strict.required_lower_cycle_complete
    summary = strict.reason
    return CarryStatus(
        timeframe=carry_tf,
        direction=carry_direction,
        state=state,
        cycle_complete=cycle_complete,
        opposite_divergence=opposite_divergence,
        opposite_impulse=opposite_impulse,
        finished=finished,
        summary=summary,
        notes=summary,
    )


def _get_divergence_row(audit: DivergenceAudit, timeframe: str) -> DivergenceState | None:
    field = TIMEFRAME_TO_AUDIT_FIELD.get(timeframe)
    if field is None:
        return None
    return getattr(audit, field)


def _is_opposite_divergence(state: DivergenceState | None, carry_direction: Direction) -> bool:
    if not _is_official_divergence(state):
        return False
    if carry_direction == Direction.UP:
        return state.direction == DivergenceDirection.BEARISH
    if carry_direction == Direction.DOWN:
        return state.direction == DivergenceDirection.BULLISH
    return False


def _is_official_divergence(state: DivergenceState | None) -> bool:
    if state is None:
        return False
    return bool(
        state.exists
        and state.abc_valid
        and state.impulse_confirmed
        and state.direction in (DivergenceDirection.BULLISH, DivergenceDirection.BEARISH)
    )


def _carry_state_from_text(state: str) -> CarryState:
    value = str(state or "").strip().upper()
    if value == CarryState.FRESH.value:
        return CarryState.FRESH
    if value == CarryState.ACTIVE.value:
        return CarryState.ACTIVE
    if value == CarryState.MATURE.value:
        return CarryState.MATURE
    if value == CarryState.EXHAUSTING.value:
        return CarryState.EXHAUSTING
    return CarryState.UNCLEAR


def _infer_origin_timeframe(carry_structure: StructureState | None) -> str:
    """Infer origin timeframe from carry timeframe for legacy callers."""

    carry_tf = getattr(carry_structure, "timeframe", "") if carry_structure is not None else ""
    reverse_map = {
        "1h": "4h",
        "15m": "1h",
        "5m": "15m",
        "3m": "5m",
    }
    return reverse_map.get(carry_tf, "")
