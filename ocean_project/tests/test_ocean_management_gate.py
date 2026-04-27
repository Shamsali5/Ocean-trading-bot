"""Tests for HOLD/CLOSE/FLIP management gate."""

from __future__ import annotations

from ocean_framework_v12_audit import FrameworkAuditTrace
from ocean_management_gate import evaluate_position_management


def _base_payload(direction: str = "BULLISH") -> dict[str, object]:
    return {
        "active_trade": {
            "exists": True,
            "existing_hold_valid": True,
            "fresh_entry_valid": False,
            "direction": direction,
            "current_status": "ACTIVE",
        },
        "carry_result": {"state": "ACTIVE", "finished": False},
        "opposite_divergence_result": {"exists": False, "direction": "NONE", "micro_only": False},
        "opposite_impulse_result": {"confirmed": False, "direction": "NONE"},
        "higher_context": {
            "supports_weakening": False,
            "opposite_side_has_carry": False,
        },
        "room_for_new_move": False,
    }


def test_none_state_when_no_active_trade_exists() -> None:
    payload = _base_payload()
    payload["active_trade"] = {"exists": False}
    decision = evaluate_position_management(**payload)
    assert decision.signal == "NONE"
    assert decision.management_state == "NONE"
    assert decision.if_already_in == "WAIT"
    assert decision.if_not_in == "WAIT"


def test_hold_long_when_origin_valid_and_no_opposite_confirmation() -> None:
    payload = _base_payload("BULLISH")
    decision = evaluate_position_management(**payload)
    assert decision.signal == "HOLD_LONG"
    assert decision.management_state == "HOLD"
    assert decision.if_already_in == "HOLD_LONG"
    assert decision.if_not_in == "WAIT"


def test_mature_carry_is_hold_with_caution_not_close() -> None:
    payload = _base_payload("BEARISH")
    payload["carry_result"] = {"state": "MATURE", "finished": False}
    decision = evaluate_position_management(**payload)
    assert decision.signal == "HOLD_SHORT"
    assert decision.management_state == "HOLD_WITH_CAUTION"
    assert "mature" in decision.reason.lower()


def test_opposite_divergence_without_impulse_is_close_watch() -> None:
    payload = _base_payload("BULLISH")
    payload["opposite_divergence_result"] = {"exists": True, "direction": "BEARISH", "micro_only": False}
    payload["opposite_impulse_result"] = {"confirmed": False, "direction": "BEARISH"}
    decision = evaluate_position_management(**payload)
    assert decision.signal == "HOLD_LONG"
    assert decision.management_state == "CLOSE_WATCH"
    assert "without confirming opposite impulse" in decision.reason


def test_full_close_requires_opposite_divergence_plus_impulse() -> None:
    payload = _base_payload("BEARISH")
    payload["carry_result"] = {"state": "EXHAUSTING", "finished": False}
    payload["opposite_divergence_result"] = {"exists": True, "direction": "BULLISH", "micro_only": False}
    payload["opposite_impulse_result"] = {"confirmed": True, "direction": "BULLISH"}
    decision = evaluate_position_management(**payload)
    assert decision.signal == "CLOSE_SHORT"
    assert decision.management_state == "FULL_CLOSE"


def test_close_and_flip_requires_new_authority_not_micro_only() -> None:
    payload = _base_payload("BULLISH")
    payload["carry_result"] = {"state": "EXHAUSTING", "finished": True}
    payload["opposite_divergence_result"] = {"exists": True, "direction": "BEARISH", "micro_only": False}
    payload["opposite_impulse_result"] = {"confirmed": True, "direction": "BEARISH"}
    payload["higher_context"] = {
        "supports_weakening": True,
        "opposite_side_has_carry": True,
        "official_opposite_authority": True,
    }
    payload["room_for_new_move"] = True
    decision = evaluate_position_management(**payload)
    assert decision.signal == "CLOSE_AND_FLIP"
    assert decision.management_state == "CLOSE_AND_FLIP"


def test_close_and_flip_requires_official_opposite_authority() -> None:
    payload = _base_payload("BULLISH")
    payload["carry_result"] = {"state": "EXHAUSTING", "finished": True}
    payload["opposite_divergence_result"] = {"exists": True, "direction": "BEARISH", "micro_only": False}
    payload["opposite_impulse_result"] = {"confirmed": True, "direction": "BEARISH"}
    payload["higher_context"] = {
        "supports_weakening": True,
        "opposite_side_has_carry": True,
        "official_opposite_authority": False,
    }
    payload["room_for_new_move"] = True
    decision = evaluate_position_management(**payload)
    assert decision.signal == "CLOSE_LONG"
    assert decision.management_state == "FULL_CLOSE"


def test_micro_divergence_cannot_flip_even_with_other_flip_inputs() -> None:
    payload = _base_payload("BULLISH")
    payload["carry_result"] = {"state": "EXHAUSTING", "finished": True}
    payload["opposite_divergence_result"] = {"exists": True, "direction": "BEARISH", "micro_only": True}
    payload["opposite_impulse_result"] = {"confirmed": True, "direction": "BEARISH"}
    payload["higher_context"] = {
        "supports_weakening": True,
        "opposite_side_has_carry": True,
        "official_opposite_authority": True,
    }
    payload["room_for_new_move"] = True
    decision = evaluate_position_management(**payload)
    assert decision.signal == "CLOSE_LONG"
    assert decision.management_state == "FULL_CLOSE"


def test_required_management_audit_checks_are_emitted() -> None:
    payload = _base_payload("BULLISH")
    payload["opposite_divergence_result"] = {"exists": True, "direction": "BEARISH", "micro_only": False}
    trace = FrameworkAuditTrace(symbol="BTCUSDT", timestamp="now")
    _ = evaluate_position_management(**payload, trace=trace)
    names = {check.name for check in trace.checks}
    assert "Existing hold separated from fresh entry" in names
    assert "Close requires opposite divergence + impulse" in names
    assert "Flip requires close condition + new authority" in names
    assert "Micro divergence alone cannot flip" in names
