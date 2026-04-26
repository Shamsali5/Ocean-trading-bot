"""Tests for deterministic Telegram report formatting."""

from __future__ import annotations

from ocean_engine.models.enums import (
    CarryState,
    Direction,
    DivergenceDirection,
    DivergenceGrade,
    FinalAction,
    SetupType,
    ZoneType,
)
from ocean_engine.models.market import (
    ActiveTradeAudit,
    ActiveTradeCandidate,
    CarryStatus,
    DecisionState,
    DivergenceAudit,
    DivergenceState,
    MarketReport,
    MultiLevelStory,
    RangeState,
    StructureState,
    SupplyDemandZone,
)
from ocean_engine.output.telegram_formatter import (
    format_compact_telegram_report,
    format_divergence_audit,
    format_final_action,
)


def _sample_report() -> MarketReport:
    decision = DecisionState(
        symbol="BTCUSDT",
        final_action=FinalAction.HOLD_LONG,
        management_state="HOLD_WITH_CAUTION",
        reason="Existing hold remains valid.",
        guard_reasons=["Type 1 validated."],
        active_trade_label="15m Bullish Type 1",
        controlling_origin="1H Bullish Type 1",
        active_execution_trade="15m Bullish Type 1",
        carrying_timeframe="5m",
        fresh_entry_valid=False,
        existing_hold_valid=True,
        too_late_to_chase=True,
    )

    divergence_audit = DivergenceAudit(
        tf_15m=DivergenceState(
            timeframe="15m",
            exists=True,
            abc_valid=True,
            direction=DivergenceDirection.BULLISH,
            grade=DivergenceGrade.STRONG,
            impulse_confirmed=True,
            price_zone="101.00-102.00",
            divergence_price=101.55,
            divergence_time_utc="2026-04-26T05:45:00Z",
            impulse_price=102.10,
            impulse_time_utc="2026-04-26T05:48:00Z",
        ),
        selected_last_meaningful_tf="15m",
    )

    active_trade_audit = ActiveTradeAudit(
        tf_15m=ActiveTradeCandidate(
            timeframe="15m",
            exists=True,
            origin_timeframe="15m",
            direction=Direction.UP,
            setup_type=SetupType.TYPE_1,
            type_label="15m Bullish Type 1",
            carry_timeframe="5m",
            carry_state=CarryState.ACTIVE,
            existing_hold_valid=True,
        ),
        selected_active_trade_tf="15m",
    )

    story = MultiLevelStory(
        active=True,
        direction=Direction.UP,
        confirmed_timeframes=["1h", "15m"],
        controlling_origin="1H Bullish Type 1",
        active_execution_trade="15m Bullish Type 1",
        carrying_timeframe="5m",
        higher_tf_status="OFFICIAL_MULTI_LEVEL",
    )

    zones = [
        SupplyDemandZone(
            timeframe="1h",
            zone_type=ZoneType.DEMAND,
            lower=100.0,
            upper=101.0,
            price_band="100.00-101.00",
            role="range edge",
            status="REACTING",
        )
    ]

    carry_status = CarryStatus(
        timeframe="5m",
        direction=Direction.UP,
        state=CarryState.ACTIVE,
        finished=False,
    )

    return MarketReport(
        symbol="BTCUSDT",
        generated_at="2026-04-26T06:00:00Z",
        current_price=102345.67,
        decision=decision,
        divergence_audit=divergence_audit,
        active_trade_audit=active_trade_audit,
        multi_level_story=story,
        zones=zones,
        carry={"5m": carry_status},
    )


def test_compact_report_includes_final_action() -> None:
    report = _sample_report()
    text = format_compact_telegram_report(report)
    assert "Signal: HOLD LONG" in text


def test_compact_report_includes_divergence_audit() -> None:
    text = format_compact_telegram_report(_sample_report())
    assert "Audit:" in text
    assert "15m:Bullish" in text


def test_market_story_summarizes_all_timeframes_current_state() -> None:
    report = _sample_report()
    report.structures = {
        "4h": StructureState(timeframe="4h", direction=Direction.DOWN, market_state="RANGE"),
        "1h": StructureState(timeframe="1h", direction=Direction.DOWN, market_state="TREND"),
        "15m": StructureState(timeframe="15m", direction=Direction.UP, market_state="TRANSITION"),
        "5m": StructureState(timeframe="5m", direction=Direction.UP, market_state="RANGE"),
        "3m": StructureState(timeframe="3m", direction=Direction.DOWN, market_state="TREND"),
    }
    text = format_compact_telegram_report(report)
    assert "Timeframe Story: 4H DOWN RANGE | 1H DOWN TREND | 15m UP TRANSITION | 5m UP RANGE | 3m DOWN TREND" in text


def test_compact_report_includes_active_trade_audit() -> None:
    text = format_compact_telegram_report(_sample_report())
    assert "ACTIVE TRADE" in text
    assert (
        "Function: NONE" in text
        or "Function: DECOMPOSITION TRADE" in text
        or "Function: BREAKOUT TRADE" in text
    )


def test_compact_report_includes_multi_level_story() -> None:
    text = format_compact_telegram_report(_sample_report())
    assert "MULTI-LEVEL STORY" in text
    assert "OFFICIAL_MULTI_LEVEL" in text


def test_compact_report_includes_supply_demand_zones() -> None:
    text = format_compact_telegram_report(_sample_report())
    assert "SUPPLY / DEMAND" in text
    assert "DEMAND" in text


def test_formatter_handles_missing_optional_fields_without_crashing() -> None:
    report = MarketReport(symbol="BTCUSDT", generated_at="2026-04-26T06:00:00Z")
    text = format_compact_telegram_report(report)
    assert "N/A" in text


def test_enum_formatting_removes_underscores() -> None:
    decision = DecisionState(symbol="BTCUSDT", final_action=FinalAction.HOLD_SHORT)
    assert "Signal: HOLD SHORT" in format_final_action(decision)


def test_guard_reasons_appear_when_present() -> None:
    report = _sample_report()
    report.decision.guard_reasons = ["Guard 1", "Guard 2"]
    report.decision.final_action = FinalAction.WAIT
    text = format_compact_telegram_report(report)
    assert "Guards: Guard 1 | Guard 2" in text


def test_formatter_does_not_change_decision_final_action() -> None:
    report = _sample_report()
    before = report.decision.final_action
    _ = format_compact_telegram_report(report)
    assert report.decision.final_action == before


def test_last_meaningful_formatter_shows_timeframe_and_direction() -> None:
    report = _sample_report()
    text = format_divergence_audit(report.divergence_audit)
    assert "Last Meaningful: 15m BULLISH" in text


def test_divergence_formatter_shows_divergence_and_impulse_price_time() -> None:
    report = _sample_report()
    text = format_divergence_audit(report.divergence_audit)
    assert "Divergence Price: 101.55" in text
    assert "Impulse Price: 102.10" in text


def test_divergence_formatter_lists_each_official_timeframe_event_details() -> None:
    report = _sample_report()
    report.divergence_audit = DivergenceAudit(
        tf_4h=DivergenceState(
            timeframe="4h",
            exists=True,
            abc_valid=True,
            direction=DivergenceDirection.BEARISH,
            grade=DivergenceGrade.MODERATE,
            impulse_confirmed=True,
            divergence_price=79400.0,
            divergence_time_utc="2026-04-20T08:00:00Z",
            impulse_price=78850.0,
            impulse_time_utc="2026-04-20T12:00:00Z",
        ),
        tf_3m=DivergenceState(
            timeframe="3m",
            exists=True,
            abc_valid=True,
            direction=DivergenceDirection.BULLISH,
            grade=DivergenceGrade.STRONG,
            impulse_confirmed=True,
            divergence_price=77880.0,
            divergence_time_utc="2026-04-26T10:02:59.999000+00:00",
            impulse_price=77992.1,
            impulse_time_utc="2026-04-26T10:08:59.999000+00:00",
        ),
        selected_last_meaningful_tf="3m",
    )
    text = format_divergence_audit(report.divergence_audit)
    assert "4H Div: 79,400.00 | Imp: 78,850.00" in text
    assert "3m Div: 77,880.00 | Imp: 77,992.10" in text


def test_removed_next_watch_section_from_compact_report() -> None:
    report = _sample_report()
    report.structures = {
        "15m": StructureState(
            timeframe="15m",
            range_state=RangeState(
                timeframe="15m",
                is_range=True,
                active=True,
                status="FAILED_BREAK_UP",
            ),
        )
    }
    text = format_compact_telegram_report(report)
    assert "NEXT WATCH" not in text


def test_type3_report_displays_active_trade_yes() -> None:
    report = _sample_report()
    report.active_trade_audit.tf_15m.setup_type = SetupType.TYPE_3
    report.active_trade_audit.tf_15m.trade_function = "BREAKOUT_TRADE"
    report.active_trade_audit.tf_15m.type_label = "15m Bullish Type 3"
    report.active_trade_audit.tf_15m.fresh_entry_valid = False
    report.active_trade_audit.tf_15m.existing_hold_valid = True
    report.active_trade_audit.tf_15m.too_late_to_chase = True
    report.active_trade_audit.tf_15m.confirmation_price = 77550.25
    report.active_trade_audit.tf_15m.confirmation_time_utc = "2026-04-26T10:15:00Z"
    text = format_compact_telegram_report(report)
    assert "Active Trade: YES" in text
    assert "Function: BREAKOUT TRADE" in text
    assert "Fresh Entry: NO" in text
    assert "Valid Hold: YES" in text
    assert "Too Late: YES" in text
    assert "Start Price/Time: 77,550.25 @ 2026-04-26T10:15:00Z" in text


def test_type2_report_displays_pullback_continuation() -> None:
    report = _sample_report()
    report.active_trade_audit.tf_15m.setup_type = SetupType.TYPE_2
    report.active_trade_audit.tf_15m.trade_function = "PULLBACK_CONTINUATION_TRADE"
    report.active_trade_audit.tf_15m.type_label = "15m Bullish Type 2"
    text = format_compact_telegram_report(report)
    assert "Type: TYPE 2" in text
    assert "Function: PULLBACK CONTINUATION TRADE" in text


def test_type1_report_displays_divergence_function() -> None:
    report = _sample_report()
    report.active_trade_audit.tf_15m.setup_type = SetupType.TYPE_1
    report.active_trade_audit.tf_15m.trade_function = "HIGHER_LEVEL_DIVERGENCE_TRADE"
    text = format_compact_telegram_report(report)
    assert "Type: TYPE 1" in text
    assert "Function: HIGHER LEVEL DIVERGENCE TRADE" in text


def test_no_divergence_but_type3_exists_displays_cleanly() -> None:
    report = _sample_report()
    report.divergence_audit = DivergenceAudit()
    report.active_trade_audit.tf_15m.setup_type = SetupType.TYPE_3
    report.active_trade_audit.tf_15m.trade_function = "BREAKOUT_TRADE"
    report.active_trade_audit.tf_15m.type_label = "15m Bullish Type 3"
    text = format_compact_telegram_report(report)
    assert "DIVERGENCE\nAudit: 4H:No | 1H:No | 15m:No | 5m:No | 3m:No" in text
    assert "Function: BREAKOUT TRADE" in text


def test_range_ownership_appears() -> None:
    report = _sample_report()
    report.structures = {
        "15m": StructureState(
            timeframe="15m",
            range_state=RangeState(
                timeframe="15m",
                is_range=True,
                active=True,
                status="ACTIVE",
                lower_edge=99.0,
                upper_edge=101.0,
                price_location="MID",
                ownership=Direction.UP,
            ),
        )
    }
    text = format_compact_telegram_report(report)
    assert "15m | Upper: 101.00 | Lower: 99.00" in text


def test_range_section_includes_upper_lower_boundaries_and_multitimeframe_notice() -> None:
    report = _sample_report()
    report.structures = {
        "4h": StructureState(
            timeframe="4h",
            range_state=RangeState(
                timeframe="4h",
                is_range=True,
                active=True,
                status="ACTIVE",
                lower_edge=73000.0,
                upper_edge=79000.0,
                price_location="UPPER_EDGE",
                ownership=Direction.UP,
            ),
        ),
        "1h": StructureState(
            timeframe="1h",
            range_state=RangeState(
                timeframe="1h",
                is_range=True,
                active=True,
                status="ACTIVE",
                lower_edge=76000.0,
                upper_edge=78000.0,
                price_location="MID",
                ownership=Direction.DOWN,
            ),
        ),
        "15m": StructureState(
            timeframe="15m",
            range_state=RangeState(
                timeframe="15m",
                is_range=True,
                active=True,
                status="ACTIVE",
                lower_edge=77280.0,
                upper_edge=78182.8,
                price_location="UPPER_EDGE",
                ownership=Direction.UP,
            ),
        ),
        "5m": StructureState(
            timeframe="5m",
            range_state=RangeState(
                timeframe="5m",
                is_range=True,
                active=True,
                status="ACTIVE",
                lower_edge=77379.0,
                upper_edge=78182.8,
                price_location="MID",
                ownership=Direction.UP,
            ),
        ),
        "3m": StructureState(
            timeframe="3m",
            range_state=RangeState(
                timeframe="3m",
                is_range=True,
                active=True,
                status="ACTIVE",
                lower_edge=77880.0,
                upper_edge=78182.8,
                price_location="MID",
                ownership=Direction.DOWN,
            ),
        ),
    }
    text = format_compact_telegram_report(report)
    assert "Active Ranges: 3" not in text
    assert "Multi-timeframe ranges: 4H,1H,15m" not in text
    assert "Upper: 79000.00" in text
    assert "Lower: 73000.00" in text
    assert "Upper: 78000.00" in text
    assert "Lower: 76000.00" in text
    assert "\n5m | Active: YES" not in text
    assert "\n3m | Active: YES" not in text
    assert "4H | Upper: 79000.00 | Lower: 73000.00" in text
    assert "1H | Upper: 78000.00 | Lower: 76000.00" in text
    assert "15m | Upper: 78182.80 | Lower: 77280.00" in text
    assert "Location:" not in text
    assert "Ownership:" not in text


def test_hierarchy_smallest_active_internal_move_uses_lowest_active_timeframe() -> None:
    report = _sample_report()
    report.story_state = None
    report.active_trade_audit = ActiveTradeAudit(
        tf_4h=ActiveTradeCandidate(
            timeframe="4h",
            exists=True,
            origin_timeframe="4h",
            direction=Direction.DOWN,
            setup_type=SetupType.TYPE_1,
            type_label="4H Bearish Type 1",
            carry_timeframe="1h",
            carry_state=CarryState.MATURE,
            existing_hold_valid=True,
        ),
        tf_3m=ActiveTradeCandidate(
            timeframe="3m",
            exists=True,
            origin_timeframe="3m",
            direction=Direction.UP,
            setup_type=SetupType.TYPE_1,
            type_label="3m Bullish Type 1",
            carry_timeframe="",
            carry_state=CarryState.ACTIVE,
            existing_hold_valid=True,
        ),
        selected_active_trade_tf="4h",
    )
    text = format_compact_telegram_report(report)
    assert "Smallest Active Internal Move: 3m" in text


def test_market_story_mentions_lower_tf_counter_move_at_range_bottom_with_demand() -> None:
    report = _sample_report()
    report.active_trade_audit = ActiveTradeAudit(
        tf_4h=ActiveTradeCandidate(
            timeframe="4h",
            exists=True,
            origin_timeframe="4h",
            direction=Direction.DOWN,
            setup_type=SetupType.TYPE_1,
            type_label="4H Bearish Type 1",
            carry_timeframe="1h",
            carry_state=CarryState.MATURE,
            existing_hold_valid=True,
        ),
        selected_active_trade_tf="4h",
    )
    report.divergence_audit = DivergenceAudit(
        tf_4h=DivergenceState(
            timeframe="4h",
            exists=True,
            abc_valid=True,
            direction=DivergenceDirection.BEARISH,
            grade=DivergenceGrade.STRONG,
            impulse_confirmed=True,
        ),
        tf_1h=DivergenceState(
            timeframe="1h",
            exists=True,
            abc_valid=True,
            direction=DivergenceDirection.BEARISH,
            grade=DivergenceGrade.STRONG,
            impulse_confirmed=True,
        ),
        tf_5m=DivergenceState(
            timeframe="5m",
            exists=True,
            abc_valid=True,
            direction=DivergenceDirection.BULLISH,
            grade=DivergenceGrade.STRONG,
            impulse_confirmed=True,
            divergence_price=73210.0,
            divergence_time_utc="2026-04-26T10:00:00Z",
        ),
        selected_last_meaningful_tf="5m",
    )
    report.structures = {
        "4h": StructureState(
            timeframe="4h",
            range_state=RangeState(
                timeframe="4h",
                is_range=True,
                active=True,
                lower_edge=73000.0,
                upper_edge=79000.0,
                status="ACTIVE",
                price_location="LOWER_EDGE",
            ),
        )
    }
    report.zones = [
        SupplyDemandZone(
            timeframe="1h",
            zone_type=ZoneType.DEMAND,
            lower=73100.0,
            upper=73300.0,
            price_band="73100.00-73300.00",
            role="bullish impulse origin",
            status="REACTING",
        )
    ]
    text = format_compact_telegram_report(report)
    assert (
        "Counter Move: 5m Bullish Divergence (tactical) from 4H range lower boundary + 1H demand."
        in text
    )
    assert "Counter Trigger Price: 73,210.00" in text


def test_failed_breakout_appears() -> None:
    report = _sample_report()
    report.structures = {
        "15m": StructureState(
            timeframe="15m",
            range_state=RangeState(
                timeframe="15m",
                is_range=True,
                active=True,
                status="FAILED_BREAK_UP",
                lower_edge=99.0,
                upper_edge=101.0,
                price_location="MID",
                ownership=Direction.UP,
            ),
        )
    }
    text = format_compact_telegram_report(report)
    assert "15m | Upper: 101.00 | Lower: 99.00" in text
    assert "FAILED_BREAK_UP" not in text


def test_formatter_shows_market_hierarchy_section() -> None:
    text = format_compact_telegram_report(_sample_report())
    assert "MARKET HIERARCHY" in text
    assert "Parent Move:" in text


def test_formatter_shows_flip_hint_when_close_and_flip_active() -> None:
    report = _sample_report()
    report.decision.final_action = FinalAction.CLOSE_AND_FLIP
    report.active_trade_audit.tf_5m = ActiveTradeCandidate(
        timeframe="5m",
        exists=True,
        origin_timeframe="5m",
        direction=Direction.DOWN,
        setup_type=SetupType.TYPE_1,
        type_label="5m Bearish Type 1",
        carry_timeframe="3m",
        carry_state=CarryState.FRESH,
        fresh_entry_valid=True,
    )
    text = format_compact_telegram_report(report)
    assert "Flip To: 5m Bearish Type 1" in text
    assert "Flip Carry: 3m" in text
