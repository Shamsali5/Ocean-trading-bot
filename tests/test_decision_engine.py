"""Tests for deterministic decision engine orchestration."""

from __future__ import annotations

from ocean_engine.models.enums import CarryState, Direction, FinalAction
from ocean_engine.models.market import (
    ActiveTradeAudit,
    ActiveTradeCandidate,
    DecisionState,
    DivergenceAudit,
    MultiLevelStory,
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
) -> ActiveTradeCandidate:
    return ActiveTradeCandidate(
        timeframe=origin_timeframe,
        exists=exists,
        origin_timeframe=origin_timeframe,
        direction=direction,
        type_label=type_label,
        carry_timeframe=carry_timeframe,
        carry_state=carry_state,
        fresh_entry_valid=fresh_entry_valid,
        existing_hold_valid=existing_hold_valid,
        too_late_to_chase=too_late_to_chase,
        current_status="FINISHED" if finished else "ACTIVE",
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
    decision = build_decision_state({}, DivergenceAudit(), audit, MultiLevelStory())
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
    decision = build_decision_state({}, DivergenceAudit(), audit, MultiLevelStory())
    assert decision.guard_reasons
    assert decision.valid is False


def test_management_state_from_carry_values() -> None:
    assert management_state_from_carry(CarryState.FRESH) == "HOLD"
    assert management_state_from_carry(CarryState.ACTIVE) == "HOLD"
    assert management_state_from_carry(CarryState.MATURE) == "HOLD_WITH_CAUTION"
    assert management_state_from_carry(CarryState.EXHAUSTING) == "CLOSE_WATCH"
    assert management_state_from_carry(CarryState.UNCLEAR) == "NONE"
