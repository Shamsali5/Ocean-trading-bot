"""Impulse and breakout-acceptance validators for framework v1.2."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ImpulseResult:
    timeframe: str
    direction: str  # "BULLISH" / "BEARISH"
    confirmed: bool
    grade: str  # STRONG / MODERATE / WEAK / INVALID / NONE
    structure_broken: str | None
    candle_index: int | None
    trigger_price: float | None
    follow_through_confirmed: bool
    immediately_erased: bool
    reason: str


@dataclass(slots=True)
class BreakoutAcceptanceResult:
    timeframe: str
    direction: str
    accepted: bool
    boundary_broken: bool
    immediate_reclaim: bool
    retest_or_acceptance: bool
    continuation_outside: bool
    trigger_price: float | None
    reason: str


def validate_impulse_after_divergence(
    candles,
    timeframe,
    direction,
    local_pivots=None,
    trace=None,
) -> ImpulseResult:
    """Validate impulse confirmation after a divergence warning."""

    direction_text = _normalize_direction(direction)
    if direction_text not in {"BULLISH", "BEARISH"}:
        result = ImpulseResult(
            timeframe=str(timeframe or ""),
            direction=direction_text,
            confirmed=False,
            grade="INVALID",
            structure_broken=None,
            candle_index=None,
            trigger_price=None,
            follow_through_confirmed=False,
            immediately_erased=False,
            reason=f"Unsupported impulse direction '{direction_text}'.",
        )
        _add_check(
            trace=trace,
            name="Impulse confirmation requires valid direction",
            passed=False,
            severity="ERROR",
            details=result.reason,
            function="validate_impulse_after_divergence",
        )
        return result

    if not candles:
        result = ImpulseResult(
            timeframe=str(timeframe or ""),
            direction=direction_text,
            confirmed=False,
            grade="NONE",
            structure_broken=None,
            candle_index=None,
            trigger_price=None,
            follow_through_confirmed=False,
            immediately_erased=False,
            reason="No candles available for impulse validation.",
        )
        _add_check(
            trace=trace,
            name="Trade-confirmed divergence requires impulse",
            passed=False,
            severity="ERROR",
            details=result.reason,
            function="validate_impulse_after_divergence",
        )
        return result

    start_index = _resolve_start_index(local_pivots, len(candles))
    candidate_index: int | None = None
    structure_broken: str | None = None
    for index in range(start_index, len(candles)):
        if index <= 0:
            continue
        candle = candles[index]
        if not _strong_close(candle, direction_text):
            continue
        body_large = _is_body_large(candles, index)
        broken, break_label = _is_structural_break(candles, index, direction_text, local_pivots)
        if not (body_large or broken):
            continue
        if not _interrupts_opposite_rhythm(candles, index, direction_text):
            continue
        candidate_index = index
        structure_broken = break_label if broken else None
        break

    if candidate_index is None:
        result = ImpulseResult(
            timeframe=str(timeframe or ""),
            direction=direction_text,
            confirmed=False,
            grade="NONE",
            structure_broken=None,
            candle_index=None,
            trigger_price=None,
            follow_through_confirmed=False,
            immediately_erased=False,
            reason="No valid post-divergence impulse candle found.",
        )
        _add_check(
            trace=trace,
            name="Trade-confirmed divergence requires impulse",
            passed=False,
            severity="ERROR",
            details=result.reason,
            function="validate_impulse_after_divergence",
        )
        return result

    follow_through = _follow_through_confirmed(candles, candidate_index, direction_text)
    erased = _immediately_erased(candles, candidate_index, direction_text)
    body_large = _is_body_large(candles, candidate_index)
    structure_break = structure_broken is not None
    carry_started = follow_through and not erased

    if erased:
        grade = "WEAK"
        confirmed = False
        reason = "Impulse immediately erased after trigger."
    elif carry_started and body_large and structure_break:
        grade = "STRONG"
        confirmed = True
        reason = "Strong impulse confirmed with structural break and follow-through carry."
    elif carry_started and (body_large or structure_break):
        grade = "MODERATE"
        confirmed = True
        reason = "Moderate impulse confirmed with carry start and directional follow-through."
    elif body_large or structure_break:
        grade = "WEAK"
        confirmed = False
        reason = "Impulse warning only: carry follow-through is not confirmed."
    else:
        grade = "INVALID"
        confirmed = False
        reason = "Impulse conditions incomplete."

    trigger_price = float(getattr(candles[candidate_index], "close", 0.0))
    result = ImpulseResult(
        timeframe=str(timeframe or ""),
        direction=direction_text,
        confirmed=confirmed,
        grade=grade,
        structure_broken=structure_broken,
        candle_index=candidate_index,
        trigger_price=trigger_price,
        follow_through_confirmed=follow_through,
        immediately_erased=erased,
        reason=reason,
    )
    _add_check(
        trace=trace,
        name="Trade-confirmed divergence requires impulse",
        passed=confirmed,
        severity="ERROR" if not confirmed else "INFO",
        details=reason,
        function="validate_impulse_after_divergence",
    )
    return result


def validate_breakout_acceptance(range_result, candles, direction, trace=None):
    """Validate accepted breakout needed for Type 3 execution."""

    direction_text = _normalize_breakout_direction(direction)
    timeframe = str(getattr(range_result, "timeframe", "") or "")
    if direction_text not in {"UP", "DOWN"}:
        result = BreakoutAcceptanceResult(
            timeframe=timeframe,
            direction=direction_text,
            accepted=False,
            boundary_broken=False,
            immediate_reclaim=False,
            retest_or_acceptance=False,
            continuation_outside=False,
            trigger_price=None,
            reason=f"Unsupported breakout direction '{direction_text}'.",
        )
        _add_check(
            trace=trace,
            name="Type 3 breakout acceptance validated",
            passed=False,
            severity="ERROR",
            details=result.reason,
            function="validate_breakout_acceptance",
        )
        return result

    is_valid_range = bool(
        range_result is not None
        and getattr(range_result, "is_range", False)
        and getattr(range_result, "upper_edge", None) is not None
        and getattr(range_result, "lower_edge", None) is not None
    )
    if not is_valid_range:
        result = BreakoutAcceptanceResult(
            timeframe=timeframe,
            direction=direction_text,
            accepted=False,
            boundary_broken=False,
            immediate_reclaim=False,
            retest_or_acceptance=False,
            continuation_outside=False,
            trigger_price=None,
            reason="Type 3 rejected: range context is invalid.",
        )
        _add_check(
            trace=trace,
            name="Type 3 breakout acceptance validated",
            passed=False,
            severity="ERROR",
            details=result.reason,
            function="validate_breakout_acceptance",
        )
        return result

    upper = float(range_result.upper_edge)
    lower = float(range_result.lower_edge)
    boundary = upper if direction_text == "UP" else lower
    closes = [float(getattr(candle, "close", 0.0)) for candle in (candles or [])]
    first_break_index = getattr(range_result, "first_break_index", None)
    if first_break_index is None or first_break_index < 0:
        first_break_index = _first_boundary_break_index(closes, boundary, direction_text)

    boundary_broken = bool(
        getattr(range_result, "breakout_confirmed", False)
        and _normalize_breakout_direction(getattr(range_result, "breakout_direction", "")) == direction_text
    )
    if not boundary_broken and first_break_index is not None:
        boundary_broken = True

    immediate_reclaim = _has_immediate_reclaim(closes, first_break_index, boundary, direction_text)
    retest_or_acceptance = bool(getattr(range_result, "retest_held", False) or getattr(range_result, "acceptance_confirmed", False))
    if not retest_or_acceptance:
        retest_or_acceptance = _has_two_outside_closes(closes, first_break_index, boundary, direction_text)

    continuation_outside = bool(
        closes
        and (
            (direction_text == "UP" and closes[-1] > boundary)
            or (direction_text == "DOWN" and closes[-1] < boundary)
        )
    )
    if not closes:
        continuation_outside = bool(getattr(range_result, "acceptance_confirmed", False))

    trigger_price = getattr(range_result, "first_accepted_close", None)
    if trigger_price is None and first_break_index is not None and 0 <= first_break_index < len(closes):
        trigger_price = closes[first_break_index]
    if trigger_price is None:
        trigger_price = boundary

    accepted = bool(
        is_valid_range
        and boundary_broken
        and not immediate_reclaim
        and retest_or_acceptance
        and continuation_outside
    )
    reason = (
        "Type 3 breakout accepted."
        if accepted
        else "Type 3 rejected: requires range, break, no immediate reclaim, acceptance/retest, and continuation outside."
    )
    result = BreakoutAcceptanceResult(
        timeframe=timeframe,
        direction=direction_text,
        accepted=accepted,
        boundary_broken=boundary_broken,
        immediate_reclaim=immediate_reclaim,
        retest_or_acceptance=retest_or_acceptance,
        continuation_outside=continuation_outside,
        trigger_price=float(trigger_price) if trigger_price is not None else None,
        reason=reason,
    )
    _add_check(
        trace=trace,
        name="Type 3 breakout acceptance validated",
        passed=accepted,
        severity="ERROR" if not accepted else "INFO",
        details=reason,
        function="validate_breakout_acceptance",
    )
    return result


def _normalize_direction(direction: Any) -> str:
    return str(getattr(direction, "value", direction)).strip().upper()


def _normalize_breakout_direction(direction: Any) -> str:
    value = _normalize_direction(direction)
    if value in {"UP", "DOWN"}:
        return value
    if value == "BULLISH":
        return "UP"
    if value == "BEARISH":
        return "DOWN"
    return value


def _resolve_start_index(local_pivots: Any, candle_count: int) -> int:
    if candle_count <= 1:
        return 0
    if isinstance(local_pivots, dict):
        raw = local_pivots.get("start_index")
    else:
        raw = getattr(local_pivots, "start_index", None)
    if raw is None:
        return max(1, candle_count - 8)
    try:
        index = int(raw)
    except (TypeError, ValueError):
        return max(1, candle_count - 8)
    return min(max(index, 1), candle_count - 1)


def _strong_close(candle: Any, direction: str) -> bool:
    open_price = float(getattr(candle, "open", 0.0))
    close = float(getattr(candle, "close", 0.0))
    high = float(getattr(candle, "high", close))
    low = float(getattr(candle, "low", close))
    candle_range = max(high - low, 1e-9)
    if direction == "BULLISH":
        return close > open_price and close >= high - 0.35 * candle_range
    return close < open_price and close <= low + 0.35 * candle_range


def _is_body_large(candles: list[Any], index: int, lookback: int = 5) -> bool:
    candle = candles[index]
    body = abs(float(getattr(candle, "close", 0.0)) - float(getattr(candle, "open", 0.0)))
    history = candles[max(0, index - lookback) : index]
    if not history:
        return body > 0.0
    avg_body = sum(
        abs(float(getattr(item, "close", 0.0)) - float(getattr(item, "open", 0.0)))
        for item in history
    ) / len(history)
    return body > avg_body * 1.2


def _is_structural_break(
    candles: list[Any],
    index: int,
    direction: str,
    local_pivots: Any,
) -> tuple[bool, str | None]:
    close = float(getattr(candles[index], "close", 0.0))
    history = candles[max(0, index - 6) : index]
    if not history:
        return (False, None)

    minor_high = _extract_pivot(local_pivots, ("minor_high", "reference_high", "reversal_high"))
    minor_low = _extract_pivot(local_pivots, ("minor_low", "reference_low", "reversal_low"))
    if direction == "BULLISH":
        level = minor_high if minor_high is not None else max(float(getattr(item, "high", 0.0)) for item in history)
        return (close > level, "minor_high")
    level = minor_low if minor_low is not None else min(float(getattr(item, "low", 0.0)) for item in history)
    return (close < level, "minor_low")


def _extract_pivot(local_pivots: Any, keys: tuple[str, ...]) -> float | None:
    if local_pivots is None:
        return None
    for key in keys:
        value = None
        if isinstance(local_pivots, dict):
            value = local_pivots.get(key)
        else:
            value = getattr(local_pivots, key, None)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _interrupts_opposite_rhythm(candles: list[Any], index: int, direction: str) -> bool:
    history = candles[max(0, index - 3) : index]
    if len(history) < 2:
        return True
    last = history[-1]
    prev = history[-2]
    last_close = float(getattr(last, "close", 0.0))
    prev_close = float(getattr(prev, "close", 0.0))
    last_open = float(getattr(last, "open", 0.0))
    if direction == "BULLISH":
        return last_close <= prev_close or last_close < last_open
    return last_close >= prev_close or last_close > last_open


def _follow_through_confirmed(candles: list[Any], index: int, direction: str) -> bool:
    if index + 1 >= len(candles):
        return False
    trigger = float(getattr(candles[index], "close", 0.0))
    next_window = candles[index + 1 : min(len(candles), index + 3)]
    if direction == "BULLISH":
        return any(float(getattr(item, "close", 0.0)) > trigger for item in next_window)
    return any(float(getattr(item, "close", 0.0)) < trigger for item in next_window)


def _immediately_erased(candles: list[Any], index: int, direction: str) -> bool:
    if index + 1 >= len(candles):
        return False
    trigger_open = float(getattr(candles[index], "open", 0.0))
    next_window = candles[index + 1 : min(len(candles), index + 3)]
    if direction == "BULLISH":
        return any(float(getattr(item, "close", 0.0)) < trigger_open for item in next_window)
    return any(float(getattr(item, "close", 0.0)) > trigger_open for item in next_window)


def _first_boundary_break_index(closes: list[float], boundary: float, direction: str) -> int | None:
    if not closes:
        return None
    if direction == "UP":
        for idx, close in enumerate(closes):
            if close > boundary:
                return idx
        return None
    for idx, close in enumerate(closes):
        if close < boundary:
            return idx
    return None


def _has_immediate_reclaim(
    closes: list[float],
    first_break_index: int | None,
    boundary: float,
    direction: str,
) -> bool:
    if first_break_index is None or first_break_index + 1 >= len(closes):
        return False
    reclaim_window = closes[first_break_index + 1 : min(len(closes), first_break_index + 3)]
    if direction == "UP":
        return any(close <= boundary for close in reclaim_window)
    return any(close >= boundary for close in reclaim_window)


def _has_two_outside_closes(
    closes: list[float],
    first_break_index: int | None,
    boundary: float,
    direction: str,
) -> bool:
    if first_break_index is None:
        return False
    outside = 0
    for close in closes[first_break_index:]:
        if direction == "UP" and close > boundary:
            outside += 1
        elif direction == "DOWN" and close < boundary:
            outside += 1
        if outside >= 2:
            return True
    return False


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
        file="ocean_impulse_acceptance.py",
        function=function,
    )
