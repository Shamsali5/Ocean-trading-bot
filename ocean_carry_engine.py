"""Strict carry assignment and lifecycle classification for framework v1.2."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ocean_framework_v12_contract import expected_carry_tf, normalize_tf


@dataclass(slots=True)
class CarryResult:
    origin_timeframe: str
    carrying_timeframe: str | None
    direction: str
    state: str  # FRESH / ACTIVE / MATURE / EXHAUSTING / UNCLEAR
    required_lower_cycle_complete: str  # YES / NO / PARTIAL / UNCLEAR
    opposite_divergence: bool
    opposite_impulse: bool
    continuation_failed: bool
    carry_finished: bool
    reason: str


def assign_carry_timeframe(origin_timeframe, trace=None):
    """Assign carry timeframe from framework contract mapping."""

    origin = normalize_tf(str(origin_timeframe or ""))
    carrying = expected_carry_tf(origin)
    if carrying is not None:
        carrying = normalize_tf(carrying)

    assigned = carrying is not None
    not_collapsed = carrying is None or carrying != origin
    _add_check(
        trace=trace,
        name="Carry timeframe assigned from origin timeframe",
        passed=assigned,
        severity="ERROR" if not assigned else "INFO",
        details=f"origin={origin}, carry={carrying}",
        function="assign_carry_timeframe",
    )
    _add_check(
        trace=trace,
        name="Carry timeframe not used as origin timeframe",
        passed=not_collapsed,
        severity="ERROR" if not not_collapsed else "INFO",
        details=f"origin={origin}, carry={carrying}",
        function="assign_carry_timeframe",
    )
    return carrying


def classify_carry_state(
    origin_timeframe,
    direction,
    lower_tf_context,
    opposite_divergence_result=None,
    opposite_impulse_result=None,
    trace=None,
) -> CarryResult:
    """Classify strict carry state from origin, carry context, and opposite signals."""

    origin = normalize_tf(str(origin_timeframe or ""))
    carry_tf = assign_carry_timeframe(origin, trace=trace)
    dir_text = _normalize_direction(direction)
    if carry_tf is None:
        result = CarryResult(
            origin_timeframe=origin,
            carrying_timeframe=None,
            direction=dir_text,
            state="UNCLEAR",
            required_lower_cycle_complete="UNCLEAR",
            opposite_divergence=False,
            opposite_impulse=False,
            continuation_failed=False,
            carry_finished=False,
            reason="No carry timeframe mapping for origin timeframe.",
        )
        _add_check(
            trace=trace,
            name="Required lower-level cycle checked",
            passed=False,
            severity="ERROR",
            details=result.reason,
            function="classify_carry_state",
        )
        _add_check(
            trace=trace,
            name="Carry finish requires opposite divergence + opposite impulse + continuation failure",
            passed=True,
            severity="INFO",
            details="Carry cannot finish without mapped carry timeframe.",
            function="classify_carry_state",
        )
        return result

    context = _extract_lower_context(lower_tf_context, dir_text)
    opposite_divergence = _as_bool(opposite_divergence_result)
    opposite_impulse = _as_bool(opposite_impulse_result)
    continuation_failed = context["continuation_failed"]

    carry_finished = bool(opposite_divergence and opposite_impulse and continuation_failed)
    finish_rule_ok = carry_finished == (
        opposite_divergence and opposite_impulse and continuation_failed
    )
    _add_check(
        trace=trace,
        name="Carry finish requires opposite divergence + opposite impulse + continuation failure",
        passed=finish_rule_ok,
        severity="ERROR" if not finish_rule_ok else "INFO",
        details=(
            "opposite_divergence="
            f"{opposite_divergence}, opposite_impulse={opposite_impulse}, "
            f"continuation_failed={continuation_failed}, carry_finished={carry_finished}"
        ),
        function="classify_carry_state",
    )

    if not context["context_available"]:
        state = "UNCLEAR"
        required_cycle = "UNCLEAR"
        reason = "Carry context unavailable on mapped lower timeframe."
    else:
        range_absorption = context["range_absorption"]
        overlap_increasing = context["overlap_increasing"]
        expansion_efficient = context["expansion_efficient"]
        impulse_recent = context["impulse_recently_confirmed"]
        continuation_clean = context["continuation_clean"]
        leg_count = context["leg_count"]

        if carry_finished:
            state = "EXHAUSTING"
        elif continuation_failed and (opposite_divergence or opposite_impulse or range_absorption):
            state = "EXHAUSTING"
        elif opposite_divergence or opposite_impulse:
            state = "EXHAUSTING"
        elif range_absorption:
            state = "MATURE"
        elif impulse_recent and continuation_clean and not overlap_increasing and leg_count <= 2:
            state = "FRESH"
        elif continuation_clean and expansion_efficient and not overlap_increasing:
            state = "ACTIVE"
        else:
            state = "MATURE"

        if carry_finished:
            required_cycle = "YES"
        elif state in {"MATURE", "EXHAUSTING"}:
            required_cycle = "PARTIAL"
        elif state in {"FRESH", "ACTIVE"}:
            required_cycle = "NO"
        else:
            required_cycle = "UNCLEAR"

        reason = (
            f"carry={carry_tf}, state={state}, impulse_recent={impulse_recent}, "
            f"continuation_clean={continuation_clean}, overlap_increasing={overlap_increasing}, "
            f"range_absorption={range_absorption}, opposite_divergence={opposite_divergence}, "
            f"opposite_impulse={opposite_impulse}, continuation_failed={continuation_failed}, "
            f"carry_finished={carry_finished}"
        )

    cycle_checked = required_cycle != "UNCLEAR"
    _add_check(
        trace=trace,
        name="Required lower-level cycle checked",
        passed=cycle_checked,
        severity="ERROR" if not cycle_checked else "INFO",
        details=(
            f"required_lower_cycle_complete={required_cycle}, carry={carry_tf}"
            if cycle_checked
            else "Required lower-level cycle is unclear."
        ),
        function="classify_carry_state",
    )

    return CarryResult(
        origin_timeframe=origin,
        carrying_timeframe=carry_tf,
        direction=dir_text,
        state=state,
        required_lower_cycle_complete=required_cycle,
        opposite_divergence=opposite_divergence,
        opposite_impulse=opposite_impulse,
        continuation_failed=continuation_failed,
        carry_finished=carry_finished,
        reason=reason,
    )


def _normalize_direction(direction: Any) -> str:
    value = str(getattr(direction, "value", direction)).strip().upper()
    if value in {"UP", "BULLISH"}:
        return "UP"
    if value in {"DOWN", "BEARISH"}:
        return "DOWN"
    return "UNCLEAR"


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    for key in ("exists", "official", "confirmed", "impulse_confirmed"):
        attr = getattr(value, key, None)
        if attr is not None:
            return bool(attr)
    return bool(value)


def _extract_lower_context(lower_tf_context: Any, direction: str) -> dict[str, Any]:
    if lower_tf_context is None:
        return {
            "context_available": False,
            "impulse_recently_confirmed": False,
            "continuation_clean": False,
            "continuation_failed": False,
            "range_absorption": False,
            "overlap_increasing": False,
            "expansion_efficient": False,
            "leg_count": 0,
        }

    active_leg = getattr(lower_tf_context, "active_leg", None)
    legs = list(getattr(lower_tf_context, "legs", []) or [])
    range_state = getattr(lower_tf_context, "range_state", None)
    market_state = str(getattr(getattr(lower_tf_context, "market_state", ""), "value", getattr(lower_tf_context, "market_state", ""))).upper()

    context_available = active_leg is not None
    if not context_available:
        return {
            "context_available": False,
            "impulse_recently_confirmed": False,
            "continuation_clean": False,
            "continuation_failed": False,
            "range_absorption": False,
            "overlap_increasing": False,
            "expansion_efficient": False,
            "leg_count": len(legs),
        }

    active_direction = _normalize_direction(getattr(active_leg, "direction", "UNCLEAR"))
    continuation_clean = active_direction == direction and direction in {"UP", "DOWN"}
    continuation_failed = not continuation_clean

    range_absorption = bool(range_state is not None and getattr(range_state, "active", False))
    if market_state == "RANGE":
        range_absorption = True
    overlap_increasing = bool(range_absorption or len(legs) >= 5)
    impulse_recently_confirmed = bool(continuation_clean and len(legs) <= 2)
    expansion_efficient = bool(continuation_clean and len(legs) <= 4 and not range_absorption)

    return {
        "context_available": True,
        "impulse_recently_confirmed": impulse_recently_confirmed,
        "continuation_clean": continuation_clean,
        "continuation_failed": continuation_failed,
        "range_absorption": range_absorption,
        "overlap_increasing": overlap_increasing,
        "expansion_efficient": expansion_efficient,
        "leg_count": len(legs),
    }


def _add_check(
    *,
    trace: Any,
    name: str,
    passed: bool,
    severity: str,
    details: str,
    function: str,
) -> None:
    if trace is None or not hasattr(trace, "add_check"):
        return
    trace.add_check(
        name=name,
        passed=bool(passed),
        severity=severity,
        details=details,
        file="ocean_carry_engine.py",
        function=function,
    )
