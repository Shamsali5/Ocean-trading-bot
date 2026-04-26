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


def test_compact_report_includes_active_trade_audit() -> None:
    text = format_compact_telegram_report(_sample_report())
    assert "Trade Audit:" in text
    assert "15m:15m Bullish Type 1" in text


def test_compact_report_includes_multi_level_story() -> None:
    text = format_compact_telegram_report(_sample_report())
    assert "Multi-Level:" in text
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
