"""Tests for deterministic decision engine orchestration."""

from __future__ import annotations

from ocean_engine.models.enums import CarryState, Direction, DivergenceDirection, FinalAction, MarketState, SetupType
from ocean_engine.models.market import (
    ActiveTradeAudit,
    ActiveTradeCandidate,
    DecisionState,
    DivergenceAudit,
    DivergenceState,
    MultiLevelStory,
    MoveContext,
    RangeState,
    StructureState,
)
from ocean_engine.trade.decision_engine import (
    build_decision_state,
    initial_decision_from_active_trade,
    management_state_from_carry,
)


def _candidate(
    *,
    exists: bool = True,
    direction: Direction = Direction.UP,
    fresh_entry_valid: bool = False,
    existing_hold_valid: bool = False,
    carry_state: CarryState = CarryState.UNCLEAR,
    finished: bool = False,
    too_late_to_chase: bool = False,
    origin_timeframe: str = "15m",
    carry_timeframe: str = "5m",
    type_label: str = "15m Bullish Type 1",
    setup_type: SetupType = SetupType.TYPE_1,
) -> ActiveTradeCandidate:
    return ActiveTradeCandidate(
        timeframe=origin_timeframe,
        exists=exists,
        origin_timeframe=origin_timeframe,
        direction=direction,
        setup_type=setup_type,
        type_label=type_label,
        carry_timeframe=carry_timeframe,
        carry_state=carry_state,
        fresh_entry_valid=fresh_entry_valid,
        existing_hold_valid=existing_hold_valid,
        too_late_to_chase=too_late_to_chase,
        current_status="FINISHED" if finished else "ACTIVE",
    )


def _type3_candidate(
    *,
    direction: Direction,
    fresh_entry_valid: bool = False,
    existing_hold_valid: bool = False,
    carry_state: CarryState = CarryState.UNCLEAR,
    too_late_to_chase: bool = False,
    finished: bool = False,
    origin_timeframe: str = "15m",
    carry_timeframe: str = "5m",
) -> ActiveTradeCandidate:
    label = f"{origin_timeframe} {'Bullish' if direction == Direction.UP else 'Bearish'} Type 3"
    return _candidate(
        direction=direction,
        fresh_entry_valid=fresh_entry_valid,
        existing_hold_valid=existing_hold_valid,
        carry_state=carry_state,
        finished=finished,
        too_late_to_chase=too_late_to_chase,
        origin_timeframe=origin_timeframe,
        carry_timeframe=carry_timeframe,
        type_label=label,
        setup_type=SetupType.TYPE_3,
    )


def _audit_with_selected(candidate: ActiveTradeCandidate) -> ActiveTradeAudit:
    audit = ActiveTradeAudit()
    field = {
        "4h": "tf_4h",
        "1h": "tf_1h",
        "15m": "tf_15m",
        "5m": "tf_5m",
        "3m": "tf_3m",
    }[candidate.origin_timeframe]
    setattr(audit, field, candidate)
    audit.selected_active_trade_tf = candidate.origin_timeframe
    return audit


def test_no_selected_active_trade_wait() -> None:
    decision = build_decision_state({}, DivergenceAudit(), ActiveTradeAudit(), MultiLevelStory())
    assert decision.final_action == FinalAction.WAIT
    assert decision.management_state == "NONE"
    assert "No locked active trade origin exists." in decision.reason


def test_bullish_fresh_entry_buy_if_guards_pass() -> None:
    candidate = _candidate(
        direction=Direction.UP,
        fresh_entry_valid=True,
        existing_hold_valid=False,
        carry_state=CarryState.FRESH,
    )
    audit = _audit_with_selected(candidate)
    decision = build_decision_state(
        {"15m": StructureState(timeframe="15m")},
        DivergenceAudit(),
        audit,
        MultiLevelStory(),
    )
    assert decision.final_action in {FinalAction.BUY, FinalAction.WAIT}


def test_bearish_fresh_entry_sell_if_guards_pass() -> None:
    candidate = _candidate(
        direction=Direction.DOWN,
        fresh_entry_valid=True,
        existing_hold_valid=False,
        carry_state=CarryState.ACTIVE,
        type_label="15m Bearish Type 1",
    )
    audit = _audit_with_selected(candidate)
    decision = build_decision_state(
        {"15m": StructureState(timeframe="15m")},
        DivergenceAudit(),
        audit,
        MultiLevelStory(),
    )
    assert decision.final_action in {FinalAction.SELL, FinalAction.WAIT}


def test_bullish_existing_hold_mature_carry_hold_long_with_caution() -> None:
    candidate = _candidate(
        direction=Direction.UP,
        fresh_entry_valid=False,
        existing_hold_valid=True,
        carry_state=CarryState.MATURE,
    )
    decision = initial_decision_from_active_trade(candidate)
    assert decision.final_action == FinalAction.HOLD_LONG
    assert decision.management_state == "HOLD_WITH_CAUTION"


def test_bearish_existing_hold_mature_carry_hold_short_with_caution() -> None:
    candidate = _candidate(
        direction=Direction.DOWN,
        fresh_entry_valid=False,
        existing_hold_valid=True,
        carry_state=CarryState.MATURE,
        type_label="15m Bearish Type 1",
    )
    decision = initial_decision_from_active_trade(candidate)
    assert decision.final_action == FinalAction.HOLD_SHORT
    assert decision.management_state == "HOLD_WITH_CAUTION"


def test_bullish_finished_carry_close_long() -> None:
    candidate = _candidate(
        direction=Direction.UP,
        fresh_entry_valid=False,
        existing_hold_valid=True,
        carry_state=CarryState.EXHAUSTING,
        finished=True,
    )
    decision = initial_decision_from_active_trade(candidate)
    assert decision.final_action == FinalAction.CLOSE_LONG
    assert decision.management_state == "FULL_CLOSE"


def test_bearish_finished_carry_close_short() -> None:
    candidate = _candidate(
        direction=Direction.DOWN,
        fresh_entry_valid=False,
        existing_hold_valid=True,
        carry_state=CarryState.EXHAUSTING,
        finished=True,
        type_label="15m Bearish Type 1",
    )
    decision = initial_decision_from_active_trade(candidate)
    assert decision.final_action == FinalAction.CLOSE_SHORT
    assert decision.management_state == "FULL_CLOSE"


def test_exhausting_without_finished_hold_close_watch_or_wait() -> None:
    candidate = _candidate(
        direction=Direction.UP,
        fresh_entry_valid=False,
        existing_hold_valid=True,
        carry_state=CarryState.EXHAUSTING,
        finished=False,
    )
    decision = initial_decision_from_active_trade(candidate)
    assert decision.final_action in {FinalAction.HOLD_LONG, FinalAction.WAIT}
    assert decision.management_state in {"CLOSE_WATCH", "NONE"}


def test_initial_buy_becomes_wait_when_guards_reject() -> None:
    candidate = _candidate(
        direction=Direction.UP,
        fresh_entry_valid=True,
        existing_hold_valid=False,
        carry_state=CarryState.FRESH,
        origin_timeframe="15m",
        carry_timeframe="15m",
    )
    audit = _audit_with_selected(candidate)
    divergence_audit = DivergenceAudit(
        tf_15m=DivergenceState(
            timeframe="15m",
            exists=True,
            abc_valid=True,
            impulse_confirmed=True,
            direction=DivergenceDirection.BEARISH,
        )
    )
    decision = build_decision_state({}, divergence_audit, audit, MultiLevelStory())
    assert decision.final_action == FinalAction.WAIT
    assert decision.guard_reasons


def test_decision_includes_multi_level_fields_when_story_exists() -> None:
    candidate = _candidate(
        direction=Direction.UP,
        fresh_entry_valid=False,
        existing_hold_valid=True,
        carry_state=CarryState.ACTIVE,
    )
    audit = _audit_with_selected(candidate)
    story = MultiLevelStory(
        active=True,
        controlling_origin="1H Bullish Type 1",
        active_execution_trade="15m Bullish Type 1",
        carrying_timeframe="5m",
        confirmed_timeframes=["1h", "15m"],
    )
    decision = build_decision_state({}, DivergenceAudit(), audit, story)
    assert decision.controlling_origin == "1H Bullish Type 1"
    assert decision.active_execution_trade == "15m Bullish Type 1"
    assert decision.carrying_timeframe == "5m"


def test_too_late_to_chase_prevents_fresh_buy_sell() -> None:
    candidate = _candidate(
        direction=Direction.UP,
        fresh_entry_valid=True,
        existing_hold_valid=False,
        carry_state=CarryState.ACTIVE,
        too_late_to_chase=True,
    )
    decision = initial_decision_from_active_trade(candidate)
    assert decision.final_action == FinalAction.WAIT


def test_guard_reasons_preserved() -> None:
    candidate = _candidate(
        direction=Direction.UP,
        fresh_entry_valid=True,
        existing_hold_valid=False,
        carry_state=CarryState.FRESH,
        origin_timeframe="15m",
        carry_timeframe="15m",
    )
    audit = _audit_with_selected(candidate)
    divergence_audit = DivergenceAudit(
        tf_15m=DivergenceState(
            timeframe="15m",
            exists=True,
            abc_valid=True,
            impulse_confirmed=True,
            direction=DivergenceDirection.BEARISH,
        )
    )
    decision = build_decision_state({}, divergence_audit, audit, MultiLevelStory())
    assert decision.guard_reasons
    assert decision.valid is False


def test_management_state_from_carry_values() -> None:
    assert management_state_from_carry(CarryState.FRESH) == "HOLD"
    assert management_state_from_carry(CarryState.ACTIVE) == "HOLD"
    assert management_state_from_carry(CarryState.MATURE) == "HOLD_WITH_CAUTION"
    assert management_state_from_carry(CarryState.EXHAUSTING) == "CLOSE_WATCH"
    assert management_state_from_carry(CarryState.UNCLEAR) == "NONE"


def test_type3_fresh_bullish_is_buy() -> None:
    candidate = _type3_candidate(
        direction=Direction.UP,
        fresh_entry_valid=True,
        existing_hold_valid=False,
        carry_state=CarryState.FRESH,
        too_late_to_chase=False,
    )
    decision = initial_decision_from_active_trade(candidate, position_mode="UNKNOWN")
    assert decision.final_action == FinalAction.BUY
    assert decision.reason == "Fresh entry is valid."


def test_type3_fresh_bearish_is_sell() -> None:
    candidate = _type3_candidate(
        direction=Direction.DOWN,
        fresh_entry_valid=True,
        existing_hold_valid=False,
        carry_state=CarryState.ACTIVE,
        too_late_to_chase=False,
    )
    decision = initial_decision_from_active_trade(candidate, position_mode="UNKNOWN")
    assert decision.final_action == FinalAction.SELL
    assert decision.reason == "Fresh entry is valid."


def test_type3_mature_bullish_long_mode_holds_long() -> None:
    candidate = _type3_candidate(
        direction=Direction.UP,
        fresh_entry_valid=False,
        existing_hold_valid=True,
        carry_state=CarryState.MATURE,
        too_late_to_chase=True,
    )
    decision = initial_decision_from_active_trade(candidate, position_mode="LONG")
    assert decision.final_action == FinalAction.HOLD_LONG
    assert decision.management_state == "HOLD_WITH_CAUTION"


def test_type3_mature_bullish_flat_mode_waits() -> None:
    candidate = _type3_candidate(
        direction=Direction.UP,
        fresh_entry_valid=False,
        existing_hold_valid=True,
        carry_state=CarryState.MATURE,
        too_late_to_chase=True,
    )
    decision = initial_decision_from_active_trade(candidate, position_mode="FLAT")
    assert decision.final_action == FinalAction.WAIT
    assert "flat position mode waits" in decision.reason


def test_type3_mature_bullish_unknown_mode_holds_with_hold_only_reason() -> None:
    candidate = _type3_candidate(
        direction=Direction.UP,
        fresh_entry_valid=False,
        existing_hold_valid=True,
        carry_state=CarryState.MATURE,
        too_late_to_chase=True,
    )
    decision = initial_decision_from_active_trade(candidate, position_mode="UNKNOWN")
    assert decision.final_action == FinalAction.HOLD_LONG
    assert "valid hold only, not fresh entry" in decision.reason.lower()


def test_type3_mature_bearish_short_mode_holds_short() -> None:
    candidate = _type3_candidate(
        direction=Direction.DOWN,
        fresh_entry_valid=False,
        existing_hold_valid=True,
        carry_state=CarryState.MATURE,
        too_late_to_chase=True,
    )
    decision = initial_decision_from_active_trade(candidate, position_mode="SHORT")
    assert decision.final_action == FinalAction.HOLD_SHORT
    assert decision.management_state == "HOLD_WITH_CAUTION"


def test_type3_mature_bearish_flat_mode_waits() -> None:
    candidate = _type3_candidate(
        direction=Direction.DOWN,
        fresh_entry_valid=False,
        existing_hold_valid=True,
        carry_state=CarryState.MATURE,
        too_late_to_chase=True,
    )
    decision = initial_decision_from_active_trade(candidate, position_mode="FLAT")
    assert decision.final_action == FinalAction.WAIT
    assert "flat position mode waits" in decision.reason


def test_reason_separates_fresh_entry_from_valid_hold_only() -> None:
    fresh_candidate = _type3_candidate(
        direction=Direction.UP,
        fresh_entry_valid=True,
        existing_hold_valid=False,
        carry_state=CarryState.FRESH,
        too_late_to_chase=False,
    )
    hold_candidate = _type3_candidate(
        direction=Direction.UP,
        fresh_entry_valid=False,
        existing_hold_valid=True,
        carry_state=CarryState.MATURE,
        too_late_to_chase=True,
    )
    fresh_decision = initial_decision_from_active_trade(fresh_candidate, position_mode="UNKNOWN")
    hold_decision = initial_decision_from_active_trade(hold_candidate, position_mode="UNKNOWN")
    assert fresh_decision.reason == "Fresh entry is valid."
    assert "valid hold only, not fresh entry" in hold_decision.reason.lower()


def test_range_ownership_does_not_create_buy_sell_by_itself() -> None:
    structures = {
        "15m": StructureState(
            timeframe="15m",
            direction=Direction.UNCLEAR,
            market_state=MarketState.RANGE,
            range_state=RangeState(
                timeframe="15m",
                is_range=True,
                active=True,
                ownership=Direction.UP,
                ownership_reason="pre-range leg UP -> bullish ownership",
            ),
        )
    }
    decision = build_decision_state(
        structures=structures,
        divergence_audit=DivergenceAudit(),
        active_trade_audit=ActiveTradeAudit(),
        multi_level_story=MultiLevelStory(),
    )
    assert decision.final_action == FinalAction.WAIT
    assert "No locked active trade origin exists." in decision.reason


def test_type3_divergence_direction_is_normalized_to_buy_sell() -> None:
    candidate = ActiveTradeCandidate(
        timeframe="15m",
        exists=True,
        origin_timeframe="15m",
        direction=DivergenceDirection.BULLISH,
        setup_type=SetupType.TYPE_3,
        type_label="15m Bullish Type 3",
        carry_timeframe="5m",
        carry_state=CarryState.FRESH,
        fresh_entry_valid=True,
        existing_hold_valid=False,
        too_late_to_chase=False,
    )
    decision = initial_decision_from_active_trade(candidate, position_mode="UNKNOWN")
    assert decision.final_action == FinalAction.BUY


def test_close_and_flip_when_selected_finished_and_opposite_fresh_exists() -> None:
    selected = _candidate(
        direction=Direction.UP,
        fresh_entry_valid=False,
        existing_hold_valid=True,
        carry_state=CarryState.EXHAUSTING,
        finished=True,
        origin_timeframe="15m",
        carry_timeframe="5m",
    )
    opposite = _candidate(
        direction=Direction.DOWN,
        fresh_entry_valid=True,
        existing_hold_valid=False,
        carry_state=CarryState.FRESH,
        origin_timeframe="5m",
        carry_timeframe="3m",
        type_label="5m Bearish Type 1",
    )
    audit = ActiveTradeAudit(
        tf_15m=selected,
        tf_5m=opposite,
        selected_active_trade_tf="15m",
    )
    decision = build_decision_state(
        structures={"15m": StructureState(timeframe="15m")},
        divergence_audit=DivergenceAudit(),
        active_trade_audit=audit,
        multi_level_story=MultiLevelStory(),
    )
    assert decision.final_action == FinalAction.CLOSE_AND_FLIP


def test_buy_not_downgraded_inside_decision_engine_for_move_context() -> None:
    candidate = _candidate(
        direction=Direction.UP,
        fresh_entry_valid=True,
        existing_hold_valid=False,
        carry_state=CarryState.FRESH,
    )
    audit = _audit_with_selected(candidate)
    decision = build_decision_state(
        structures={"15m": StructureState(timeframe="15m")},
        divergence_audit=DivergenceAudit(),
        active_trade_audit=audit,
        multi_level_story=MultiLevelStory(),
    )
    assert decision.final_action in {FinalAction.BUY, FinalAction.WAIT}
