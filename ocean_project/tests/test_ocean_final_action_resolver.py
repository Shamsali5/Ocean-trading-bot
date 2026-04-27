"""Tests for one-action-only final resolver."""

from __future__ import annotations

from ocean_final_action_resolver import resolve_final_action
from ocean_framework_v12_audit import FrameworkAuditTrace


def test_fatal_framework_failures_force_wait() -> None:
    trace = FrameworkAuditTrace(symbol="BTCUSDT", timestamp="now")
    trace.add_check(
        name="fatal",
        passed=False,
        severity="FATAL",
        details="fatal condition",
    )
    decision = resolve_final_action(
        entry_decision={"fresh_entry_valid": True, "side": "BUY", "reason": "entry ok"},
        management_decision={"signal": "HOLD_SHORT", "management_state": "HOLD", "reason": "manage"},
        active_trade={"exists": True},
        framework_trace=trace,
        trace=trace,
    )
    assert decision.signal == "WAIT"
    assert "Fatal framework" in decision.reason


def test_active_trade_uses_management_priority() -> None:
    decision = resolve_final_action(
        entry_decision={"fresh_entry_valid": True, "side": "BUY", "reason": "entry ok"},
        management_decision={
            "signal": "HOLD_SHORT",
            "management_state": "HOLD",
            "reason": "existing short still valid",
        },
        active_trade={"exists": True},
        framework_trace=None,
    )
    assert decision.signal == "HOLD SHORT"
    assert "existing short" in decision.reason


def test_no_active_trade_uses_entry_signal() -> None:
    decision = resolve_final_action(
        entry_decision={"fresh_entry_valid": True, "side": "SELL", "reason": "fresh sell"},
        management_decision={"signal": "NONE", "management_state": "NONE"},
        active_trade={"exists": False},
        framework_trace=None,
    )
    assert decision.signal == "SELL"


def test_no_active_trade_invalid_entry_wait() -> None:
    decision = resolve_final_action(
        entry_decision={"fresh_entry_valid": False, "side": None, "reason": "invalid fresh entry"},
        management_decision={"signal": "NONE", "management_state": "NONE"},
        active_trade={"exists": False},
        framework_trace=None,
    )
    assert decision.signal == "WAIT"


def test_conflicting_signals_are_resolved_and_audited() -> None:
    trace = FrameworkAuditTrace(symbol="BTCUSDT", timestamp="now")
    _ = resolve_final_action(
        entry_decision={"fresh_entry_valid": True, "side": "BUY", "reason": "entry buy"},
        management_decision={"signal": "CLOSE_SHORT", "management_state": "FULL_CLOSE", "reason": "close short"},
        active_trade={"exists": True},
        framework_trace=trace,
        trace=trace,
    )
    names = {check.name for check in trace.checks}
    assert "Final action is one clear action" in names
    assert "Existing hold separated from fresh entry" in names
    assert "Conflicting signals resolved" in names
    assert "Fatal framework failures force WAIT" in names
