"""Tests for parent/current move story engine."""

from __future__ import annotations

from ocean_engine.models.enums import Direction, MarketState, SetupType, ZoneType
from ocean_engine.models.market import (
    ActiveTradeAudit,
    ActiveTradeCandidate,
    DivergenceAudit,
    MultiLevelStory,
    RangeState,
    StoryState,
    StructureState,
    SupplyDemandZone,
)
from ocean_engine.trade.story_engine import build_story_state


def _structure(
    timeframe: str,
    *,
    direction: Direction,
    market_state: MarketState,
    range_active: bool = False,
) -> StructureState:
    return StructureState(
        timeframe=timeframe,
        direction=direction,
        market_state=market_state,
        range_state=RangeState(timeframe=timeframe, active=range_active),
    )


def _candidate(
    *,
    timeframe: str,
    direction: Direction,
    setup_type: SetupType,
    carry_timeframe: str = "",
) -> ActiveTradeCandidate:
    mapped_direction = Direction.UP if direction == Direction.UP else Direction.DOWN
    return ActiveTradeCandidate(
        timeframe=timeframe,
        exists=True,
        origin_timeframe=timeframe,
        direction=mapped_direction,
        setup_type=setup_type,
        carry_timeframe=carry_timeframe,
        type_label=f"{timeframe} {'Bullish' if direction == Direction.UP else 'Bearish'} {setup_type.value}",
    )


def test_parent_4h_up_and_active_15m_bullish_type3_is_with_parent() -> None:
    structures = {
        "4h": _structure("4h", direction=Direction.UP, market_state=MarketState.TREND),
        "15m": _structure("15m", direction=Direction.UP, market_state=MarketState.TRANSITION),
    }
    audit = ActiveTradeAudit(
        tf_15m=_candidate(timeframe="15m", direction=Direction.UP, setup_type=SetupType.TYPE_3, carry_timeframe="5m"),
        selected_active_trade_tf="15m",
    )
    story = build_story_state(
        structures=structures,
        divergence_audit=DivergenceAudit(),
        active_trade_audit=audit,
        multi_level_story=MultiLevelStory(),
        range_states=None,
        zones=[],
    )
    assert isinstance(story, StoryState)
    assert story.parent_timeframe == "4h"
    assert story.parent_direction == Direction.UP
    assert story.current_move_timeframe == "15m"
    assert story.current_move_direction == Direction.UP
    assert story.current_move_origin == "BREAKOUT"
    assert story.current_move_with_parent is True
    assert story.carrying_timeframe == "5m"


def test_parent_4h_up_and_active_15m_bearish_type1_is_against_parent() -> None:
    structures = {
        "4h": _structure("4h", direction=Direction.UP, market_state=MarketState.TREND),
        "15m": _structure("15m", direction=Direction.DOWN, market_state=MarketState.TRANSITION),
    }
    audit = ActiveTradeAudit(
        tf_15m=_candidate(timeframe="15m", direction=Direction.DOWN, setup_type=SetupType.TYPE_1, carry_timeframe="5m"),
        selected_active_trade_tf="15m",
    )
    story = build_story_state(
        structures=structures,
        divergence_audit=DivergenceAudit(),
        active_trade_audit=audit,
        multi_level_story=MultiLevelStory(),
        range_states=None,
        zones=[],
    )
    assert story.parent_timeframe == "4h"
    assert story.parent_direction == Direction.UP
    assert story.current_move_timeframe == "15m"
    assert story.current_move_direction == Direction.DOWN
    assert story.current_move_origin == "DIVERGENCE"
    assert story.current_move_with_parent is False


def test_no_active_trade_sets_current_move_unclear() -> None:
    structures = {"4h": _structure("4h", direction=Direction.UP, market_state=MarketState.TREND)}
    story = build_story_state(
        structures=structures,
        divergence_audit=DivergenceAudit(),
        active_trade_audit=ActiveTradeAudit(),
        multi_level_story=MultiLevelStory(),
        range_states=None,
        zones=[],
    )
    assert story.current_move_timeframe == ""
    assert story.current_move_direction == Direction.UNCLEAR
    assert story.current_move_origin == "UNCLEAR"
    assert story.current_move_with_parent is False


def test_summary_includes_parent_current_origin_and_carry() -> None:
    structures = {
        "4h": _structure("4h", direction=Direction.UP, market_state=MarketState.TREND),
        "15m": _structure("15m", direction=Direction.UP, market_state=MarketState.TRANSITION),
    }
    audit = ActiveTradeAudit(
        tf_15m=_candidate(timeframe="15m", direction=Direction.UP, setup_type=SetupType.TYPE_3, carry_timeframe="5m"),
        selected_active_trade_tf="15m",
    )
    story = build_story_state(
        structures=structures,
        divergence_audit=DivergenceAudit(),
        active_trade_audit=audit,
        multi_level_story=MultiLevelStory(
            controlling_origin="1H Bullish Type 3",
            active_execution_trade="15m Bullish Type 3",
            carrying_timeframe="5m",
        ),
        range_states={"15m": RangeState(timeframe="15m", active=True)},
        zones=[SupplyDemandZone(timeframe="15m", zone_type=ZoneType.DEMAND, lower=100.0, upper=101.0)],
    )
    text = story.summary.lower()
    assert "parent=" in text
    assert "current=" in text
    assert "origin=" in text
    assert "carry=" in text

