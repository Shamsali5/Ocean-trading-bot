"""Centralized official divergence classifier for framework v1.2."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class DivergenceResult:
    timeframe: str
    direction: str  # "BULLISH" / "BEARISH"
    official: bool
    grade: str  # ELITE / STRONG / MODERATE / WEAK / INVALID
    abc_valid: bool
    b_reset_valid: bool
    c_test_valid: bool
    vel_divergence: bool
    acc_divergence: bool
    acc_area_divergence: bool
    b_zero_reset: bool
    impulse_confirmed: bool
    impulse_grade: str
    lower_tf_carry_available: bool
    role: str  # ORIGIN / SUPPORT / FINISH_WARNING / LOCAL_NOISE
    price_zone: str | None
    reason: str


def classify_divergence(
    abc_result,
    vacc_result,
    impulse_result=None,
    carry_result=None,
    trace=None,
) -> DivergenceResult:
    """Classify one divergence row using validated A-B-C + VAcc + impulse/carry."""

    timeframe = str(getattr(abc_result, "timeframe", "") or "")
    direction = _normalize_direction(getattr(abc_result, "direction", "NONE"))
    abc_valid = bool(getattr(abc_result, "valid", False))
    b_reset_valid = bool(getattr(abc_result, "b_reset_valid", False))
    c_test_valid = bool(getattr(abc_result, "c_test_valid", False))

    vel_divergence = bool(getattr(vacc_result, "vel_weaker", False))
    acc_divergence = bool(getattr(vacc_result, "acc_weaker", False))
    acc_area_divergence = bool(getattr(vacc_result, "acc_area_weaker", False))
    b_zero_reset = bool(getattr(vacc_result, "b_zero_reset", False))
    core_weakening_count = sum((vel_divergence, acc_divergence, acc_area_divergence))
    energy_valid = bool(getattr(vacc_result, "valid_energy_weakening", core_weakening_count >= 2))

    impulse_confirmed, impulse_grade = _extract_impulse(impulse_result)
    lower_tf_carry_available = _extract_carry_available(carry_result)

    _add_check(
        trace=trace,
        name="Official divergence requires A-B-C",
        passed=abc_valid,
        severity="ERROR" if not abc_valid else "INFO",
        details="A-B-C validator must pass before any official divergence is allowed.",
    )
    _add_check(
        trace=trace,
        name="Official divergence requires energy weakening",
        passed=energy_valid,
        severity="ERROR" if not energy_valid else "INFO",
        details="At least two of velocity/acceleration/acc-area must weaken from A to C.",
    )
    _add_check(
        trace=trace,
        name="Trade-confirmed divergence requires impulse",
        passed=impulse_confirmed,
        severity="ERROR" if not impulse_confirmed else "INFO",
        details="Impulse confirmation is required for executable BUY/SELL divergence trades.",
    )

    grade = "INVALID"
    official = False
    role = "LOCAL_NOISE"
    reason = "A-B-C invalid."

    if abc_valid:
        if (
            c_test_valid
            and b_reset_valid
            and vel_divergence
            and acc_divergence
            and acc_area_divergence
            and impulse_confirmed
            and lower_tf_carry_available
        ):
            grade = "ELITE"
            official = True
            role = "ORIGIN"
            reason = "Elite divergence: clean A-B-C, full A-vs-C weakening, impulse, and carry start."
        elif c_test_valid and impulse_confirmed and core_weakening_count >= 2:
            grade = "STRONG"
            official = True
            role = "SUPPORT" if not lower_tf_carry_available else "ORIGIN"
            reason = "Strong divergence: clean A-B-C, C retest/break, >=2 weakening signals, impulse confirmed."
        elif impulse_confirmed and impulse_grade in {"MODERATE", "STRONG"} and core_weakening_count >= 1:
            grade = "MODERATE"
            official = False
            role = "FINISH_WARNING"
            reason = "Moderate warning: A-B-C exists with partial weakening and non-weak impulse."
        else:
            grade = "WEAK"
            official = False
            role = "FINISH_WARNING" if core_weakening_count >= 1 else "LOCAL_NOISE"
            if not impulse_confirmed:
                reason = "Weak warning only: impulse missing, cannot confirm BUY/SELL."
            elif not c_test_valid:
                reason = "Weak warning only: Segment C did not meaningfully retest/break structural level."
            else:
                reason = "Weak warning only: insufficient combined A-vs-C weakening quality."

    weak_not_executable = grade not in {"WEAK", "INVALID"} or not official
    _add_check(
        trace=trace,
        name="Weak divergence cannot generate BUY/SELL",
        passed=weak_not_executable,
        severity="ERROR" if not weak_not_executable else "INFO",
        details=f"grade={grade}, official={official}",
    )

    return DivergenceResult(
        timeframe=timeframe,
        direction=direction,
        official=official,
        grade=grade,
        abc_valid=abc_valid,
        b_reset_valid=b_reset_valid,
        c_test_valid=c_test_valid,
        vel_divergence=vel_divergence,
        acc_divergence=acc_divergence,
        acc_area_divergence=acc_area_divergence,
        b_zero_reset=b_zero_reset,
        impulse_confirmed=impulse_confirmed,
        impulse_grade=impulse_grade,
        lower_tf_carry_available=lower_tf_carry_available,
        role=role,
        price_zone=_derive_price_zone(direction=direction, abc_result=abc_result),
        reason=reason,
    )


def _normalize_direction(raw: Any) -> str:
    value = str(getattr(raw, "value", raw)).strip().upper()
    if value in {"BULLISH", "BEARISH"}:
        return value
    return "NONE"


def _extract_impulse(impulse_result: Any) -> tuple[bool, str]:
    if impulse_result is None:
        return (False, "NONE")
    if isinstance(impulse_result, bool):
        return (impulse_result, "STRONG" if impulse_result else "NONE")
    if isinstance(impulse_result, (tuple, list)) and impulse_result:
        confirmed = bool(impulse_result[0])
        grade = str(impulse_result[1]).upper() if len(impulse_result) > 1 and impulse_result[1] else "NONE"
        return (confirmed, _normalize_impulse_grade(grade, confirmed))
    confirmed = bool(
        getattr(impulse_result, "impulse_confirmed", getattr(impulse_result, "confirmed", False))
    )
    raw_grade = str(getattr(impulse_result, "impulse_grade", getattr(impulse_result, "grade", ""))).upper()
    return (confirmed, _normalize_impulse_grade(raw_grade, confirmed))


def _normalize_impulse_grade(grade: str, confirmed: bool) -> str:
    if grade in {"STRONG", "MODERATE", "WEAK", "INVALID", "NONE"}:
        return grade
    return "STRONG" if confirmed else "NONE"


def _extract_carry_available(carry_result: Any) -> bool:
    if carry_result is None:
        return False
    if isinstance(carry_result, bool):
        return carry_result
    if isinstance(carry_result, dict):
        if "lower_tf_carry_available" in carry_result:
            return bool(carry_result.get("lower_tf_carry_available"))
        state = str(carry_result.get("state", "")).upper()
        return state in {"FRESH", "ACTIVE"}
    flag = getattr(carry_result, "lower_tf_carry_available", None)
    if flag is not None:
        return bool(flag)
    state = str(getattr(carry_result, "state", "")).upper()
    return state in {"FRESH", "ACTIVE"}


def _derive_price_zone(direction: str, abc_result: Any) -> str | None:
    segment_c = getattr(abc_result, "segment_c", None)
    if segment_c is None:
        return None
    if direction == "BEARISH":
        high = float(getattr(segment_c, "high", 0.0) or 0.0)
        return f"{high:.2f}-{high:.2f}"
    if direction == "BULLISH":
        low = float(getattr(segment_c, "low", 0.0) or 0.0)
        return f"{low:.2f}-{low:.2f}"
    return None


def _add_check(trace: Any, *, name: str, passed: bool, severity: str, details: str) -> None:
    if trace is None or not hasattr(trace, "add_check"):
        return
    trace.add_check(
        name=name,
        passed=bool(passed),
        severity=severity,
        details=details,
        file="ocean_divergence_classifier.py",
        function="classify_divergence",
    )
