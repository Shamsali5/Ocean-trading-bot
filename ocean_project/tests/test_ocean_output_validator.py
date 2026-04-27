"""Tests for required A-R output validator and renderer."""

from __future__ import annotations

from ocean_framework_v12_audit import FrameworkAuditTrace
from ocean_output_validator import render_framework_output, validate_required_output_sections


def test_validator_returns_valid_for_complete_output() -> None:
    output = {
        "A META": {"symbol": "BTCUSDT", "timestamp": "2026-04-27T00:00:00Z"},
        "B HIGHER_TIMEFRAME_CONTEXT": {"highest_tf": "4H", "parent_bias": "DOWN"},
        "C CURRENT_MOVE": {"timeframe": "15m", "direction": "UP", "origin": "DIVERGENCE_ORIGIN"},
        "D STRUCTURE_STATE": {"state": "RANGE", "timeframe": "15m"},
        "E DIVERGENCE_STATE": {"exists": True, "direction": "BULLISH", "grade": "STRONG"},
        "F LAST_MEANINGFUL_DIVERGENCE": {"timeframe": "15m", "direction": "BULLISH"},
        "G IMPULSE_ACCEPTANCE": {"impulse_confirmed": True, "acceptance_valid": True},
        "H SUPPLY_DEMAND_ZONE_MAP": {"zones": []},
        "I CARRY_STATUS": {"state": "ACTIVE", "carrying_tf": "5m"},
        "J MULTI_LEVEL_STORY": {"active": True, "controlling_origin": "1H Bullish Type 1"},
        "K TRADE_CLASSIFICATION": {"trade_function": "DECOMPOSITION_TRADE", "type_label": "15m Bullish Type 1"},
        "L MANAGEMENT_STATE": {"management_state": "HOLD"},
        "M CURRENT_ACTIVE_MEANINGFUL_TRADE": {"exists": True, "label": "15m Bullish Type 1"},
        "N POSITION_MANAGEMENT_FOR_ACTIVE_TRADE": {"already_in_status": "HOLD LONG", "not_in_status": "WAIT"},
        "O MARKET_HIERARCHY": {"controlling_origin": "1H Bullish Type 1", "active_execution_trade": "15m Bullish Type 1"},
        "P WHAT_TO_WATCH_NEXT": {"next_event": "carry continuation"},
        "Q CURRENT_MOVE_SUMMARY": {"summary": "bullish continuation with active carry"},
        "R FINAL_EXECUTION_BLOCK": {
            "Signal": "HOLD LONG",
            "Trade Function": "DECOMPOSITION_TRADE",
            "Type Label": "15m Bullish Type 1",
            "Controlling Origin": "1H Bullish Type 1",
            "Active Execution Trade": "15m Bullish Type 1",
            "Entry Zone": "100.00-101.00",
            "Stop / Invalidation": "Break below 100.00",
            "Carrying TF": "5m",
            "Management State": "HOLD",
            "Reason": "Existing hold remains valid.",
        },
    }
    result = validate_required_output_sections(output)
    assert result["valid"] is True
    assert result["missing_sections"] == []
    assert result["missing_fields"] == {}


def test_validator_marks_missing_sections_and_fields() -> None:
    output = {
        "A META": {"symbol": "BTCUSDT"},
        "R FINAL_EXECUTION_BLOCK": {"Signal": "WAIT"},
    }
    trace = FrameworkAuditTrace(symbol="BTCUSDT", timestamp="now")
    result = validate_required_output_sections(output, trace=trace)
    assert result["valid"] is False
    assert "B HIGHER_TIMEFRAME_CONTEXT" in result["missing_sections"]
    assert "A META" in result["missing_fields"]
    assert "R FINAL_EXECUTION_BLOCK" in result["missing_fields"]
    names = {check.name for check in trace.checks}
    assert "Required output section exists" in names
    assert "Required output section fields exist" in names


def test_renderer_outputs_stable_sections_without_raw_json_dump() -> None:
    output = {
        "A META": {"symbol": "BTCUSDT", "timestamp": "2026-04-27T00:00:00Z"},
        "R FINAL_EXECUTION_BLOCK": {
            "Signal": "WAIT",
            "Trade Function": "NONE",
            "Type Label": "NONE",
            "Controlling Origin": "N/A",
            "Active Execution Trade": "N/A",
            "Entry Zone": "N/A",
            "Stop / Invalidation": "N/A",
            "Carrying TF": "N/A",
            "Management State": "NONE",
            "Reason": "No valid setup.",
        },
    }
    rendered = render_framework_output(output)
    assert "A META" in rendered
    assert "R FINAL_EXECUTION_BLOCK" in rendered
    assert "Signal: WAIT" in rendered
    assert "Controlling Origin: N/A" in rendered
    assert "Active Execution Trade: N/A" in rendered
    assert "Carrying TF: N/A" in rendered
    assert "{" not in rendered
    assert "}" not in rendered

