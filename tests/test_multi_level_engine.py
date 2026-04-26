"""Tests for multi-level same-story confirmation engine."""

from __future__ import annotations

from ocean_engine.models.enums import DivergenceDirection, DivergenceGrade, Direction, SetupType, TradeFunction
from ocean_engine.models.market import ActiveTradeAudit, ActiveTradeCandidate, DivergenceAudit, DivergenceState
from ocean_engine.trade.multi_level_engine import (
    build_multi_level_story,
    get_official_timeframes_by_direction,
    multi_level_summary,
)


def _official_divergence(timeframe: str, direction: DivergenceDirection) -> DivergenceState:
    return DivergenceState(
        timeframe=timeframe,
        exists=True,
        abc_valid=True,
        direction=direction,
        grade=DivergenceGrade.STRONG,
        impulse_confirmed=True,
    )


def _official_trade(timeframe: str, direction: DivergenceDirection, carry_tf: str = "") -> ActiveTradeCandidate:
    mapped_direction = Direction.UP if direction == DivergenceDirection.BULLISH else Direction.DOWN
    return ActiveTradeCandidate(
        timeframe=timeframe,
        exists=True,
        origin_timeframe=timeframe,
        direction=mapped_direction,
        setup_type=SetupType.TYPE_1,
        carry_timeframe=carry_tf,
        type_label=f"{timeframe} {'Bullish' if direction == DivergenceDirection.BULLISH else 'Bearish'} Type 1",
        existing_hold_valid=True,
    )


def _official_type3(timeframe: str, direction: Direction, carry_tf: str = "") -> ActiveTradeCandidate:
    mapped = DivergenceDirection.BULLISH if direction == Direction.UP else DivergenceDirection.BEARISH
    return ActiveTradeCandidate(
        timeframe=timeframe,
        exists=True,
        origin_timeframe=timeframe,
        direction=mapped,
        setup_type=SetupType.TYPE_3,
        trade_function=TradeFunction.BREAKOUT_TRADE,
        carry_timeframe=carry_tf,
        type_label=f"{timeframe} {'Bullish' if direction == Direction.UP else 'Bearish'} Type 3",
        existing_hold_valid=True,
    )


def test_one_official_15m_only_is_not_active() -> None:
    divergence_audit = DivergenceAudit(tf_15m=_official_divergence("15m", DivergenceDirection.BEARISH))
    active_trade_audit = ActiveTradeAudit()
    story = build_multi_level_story(divergence_audit, active_trade_audit)
    assert story.active is False


def test_official_1h_plus_15m_bearish_is_active() -> None:
    divergence_audit = DivergenceAudit(
        tf_1h=_official_divergence("1h", DivergenceDirection.BEARISH),
        tf_15m=_official_divergence("15m", DivergenceDirection.BEARISH),
    )
    story = build_multi_level_story(divergence_audit, ActiveTradeAudit())
    assert story.active is True
    assert story.direction == Direction.DOWN


def test_official_1h_plus_15m_bullish_is_active() -> None:
    divergence_audit = DivergenceAudit(
        tf_1h=_official_divergence("1h", DivergenceDirection.BULLISH),
        tf_15m=_official_divergence("15m", DivergenceDirection.BULLISH),
    )
    story = build_multi_level_story(divergence_audit, ActiveTradeAudit())
    assert story.active is True
    assert story.direction == Direction.UP


def test_15m_official_does_not_promote_1h_into_official() -> None:
    divergence_audit = DivergenceAudit(tf_15m=_official_divergence("15m", DivergenceDirection.BEARISH))
    grouped = get_official_timeframes_by_direction(divergence_audit, ActiveTradeAudit())
    bearish_tfs = {row["timeframe"] for row in grouped["BEARISH"]}
    assert "15m" in bearish_tfs
    assert "1h" not in bearish_tfs


def test_controlling_origin_chooses_higher_timeframe() -> None:
    divergence_audit = DivergenceAudit(
        tf_1h=_official_divergence("1h", DivergenceDirection.BEARISH),
        tf_15m=_official_divergence("15m", DivergenceDirection.BEARISH),
    )
    story = build_multi_level_story(divergence_audit, ActiveTradeAudit())
    assert "1H" in story.controlling_origin.upper()


def test_active_execution_trade_uses_selected_active_trade_if_same_direction() -> None:
    divergence_audit = DivergenceAudit(
        tf_1h=_official_divergence("1h", DivergenceDirection.BEARISH),
        tf_15m=_official_divergence("15m", DivergenceDirection.BEARISH),
    )
    active_trade_audit = ActiveTradeAudit(
        tf_15m=_official_trade("15m", DivergenceDirection.BEARISH, carry_tf="5m"),
        selected_active_trade_tf="15m",
    )
    story = build_multi_level_story(divergence_audit, active_trade_audit)
    assert "15m" in story.active_execution_trade


def test_type3_1h_plus_15m_bullish_is_active() -> None:
    active_trade_audit = ActiveTradeAudit(
        tf_1h=_official_type3("1h", Direction.UP, carry_tf="15m"),
        tf_15m=_official_type3("15m", Direction.UP, carry_tf="5m"),
        selected_active_trade_tf="15m",
    )
    story = build_multi_level_story(DivergenceAudit(), active_trade_audit)
    assert story.active is True
    assert story.direction == Direction.UP
    assert story.higher_tf_status == "OFFICIAL_MULTI_LEVEL"


def test_type3_1h_plus_15m_bearish_is_active() -> None:
    active_trade_audit = ActiveTradeAudit(
        tf_1h=_official_type3("1h", Direction.DOWN, carry_tf="15m"),
        tf_15m=_official_type3("15m", Direction.DOWN, carry_tf="5m"),
        selected_active_trade_tf="15m",
    )
    story = build_multi_level_story(DivergenceAudit(), active_trade_audit)
    assert story.active is True
    assert story.direction == Direction.DOWN
    assert story.higher_tf_status == "OFFICIAL_MULTI_LEVEL"


def test_type3_4h_plus_1h_bullish_uses_4h_as_controlling_origin() -> None:
    active_trade_audit = ActiveTradeAudit(
        tf_4h=_official_type3("4h", Direction.UP, carry_tf="1h"),
        tf_1h=_official_type3("1h", Direction.UP, carry_tf="15m"),
        selected_active_trade_tf="1h",
    )
    story = build_multi_level_story(DivergenceAudit(), active_trade_audit)
    assert story.active is True
    assert "4H" in story.controlling_origin.upper()


def test_only_15m_type3_is_not_multi_level_active() -> None:
    active_trade_audit = ActiveTradeAudit(
        tf_15m=_official_type3("15m", Direction.UP, carry_tf="5m"),
        selected_active_trade_tf="15m",
    )
    story = build_multi_level_story(DivergenceAudit(), active_trade_audit)
    assert story.active is False
    assert story.higher_tf_status == "WEAKENING_CONTEXT_ONLY"


def test_type3_active_execution_trade_uses_selected_active_trade() -> None:
    active_trade_audit = ActiveTradeAudit(
        tf_1h=_official_type3("1h", Direction.UP, carry_tf="15m"),
        tf_15m=_official_type3("15m", Direction.UP, carry_tf="5m"),
        selected_active_trade_tf="15m",
    )
    story = build_multi_level_story(DivergenceAudit(), active_trade_audit)
    assert "15m" in story.active_execution_trade
    assert "Type 3" in story.active_execution_trade


def test_type3_carry_comes_from_selected_active_trade() -> None:
    active_trade_audit = ActiveTradeAudit(
        tf_1h=_official_type3("1h", Direction.UP, carry_tf="15m"),
        tf_15m=_official_type3("15m", Direction.UP, carry_tf="5m"),
        selected_active_trade_tf="15m",
    )
    story = build_multi_level_story(DivergenceAudit(), active_trade_audit)
    assert story.carrying_timeframe == "5m"


def test_type3_is_not_treated_as_divergence() -> None:
    active_trade_audit = ActiveTradeAudit(
        tf_1h=_official_type3("1h", Direction.UP, carry_tf="15m"),
        tf_15m=_official_type3("15m", Direction.UP, carry_tf="5m"),
    )
    grouped = get_official_timeframes_by_direction(DivergenceAudit(), active_trade_audit)
    bullish = grouped["BULLISH"]
    assert len(bullish) == 2
    assert all(str(row["source"]) == "TRADE" for row in bullish)
    assert all("Divergence" not in str(row["label"]) for row in bullish)


def test_type3_rows_with_divergence_direction_are_normalized_for_multilevel() -> None:
    active_trade_audit = ActiveTradeAudit(
        tf_1h=ActiveTradeCandidate(
            timeframe="1h",
            exists=True,
            origin_timeframe="1h",
            direction=DivergenceDirection.BULLISH,
            setup_type=SetupType.TYPE_3,
            trade_function=TradeFunction.BREAKOUT_TRADE,
            carry_timeframe="15m",
            type_label="1H Bullish Type 3",
            existing_hold_valid=True,
        ),
        tf_15m=ActiveTradeCandidate(
            timeframe="15m",
            exists=True,
            origin_timeframe="15m",
            direction=DivergenceDirection.BULLISH,
            setup_type=SetupType.TYPE_3,
            trade_function=TradeFunction.BREAKOUT_TRADE,
            carry_timeframe="5m",
            type_label="15m Bullish Type 3",
            existing_hold_valid=True,
        ),
        selected_active_trade_tf="15m",
    )
    story = build_multi_level_story(DivergenceAudit(), active_trade_audit)
    assert story.active is True
    assert story.direction == Direction.UP


def test_active_execution_trade_ignores_selected_trade_when_direction_mismatches() -> None:
    divergence_audit = DivergenceAudit(
        tf_1h=_official_divergence("1h", DivergenceDirection.BEARISH),
        tf_15m=_official_divergence("15m", DivergenceDirection.BEARISH),
    )
    active_trade_audit = ActiveTradeAudit(
        tf_15m=_official_trade("15m", DivergenceDirection.BULLISH, carry_tf="5m"),
        selected_active_trade_tf="15m",
    )
    story = build_multi_level_story(divergence_audit, active_trade_audit)
    assert "15m Bullish" not in story.active_execution_trade


def test_carry_timeframe_comes_from_active_execution_trade() -> None:
    divergence_audit = DivergenceAudit(
        tf_1h=_official_divergence("1h", DivergenceDirection.BULLISH),
        tf_15m=_official_divergence("15m", DivergenceDirection.BULLISH),
    )
    active_trade_audit = ActiveTradeAudit(
        tf_15m=_official_trade("15m", DivergenceDirection.BULLISH, carry_tf="5m"),
        selected_active_trade_tf="15m",
    )
    story = build_multi_level_story(divergence_audit, active_trade_audit)
    assert story.carrying_timeframe == "5m"


def test_no_official_rows_gives_inactive_story_and_none_status() -> None:
    story = build_multi_level_story(DivergenceAudit(), ActiveTradeAudit())
    assert story.active is False
    assert story.higher_tf_status == "NONE"


def test_summary_includes_confirmed_control_execution_and_carry() -> None:
    divergence_audit = DivergenceAudit(
        tf_1h=_official_divergence("1h", DivergenceDirection.BEARISH),
        tf_15m=_official_divergence("15m", DivergenceDirection.BEARISH),
    )
    active_trade_audit = ActiveTradeAudit(
        tf_15m=_official_trade("15m", DivergenceDirection.BEARISH, carry_tf="5m"),
        selected_active_trade_tf="15m",
    )
    story = build_multi_level_story(divergence_audit, active_trade_audit)
    summary = multi_level_summary(story)
    assert "confirmed" in summary.lower()
    assert "controlling" in summary.lower()
    assert "execution" in summary.lower()
    assert "carry" in summary.lower()
