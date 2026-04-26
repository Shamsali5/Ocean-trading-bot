"""Parent/current move story synthesis for framework context."""

from __future__ import annotations

from ocean_engine.models.enums import Direction, MarketState, SetupType
from ocean_engine.models.market import (
    ActiveTradeAudit,
    ActiveTradeCandidate,
    DivergenceAudit,
    MultiLevelStory,
    StoryState,
    StructureState,
    SupplyDemandZone,
)
from ocean_engine.trade.active_trade_engine import select_active_trade

TIMEFRAME_ORDER = ("4h", "1h", "15m", "5m", "3m")
TIMEFRAME_RANK = {"4h": 5, "1h": 4, "15m": 3, "5m": 2, "3m": 1}


def build_story_state(
    *,
    structures: dict[str, StructureState],
    divergence_audit: DivergenceAudit,
    active_trade_audit: ActiveTradeAudit,
    multi_level_story: MultiLevelStory | None,
    range_states: dict[str, object] | None = None,
    ranges: dict[str, object] | None = None,
    zones: list[SupplyDemandZone] | None = None,
) -> StoryState:
    """Build parent/current move context without predictive assumptions."""

    del divergence_audit, range_states, ranges, zones  # Reserved for future story enrichments.

    highest_relevant_tf = _highest_relevant_timeframe(structures)
    parent_tf = _resolve_parent_timeframe(structures, highest_relevant_tf)
    parent_state = structures.get(parent_tf).market_state if parent_tf in structures else MarketState.UNCLEAR
    parent_direction = _resolve_parent_direction(structures.get(parent_tf))
    parent_active = parent_state in {MarketState.TREND, MarketState.RANGE}

    selected_trade = select_active_trade(active_trade_audit)
    current_move_timeframe = ""
    current_move_direction = Direction.UNCLEAR
    current_move_origin = "UNCLEAR"
    carrying_timeframe = ""
    active_execution_trade = ""

    if selected_trade is not None and selected_trade.exists:
        current_move_timeframe = selected_trade.origin_timeframe
        current_move_direction = _candidate_direction(selected_trade)
        current_move_origin = _origin_from_setup(selected_trade.setup_type)
        carrying_timeframe = selected_trade.carry_timeframe
        active_execution_trade = selected_trade.type_label

    controlling_origin = ""
    if multi_level_story is not None:
        controlling_origin = multi_level_story.controlling_origin
        if not active_execution_trade:
            active_execution_trade = multi_level_story.active_execution_trade
        if not carrying_timeframe:
            carrying_timeframe = multi_level_story.carrying_timeframe

    current_move_with_parent = (
        parent_active
        and parent_direction in {Direction.UP, Direction.DOWN}
        and current_move_direction in {Direction.UP, Direction.DOWN}
        and current_move_direction == parent_direction
    )

    parent_direction_label = parent_direction.value if isinstance(parent_direction, Direction) else str(parent_direction)
    current_direction_label = (
        current_move_direction.value if isinstance(current_move_direction, Direction) else str(current_move_direction)
    )
    parent_state_label = parent_state.value if isinstance(parent_state, MarketState) else str(parent_state)
    if current_move_direction not in {Direction.UP, Direction.DOWN}:
        with_parent_label = "UNCLEAR"
    elif current_move_with_parent is True:
        with_parent_label = "WITH_PARENT"
    else:
        with_parent_label = "AGAINST_PARENT"
    summary = (
        f"parent={parent_tf or 'UNCLEAR'} {parent_direction_label} {parent_state_label} | "
        f"current={current_move_timeframe or 'UNCLEAR'} {current_direction_label} | "
        f"origin={current_move_origin} | carry={carrying_timeframe or 'NONE'} | {with_parent_label}"
    )

    return StoryState(
        highest_relevant_tf=highest_relevant_tf,
        parent_timeframe=parent_tf,
        parent_direction=parent_direction,
        parent_state=parent_state,
        parent_active=parent_active,
        current_move_timeframe=current_move_timeframe,
        current_move_direction=current_move_direction,
        current_move_origin=current_move_origin,
        current_move_with_parent=current_move_with_parent,
        controlling_origin=controlling_origin,
        active_execution_trade=active_execution_trade,
        carrying_timeframe=carrying_timeframe,
        summary=summary,
    )


def _highest_relevant_timeframe(structures: dict[str, StructureState]) -> str:
    available = [tf for tf in TIMEFRAME_ORDER if tf in structures]
    if not available:
        return ""
    return max(available, key=lambda tf: TIMEFRAME_RANK.get(tf, 0))


def _resolve_parent_timeframe(structures: dict[str, StructureState], fallback_tf: str) -> str:
    for tf in TIMEFRAME_ORDER:
        state = structures.get(tf)
        if state is None:
            continue
        if state.market_state in {MarketState.TREND, MarketState.RANGE}:
            return tf
    return fallback_tf


def _resolve_parent_direction(state: StructureState | None) -> Direction:
    if state is None:
        return Direction.UNCLEAR
    if state.direction in {Direction.UP, Direction.DOWN}:
        return state.direction
    if state.active_leg is not None and state.active_leg.direction in {Direction.UP, Direction.DOWN}:
        return state.active_leg.direction
    return Direction.UNCLEAR


def _origin_from_setup(setup_type: SetupType) -> str:
    if setup_type == SetupType.TYPE_3:
        return "BREAKOUT"
    if setup_type == SetupType.TYPE_1:
        return "DIVERGENCE"
    if setup_type == SetupType.TYPE_2:
        return "PULLBACK_RESTART"
    return "UNCLEAR"


def _candidate_direction(candidate: ActiveTradeCandidate) -> Direction:
    value = getattr(candidate.direction, "value", candidate.direction)
    if value in (Direction.UP, Direction.DOWN):
        return value
    if str(value).upper() == "BULLISH":
        return Direction.UP
    if str(value).upper() == "BEARISH":
        return Direction.DOWN
    if candidate.carry_direction in {Direction.UP, Direction.DOWN}:
        return candidate.carry_direction
    return Direction.UNCLEAR
