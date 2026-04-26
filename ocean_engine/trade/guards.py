"""Hard safety guards for deterministic decision actions."""

from __future__ import annotations

from ocean_engine.models.enums import CarryState, Direction, FinalAction, MarketState, SetupType
from ocean_engine.models.market import (
    ActiveTradeCandidate,
    DecisionState,
    DivergenceAudit,
    MultiLevelStory,
    StructureState,
)

TIMEFRAME_TO_DIVERGENCE_FIELD = {
    "4h": "tf_4h",
    "1h": "tf_1h",
    "15m": "tf_15m",
    "5m": "tf_5m",
    "3m": "tf_3m",
}
BUY_SELL_ACTIONS = {FinalAction.BUY, FinalAction.SELL}


def guard_buy_sell_requires_active_trade(
    decision: DecisionState,
    active_trade: ActiveTradeCandidate | None,
) -> DecisionState:
    """Prevent BUY/SELL when active trade prerequisites are absent."""

    if decision.final_action not in BUY_SELL_ACTIONS:
        return decision
    if active_trade is None or not active_trade.exists:
        return _wait_with_reason(decision, "No active trade candidate for BUY/SELL.")
    if not active_trade.fresh_entry_valid:
        return _wait_with_reason(decision, "Fresh entry is not valid for BUY/SELL.")
    if active_trade.carry_state not in {CarryState.FRESH, CarryState.ACTIVE}:
        return _wait_with_reason(decision, "Carry state must be FRESH or ACTIVE for BUY/SELL.")
    return decision


def guard_type1_requires_same_tf_divergence(
    decision: DecisionState,
    active_trade: ActiveTradeCandidate | None,
    divergence_audit: DivergenceAudit,
) -> DecisionState:
    """Ensure Type 1 candidate has official same-timeframe divergence support."""

    if decision.final_action not in BUY_SELL_ACTIONS:
        return decision
    if active_trade is None or active_trade.setup_type != SetupType.TYPE_1:
        return decision

    field = TIMEFRAME_TO_DIVERGENCE_FIELD.get(active_trade.origin_timeframe)
    if field is None:
        return _wait_with_reason(decision, "Unknown origin timeframe for Type 1 divergence check.")
    row = getattr(divergence_audit, field)
    if not (row.exists and row.abc_valid and row.impulse_confirmed):
        return _wait_with_reason(decision, "Type 1 requires official same-timeframe divergence.")

    expected_direction = Direction.UP if row.direction.value == "BULLISH" else Direction.DOWN
    if row.direction.value not in {"BULLISH", "BEARISH"}:
        return _wait_with_reason(decision, "Type 1 divergence direction is unclear.")
    if active_trade.direction != expected_direction:
        return _wait_with_reason(decision, "Type 1 divergence direction mismatches active trade direction.")
    return decision


def guard_range_midpoint_wait(
    decision: DecisionState,
    structures: dict[str, StructureState],
) -> DecisionState:
    """Force WAIT for fresh entries while a monitored range is at midpoint."""

    if decision.final_action not in BUY_SELL_ACTIONS:
        return decision
    for structure in structures.values():
        range_state = structure.range_state
        if range_state is None:
            continue
        if range_state.active and range_state.price_location == "MID":
            return _wait_with_reason(decision, "Range midpoint requires WAIT for fresh entry.")
    return decision


def guard_exhausting_carry_blocks_entry(
    decision: DecisionState,
    active_trade: ActiveTradeCandidate | None,
) -> DecisionState:
    """Block BUY/SELL when carry is already exhausting."""

    if decision.final_action not in BUY_SELL_ACTIONS:
        return decision
    if active_trade is not None and active_trade.carry_state == CarryState.EXHAUSTING:
        return _wait_with_reason(decision, "Exhausting carry blocks fresh entry.")
    return decision


def guard_no_clear_carry_wait(
    decision: DecisionState,
    active_trade: ActiveTradeCandidate | None,
) -> DecisionState:
    """Require clear carry mapping/state before BUY/SELL."""

    if decision.final_action not in BUY_SELL_ACTIONS:
        return decision
    if active_trade is None:
        return decision
    if not active_trade.carry_timeframe:
        return _wait_with_reason(decision, "Carry timeframe is missing.")
    if active_trade.carry_state == CarryState.UNCLEAR:
        return _wait_with_reason(decision, "Carry state is UNCLEAR.")
    return decision


def guard_no_cross_timeframe_origin_promotion(
    decision: DecisionState,
    active_trade: ActiveTradeCandidate | None,
) -> DecisionState:
    """Prevent suspicious origin/carry timeframe collapse for Type 1 entries."""

    if decision.final_action not in BUY_SELL_ACTIONS:
        return decision
    if active_trade is None:
        return decision
    if (
        active_trade.setup_type == SetupType.TYPE_1
        and active_trade.origin_timeframe
        and active_trade.origin_timeframe == active_trade.carry_timeframe
    ):
        return _wait_with_reason(decision, "Origin timeframe equals carry timeframe for Type 1.")
    return decision


def guard_multilevel_requires_two_official_timeframes(
    decision: DecisionState,
    multi_level_story: MultiLevelStory | None,
) -> DecisionState:
    """Downgrade active multi-level story unless at least two rows confirm."""

    if multi_level_story is None:
        return decision
    if multi_level_story.active and len(multi_level_story.confirmed_timeframes) < 2:
        multi_level_story.active = False
        decision = _add_reason(decision, "Multi-level story downgraded: fewer than two official timeframes.")
    return decision


def apply_decision_guards(
    decision: DecisionState,
    active_trade: ActiveTradeCandidate | None,
    divergence_audit: DivergenceAudit,
    structures: dict[str, StructureState],
    multi_level_story: MultiLevelStory | None,
) -> DecisionState:
    """Apply all deterministic safety guards in stable order."""

    guarded = guard_buy_sell_requires_active_trade(decision, active_trade)
    guarded = guard_type1_requires_same_tf_divergence(guarded, active_trade, divergence_audit)
    guarded = guard_no_clear_carry_wait(guarded, active_trade)
    guarded = guard_exhausting_carry_blocks_entry(guarded, active_trade)
    guarded = guard_range_midpoint_wait(guarded, structures)
    guarded = guard_no_cross_timeframe_origin_promotion(guarded, active_trade)
    guarded = guard_multilevel_requires_two_official_timeframes(guarded, multi_level_story)

    if guarded.guard_reasons:
        guarded.valid = False
        guarded.reason = "; ".join(guarded.guard_reasons)
    else:
        guarded.valid = True
    return guarded


def _wait_with_reason(decision: DecisionState, reason: str) -> DecisionState:
    decision.final_action = FinalAction.WAIT
    decision.action = FinalAction.WAIT
    return _add_reason(decision, reason)


def _add_reason(decision: DecisionState, reason: str) -> DecisionState:
    if reason not in decision.guard_reasons:
        decision.guard_reasons.append(reason)
    return decision
