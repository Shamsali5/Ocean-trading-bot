"""HOLD/CLOSE/FLIP management gate for existing position handling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ManagementDecision:
    signal: str
    management_state: str
    if_already_in: str
    if_not_in: str
    reason: str


def evaluate_position_management(
    active_trade,
    carry_result,
    opposite_divergence_result,
    opposite_impulse_result,
    higher_context,
    room_for_new_move,
    trace=None,
) -> ManagementDecision:
    """Evaluate HOLD/CLOSE/FLIP outcomes for an existing position."""

    if not _bool(active_trade, "exists"):
        _add_check(
            trace=trace,
            name="Existing hold separated from fresh entry",
            passed=True,
            severity="INFO",
            details="No active trade to manage.",
        )
        _add_check(
            trace=trace,
            name="Close requires opposite divergence + impulse",
            passed=True,
            severity="INFO",
            details="No close attempt without active trade.",
        )
        _add_check(
            trace=trace,
            name="Flip requires close condition + new authority",
            passed=True,
            severity="INFO",
            details="No flip attempt without active trade.",
        )
        _add_check(
            trace=trace,
            name="Micro divergence alone cannot flip",
            passed=True,
            severity="INFO",
            details="No divergence context available.",
        )
        return ManagementDecision(
            signal="NONE",
            management_state="NONE",
            if_already_in="WAIT",
            if_not_in="WAIT",
            reason="No active trade to manage.",
        )

    existing_hold_valid = _bool(active_trade, "existing_hold_valid")
    fresh_entry_valid = _bool(active_trade, "fresh_entry_valid")
    side = _position_side(active_trade)

    carry_state = str(_value(carry_result, "state", fallback=("carry_state",)) or "").strip().upper()
    carry_finished = bool(_bool(carry_result, "finished")) or str(
        _value(active_trade, "current_status", fallback=("status",)) or ""
    ).strip().upper() == "FINISHED"
    continuation_failed = bool(
        carry_finished
        or carry_state == "EXHAUSTING"
        or _bool(carry_result, "continuation_failed")
    )

    divergence_exists = bool(
        _bool(opposite_divergence_result, "exists")
        or _bool(opposite_divergence_result, "confirmed")
    )
    divergence_direction = _normalize_direction(
        _value(opposite_divergence_result, "direction")
    )
    opposite_divergence = bool(divergence_exists and _is_opposite(side, divergence_direction))

    impulse_confirmed = bool(
        _bool(opposite_impulse_result, "confirmed")
        or _bool(opposite_impulse_result, "valid")
    )
    impulse_direction = _normalize_direction(_value(opposite_impulse_result, "direction"))
    if impulse_direction in {"BULLISH", "BEARISH"} and not _is_opposite(side, impulse_direction):
        impulse_confirmed = False
    opposite_impulse = bool(opposite_divergence and impulse_confirmed)

    close_condition_met = bool(opposite_divergence and opposite_impulse and continuation_failed)
    close_attempted = bool(opposite_divergence or carry_state == "EXHAUSTING" or carry_finished)

    higher_supports_weakening = bool(
        _bool(higher_context, "supports_weakening")
        or _bool(higher_context, "higher_supports_weakening")
    )
    opposite_side_has_carry = bool(
        _bool(higher_context, "opposite_side_has_carry")
        or _bool(higher_context, "opposite_has_carry")
    )
    micro_divergence_only = bool(
        _bool(opposite_divergence_result, "micro")
        or _bool(opposite_divergence_result, "micro_only")
    )
    new_authority_ready = bool(
        close_condition_met
        and opposite_side_has_carry
        and higher_supports_weakening
        and bool(room_for_new_move)
        and not micro_divergence_only
    )
    flip_attempted = bool(close_condition_met and opposite_side_has_carry and bool(room_for_new_move))

    _add_check(
        trace=trace,
        name="Existing hold separated from fresh entry",
        passed=True,
        severity="INFO",
        details=(
            f"existing_hold_valid={existing_hold_valid}, "
            f"fresh_entry_valid={fresh_entry_valid}, side={side}"
        ),
    )
    _add_check(
        trace=trace,
        name="Close requires opposite divergence + impulse",
        passed=(not close_attempted) or close_condition_met,
        severity="ERROR" if close_attempted and not close_condition_met else "INFO",
        details=(
            f"opposite_divergence={opposite_divergence}, opposite_impulse={opposite_impulse}, "
            f"continuation_failed={continuation_failed}"
        ),
    )
    _add_check(
        trace=trace,
        name="Flip requires close condition + new authority",
        passed=(not flip_attempted) or new_authority_ready,
        severity="ERROR" if flip_attempted and not new_authority_ready else "INFO",
        details=(
            f"close_condition={close_condition_met}, opposite_side_has_carry={opposite_side_has_carry}, "
            f"higher_supports_weakening={higher_supports_weakening}, room_for_new_move={bool(room_for_new_move)}"
        ),
    )
    _add_check(
        trace=trace,
        name="Micro divergence alone cannot flip",
        passed=not (micro_divergence_only and new_authority_ready),
        severity="ERROR" if micro_divergence_only and new_authority_ready else "INFO",
        details=f"micro_divergence_only={micro_divergence_only}, flip_ready={new_authority_ready}",
    )

    if not existing_hold_valid or side == "NONE":
        return ManagementDecision(
            signal="NONE",
            management_state="NONE",
            if_already_in="WAIT",
            if_not_in="WAIT",
            reason="No existing position ownership for management gate.",
        )

    hold_signal = "HOLD_LONG" if side == "LONG" else "HOLD_SHORT"
    close_signal = "CLOSE_LONG" if side == "LONG" else "CLOSE_SHORT"

    if new_authority_ready:
        return ManagementDecision(
            signal="CLOSE_AND_FLIP",
            management_state="CLOSE_AND_FLIP",
            if_already_in="CLOSE_AND_FLIP",
            if_not_in="WAIT",
            reason="Old move finished with opposite divergence+impulse and new opposite authority.",
        )

    if close_condition_met:
        return ManagementDecision(
            signal=close_signal,
            management_state="FULL_CLOSE",
            if_already_in=close_signal,
            if_not_in="WAIT",
            reason="Carry-level opposite divergence+impulse confirmed and continuation finished.",
        )

    if opposite_divergence and not opposite_impulse:
        return ManagementDecision(
            signal=hold_signal,
            management_state="CLOSE_WATCH",
            if_already_in=hold_signal,
            if_not_in="WAIT",
            reason="Opposite divergence detected without confirming opposite impulse.",
        )

    if carry_state == "MATURE":
        return ManagementDecision(
            signal=hold_signal,
            management_state="HOLD_WITH_CAUTION",
            if_already_in=hold_signal,
            if_not_in="WAIT",
            reason="Carry is mature but not structurally finished.",
        )

    if carry_state in {"EXHAUSTING", "UNCLEAR"} or carry_finished:
        return ManagementDecision(
            signal=hold_signal,
            management_state="CLOSE_WATCH",
            if_already_in=hold_signal,
            if_not_in="WAIT",
            reason="Carry is exhausting/unclear without complete opposite close confirmation.",
        )

    return ManagementDecision(
        signal=hold_signal,
        management_state="HOLD",
        if_already_in=hold_signal,
        if_not_in="WAIT",
        reason="Existing hold remains valid and no opposite close trigger is confirmed.",
    )


def _position_side(active_trade: Any) -> str:
    direction = _normalize_direction(_value(active_trade, "direction"))
    if direction == "BULLISH":
        return "LONG"
    if direction == "BEARISH":
        return "SHORT"
    return "NONE"


def _is_opposite(side: str, direction: str) -> bool:
    if side == "LONG":
        return direction == "BEARISH"
    if side == "SHORT":
        return direction == "BULLISH"
    return False


def _normalize_direction(raw: Any) -> str:
    value = str(getattr(raw, "value", raw) or "").strip().upper()
    if value in {"BULLISH", "UP", "BUY"}:
        return "BULLISH"
    if value in {"BEARISH", "DOWN", "SELL"}:
        return "BEARISH"
    return "NONE"


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
        file="ocean_management_gate.py",
        function="evaluate_position_management",
    )
