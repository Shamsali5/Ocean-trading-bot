"""Tests for final BUY/SELL/WAIT entry gate."""

from __future__ import annotations

from ocean_entry_gate import evaluate_fresh_entry
from ocean_framework_v12_audit import FrameworkAuditTrace


def _base_payload(direction: str = "BULLISH") -> dict[str, object]:
    return {
        "move_context": {
            "current_timeframe": "15m",
            "current_origin": "DIVERGENCE",
        },
        "type_classification": {
            "type_label": "TYPE_1",
            "valid": True,
            "origin_timeframe": "15m",
            "direction": direction,
            "invalidation": "Break below 100.00 invalidates.",
            "entry_zone": "100.00-101.00",
        },
        "trade_function_result": {
            "trade_function": "DECOMPOSITION_TRADE" if direction == "BULLISH" else "HIGHER_LEVEL_DIVERGENCE_TRADE",
            "valid": True,
        },
        "impulse_result": {
            "confirmed": True,
            "acceptance_valid": True,
        },
        "carry_result": {
            "state": "ACTIVE",
            "timeframe": "5m",
            "finished": False,
        },
        "range_result": {
            "active": False,
            "price_location": "LOWER_EDGE",
        },
        "zone_results": [],
        "multi_level_result": {
            "direction": direction,
            "valid": True,
            "controlling_origin": "1H Bearish Type 1" if direction == "BEARISH" else "1H Bullish Type 1",
            "active_execution_trade": "15m Bearish Type 1" if direction == "BEARISH" else "15m Bullish Type 1",
            "carrying_timeframe": "5m",
            "higher_tf_official_or_context": "OFFICIAL_MULTI_LEVEL",
        },
    }


def test_buy_gate_passes_when_all_conditions_satisfied() -> None:
    payload = _base_payload("BULLISH")
    decision = evaluate_fresh_entry(**payload)
    assert decision.fresh_entry_valid is True
    assert decision.side == "BUY"


def test_sell_gate_passes_when_all_conditions_satisfied() -> None:
    payload = _base_payload("BEARISH")
    decision = evaluate_fresh_entry(**payload)
    assert decision.fresh_entry_valid is True
    assert decision.side == "SELL"


def test_zone_touch_alone_cannot_produce_buy_or_sell() -> None:
    payload = _base_payload("BULLISH")
    payload["zone_results"] = [{"timeframe": "15m", "zone_type": "DEMAND", "status": "REACTING"}]
    decision = evaluate_fresh_entry(**payload)
    assert decision.fresh_entry_valid is False
    assert decision.side is None
    assert "Zone exists but no structural confirmation" in decision.reason


def test_divergence_without_impulse_forces_wait() -> None:
    payload = _base_payload("BULLISH")
    payload["impulse_result"] = {"confirmed": False, "acceptance_valid": False}
    decision = evaluate_fresh_entry(**payload)
    assert decision.fresh_entry_valid is False
    assert decision.side is None
    assert "No impulse blocks entry" in decision.reason


def test_carry_exhausting_forces_wait() -> None:
    payload = _base_payload("BEARISH")
    payload["carry_result"] = {"state": "EXHAUSTING", "timeframe": "5m", "finished": False}
    decision = evaluate_fresh_entry(**payload)
    assert decision.fresh_entry_valid is False
    assert decision.side is None
    assert "carry exhausting" in decision.reason.lower()


def test_range_midpoint_blocks_entry() -> None:
    payload = _base_payload("BULLISH")
    payload["range_result"] = {"active": True, "price_location": "MID"}
    decision = evaluate_fresh_entry(**payload)
    assert decision.fresh_entry_valid is False
    assert decision.side is None
    assert "Range midpoint blocks fresh entry" in decision.reason


def test_breakout_without_acceptance_waits() -> None:
    payload = _base_payload("BULLISH")
    payload["type_classification"]["type_label"] = "TYPE_3"
    payload["trade_function_result"]["trade_function"] = "BREAKOUT_TRADE"
    payload["impulse_result"] = {"confirmed": True, "acceptance_valid": False}
    decision = evaluate_fresh_entry(**payload)
    assert decision.fresh_entry_valid is False
    assert decision.side is None
    assert "Breakout has no acceptance" in decision.reason


def test_required_audit_checks_are_emitted() -> None:
    payload = _base_payload("BULLISH")
    payload["impulse_result"] = {"confirmed": False, "acceptance_valid": False}
    trace = FrameworkAuditTrace(symbol="BTCUSDT", timestamp="now")
    _ = evaluate_fresh_entry(**payload, trace=trace)
    names = {check.name for check in trace.checks}
    assert "BUY gate checked" in names
    assert "SELL gate checked" in names
    assert "No fresh entry if carry exhausting" in names
    assert "Range midpoint blocks fresh entry" in names
    assert "No clear carry blocks entry" in names
    assert "No impulse blocks entry" in names
