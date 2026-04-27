"""Resolve framework output into exactly one final action."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ocean_framework_v12_contract import FINAL_ACTIONS


@dataclass(slots=True)
class FinalDecision:
    signal: str
    trade_function: str
    type_label: str
    controlling_origin: str
    active_execution_trade: str
    entry_zone: str
    stop_or_invalidation: str
    carrying_tf: str
    management_state: str
    reason: str


def resolve_final_action(
    entry_decision,
    management_decision,
    active_trade,
    framework_trace,
    trace=None,
) -> FinalDecision:
    """Return one contract-valid final action using framework priority rules."""

    has_active_trade = bool(_bool(active_trade, "exists"))
    fatal_framework_error = _framework_has_fatal_error(framework_trace)
    mgmt_signal = _normalize_signal(_value(management_decision, "signal"))
    entry_signal = _normalize_signal(
        _value(entry_decision, "side")
        if _value(entry_decision, "side") is not None
        else _value(entry_decision, "signal")
    )
    entry_valid = bool(
        _bool(entry_decision, "fresh_entry_valid")
        or (entry_signal in {"BUY", "SELL"} and _value(entry_decision, "side") is not None)
    )
    mgmt_state = str(_value(management_decision, "management_state") or "NONE").strip().upper()
    if mgmt_state not in {
        "HOLD",
        "HOLD_WITH_CAUTION",
        "CLOSE_WATCH",
        "FULL_CLOSE",
        "CLOSE_AND_FLIP",
        "NONE",
    }:
        mgmt_state = "NONE"

    conflict = _signals_conflict(
        entry_signal=entry_signal,
        management_signal=mgmt_signal,
        has_active_trade=has_active_trade,
    )
    _add_check(
        trace=trace,
        name="Existing hold separated from fresh entry",
        passed=not (has_active_trade and entry_signal in {"BUY", "SELL"} and mgmt_signal not in {"WAIT", "NONE", "CLOSE AND FLIP"}),
        severity="ERROR"
        if has_active_trade and entry_signal in {"BUY", "SELL"} and mgmt_signal not in {"WAIT", "NONE", "CLOSE AND FLIP"}
        else "INFO",
        details=(
            f"has_active_trade={has_active_trade}, entry_signal={entry_signal}, management_signal={mgmt_signal}"
        ),
    )

    resolved_signal = "WAIT"
    reason = ""
    if fatal_framework_error:
        resolved_signal = "WAIT"
        reason = "Fatal framework failures force WAIT."
    elif has_active_trade:
        if mgmt_signal in {"HOLD LONG", "HOLD SHORT", "CLOSE LONG", "CLOSE SHORT", "CLOSE AND FLIP"}:
            resolved_signal = mgmt_signal
            reason = str(_value(management_decision, "reason") or "Active trade uses management decision.")
        elif conflict:
            resolved_signal = "WAIT"
            reason = "Conflicting entry and management signals with active trade."
        else:
            resolved_signal = "WAIT"
            reason = "Active trade exists but no valid management signal."
    else:
        if entry_valid and entry_signal in {"BUY", "SELL"}:
            resolved_signal = entry_signal
            reason = str(_value(entry_decision, "reason") or "No active trade; using fresh entry decision.")
        else:
            resolved_signal = "WAIT"
            reason = str(_value(entry_decision, "reason") or "No active trade and no valid fresh entry.")

    if conflict and not fatal_framework_error and resolved_signal != "CLOSE AND FLIP":
        if has_active_trade and mgmt_signal in {"HOLD LONG", "HOLD SHORT", "CLOSE LONG", "CLOSE SHORT", "CLOSE AND FLIP"}:
            # Management decision has explicit priority for active positions.
            resolved_signal = mgmt_signal
            reason = str(_value(management_decision, "reason") or "Management signal prioritized for active trade.")
        else:
            resolved_signal = "WAIT"
            reason = "Conflicting signals resolved to WAIT."

    if resolved_signal not in set(FINAL_ACTIONS):
        resolved_signal = "WAIT"
        reason = f"Resolved signal was outside contract FINAL_ACTIONS; forced WAIT."

    _add_check(
        trace=trace,
        name="Conflicting signals resolved",
        passed=not conflict or resolved_signal in {"WAIT", mgmt_signal},
        severity="ERROR" if conflict and resolved_signal not in {"WAIT", mgmt_signal} else "INFO",
        details=(
            f"conflict={conflict}, entry_signal={entry_signal}, management_signal={mgmt_signal}, resolved={resolved_signal}"
        ),
    )
    _add_check(
        trace=trace,
        name="Fatal framework failures force WAIT",
        passed=(not fatal_framework_error) or resolved_signal == "WAIT",
        severity="ERROR" if fatal_framework_error and resolved_signal != "WAIT" else "INFO",
        details=f"fatal_framework_error={fatal_framework_error}, resolved={resolved_signal}",
    )
    _add_check(
        trace=trace,
        name="Final action is one clear action",
        passed=resolved_signal in set(FINAL_ACTIONS),
        severity="ERROR" if resolved_signal not in set(FINAL_ACTIONS) else "INFO",
        details=f"resolved_signal={resolved_signal}",
    )

    return FinalDecision(
        signal=resolved_signal,
        trade_function=str(_value(active_trade, "trade_function", fallback=("trade_function_label",)) or "NONE"),
        type_label=str(_value(active_trade, "type_label") or ""),
        controlling_origin=str(_value(active_trade, "controlling_origin") or ""),
        active_execution_trade=str(_value(active_trade, "active_execution_trade") or ""),
        entry_zone=str(
            _value(entry_decision, "entry_zone", fallback=("origin_price_zone",))
            or _value(active_trade, "origin_price_zone")
            or ""
        ),
        stop_or_invalidation=str(
            _value(entry_decision, "invalidation", fallback=("stop_or_invalidation",))
            or _value(active_trade, "invalidation")
            or ""
        ),
        carrying_tf=str(_value(active_trade, "carry_timeframe", fallback=("carrying_tf",)) or ""),
        management_state=mgmt_state,
        reason=reason,
    )


def _framework_has_fatal_error(framework_trace: Any) -> bool:
    if framework_trace is None:
        return False
    if hasattr(framework_trace, "has_fatal"):
        try:
            return bool(framework_trace.has_fatal())
        except Exception:
            return False
    checks = getattr(framework_trace, "checks", None)
    if not isinstance(checks, list):
        return False
    for check in checks:
        passed = bool(getattr(check, "passed", True))
        severity = str(getattr(check, "severity", "")).strip().upper()
        if (not passed) and severity == "FATAL":
            return True
    return False


def _signals_conflict(entry_signal: str, management_signal: str, has_active_trade: bool) -> bool:
    if not has_active_trade:
        return False
    if entry_signal not in {"BUY", "SELL"}:
        return False
    if management_signal in {"WAIT", "NONE"}:
        return False
    if management_signal == "CLOSE AND FLIP":
        return False
    return True


def _normalize_signal(value: Any) -> str:
    text = str(value or "").strip().upper().replace("_", " ")
    mapping = {
        "BUY": "BUY",
        "SELL": "SELL",
        "HOLD LONG": "HOLD LONG",
        "HOLD SHORT": "HOLD SHORT",
        "CLOSE LONG": "CLOSE LONG",
        "CLOSE SHORT": "CLOSE SHORT",
        "CLOSE AND FLIP": "CLOSE AND FLIP",
        "WAIT": "WAIT",
        "NONE": "NONE",
    }
    return mapping.get(text, "WAIT")


def _value(result: Any, key: str, fallback: tuple[str, ...] = ()) -> Any:
    if result is None:
        return None
    if isinstance(result, dict):
        if key in result:
            return result.get(key)
        for alt in fallback:
            if alt in result:
                return result.get(alt)
        return None
    value = getattr(result, key, None)
    if value is not None:
        return value
    for alt in fallback:
        value = getattr(result, alt, None)
        if value is not None:
            return value
    return None


def _bool(result: Any, key: str, fallback: tuple[str, ...] = ()) -> bool:
    return bool(_value(result, key, fallback))


def _add_check(
    *,
    trace: Any,
    name: str,
    passed: bool,
    severity: str,
    details: str,
) -> None:
    if trace is None or not hasattr(trace, "add_check"):
        return
    trace.add_check(
        name=name,
        passed=bool(passed),
        severity=severity,
        details=details,
        file="ocean_final_action_resolver.py",
        function="resolve_final_action",
    )
