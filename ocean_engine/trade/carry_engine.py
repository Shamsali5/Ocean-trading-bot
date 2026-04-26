"""Carry timeframe and lifecycle classification from divergence origin."""

from __future__ import annotations

from ocean_engine.models.enums import CarryState, Direction, DivergenceDirection, MarketState
from ocean_engine.models.market import CarryStatus, DivergenceAudit, DivergenceState, StructureState

TIMEFRAME_CARRY_MAP = {
    "4h": "1h",
    "1h": "15m",
    "15m": "5m",
    "5m": "3m",
    "3m": None,
}
TIMEFRAME_TO_AUDIT_FIELD = {
    "4h": "tf_4h",
    "1h": "tf_1h",
    "15m": "tf_15m",
    "5m": "tf_5m",
    "3m": "tf_3m",
}


def get_carry_timeframe(origin_tf: str) -> str | None:
    """Map origin timeframe to its next lower carry timeframe."""

    return TIMEFRAME_CARRY_MAP.get(origin_tf)


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
) -> CarryState:
    """Classify current carry lifecycle state for the mapped carry timeframe."""

    if carry_structure is None or carry_direction in (Direction.NONE, Direction.UNCLEAR):
        return CarryState.UNCLEAR

    active_leg = carry_structure.active_leg
    if active_leg is None:
        return CarryState.UNCLEAR

    opposite_divergence = _is_opposite_divergence(carry_divergence, carry_direction)
    opposite_impulse = bool(opposite_divergence and carry_divergence and carry_divergence.impulse_confirmed)
    if opposite_impulse:
        return CarryState.EXHAUSTING

    range_active = bool(
        carry_structure.range_state is not None
        and carry_structure.range_state.active
    ) or carry_structure.market_state == MarketState.RANGE

    if active_leg.direction != carry_direction:
        return CarryState.MATURE if not opposite_impulse else CarryState.EXHAUSTING

    if range_active:
        return CarryState.MATURE

    leg_count = len(carry_structure.legs)
    if leg_count <= 2:
        return CarryState.FRESH
    return CarryState.ACTIVE


def is_carry_finished(carry_divergence: DivergenceState | None, carry_direction: Direction) -> bool:
    """Determine whether carry is finished by opposite official impulse."""

    if not _is_official_divergence(carry_divergence):
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
) -> CarryStatus:
    """Build carry status from origin timeframe, mapped carry row, and structure."""

    carry_tf = get_carry_timeframe(origin_tf)
    carry_direction = direction_from_divergence(origin_direction)
    if carry_tf is None:
        return CarryStatus(
            timeframe=origin_tf,
            direction=carry_direction,
            state=CarryState.UNCLEAR,
            cycle_complete="UNCLEAR",
            summary=f"No lower carry timeframe for origin {origin_tf}.",
        )

    carry_structure = structures.get(carry_tf)
    carry_divergence = _get_divergence_row(divergence_audit, carry_tf)

    opposite_divergence = _is_opposite_divergence(carry_divergence, carry_direction)
    opposite_impulse = bool(opposite_divergence and carry_divergence and carry_divergence.impulse_confirmed)
    finished = is_carry_finished(carry_divergence, carry_direction)

    state = classify_carry_state(
        carry_structure=carry_structure,
        carry_direction=carry_direction,
        carry_divergence=carry_divergence,
    )

    cycle_complete = "YES" if finished else "NO" if state != CarryState.UNCLEAR else "UNCLEAR"
    summary = (
        f"Origin {origin_tf} -> carry {carry_tf}, direction={carry_direction.value}, "
        f"state={state.value}, opposite_divergence={opposite_divergence}, "
        f"opposite_impulse={opposite_impulse}, finished={finished}"
    )
    return CarryStatus(
        timeframe=carry_tf,
        direction=carry_direction,
        state=state,
        cycle_complete=cycle_complete,
        opposite_divergence=opposite_divergence,
        opposite_impulse=opposite_impulse,
        finished=finished,
        summary=summary,
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
