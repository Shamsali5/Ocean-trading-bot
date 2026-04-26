"""Final deterministic action selection from active trade context."""

from __future__ import annotations

from ocean_engine.models.enums import CarryState, Direction, FinalAction
from ocean_engine.models.market import (
    ActiveTradeAudit,
    ActiveTradeCandidate,
    DecisionState,
    DivergenceAudit,
    MultiLevelStory,
    StructureState,
    SupplyDemandZone,
)
from ocean_engine.trade.active_trade_engine import select_active_trade
from ocean_engine.trade.guards import apply_decision_guards


def selected_active_trade_or_default(active_trade_audit: ActiveTradeAudit) -> ActiveTradeCandidate:
    """Return selected active trade candidate or canonical empty placeholder."""

    selected = select_active_trade(active_trade_audit)
    if selected is not None:
        return selected
    return ActiveTradeCandidate(
        timeframe="",
        exists=False,
        origin_timeframe="",
        selection_reason="No locked active trade origin exists.",
    )


def management_state_from_carry(carry_state: CarryState) -> str:
    """Map carry state to deterministic management state string."""

    if carry_state in {CarryState.FRESH, CarryState.ACTIVE}:
        return "HOLD"
    if carry_state == CarryState.MATURE:
        return "HOLD_WITH_CAUTION"
    if carry_state == CarryState.EXHAUSTING:
        return "CLOSE_WATCH"
    return "NONE"


def initial_decision_from_active_trade(active_trade: ActiveTradeCandidate) -> DecisionState:
    """Create initial deterministic decision prior to hard guard pass."""

    decision = DecisionState(symbol="", final_action=FinalAction.WAIT, management_state="NONE")
    decision.active_trade_label = active_trade.type_label
    decision.carrying_timeframe = active_trade.carry_timeframe
    decision.fresh_entry_valid = active_trade.fresh_entry_valid
    decision.existing_hold_valid = active_trade.existing_hold_valid
    decision.too_late_to_chase = active_trade.too_late_to_chase

    if not active_trade.exists:
        decision.reason = "No locked active trade origin exists."
        return decision

    carry_finished = (
        active_trade.carry_state == CarryState.EXHAUSTING
        and active_trade.existing_hold_valid
        and active_trade.current_status.upper() == "FINISHED"
    )
    if carry_finished:
        if active_trade.direction == Direction.UP:
            decision.final_action = FinalAction.CLOSE_LONG
        elif active_trade.direction == Direction.DOWN:
            decision.final_action = FinalAction.CLOSE_SHORT
        else:
            decision.final_action = FinalAction.WAIT
        decision.management_state = "FULL_CLOSE"
        decision.reason = "Carry finished via opposite divergence + impulse."
        decision.action = decision.final_action
        return decision

    if active_trade.fresh_entry_valid and not active_trade.too_late_to_chase:
        if active_trade.direction == Direction.UP:
            decision.final_action = FinalAction.BUY
        elif active_trade.direction == Direction.DOWN:
            decision.final_action = FinalAction.SELL
        else:
            decision.final_action = FinalAction.WAIT
        decision.management_state = "HOLD"
        decision.reason = "Fresh entry is valid."
        decision.action = decision.final_action
        return decision

    if active_trade.existing_hold_valid:
        if active_trade.direction == Direction.UP:
            decision.final_action = FinalAction.HOLD_LONG
        elif active_trade.direction == Direction.DOWN:
            decision.final_action = FinalAction.HOLD_SHORT
        else:
            decision.final_action = FinalAction.WAIT
        decision.management_state = management_state_from_carry(active_trade.carry_state)
        decision.reason = "Existing hold remains valid."
        decision.action = decision.final_action
        return decision

    decision.final_action = FinalAction.WAIT
    decision.management_state = "NONE"
    decision.reason = "No clean active trade state."
    decision.action = decision.final_action
    return decision


def build_decision_state(
    structures: dict[str, StructureState],
    divergence_audit: DivergenceAudit,
    active_trade_audit: ActiveTradeAudit,
    multi_level_story: MultiLevelStory | None,
    zones: list[SupplyDemandZone] | None = None,
) -> DecisionState:
    """Build final decision state and apply hard safety guards."""

    selected = selected_active_trade_or_default(active_trade_audit)
    decision = initial_decision_from_active_trade(selected)

    if multi_level_story is not None:
        decision.controlling_origin = multi_level_story.controlling_origin
        decision.active_execution_trade = multi_level_story.active_execution_trade

    guarded = apply_decision_guards(
        decision=decision,
        active_trade=selected if selected.exists else None,
        divergence_audit=divergence_audit,
        structures=structures,
        multi_level_story=multi_level_story,
    )
    guarded.action = guarded.final_action
    return guarded
