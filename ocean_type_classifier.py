"""Strict Type 1/2/3 classifier for framework v1.2."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class TypeClassification:
    type_label: str  # TYPE_1 / TYPE_2 / TYPE_3 / NONE
    full_label: str  # e.g. "15m Bullish Type 1"
    timeframe: str | None
    direction: str | None
    valid: bool
    reason: str


def classify_type_1(divergence_result, impulse_result, carry_result, trace=None):
    """Classify Type 1 validity from divergence + impulse + carry."""

    timeframe = _normalize_timeframe(_value_from_result(divergence_result, "timeframe"))
    direction = _normalize_direction(
        _value_from_result(divergence_result, "direction", fallback_keys=("trend_direction",))
    )
    official = bool(_bool_from_result(divergence_result, "official", fallback_keys=("exists",)))
    vacc_weakening = _resolve_vacc_weakening(divergence_result)
    impulse_confirmed = bool(_bool_from_result(impulse_result, "confirmed", fallback_keys=("impulse_confirmed",)))
    opposite_impulse_confirmed = impulse_confirmed
    lower_tf_carry_started = _resolve_carry_started(carry_result, allow_mature=False)

    valid = bool(
        official
        and vacc_weakening
        and opposite_impulse_confirmed
        and lower_tf_carry_started
        and timeframe is not None
        and direction in {"BULLISH", "BEARISH"}
    )
    result = _build_result(
        valid=valid,
        type_label="TYPE_1",
        timeframe=timeframe,
        direction=direction,
        reason=(
            "Type 1 valid: official divergence + VAcc weakening + opposite impulse + carry start."
            if valid
            else (
                "Type 1 invalid: requires official divergence, VAcc weakening, opposite impulse, and carry start."
            )
        ),
    )

    _add_check(
        trace=trace,
        name="Type 1 requires divergence + impulse + carry",
        passed=valid,
        severity="ERROR" if not valid else "INFO",
        details=(
            f"official={official}, vacc_weakening={vacc_weakening}, "
            f"opposite_impulse_confirmed={opposite_impulse_confirmed}, carry_started={lower_tf_carry_started}"
        ),
        function="classify_type_1",
    )
    _emit_label_checks(trace=trace, result=result, function="classify_type_1")
    _emit_forbidden_source_checks(
        trace=trace,
        from_zone_only=False,
        from_vacc_only=bool(vacc_weakening and not official and not impulse_confirmed),
        function="classify_type_1",
    )
    return result


def classify_type_2(prior_type_1, pullback_context, continuation_impulse, carry_result, trace=None):
    """Classify Type 2 validity from prior Type 1 and continuation context."""

    prior_exists = bool(_bool_from_result(prior_type_1, "valid", fallback_keys=("exists",)))
    prior_type_label = str(
        _value_from_result(prior_type_1, "type_label", fallback_keys=("setup_type",))
        or ""
    ).upper().replace(" ", "_")
    prior_is_type1 = "TYPE_1" in prior_type_label
    timeframe = _normalize_timeframe(
        _value_from_result(prior_type_1, "timeframe", fallback_keys=("origin_timeframe",))
    )
    direction = _normalize_direction(
        _value_from_result(prior_type_1, "direction", fallback_keys=("carry_direction",))
    )
    price_pulled_back = bool(_bool_from_result(pullback_context, "pulled_back", fallback_keys=("has_pullback",)))
    not_invalidated = bool(
        _bool_from_result(pullback_context, "not_invalidated", fallback_keys=("valid", "holds_type1"))
    )
    pullback_weakens = bool(_bool_from_result(pullback_context, "weakens", fallback_keys=("weakened",)))
    continuation_confirmed = bool(
        _bool_from_result(continuation_impulse, "confirmed", fallback_keys=("impulse_confirmed",))
    )
    carry_resumes = _resolve_carry_started(carry_result, allow_mature=True)

    valid = bool(
        prior_exists
        and prior_is_type1
        and price_pulled_back
        and not_invalidated
        and pullback_weakens
        and continuation_confirmed
        and carry_resumes
        and timeframe is not None
        and direction in {"BULLISH", "BEARISH"}
    )
    result = _build_result(
        valid=valid,
        type_label="TYPE_2",
        timeframe=timeframe,
        direction=direction,
        reason=(
            "Type 2 valid: prior Type 1 + weakening pullback + continuation impulse + resumed carry."
            if valid
            else (
                "Type 2 invalid: requires prior Type 1, valid/weakening pullback, continuation impulse, and resumed carry."
            )
        ),
    )

    _add_check(
        trace=trace,
        name="Type 1 requires divergence + impulse + carry",
        passed=prior_exists and prior_is_type1,
        severity="ERROR" if not (prior_exists and prior_is_type1) else "INFO",
        details=f"prior_exists={prior_exists}, prior_is_type1={prior_is_type1}",
        function="classify_type_2",
    )
    _emit_label_checks(trace=trace, result=result, function="classify_type_2")
    _emit_forbidden_source_checks(
        trace=trace,
        from_zone_only=False,
        from_vacc_only=False,
        function="classify_type_2",
    )
    return result


def classify_type_3(range_result, breakout_acceptance_result, carry_result, trace=None):
    """Classify Type 3 validity from range breakout acceptance + continuation."""

    timeframe = _normalize_timeframe(
        _value_from_result(range_result, "timeframe", fallback_keys=("origin_timeframe",))
    )
    carry_direction = _normalize_direction(_value_from_result(carry_result, "direction"))
    breakout_direction = _normalize_breakout_direction(
        _value_from_result(
            breakout_acceptance_result,
            "direction",
            fallback_keys=("breakout_direction",),
        )
    )
    direction = _direction_from_breakout_or_carry(breakout_direction, carry_direction)

    valid_range = bool(
        _bool_from_result(range_result, "valid", fallback_keys=("active", "is_range"))
        and _value_from_result(range_result, "upper_edge") is not None
        and _value_from_result(range_result, "lower_edge") is not None
    )
    boundary_broken = bool(_bool_from_result(breakout_acceptance_result, "boundary_broken"))
    retest_or_acceptance = bool(
        _bool_from_result(
            breakout_acceptance_result,
            "retest_or_acceptance",
            fallback_keys=("acceptance_confirmed",),
        )
    )
    continuation_outside = bool(
        _bool_from_result(
            breakout_acceptance_result,
            "continuation_outside",
            fallback_keys=("follow_through_confirmed",),
        )
    )
    accepted = bool(
        _bool_from_result(
            breakout_acceptance_result,
            "accepted",
            fallback_keys=("confirmed",),
        )
    )
    carry_resumes = _resolve_carry_started(carry_result, allow_mature=True)

    valid = bool(
        valid_range
        and boundary_broken
        and retest_or_acceptance
        and continuation_outside
        and accepted
        and carry_resumes
        and timeframe is not None
        and direction in {"BULLISH", "BEARISH"}
    )
    result = _build_result(
        valid=valid,
        type_label="TYPE_3",
        timeframe=timeframe,
        direction=direction,
        reason=(
            "Type 3 valid: range + breakout acceptance + outside continuation + carry resume."
            if valid
            else (
                "Type 3 invalid: requires valid range, boundary break, acceptance/retest, outside continuation, and carry resume."
            )
        ),
    )

    _add_check(
        trace=trace,
        name="Type 3 requires breakout acceptance",
        passed=bool(valid_range and accepted and boundary_broken and retest_or_acceptance and continuation_outside),
        severity="ERROR"
        if not bool(valid_range and accepted and boundary_broken and retest_or_acceptance and continuation_outside)
        else "INFO",
        details=(
            f"valid_range={valid_range}, accepted={accepted}, boundary_broken={boundary_broken}, "
            f"retest_or_acceptance={retest_or_acceptance}, continuation_outside={continuation_outside}"
        ),
        function="classify_type_3",
    )
    _emit_label_checks(trace=trace, result=result, function="classify_type_3")
    _emit_forbidden_source_checks(
        trace=trace,
        from_zone_only=False,
        from_vacc_only=False,
        function="classify_type_3",
    )
    return result


def _build_result(
    *,
    valid: bool,
    type_label: str,
    timeframe: str | None,
    direction: str | None,
    reason: str,
) -> TypeClassification:
    clean_type = type_label if valid else "NONE"
    clean_timeframe = timeframe if valid else None
    clean_direction = direction if valid else None
    full_label = _full_label(clean_timeframe, clean_direction, clean_type) if valid else "NONE"
    return TypeClassification(
        type_label=clean_type,
        full_label=full_label,
        timeframe=clean_timeframe,
        direction=clean_direction,
        valid=bool(valid),
        reason=reason,
    )


def _full_label(timeframe: str | None, direction: str | None, type_label: str) -> str:
    if timeframe is None or direction not in {"BULLISH", "BEARISH"}:
        return "NONE"
    tf = timeframe.upper() if timeframe in {"1h", "4h"} else timeframe
    side = "Bullish" if direction == "BULLISH" else "Bearish"
    return f"{tf} {side} Type {type_label.split('_')[-1]}"


def _normalize_timeframe(raw: Any) -> str | None:
    text = str(raw or "").strip()
    return text if text else None


def _normalize_direction(raw: Any) -> str:
    value = str(getattr(raw, "value", raw)).strip().upper()
    if value in {"BULLISH", "UP"}:
        return "BULLISH"
    if value in {"BEARISH", "DOWN"}:
        return "BEARISH"
    return "NONE"


def _normalize_breakout_direction(raw: Any) -> str:
    value = str(getattr(raw, "value", raw)).strip().upper()
    if value in {"UP", "BULLISH"}:
        return "UP"
    if value in {"DOWN", "BEARISH"}:
        return "DOWN"
    return "NONE"


def _direction_from_breakout_or_carry(breakout_direction: str, carry_direction: str) -> str:
    if breakout_direction == "UP":
        return "BULLISH"
    if breakout_direction == "DOWN":
        return "BEARISH"
    return carry_direction if carry_direction in {"BULLISH", "BEARISH"} else "NONE"


def _resolve_vacc_weakening(divergence_result: Any) -> bool:
    direct = _value_from_result(divergence_result, "valid_energy_weakening")
    if direct is not None:
        return bool(direct)
    weakening_count = _value_from_result(divergence_result, "weakening_count")
    if weakening_count is not None:
        try:
            return int(weakening_count) >= 2
        except (TypeError, ValueError):
            return False
    flags = (
        _bool_from_result(divergence_result, "vel_divergence", fallback_keys=("velocity_weaker",)),
        _bool_from_result(divergence_result, "acc_divergence", fallback_keys=("acceleration_weaker",)),
        _bool_from_result(divergence_result, "acc_area_divergence", fallback_keys=("acceleration_area_weaker",)),
    )
    if sum(bool(flag) for flag in flags) >= 2:
        return True
    # Official divergence rows already passed strict weakening gates upstream.
    return bool(_bool_from_result(divergence_result, "official", fallback_keys=("exists",)))


def _resolve_carry_started(carry_result: Any, *, allow_mature: bool) -> bool:
    state = str(_value_from_result(carry_result, "state") or "").upper()
    finished = bool(_bool_from_result(carry_result, "finished", fallback_keys=("carry_finished",)))
    available = bool(_bool_from_result(carry_result, "lower_tf_carry_available"))
    if state == "MATURE" and not allow_mature:
        return False
    if available:
        return not finished
    valid_states = {"FRESH", "ACTIVE", "MATURE"} if allow_mature else {"FRESH", "ACTIVE"}
    return state in valid_states and not finished


def _value_from_result(result: Any, key: str, fallback_keys: tuple[str, ...] = ()) -> Any:
    if result is None:
        return None
    if isinstance(result, dict):
        if key in result:
            return result.get(key)
        for alt in fallback_keys:
            if alt in result:
                return result.get(alt)
        return None
    value = getattr(result, key, None)
    if value is not None:
        return value
    for alt in fallback_keys:
        value = getattr(result, alt, None)
        if value is not None:
            return value
    return None


def _bool_from_result(result: Any, key: str, fallback_keys: tuple[str, ...] = ()) -> bool:
    return bool(_value_from_result(result, key, fallback_keys))


def _emit_label_checks(trace: Any, result: TypeClassification, function: str) -> None:
    _add_check(
        trace=trace,
        name="Type label includes timeframe",
        passed=bool(not result.valid or result.timeframe),
        severity="ERROR" if result.valid and not result.timeframe else "INFO",
        details=f"type_label={result.type_label}, timeframe={result.timeframe}",
        function=function,
    )
    _add_check(
        trace=trace,
        name="Type label includes direction",
        passed=bool(not result.valid or result.direction in {"BULLISH", "BEARISH"}),
        severity="ERROR" if result.valid and result.direction not in {"BULLISH", "BEARISH"} else "INFO",
        details=f"type_label={result.type_label}, direction={result.direction}",
        function=function,
    )


def _emit_forbidden_source_checks(
    *,
    trace: Any,
    from_zone_only: bool,
    from_vacc_only: bool,
    function: str,
) -> None:
    _add_check(
        trace=trace,
        name="Type cannot be assigned from zone alone",
        passed=not from_zone_only,
        severity="ERROR" if from_zone_only else "INFO",
        details="Zone-only context is insufficient for type assignment.",
        function=function,
    )
    _add_check(
        trace=trace,
        name="Type cannot be assigned from VAcc alone",
        passed=not from_vacc_only,
        severity="ERROR" if from_vacc_only else "INFO",
        details="VAcc-only context is insufficient for type assignment.",
        function=function,
    )


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
        file="ocean_type_classifier.py",
        function=function,
    )
