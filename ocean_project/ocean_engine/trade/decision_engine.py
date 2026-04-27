"""Final deterministic action selection from active trade context."""

from __future__ import annotations

from ocean_entry_gate import evaluate_fresh_entry
from ocean_final_action_resolver import resolve_final_action
from ocean_management_gate import evaluate_position_management
from ocean_engine.models.enums import CarryState, Direction, FinalAction, SetupType
from ocean_engine.models.market import (
    ActiveTradeAudit,
    ActiveTradeCandidate,
    DecisionState,
    DivergenceAudit,
    MoveContext,
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


def _normalize_position_mode(position_mode: str) -> str:
    normalized = position_mode.strip().upper()
    if normalized in {"UNKNOWN", "FLAT", "LONG", "SHORT"}:
        return normalized
    return "UNKNOWN"


def _candidate_direction(active_trade: ActiveTradeCandidate) -> Direction:
    """Normalize candidate direction to canonical UP/DOWN enums."""

    value = getattr(active_trade.direction, "value", active_trade.direction)
    if value in (Direction.UP, Direction.DOWN):
        return value
    text = str(value).upper()
    if text == "BULLISH":
        return Direction.UP
    if text == "BEARISH":
        return Direction.DOWN
    if active_trade.carry_direction in {Direction.UP, Direction.DOWN}:
        return active_trade.carry_direction
    return Direction.UNCLEAR


def initial_decision_from_active_trade(
    active_trade: ActiveTradeCandidate,
    *,
    position_mode: str = "UNKNOWN",
) -> DecisionState:
    """Create initial deterministic decision prior to hard guard pass."""

    resolved_position_mode = _normalize_position_mode(position_mode)
    decision = DecisionState(symbol="", final_action=FinalAction.WAIT, management_state="NONE")
    decision.active_trade_label = active_trade.type_label
    decision.carrying_timeframe = active_trade.carry_timeframe
    decision.fresh_entry_valid = active_trade.fresh_entry_valid
    decision.existing_hold_valid = active_trade.existing_hold_valid
    decision.too_late_to_chase = active_trade.too_late_to_chase

    if not active_trade.exists:
        decision.reason = "No locked active trade origin exists."
        return decision

    candidate_direction = _candidate_direction(active_trade)
    carry_finished = (
        active_trade.carry_state == CarryState.EXHAUSTING
        and active_trade.existing_hold_valid
        and active_trade.current_status.upper() == "FINISHED"
    )
    if carry_finished:
        if candidate_direction == Direction.UP:
            decision.final_action = FinalAction.CLOSE_LONG
        elif candidate_direction == Direction.DOWN:
            decision.final_action = FinalAction.CLOSE_SHORT
        else:
            decision.final_action = FinalAction.WAIT
        decision.management_state = "FULL_CLOSE"
        decision.reason = "Carry finished via opposite divergence + impulse."
        decision.action = decision.final_action
        return decision

    if active_trade.fresh_entry_valid and not active_trade.too_late_to_chase:
        if candidate_direction == Direction.UP:
            decision.final_action = FinalAction.BUY
        elif candidate_direction == Direction.DOWN:
            decision.final_action = FinalAction.SELL
        else:
            decision.final_action = FinalAction.WAIT
        decision.management_state = "HOLD"
        decision.reason = "Fresh entry is valid."
        decision.action = decision.final_action
        return decision

    if active_trade.existing_hold_valid and active_trade.too_late_to_chase:
        if resolved_position_mode == "FLAT":
            decision.final_action = FinalAction.WAIT
            decision.reason = "Valid hold only, not fresh entry; flat position mode waits."
        elif candidate_direction == Direction.UP:
            if resolved_position_mode in {"LONG", "UNKNOWN"}:
                decision.final_action = FinalAction.HOLD_LONG
                if resolved_position_mode == "UNKNOWN":
                    decision.reason = "Valid hold only, not fresh entry."
                else:
                    decision.reason = "Existing long hold remains valid."
            else:
                decision.final_action = FinalAction.WAIT
                decision.reason = "Position mode does not permit bullish hold."
        elif candidate_direction == Direction.DOWN:
            if resolved_position_mode in {"SHORT", "UNKNOWN"}:
                decision.final_action = FinalAction.HOLD_SHORT
                if resolved_position_mode == "UNKNOWN":
                    decision.reason = "Valid hold only, not fresh entry."
                else:
                    decision.reason = "Existing short hold remains valid."
            else:
                decision.final_action = FinalAction.WAIT
                decision.reason = "Position mode does not permit bearish hold."
        else:
            decision.final_action = FinalAction.WAIT
            decision.reason = "Valid hold exists but direction is unclear."
        decision.management_state = management_state_from_carry(active_trade.carry_state)
        decision.action = decision.final_action
        return decision

    if active_trade.existing_hold_valid:
        if candidate_direction == Direction.UP:
            decision.final_action = FinalAction.HOLD_LONG
        elif candidate_direction == Direction.DOWN:
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
    position_mode: str = "UNKNOWN",
    move_context: MoveContext | None = None,
    trace=None,
) -> DecisionState:
    """Build final decision state and apply hard safety guards."""

    selected = selected_active_trade_or_default(active_trade_audit)
    resolved_position_mode = _normalize_position_mode(position_mode)
    decision = initial_decision_from_active_trade(selected, position_mode=position_mode)
    entry_decision_payload = {
        "fresh_entry_valid": bool(selected.fresh_entry_valid),
        "side": (
            "BUY"
            if _candidate_direction(selected) == Direction.UP and selected.fresh_entry_valid and not selected.too_late_to_chase
            else "SELL"
            if _candidate_direction(selected) == Direction.DOWN and selected.fresh_entry_valid and not selected.too_late_to_chase
            else None
        ),
        "entry_zone": selected.origin_price_zone,
        "invalidation": selected.invalidation,
        "reason": decision.reason,
    }

    if multi_level_story is not None:
        decision.controlling_origin = multi_level_story.controlling_origin
        decision.active_execution_trade = multi_level_story.active_execution_trade

    selected_direction = _candidate_direction(selected)
    opposite_selected = _selected_opposite_trade(active_trade_audit, selected_direction)
    management_decision = _evaluate_management_decision(
        selected=selected,
        selected_direction=selected_direction,
        divergence_audit=divergence_audit,
        opposite_selected=opposite_selected,
        multi_level_story=multi_level_story,
        structures=structures,
        trace=trace,
    )
    if management_decision is not None and resolved_position_mode in {"LONG", "SHORT", "FLAT"}:
        management_signal = (
            management_decision.if_already_in
            if resolved_position_mode in {"LONG", "SHORT"}
            else management_decision.if_not_in
        )
        management_action = _action_from_management_signal(
            management_signal,
            selected_direction,
        )
        if management_action != FinalAction.WAIT:
            decision.final_action = management_action
            decision.action = management_action
            decision.management_state = management_decision.management_state
            decision.reason = management_decision.reason
            entry_decision_payload["reason"] = decision.reason

    if (
        move_context is not None
        and decision.final_action in {FinalAction.BUY, FinalAction.SELL}
        and move_context.current_origin == "UNCLEAR"
    ):
        decision.final_action = FinalAction.WAIT
        decision.action = FinalAction.WAIT
        decision.management_state = "NONE"
        decision.reason = "Parent/current move separation unclear; framework v1.2 requires current move origin for fresh entry."

    if decision.final_action in {FinalAction.BUY, FinalAction.SELL}:
        selected_direction = _candidate_direction(selected)
        gate_side = (
            "BUY"
            if selected_direction == Direction.UP
            else "SELL"
            if selected_direction == Direction.DOWN
            else None
        )
        origin_field_map = {
            "4h": "tf_4h",
            "1h": "tf_1h",
            "15m": "tf_15m",
            "5m": "tf_5m",
            "3m": "tf_3m",
        }
        origin_field = origin_field_map.get(selected.origin_timeframe or "")
        divergence_row = getattr(divergence_audit, origin_field, None) if origin_field else None
        range_row = structures.get(selected.origin_timeframe).range_state if selected.origin_timeframe in structures else None
        entry_decision = evaluate_fresh_entry(
            move_context=move_context,
            type_classification={
                "type_label": selected.setup_type.value if selected.setup_type is not None else "NONE",
                "full_label": selected.type_label,
                "valid": bool(selected.exists and selected.setup_type in {SetupType.TYPE_1, SetupType.TYPE_2, SetupType.TYPE_3}),
                "origin_timeframe": selected.origin_timeframe,
                "direction": (
                    "BULLISH"
                    if selected_direction == Direction.UP
                    else "BEARISH"
                    if selected_direction == Direction.DOWN
                    else "NONE"
                ),
                "invalidation": selected.invalidation,
            },
            trade_function_result={
                "trade_function": (
                    selected.trade_function.value
                    if hasattr(selected.trade_function, "value")
                    else str(selected.trade_function)
                ),
                "valid": bool(
                    selected.trade_function is not None
                    and str(getattr(selected.trade_function, "value", selected.trade_function)).upper() != "NONE"
                ),
            },
            impulse_result={
                "confirmed": bool(
                    selected.confirmation_price is not None
                    and (
                        divergence_row is None
                        or bool(getattr(divergence_row, "impulse_confirmed", False))
                    )
                ),
                "acceptance_valid": bool(selected.setup_type == SetupType.TYPE_3),
            },
            carry_result={
                "state": selected.carry_state.value if hasattr(selected.carry_state, "value") else str(selected.carry_state),
                "timeframe": selected.carry_timeframe,
                "finished": selected.current_status.upper() == "FINISHED",
                "exhausting": selected.carry_state == CarryState.EXHAUSTING,
            },
            range_result=range_row,
            zone_results=zones or [],
            multi_level_result=multi_level_story,
            trace=trace,
        )
        if not entry_decision.fresh_entry_valid or entry_decision.side not in {"BUY", "SELL"}:
            decision.final_action = FinalAction.WAIT
            decision.action = FinalAction.WAIT
            decision.management_state = "NONE"
            decision.reason = entry_decision.reason
            decision.fresh_entry_valid = False
            if entry_decision.reason and entry_decision.reason not in decision.guard_reasons:
                decision.guard_reasons.append(entry_decision.reason)
        elif gate_side is not None and entry_decision.side != gate_side:
            decision.final_action = FinalAction.WAIT
            decision.action = FinalAction.WAIT
            decision.management_state = "NONE"
            decision.reason = "Entry gate side mismatch with active trade direction."
            decision.fresh_entry_valid = False
            if decision.reason not in decision.guard_reasons:
                decision.guard_reasons.append(decision.reason)
        entry_decision_payload = {
            "fresh_entry_valid": bool(entry_decision.fresh_entry_valid),
            "side": entry_decision.side,
            "entry_zone": entry_decision.entry_zone,
            "invalidation": entry_decision.invalidation,
            "reason": entry_decision.reason,
        }

    final_resolved = resolve_final_action(
        entry_decision=entry_decision_payload,
        management_decision=management_decision,
        active_trade={
            "exists": selected.exists,
            "trade_function": (
                selected.trade_function.value
                if hasattr(selected.trade_function, "value")
                else str(selected.trade_function)
            ),
            "type_label": selected.type_label,
            "controlling_origin": decision.controlling_origin,
            "active_execution_trade": decision.active_execution_trade,
            "origin_price_zone": selected.origin_price_zone,
            "invalidation": selected.invalidation,
            "carry_timeframe": selected.carry_timeframe,
        },
        framework_trace=trace,
        trace=trace,
    )
    resolved_action = _action_from_signal(final_resolved.signal)
    decision.final_action = resolved_action
    decision.action = resolved_action
    decision.management_state = final_resolved.management_state
    decision.reason = final_resolved.reason

    guarded = apply_decision_guards(
        decision=decision,
        active_trade=selected if selected.exists else None,
        divergence_audit=divergence_audit,
        structures=structures,
        multi_level_story=multi_level_story,
    )
    guarded.action = guarded.final_action
    return guarded


def _selected_opposite_trade(
    audit: ActiveTradeAudit,
    selected_direction: Direction,
) -> ActiveTradeCandidate | None:
    if selected_direction not in {Direction.UP, Direction.DOWN}:
        return None
    selected_tf = audit.selected_active_trade_tf
    mapping = {"4h": "tf_4h", "1h": "tf_1h", "15m": "tf_15m", "5m": "tf_5m", "3m": "tf_3m"}
    opposite_direction = Direction.DOWN if selected_direction == Direction.UP else Direction.UP
    for tf, field in mapping.items():
        if tf == selected_tf:
            continue
        candidate = getattr(audit, field)
        if not candidate.exists:
            continue
        if _candidate_direction(candidate) != opposite_direction:
            continue
        if not candidate.fresh_entry_valid:
            continue
        if candidate.carry_state not in {CarryState.FRESH, CarryState.ACTIVE}:
            continue
        return candidate
    return None


def _evaluate_management_decision(
    selected: ActiveTradeCandidate,
    selected_direction: Direction,
    divergence_audit: DivergenceAudit,
    opposite_selected: ActiveTradeCandidate | None,
    multi_level_story: MultiLevelStory | None,
    structures: dict[str, StructureState],
    trace,
):
    if not selected.exists:
        return None
    if selected_direction not in {Direction.UP, Direction.DOWN}:
        return None
    if not selected.existing_hold_valid:
        return None

    carry_tf = selected.carry_timeframe or selected.origin_timeframe
    divergence_field = {"4h": "tf_4h", "1h": "tf_1h", "15m": "tf_15m", "5m": "tf_5m", "3m": "tf_3m"}.get(carry_tf)
    divergence_row = getattr(divergence_audit, divergence_field) if divergence_field else None
    opposite_dir = Direction.DOWN if selected_direction == Direction.UP else Direction.UP
    opposite_label = "BEARISH" if opposite_dir == Direction.DOWN else "BULLISH"
    divergence_direction = _normalize_direction(_direction_value(getattr(divergence_row, "direction", None)))
    opposite_divergence_exists = bool(
        divergence_row is not None
        and getattr(divergence_row, "exists", False)
        and getattr(divergence_row, "abc_valid", False)
        and divergence_direction == opposite_label
    )
    opposite_impulse_confirmed = bool(
        opposite_divergence_exists
        and divergence_row is not None
        and getattr(divergence_row, "impulse_confirmed", False)
    )
    grade_value = str(_direction_value(getattr(divergence_row, "grade", ""))).upper()
    weakening_count = int(getattr(divergence_row, "weakening_count", 0) or 0)
    # "Micro divergence alone" should not block flips when opposite impulse
    # is already confirmed and higher-level authority aligns.
    micro_only = bool(
        opposite_divergence_exists
        and grade_value == "WEAK"
        and weakening_count <= 1
        and not opposite_impulse_confirmed
    )

    story_direction = _normalize_direction(_direction_value(getattr(multi_level_story, "direction", None)))
    higher_supports_weakening = story_direction == opposite_label
    opposite_side_has_carry = bool(
        opposite_selected is not None
        and opposite_selected.exists
        and opposite_selected.fresh_entry_valid
        and opposite_selected.carry_state in {CarryState.FRESH, CarryState.ACTIVE}
        and not opposite_selected.too_late_to_chase
    )
    room_for_new_move = bool(
        opposite_side_has_carry and _room_allows_opposite_move(structures, opposite_selected)
    )

    return evaluate_position_management(
        active_trade={
            "exists": selected.exists,
            "existing_hold_valid": selected.existing_hold_valid,
            "fresh_entry_valid": selected.fresh_entry_valid,
            "direction": (
                "BULLISH"
                if selected_direction == Direction.UP
                else "BEARISH"
                if selected_direction == Direction.DOWN
                else "NONE"
            ),
            "current_status": selected.current_status,
        },
        carry_result={
            "state": selected.carry_state.value if hasattr(selected.carry_state, "value") else str(selected.carry_state),
            "finished": selected.current_status.upper() == "FINISHED",
        },
        opposite_divergence_result={
            "exists": opposite_divergence_exists,
            "direction": opposite_label if opposite_divergence_exists else "NONE",
            "micro_only": micro_only,
        },
        opposite_impulse_result={
            "confirmed": opposite_impulse_confirmed,
            "direction": opposite_label if opposite_impulse_confirmed else "NONE",
        },
        higher_context={
            "supports_weakening": higher_supports_weakening,
            "opposite_side_has_carry": opposite_side_has_carry,
        },
        room_for_new_move=room_for_new_move,
        trace=trace,
    )


def _action_from_management_signal(signal: str, selected_direction: Direction) -> FinalAction:
    normalized = str(signal or "").strip().upper()
    if normalized == "HOLD_LONG":
        return FinalAction.HOLD_LONG
    if normalized == "HOLD_SHORT":
        return FinalAction.HOLD_SHORT
    if normalized == "CLOSE_LONG":
        return FinalAction.CLOSE_LONG
    if normalized == "CLOSE_SHORT":
        return FinalAction.CLOSE_SHORT
    if normalized == "CLOSE_AND_FLIP":
        return FinalAction.CLOSE_AND_FLIP
    if normalized == "HOLD":
        if selected_direction == Direction.UP:
            return FinalAction.HOLD_LONG
        if selected_direction == Direction.DOWN:
            return FinalAction.HOLD_SHORT
    return FinalAction.WAIT


def _action_from_signal(signal: str) -> FinalAction:
    normalized = str(signal or "").strip().upper().replace("_", " ")
    if normalized == "BUY":
        return FinalAction.BUY
    if normalized == "SELL":
        return FinalAction.SELL
    if normalized == "HOLD LONG":
        return FinalAction.HOLD_LONG
    if normalized == "HOLD SHORT":
        return FinalAction.HOLD_SHORT
    if normalized == "CLOSE LONG":
        return FinalAction.CLOSE_LONG
    if normalized == "CLOSE SHORT":
        return FinalAction.CLOSE_SHORT
    if normalized == "CLOSE AND FLIP":
        return FinalAction.CLOSE_AND_FLIP
    return FinalAction.WAIT


def _direction_value(value) -> str:
    return str(getattr(value, "value", value) or "")


def _normalize_direction(value: str) -> str:
    text = str(value or "").strip().upper()
    if text in {"UP", "BULLISH", "BUY"}:
        return "BULLISH"
    if text in {"DOWN", "BEARISH", "SELL"}:
        return "BEARISH"
    return "NONE"


def _room_allows_opposite_move(
    structures: dict[str, StructureState],
    opposite_selected: ActiveTradeCandidate | None,
) -> bool:
    if opposite_selected is None:
        return False
    structure = structures.get(opposite_selected.origin_timeframe)
    if structure is None or structure.range_state is None:
        return True
    if not structure.range_state.active:
        return True
    location = str(structure.range_state.price_location or "").strip().upper()
    return location not in {"MID", "MIDPOINT"}
