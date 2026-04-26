"""Offline synthetic framework scenarios for deterministic behavior checks."""

from __future__ import annotations

from ocean_engine.models.enums import (
    CarryState,
    Direction,
    DivergenceDirection,
    DivergenceGrade,
    FinalAction,
    MarketState,
    SetupType,
)
from ocean_engine.models.market import (
    ActiveTradeAudit,
    ActiveTradeCandidate,
    Candle,
    DivergenceAudit,
    DivergenceState,
    Leg,
    MultiLevelStory,
    RangeState,
    StructureState,
)
from ocean_engine.trade.active_trade_engine import build_active_trade_audit, build_type1_candidate
from ocean_engine.trade.decision_engine import build_decision_state
from ocean_engine.trade.multi_level_engine import build_multi_level_story, get_official_timeframes_by_direction


def _candles(closes: list[float]) -> list[Candle]:
    candles: list[Candle] = []
    for idx, close in enumerate(closes):
        candles.append(
            Candle(
                open_time=idx,
                open=close,
                high=close + 0.4,
                low=close - 0.4,
                close=close,
                volume=1.0,
                close_time=idx,
            )
        )
    return candles


def _official_divergence(timeframe: str, direction: DivergenceDirection, zone: str) -> DivergenceState:
    return DivergenceState(
        timeframe=timeframe,
        exists=True,
        abc_valid=True,
        direction=direction,
        grade=DivergenceGrade.STRONG,
        impulse_confirmed=True,
        price_zone=zone,
    )


def _carry_structure(timeframe: str, direction: Direction) -> StructureState:
    leg = Leg(
        start_index=0,
        end_index=2,
        direction=direction,
        high=101.0 if direction == Direction.UP else 105.0,
        low=99.0 if direction == Direction.UP else 103.0,
        is_active=True,
    )
    return StructureState(
        timeframe=timeframe,
        legs=[leg],
        active_leg=leg,
        current_price=leg.high if direction == Direction.UP else leg.low,
        candles=_candles([100.0, 100.3, 100.6] if direction == Direction.UP else [104.0, 103.6, 103.2]),
    )


def _type3_structure(timeframe: str, direction: Direction, current_price: float) -> StructureState:
    if direction == Direction.UP:
        status = "BROKEN_UP"
        upper = 100.0
        lower = 90.0
    else:
        status = "BROKEN_DOWN"
        upper = 110.0
        lower = 100.0
    active_leg = Leg(
        start_index=2,
        end_index=4,
        direction=direction,
        high=max(current_price, upper + 0.8),
        low=min(current_price, lower - 0.8),
        is_active=True,
    )
    return StructureState(
        timeframe=timeframe,
        legs=[
            Leg(start_index=0, end_index=1, direction=Direction.UP, high=upper, low=lower),
            Leg(start_index=1, end_index=2, direction=Direction.DOWN, high=upper + 0.4, low=lower - 0.4),
            active_leg,
        ],
        active_leg=active_leg,
        current_price=current_price,
        range_state=RangeState(
            timeframe=timeframe,
            is_range=True,
            active=True,
            upper_edge=upper,
            lower_edge=lower,
            status=status,
            breakout_direction=direction,
            breakout_confirmed=True,
            acceptance_confirmed=True,
            first_accepted_close=current_price,
        ),
        candles=_candles([lower + 4.0, lower + 6.0, upper + 0.5] if direction == Direction.UP else [upper - 4.0, upper - 6.0, lower - 0.5]),
    )


def test_scenario_1_clean_bullish_type1_divergence() -> None:
    structures = {
        "15m": StructureState(timeframe="15m", candles=_candles([100.0, 100.4, 100.8]), current_price=100.8),
        "5m": _carry_structure("5m", Direction.UP),
    }
    divergence_audit = DivergenceAudit(tf_15m=_official_divergence("15m", DivergenceDirection.BULLISH, "100.00-101.00"))

    active_trade_audit = build_active_trade_audit(structures, divergence_audit)
    candidate = active_trade_audit.tf_15m
    decision = build_decision_state(structures, divergence_audit, active_trade_audit, MultiLevelStory(), position_mode="FLAT")

    assert candidate.exists is True
    assert candidate.setup_type == SetupType.TYPE_1
    assert candidate.direction == DivergenceDirection.BULLISH
    assert candidate.carry_direction == Direction.UP
    assert decision.final_action in {FinalAction.BUY, FinalAction.HOLD_LONG, FinalAction.WAIT}


def test_scenario_2_clean_bearish_type1_divergence() -> None:
    structures = {
        "15m": StructureState(timeframe="15m", candles=_candles([110.0, 109.4, 108.8]), current_price=108.8),
        "5m": _carry_structure("5m", Direction.DOWN),
    }
    divergence_audit = DivergenceAudit(tf_15m=_official_divergence("15m", DivergenceDirection.BEARISH, "109.00-110.00"))

    active_trade_audit = build_active_trade_audit(structures, divergence_audit)
    candidate = active_trade_audit.tf_15m

    assert candidate.exists is True
    assert candidate.setup_type == SetupType.TYPE_1
    assert candidate.direction == DivergenceDirection.BEARISH


def test_scenario_3_bullish_type3_breakout_without_divergence() -> None:
    structures = {
        "15m": _type3_structure("15m", Direction.UP, current_price=101.3),
        "5m": _carry_structure("5m", Direction.UP),
    }
    divergence_audit = DivergenceAudit()

    active_trade_audit = build_active_trade_audit(structures, divergence_audit)
    candidate = active_trade_audit.tf_15m

    assert structures["15m"].range_state.status == "BROKEN_UP"
    assert candidate.exists is True
    assert candidate.setup_type == SetupType.TYPE_3
    assert candidate.trade_function.name == "BREAKOUT_TRADE"
    assert divergence_audit.tf_15m.exists is False


def test_scenario_4_bearish_type3_breakdown() -> None:
    structures = {
        "15m": _type3_structure("15m", Direction.DOWN, current_price=99.0),
        "5m": _carry_structure("5m", Direction.DOWN),
    }
    active_trade_audit = build_active_trade_audit(structures, DivergenceAudit())
    candidate = active_trade_audit.tf_15m

    assert structures["15m"].range_state.status == "BROKEN_DOWN"
    assert candidate.exists is True
    assert candidate.setup_type == SetupType.TYPE_3


def test_scenario_5_bullish_type2_continuation() -> None:
    impulse = Leg(start_index=0, end_index=2, direction=Direction.UP, high=112.0, low=100.0)
    pullback = Leg(start_index=2, end_index=3, direction=Direction.DOWN, high=111.0, low=102.0)
    continuation = Leg(start_index=3, end_index=4, direction=Direction.UP, high=113.0, low=103.0, is_active=True)
    structures = {
        "15m": StructureState(
            timeframe="15m",
            legs=[impulse, pullback, continuation],
            active_leg=continuation,
            current_price=113.0,
            candles=_candles([108.0, 110.0, 112.0, 104.0, 113.0]),
        ),
        "5m": _carry_structure("5m", Direction.UP),
    }
    divergence_audit = DivergenceAudit(tf_15m=_official_divergence("15m", DivergenceDirection.BULLISH, "100.00-101.00"))

    prior_type1 = build_type1_candidate("15m", divergence_audit.tf_15m, structures, divergence_audit)
    active_trade_audit = build_active_trade_audit(structures, divergence_audit)
    candidate = active_trade_audit.tf_15m

    assert prior_type1.exists is True
    assert candidate.exists is True
    assert candidate.setup_type == SetupType.TYPE_2
    assert candidate.direction == DivergenceDirection.BULLISH


def test_scenario_6_range_midpoint_blocks_fresh_buy_sell() -> None:
    structures = {
        "15m": StructureState(
            timeframe="15m",
            current_price=100.5,
            range_state=RangeState(
                timeframe="15m",
                is_range=True,
                active=True,
                upper_edge=102.0,
                lower_edge=99.0,
                midpoint=100.5,
                price_location="MID",
            ),
            candles=_candles([100.0, 100.2, 100.5]),
        ),
        "5m": _carry_structure("5m", Direction.UP),
    }
    divergence_audit = DivergenceAudit(tf_15m=_official_divergence("15m", DivergenceDirection.BULLISH, "99.50-100.20"))
    active_trade_audit = build_active_trade_audit(structures, divergence_audit)
    decision = build_decision_state(
        structures,
        divergence_audit,
        active_trade_audit,
        MultiLevelStory(),
        position_mode="FLAT",
    )

    assert decision.final_action == FinalAction.WAIT


def test_scenario_7_failed_breakout_blocks_type3() -> None:
    structures = {
        "15m": StructureState(
            timeframe="15m",
            current_price=99.6,
            range_state=RangeState(
                timeframe="15m",
                is_range=True,
                active=True,
                upper_edge=100.0,
                lower_edge=90.0,
                status="FAILED_BREAK_UP",
                breakout_direction=Direction.UP,
            ),
            candles=_candles([98.0, 100.8, 99.9]),
        ),
        "5m": _carry_structure("5m", Direction.UP),
    }
    active_trade_audit = build_active_trade_audit(structures, DivergenceAudit())
    assert structures["15m"].range_state.status == "FAILED_BREAK_UP"
    assert active_trade_audit.tf_15m.exists is False


def test_scenario_8_multilevel_type3_same_direction() -> None:
    structures = {
        "1h": _type3_structure("1h", Direction.UP, current_price=101.8),
        "15m": _type3_structure("15m", Direction.UP, current_price=101.1),
        "5m": _carry_structure("5m", Direction.UP),
        "3m": _carry_structure("3m", Direction.UP),
    }
    active_trade_audit = ActiveTradeAudit(
        tf_1h=ActiveTradeCandidate(
            timeframe="1h",
            exists=True,
            origin_timeframe="1h",
            direction=Direction.UP,
            setup_type=SetupType.TYPE_3,
            type_label="1H Bullish Type 3",
            carry_timeframe="15m",
            carry_state=CarryState.ACTIVE,
            existing_hold_valid=True,
        ),
        tf_15m=ActiveTradeCandidate(
            timeframe="15m",
            exists=True,
            origin_timeframe="15m",
            direction=Direction.UP,
            setup_type=SetupType.TYPE_3,
            type_label="15m Bullish Type 3",
            carry_timeframe="5m",
            carry_state=CarryState.ACTIVE,
            existing_hold_valid=True,
        ),
        selected_active_trade_tf="15m",
    )
    story = build_multi_level_story(DivergenceAudit(), active_trade_audit)

    assert story.active is True
    assert "1H" in story.controlling_origin.upper()
    assert "15m" in story.active_execution_trade
    assert story.carrying_timeframe == "5m"


def test_scenario_9_lower_tf_divergence_only_no_promotion() -> None:
    structures = {
        "5m": StructureState(timeframe="5m", candles=_candles([100.0, 99.6, 99.2]), current_price=99.2),
        "3m": _carry_structure("3m", Direction.DOWN),
    }
    divergence_audit = DivergenceAudit(tf_5m=_official_divergence("5m", DivergenceDirection.BEARISH, "99.50-100.00"))

    active_trade_audit = build_active_trade_audit(structures, divergence_audit)
    grouped = get_official_timeframes_by_direction(divergence_audit, active_trade_audit)
    bearish_tfs = {str(row["timeframe"]) for row in grouped["BEARISH"]}

    assert "5m" in bearish_tfs
    assert "15m" not in bearish_tfs
    assert "1h" not in bearish_tfs
