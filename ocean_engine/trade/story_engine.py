"""Parent/current move story synthesis for framework context."""

from __future__ import annotations

from ocean_engine.models.enums import Direction, MarketState, SetupType
from ocean_engine.models.market import (
    ActiveTradeAudit,
    ActiveTradeCandidate,
    DivergenceAudit,
    MoveContext,
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
    selected_trade = select_active_trade(active_trade_audit)
    move_context = build_move_context(structures=structures, selected_trade=selected_trade)

    controlling_origin = ""
    if multi_level_story is not None:
        controlling_origin = multi_level_story.controlling_origin
    active_execution_trade = (
        getattr(selected_trade, "type_label", "") if selected_trade is not None and selected_trade.exists else ""
    )
    if not active_execution_trade and multi_level_story is not None:
        active_execution_trade = multi_level_story.active_execution_trade
    carrying_timeframe = (
        getattr(selected_trade, "carry_timeframe", "")
        if selected_trade is not None and selected_trade.exists
        else ""
    )
    if not carrying_timeframe and multi_level_story is not None:
        carrying_timeframe = multi_level_story.carrying_timeframe

    story_summary = f"{move_context.summary} | carry={carrying_timeframe or 'NONE'}"
    return StoryState(
        highest_relevant_tf=highest_relevant_tf,
        parent_timeframe=move_context.parent_timeframe,
        parent_direction=move_context.parent_direction,
        parent_state=move_context.parent_state,
        parent_active=bool(move_context.parent_active),
        current_move_timeframe=move_context.current_timeframe,
        current_move_direction=move_context.current_direction,
        current_move_origin=move_context.current_origin,
        current_move_with_parent=bool(move_context.current_with_parent) if move_context.current_with_parent is not None else False,
        controlling_origin=controlling_origin,
        active_execution_trade=active_execution_trade,
        carrying_timeframe=carrying_timeframe,
        move_context=move_context,
        summary=story_summary,
    )


def build_move_context(
    *,
    structures: dict[str, StructureState],
    selected_trade: ActiveTradeCandidate | None,
) -> MoveContext:
    """Build explicit parent/current move separation context."""

    highest_relevant_tf = _highest_relevant_timeframe(structures)
    parent_tf = _resolve_parent_timeframe(structures, highest_relevant_tf)
    parent_state = structures.get(parent_tf).market_state if parent_tf in structures else MarketState.UNCLEAR
    parent_direction = _resolve_parent_direction(structures.get(parent_tf))
    parent_active = parent_state in {MarketState.TREND, MarketState.RANGE}

    current_tf = ""
    current_direction = Direction.UNCLEAR
    current_state = MarketState.UNCLEAR
    current_origin = "UNCLEAR"
    current_origin_price_zone: str | None = None
    current_with_parent: bool | None = None

    if selected_trade is not None and selected_trade.exists:
        current_tf = selected_trade.origin_timeframe
        current_direction = _candidate_direction(selected_trade)
        current_state = _resolve_current_state(structures.get(current_tf))
        current_origin = _origin_from_setup(selected_trade.setup_type)
        current_origin_price_zone = selected_trade.origin_price_zone or None

    if (
        parent_direction in {Direction.UP, Direction.DOWN}
        and current_direction in {Direction.UP, Direction.DOWN}
    ):
        current_with_parent = current_direction == parent_direction

    if current_tf and current_tf == parent_tf:
        # Parent/current cannot collapse into one label.
        current_origin = "UNCLEAR"
        current_with_parent = None

    parent_dir_label = parent_direction.value if isinstance(parent_direction, Direction) else str(parent_direction)
    current_dir_label = current_direction.value if isinstance(current_direction, Direction) else str(current_direction)
    parent_state_label = parent_state.value if isinstance(parent_state, MarketState) else str(parent_state)
    current_state_label = current_state.value if isinstance(current_state, MarketState) else str(current_state)
    if current_with_parent is True:
        alignment = "WITH_PARENT"
    elif current_with_parent is False:
        alignment = "AGAINST_PARENT"
    else:
        alignment = "UNCLEAR"
    summary = (
        f"parent={parent_tf or 'UNCLEAR'} {parent_dir_label} {parent_state_label} | "
        f"current={current_tf or 'UNCLEAR'} {current_dir_label} {current_state_label} | "
        f"origin={current_origin} zone={current_origin_price_zone or 'N/A'} | {alignment}"
    )
    return MoveContext(
        parent_direction=parent_dir_label,
        parent_timeframe=parent_tf,
        parent_state=parent_state_label,
        parent_active=parent_active if parent_tf else None,
        current_direction=current_dir_label,
        current_timeframe=current_tf,
        current_state=current_state_label,
        current_origin=current_origin,
        current_origin_price_zone=current_origin_price_zone,
        current_with_parent=current_with_parent,
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


def _resolve_current_state(state: StructureState | None) -> MarketState:
    if state is None:
        return MarketState.UNCLEAR
    return state.market_state if state.market_state is not None else MarketState.UNCLEAR


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
