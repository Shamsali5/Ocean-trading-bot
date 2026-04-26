"""Tests for deterministic decision guard safety rules."""

from __future__ import annotations

from ocean_engine.models.enums import (
    CarryState,
    Direction,
    DivergenceDirection,
    FinalAction,
    MarketState,
    SetupType,
)
from ocean_engine.models.market import (
    ActiveTradeCandidate,
    DecisionState,
    DivergenceAudit,
    DivergenceState,
    MultiLevelStory,
    RangeState,
    StructureState,
)
from ocean_engine.trade.guards import apply_decision_guards


def _decision(action: FinalAction = FinalAction.BUY) -> DecisionState:
    return DecisionState(symbol="BTCUSDT", final_action=action)


def _candidate(
    exists: bool = True,
    fresh: bool = True,
    carry_state: CarryState = CarryState.FRESH,
    setup_type: SetupType = SetupType.TYPE_1,
    direction: Direction = Direction.UP,
    origin_tf: str = "15m",
    carry_tf: str = "5m",
) -> ActiveTradeCandidate:
    return ActiveTradeCandidate(
        timeframe=origin_tf,
        exists=exists,
        origin_timeframe=origin_tf,
        direction=direction,
        setup_type=setup_type,
        fresh_entry_valid=fresh,
        existing_hold_valid=fresh,
        carry_timeframe=carry_tf,
        carry_state=carry_state,
        type_label=f"{origin_tf} Type 1",
    )


def _div_state(
    timeframe: str,
    exists: bool = True,
    direction: DivergenceDirection = DivergenceDirection.BULLISH,
    abc_valid: bool = True,
    impulse_confirmed: bool = True,
) -> DivergenceState:
    return DivergenceState(
        timeframe=timeframe,
        exists=exists,
        direction=direction,
        abc_valid=abc_valid,
        impulse_confirmed=impulse_confirmed,
    )


def test_buy_becomes_wait_if_no_active_trade() -> None:
    decision = _decision(FinalAction.BUY)
    active_trade = _candidate(exists=False)
    guarded = apply_decision_guards(decision, active_trade, DivergenceAudit(), {}, MultiLevelStory())
    assert guarded.final_action == FinalAction.WAIT


def test_buy_becomes_wait_if_fresh_entry_false() -> None:
    decision = _decision(FinalAction.BUY)
    active_trade = _candidate(fresh=False, carry_state=CarryState.ACTIVE)
    divergence_audit = DivergenceAudit(tf_15m=_div_state("15m", direction=DivergenceDirection.BULLISH))
    guarded = apply_decision_guards(decision, active_trade, divergence_audit, {}, MultiLevelStory())
    assert guarded.final_action == FinalAction.WAIT


def test_buy_survives_if_active_trade_exists_fresh_and_carry_fresh() -> None:
    decision = _decision(FinalAction.BUY)
    active_trade = _candidate(fresh=True, carry_state=CarryState.FRESH)
    divergence_audit = DivergenceAudit(tf_15m=_div_state("15m", direction=DivergenceDirection.BULLISH))
    guarded = apply_decision_guards(decision, active_trade, divergence_audit, {}, MultiLevelStory())
    assert guarded.final_action == FinalAction.BUY


def test_buy_survives_if_carry_active() -> None:
    decision = _decision(FinalAction.BUY)
    active_trade = _candidate(fresh=True, carry_state=CarryState.ACTIVE)
    divergence_audit = DivergenceAudit(tf_15m=_div_state("15m", direction=DivergenceDirection.BULLISH))
    guarded = apply_decision_guards(decision, active_trade, divergence_audit, {}, MultiLevelStory())
    assert guarded.final_action == FinalAction.BUY


def test_buy_becomes_wait_if_carry_mature() -> None:
    decision = _decision(FinalAction.BUY)
    active_trade = _candidate(fresh=True, carry_state=CarryState.MATURE)
    divergence_audit = DivergenceAudit(tf_15m=_div_state("15m", direction=DivergenceDirection.BULLISH))
    guarded = apply_decision_guards(decision, active_trade, divergence_audit, {}, MultiLevelStory())
    assert guarded.final_action == FinalAction.WAIT


def test_buy_becomes_wait_if_carry_exhausting() -> None:
    decision = _decision(FinalAction.BUY)
    active_trade = _candidate(fresh=True, carry_state=CarryState.EXHAUSTING)
    divergence_audit = DivergenceAudit(tf_15m=_div_state("15m", direction=DivergenceDirection.BULLISH))
    guarded = apply_decision_guards(decision, active_trade, divergence_audit, {}, MultiLevelStory())
    assert guarded.final_action == FinalAction.WAIT


def test_type1_mismatched_timeframe_divergence_becomes_wait() -> None:
    decision = _decision(FinalAction.BUY)
    active_trade = _candidate(origin_tf="15m", direction=Direction.UP)
    divergence_audit = DivergenceAudit(tf_15m=_div_state("15m", direction=DivergenceDirection.BEARISH))
    guarded = apply_decision_guards(decision, active_trade, divergence_audit, {}, MultiLevelStory())
    assert guarded.final_action == FinalAction.WAIT


def test_type1_same_timeframe_official_divergence_survives() -> None:
    decision = _decision(FinalAction.BUY)
    active_trade = _candidate(origin_tf="15m", direction=Direction.UP)
    divergence_audit = DivergenceAudit(tf_15m=_div_state("15m", direction=DivergenceDirection.BULLISH))
    guarded = apply_decision_guards(decision, active_trade, divergence_audit, {}, MultiLevelStory())
    assert guarded.final_action == FinalAction.BUY


def test_range_midpoint_changes_buy_to_wait() -> None:
    decision = _decision(FinalAction.BUY)
    active_trade = _candidate()
    divergence_audit = DivergenceAudit(tf_15m=_div_state("15m", direction=DivergenceDirection.BULLISH))
    structures = {
        "15m": StructureState(
            timeframe="15m",
            range_state=RangeState(timeframe="15m", active=True, price_location="MID", is_range=True),
            market_state=MarketState.RANGE,
        )
    }
    guarded = apply_decision_guards(decision, active_trade, divergence_audit, structures, MultiLevelStory())
    assert guarded.final_action == FinalAction.WAIT


def test_range_midpoint_does_not_force_hold_to_wait() -> None:
    decision = _decision(FinalAction.HOLD_LONG)
    active_trade = _candidate()
    structures = {
        "15m": StructureState(
            timeframe="15m",
            range_state=RangeState(timeframe="15m", active=True, price_location="MID", is_range=True),
            market_state=MarketState.RANGE,
        )
    }
    guarded = apply_decision_guards(decision, active_trade, DivergenceAudit(), structures, MultiLevelStory())
    assert guarded.final_action == FinalAction.HOLD_LONG


def test_unclear_carry_changes_buy_to_wait() -> None:
    decision = _decision(FinalAction.BUY)
    active_trade = _candidate(carry_state=CarryState.UNCLEAR, carry_tf="")
    divergence_audit = DivergenceAudit(tf_15m=_div_state("15m", direction=DivergenceDirection.BULLISH))
    guarded = apply_decision_guards(decision, active_trade, divergence_audit, {}, MultiLevelStory())
    assert guarded.final_action == FinalAction.WAIT


def test_active_trade_origin_equal_carry_blocks_buy_for_type1() -> None:
    decision = _decision(FinalAction.BUY)
    active_trade = _candidate(origin_tf="15m", carry_tf="15m", setup_type=SetupType.TYPE_1)
    divergence_audit = DivergenceAudit(tf_15m=_div_state("15m", direction=DivergenceDirection.BULLISH))
    guarded = apply_decision_guards(decision, active_trade, divergence_audit, {}, MultiLevelStory())
    assert guarded.final_action == FinalAction.WAIT


def test_multilevel_active_with_fewer_than_two_confirmed_is_downgraded() -> None:
    decision = _decision(FinalAction.WAIT)
    active_trade = _candidate()
    story = MultiLevelStory(active=True, confirmed_timeframes=["15m"], higher_tf_status="OFFICIAL_MULTI_LEVEL")
    guarded = apply_decision_guards(decision, active_trade, DivergenceAudit(), {}, story)
    assert story.active is False
    assert story.higher_tf_status == "WEAKENING_CONTEXT_ONLY"
    assert guarded.final_action == FinalAction.WAIT


def test_apply_decision_guards_accumulates_guard_reasons() -> None:
    decision = _decision(FinalAction.BUY)
    active_trade = _candidate(exists=False, fresh=False, carry_state=CarryState.EXHAUSTING, carry_tf="")
    guarded = apply_decision_guards(decision, active_trade, DivergenceAudit(), {}, MultiLevelStory())
    assert guarded.final_action == FinalAction.WAIT
    assert len(guarded.guard_reasons) >= 2
    assert guarded.valid is False
