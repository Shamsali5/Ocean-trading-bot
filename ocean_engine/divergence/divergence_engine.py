"""Divergence confirmation from A-B-C structure plus VAcc weakening."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ocean_divergence_classifier import classify_divergence
from ocean_impulse_acceptance import validate_impulse_after_divergence
from ocean_abc_validator import ABCSegment, ABCValidationResult
from ocean_engine.energy.vacc_engine import (
    get_segment_acceleration_area,
    get_segment_velocity_energy,
    has_zero_axis_reset,
)
from ocean_engine.models.enums import Direction, DivergenceDirection, DivergenceGrade
from ocean_engine.models.market import ABCStructure, Candle, DivergenceState, VAccSeries


@dataclass(slots=True)
class VAccComparisonResult:
    timeframe: str
    direction: str
    vel_weaker: bool
    acc_weaker: bool
    acc_area_weaker: bool
    b_zero_reset: bool
    weakening_count: int
    valid_energy_weakening: bool
    reason: str


def compare_segment_energy(abc: ABCStructure, vacc_series: VAccSeries) -> dict[str, bool | int]:
    """Compare A vs C segment energy and count weakening signals."""

    abc_validation = _abc_validation_from_abc(abc, vacc_series=vacc_series)
    comparison = compare_vacc_energy_a_vs_c(
        candles=[],
        abc_result=abc_validation,
        vacc_series=vacc_series,
    )
    if not comparison.valid_energy_weakening:
        return {
            "velocity_weaker": False,
            "acceleration_weaker": False,
            "acceleration_area_weaker": False,
            "zero_axis_reset": False,
            "weakening_count": 0,
        }
    return {
        "velocity_weaker": comparison.vel_weaker,
        "acceleration_weaker": comparison.acc_weaker,
        "acceleration_area_weaker": comparison.acc_area_weaker,
        "zero_axis_reset": comparison.b_zero_reset,
        "weakening_count": comparison.weakening_count,
    }


def compare_vacc_energy_a_vs_c(
    candles,
    abc_result,
    vacc_series,
    trace=None,
) -> VAccComparisonResult:
    """Compare Segment-A vs Segment-C directional VAcc after A-B-C validation."""

    timeframe = str(getattr(abc_result, "timeframe", "") or "")
    direction = str(getattr(abc_result, "direction", "") or "").upper()
    abc_valid = bool(getattr(abc_result, "valid", False))
    if not abc_valid:
        result = VAccComparisonResult(
            timeframe=timeframe,
            direction=direction or "UNKNOWN",
            vel_weaker=False,
            acc_weaker=False,
            acc_area_weaker=False,
            b_zero_reset=False,
            weakening_count=0,
            valid_energy_weakening=False,
            reason="A-B-C invalid; skipping VAcc comparison.",
        )
        _emit_vacc_checks(trace=trace, result=result, compared_after_abc=False)
        return result

    segment_a = getattr(abc_result, "segment_a", None)
    segment_b = getattr(abc_result, "segment_b", None)
    segment_c = getattr(abc_result, "segment_c", None)
    if segment_a is None or segment_b is None or segment_c is None:
        result = VAccComparisonResult(
            timeframe=timeframe,
            direction=direction or "UNKNOWN",
            vel_weaker=False,
            acc_weaker=False,
            acc_area_weaker=False,
            b_zero_reset=False,
            weakening_count=0,
            valid_energy_weakening=False,
            reason="A/B/C segments missing for VAcc comparison.",
        )
        _emit_vacc_checks(trace=trace, result=result, compared_after_abc=False)
        return result

    if direction == "BEARISH":
        energy_direction = Direction.UP
    elif direction == "BULLISH":
        energy_direction = Direction.DOWN
    else:
        result = VAccComparisonResult(
            timeframe=timeframe,
            direction=direction or "UNKNOWN",
            vel_weaker=False,
            acc_weaker=False,
            acc_area_weaker=False,
            b_zero_reset=False,
            weakening_count=0,
            valid_energy_weakening=False,
            reason=f"Unsupported divergence direction '{direction}'.",
        )
        _emit_vacc_checks(trace=trace, result=result, compared_after_abc=False)
        return result

    a_velocity = get_segment_velocity_energy(
        vacc_series=vacc_series,
        start_index=segment_a.start_index,
        end_index=segment_a.end_index,
        direction=energy_direction,
    )
    c_velocity = get_segment_velocity_energy(
        vacc_series=vacc_series,
        start_index=segment_c.start_index,
        end_index=segment_c.end_index,
        direction=energy_direction,
    )
    vel_weaker = c_velocity < a_velocity

    a_acc_peak = _directional_acc_peak(
        vacc_series=vacc_series,
        start_index=segment_a.start_index,
        end_index=segment_a.end_index,
        direction=energy_direction,
    )
    c_acc_peak = _directional_acc_peak(
        vacc_series=vacc_series,
        start_index=segment_c.start_index,
        end_index=segment_c.end_index,
        direction=energy_direction,
    )
    acc_weaker = c_acc_peak < a_acc_peak

    a_acc_area = get_segment_acceleration_area(
        vacc_series=vacc_series,
        start_index=segment_a.start_index,
        end_index=segment_a.end_index,
        direction=energy_direction,
    )
    c_acc_area = get_segment_acceleration_area(
        vacc_series=vacc_series,
        start_index=segment_c.start_index,
        end_index=segment_c.end_index,
        direction=energy_direction,
    )
    acc_area_weaker = c_acc_area < a_acc_area

    b_zero_reset = has_zero_axis_reset(
        vacc_series=vacc_series,
        start_index=segment_b.start_index,
        end_index=segment_b.end_index,
        tolerance=0.0,
    )

    core_weakening = sum((vel_weaker, acc_weaker, acc_area_weaker))
    valid_energy_weakening = core_weakening >= 2
    weakening_count = core_weakening + (1 if b_zero_reset else 0)
    if valid_energy_weakening and b_zero_reset:
        reason = "A-vs-C energy weakened (>=2) and Segment-B zero reset confirmed."
    elif valid_energy_weakening:
        reason = "A-vs-C energy weakened (>=2) without Segment-B zero reset."
    else:
        reason = "Insufficient A-vs-C weakening; need >=2 of vel/acc/acc-area."

    result = VAccComparisonResult(
        timeframe=timeframe,
        direction=direction,
        vel_weaker=vel_weaker,
        acc_weaker=acc_weaker,
        acc_area_weaker=acc_area_weaker,
        b_zero_reset=b_zero_reset,
        weakening_count=weakening_count,
        valid_energy_weakening=valid_energy_weakening,
        reason=reason,
    )
    _emit_vacc_checks(trace=trace, result=result, compared_after_abc=True)
    return result


def _abc_validation_from_abc(abc: ABCStructure, vacc_series: VAccSeries) -> ABCValidationResult:
    """Create an ABCValidationResult adapter from ABCStructure for energy comparison."""

    direction_text = (
        "BEARISH"
        if abc.direction == DivergenceDirection.BEARISH
        else "BULLISH"
        if abc.direction == DivergenceDirection.BULLISH
        else "UNKNOWN"
    )
    segment_a = _segment_from_leg(abc.segment_a, vacc_series=vacc_series)
    segment_b = _segment_from_leg(abc.segment_b, vacc_series=vacc_series)
    segment_c = _segment_from_leg(abc.segment_c, vacc_series=vacc_series)
    return ABCValidationResult(
        timeframe=abc.timeframe,
        direction=direction_text,
        valid=bool(abc.abc_valid and segment_a and segment_b and segment_c),
        segment_a=segment_a,
        segment_b=segment_b,
        segment_c=segment_c,
        b_reset_valid=bool(abc.b_reset_valid),
        c_test_valid=bool(abc.c_retest_valid),
        same_timeframe_valid=True,
        reason=abc.summary or "ABC structure adapted for VAcc comparison.",
    )


def _segment_from_leg(leg: Any, vacc_series: VAccSeries) -> ABCSegment | None:
    if leg is None:
        return None
    start_index = int(getattr(leg, "start_index", -1))
    end_index = int(getattr(leg, "end_index", -1))
    if start_index < 0 or end_index < start_index:
        return None
    direction = _leg_direction(leg)
    start_price = float(getattr(leg, "start_price", 0.0) or 0.0)
    end_price = float(getattr(leg, "end_price", 0.0) or 0.0)
    high = float(getattr(leg, "high", 0.0) or 0.0)
    low = float(getattr(leg, "low", 0.0) or 0.0)
    if direction not in {"UP", "DOWN"}:
        direction = "UP" if end_price >= start_price else "DOWN"
    energy_direction = Direction.UP if direction == "UP" else Direction.DOWN
    vel_area = get_segment_velocity_energy(
        vacc_series=vacc_series,
        start_index=start_index,
        end_index=end_index,
        direction=energy_direction,
    )
    acc_area = get_segment_acceleration_area(
        vacc_series=vacc_series,
        start_index=start_index,
        end_index=end_index,
        direction=energy_direction,
    )
    return ABCSegment(
        start_index=start_index,
        end_index=end_index,
        start_price=start_price,
        end_price=end_price,
        direction=direction,
        high=high,
        low=low,
        vacc_vel_area=float(vel_area),
        vacc_acc_area=float(acc_area),
        vacc_total_area=float(abs(vel_area) + abs(acc_area)),
    )


def _directional_acc_peak(
    *,
    vacc_series: VAccSeries,
    start_index: int,
    end_index: int,
    direction: Direction,
) -> float:
    points = vacc_series.points
    if start_index < 0 or end_index < start_index or end_index >= len(points):
        return 0.0
    segment = points[start_index : end_index + 1]
    if direction == Direction.UP:
        candidates = [float(point.acceleration) for point in segment if float(point.acceleration) > 0.0]
    else:
        candidates = [abs(float(point.acceleration)) for point in segment if float(point.acceleration) < 0.0]
    if not candidates:
        return 0.0
    return max(candidates)


def _leg_direction(leg: Any) -> str:
    raw = getattr(getattr(leg, "direction", ""), "value", getattr(leg, "direction", ""))
    text = str(raw).strip().upper()
    if text in {"UP", "DOWN"}:
        return text
    if text == "BULLISH":
        return "UP"
    if text == "BEARISH":
        return "DOWN"
    return text


def _emit_vacc_checks(trace: Any, result: VAccComparisonResult, compared_after_abc: bool) -> None:
    _add_check(
        trace,
        name="VAcc compared only after A-B-C",
        passed=compared_after_abc,
        details=result.reason,
    )
    _add_check(
        trace,
        name="Vel A-vs-C weakening checked",
        passed=result.vel_weaker,
        details=result.reason,
    )
    _add_check(
        trace,
        name="Acc A-vs-C weakening checked",
        passed=result.acc_weaker,
        details=result.reason,
    )
    _add_check(
        trace,
        name="Acc-area A-vs-C weakening checked",
        passed=result.acc_area_weaker,
        details=result.reason,
    )
    _add_check(
        trace,
        name="Segment B zero reset checked",
        passed=result.b_zero_reset,
        details=result.reason,
    )


def _add_check(trace: Any, *, name: str, passed: bool, details: str) -> None:
    if trace is None or not hasattr(trace, "add_check"):
        return
    trace.add_check(
        name=name,
        passed=bool(passed),
        severity="INFO" if passed else "ERROR",
        details=details,
        file="ocean_engine/divergence/divergence_engine.py",
        function="compare_vacc_energy_a_vs_c",
    )


def _legacy_energy_dict(result: VAccComparisonResult) -> dict[str, bool | int]:
    """Return dict-compatible energy payload for older call sites/tests."""

    if not result.valid_energy_weakening:
        return {
            "velocity_weaker": False,
            "acceleration_weaker": False,
            "acceleration_area_weaker": False,
            "zero_axis_reset": False,
            "weakening_count": 0,
        }
    return {
        "velocity_weaker": result.vel_weaker,
        "acceleration_weaker": result.acc_weaker,
        "acceleration_area_weaker": result.acc_area_weaker,
        "zero_axis_reset": result.b_zero_reset,
        "weakening_count": result.weakening_count,
    }


def detect_opposite_impulse(
    candles: list[Candle],
    abc: ABCStructure,
    lookahead: int = 5,
    body_multiplier: float = 1.2,
) -> bool:
    """Confirm post-C opposite impulse using body and close location rules."""

    if abc.segment_c is None or abc.direction not in (DivergenceDirection.BEARISH, DivergenceDirection.BULLISH):
        return False
    if lookahead < 1:
        return False

    c_end = abc.segment_c.end_index
    start = c_end + 1
    if start >= len(candles):
        return False

    end = min(len(candles), start + lookahead)
    for index in range(start, end):
        candle = candles[index]
        body = abs(candle.close - candle.open)

        history_start = max(0, index - lookahead)
        history = candles[history_start:index]
        if not history:
            continue
        average_body = sum(abs(item.close - item.open) for item in history) / len(history)
        if body <= average_body * body_multiplier:
            continue

        candle_range = candle.high - candle.low
        if candle_range <= 0.0:
            continue

        previous = candles[index - 1] if index > 0 else None
        recent_window = candles[history_start:index]
        recent_minor_low = min(item.low for item in recent_window) if recent_window else candle.low
        recent_minor_high = max(item.high for item in recent_window) if recent_window else candle.high

        if abc.direction == DivergenceDirection.BEARISH:
            close_in_lower = candle.close <= (candle.low + 0.30 * candle_range)
            break_prev = previous is not None and candle.close < previous.low
            break_recent = candle.close < recent_minor_low
            if close_in_lower and (break_prev or break_recent):
                return True
        else:
            close_in_upper = candle.close >= (candle.high - 0.30 * candle_range)
            break_prev = previous is not None and candle.close > previous.high
            break_recent = candle.close > recent_minor_high
            if close_in_upper and (break_prev or break_recent):
                return True
    return False


def detect_opposite_impulse_details(
    candles: list[Candle],
    abc: ABCStructure,
    lookahead: int = 5,
    body_multiplier: float = 1.2,
) -> tuple[bool, float | None, int | None]:
    """Return impulse confirmation plus first confirmed impulse price/time."""

    if abc.segment_c is None or abc.direction not in (DivergenceDirection.BEARISH, DivergenceDirection.BULLISH):
        return (False, None, None)
    if lookahead < 1:
        return (False, None, None)

    c_end = abc.segment_c.end_index
    start = c_end + 1
    if start >= len(candles):
        return (False, None, None)

    end = min(len(candles), start + lookahead)
    for index in range(start, end):
        candle = candles[index]
        body = abs(candle.close - candle.open)
        history_start = max(0, index - lookahead)
        history = candles[history_start:index]
        if not history:
            continue
        average_body = sum(abs(item.close - item.open) for item in history) / len(history)
        if body <= average_body * body_multiplier:
            continue

        candle_range = candle.high - candle.low
        if candle_range <= 0.0:
            continue

        previous = candles[index - 1] if index > 0 else None
        recent_window = candles[history_start:index]
        recent_minor_low = min(item.low for item in recent_window) if recent_window else candle.low
        recent_minor_high = max(item.high for item in recent_window) if recent_window else candle.high

        if abc.direction == DivergenceDirection.BEARISH:
            close_in_lower = candle.close <= (candle.low + 0.30 * candle_range)
            break_prev = previous is not None and candle.close < previous.low
            break_recent = candle.close < recent_minor_low
            if close_in_lower and (break_prev or break_recent):
                return (True, candle.close, candle.close_time)
        else:
            close_in_upper = candle.close >= (candle.high - 0.30 * candle_range)
            break_prev = previous is not None and candle.close > previous.high
            break_recent = candle.close > recent_minor_high
            if close_in_upper and (break_prev or break_recent):
                return (True, candle.close, candle.close_time)
    return (False, None, None)


def grade_divergence(
    abc_valid: bool,
    weakening_count: int,
    impulse_confirmed: bool,
) -> DivergenceGrade:
    """Map weakening/impulse evidence to divergence grade."""

    if not abc_valid:
        return DivergenceGrade.INVALID
    if not impulse_confirmed or weakening_count == 0:
        return DivergenceGrade.WEAK
    if weakening_count == 3:
        return DivergenceGrade.ELITE
    if weakening_count >= 2:
        return DivergenceGrade.STRONG
    return DivergenceGrade.MODERATE


def detect_divergence_from_abc(
    abc: ABCStructure,
    candles: list[Candle],
    vacc_series: VAccSeries,
    abc_validation: ABCValidationResult | None = None,
    trace: Any | None = None,
) -> DivergenceState:
    """Convert an A-B-C candidate into official divergence state."""

    if abc_validation is None:
        abc_validation = _abc_validation_from_abc(abc, vacc_series=vacc_series)
    if not abc.abc_valid:
        abc_validation.valid = False
        abc_validation.reason = abc_validation.reason or "A-B-C candidate is invalid."

    energy = compare_vacc_energy_a_vs_c(
        candles=candles,
        abc_result=abc_validation,
        vacc_series=vacc_series,
        trace=trace,
    )
    impulse_direction = (
        "BULLISH" if abc.direction == DivergenceDirection.BULLISH else "BEARISH"
    )
    local_pivots = {
        "start_index": (abc.segment_c.end_index + 1) if abc.segment_c is not None else 0,
        "minor_high": float(getattr(abc.segment_b, "high", 0.0) or 0.0),
        "minor_low": float(getattr(abc.segment_b, "low", 0.0) or 0.0),
    }
    impulse_result = validate_impulse_after_divergence(
        candles=candles,
        timeframe=abc.timeframe,
        direction=impulse_direction,
        local_pivots=local_pivots,
        trace=trace,
    )
    impulse_confirmed = impulse_result.confirmed
    impulse_price = impulse_result.trigger_price
    impulse_time = _close_time_from_index(candles, impulse_result.candle_index)
    classification = classify_divergence(
        abc_result=abc_validation,
        vacc_result=energy,
        impulse_result=(impulse_confirmed, impulse_result.grade),
        carry_result=None,
        trace=trace,
    )
    grade = _classifier_grade_to_enum(classification.grade)
    direction = (
        DivergenceDirection.NONE
        if not classification.abc_valid
        else _classifier_direction_to_enum(classification.direction, fallback=abc.direction)
    )
    exists = bool(classification.official)
    weakening_count = energy.weakening_count

    zone_text = ""
    divergence_price: float | None = None
    divergence_time_utc = ""
    if abc.segment_c is not None:
        if abc.direction == DivergenceDirection.BEARISH:
            zone_text = f"{abc.segment_c.high:.2f}-{abc.segment_c.high:.2f}"
            divergence_price = abc.segment_c.high
        elif abc.direction == DivergenceDirection.BULLISH:
            zone_text = f"{abc.segment_c.low:.2f}-{abc.segment_c.low:.2f}"
            divergence_price = abc.segment_c.low
        divergence_time_utc = _close_time_to_utc(abc.segment_c.end_time)
    if classification.price_zone:
        zone_text = classification.price_zone

    return DivergenceState(
        timeframe=abc.timeframe,
        exists=exists,
        abc_valid=classification.abc_valid,
        direction=direction,
        grade=grade,
        weakening_count=weakening_count,
        impulse_confirmed=impulse_confirmed,
        velocity_weaker=energy.vel_weaker,
        acceleration_weaker=energy.acc_weaker,
        acceleration_area_weaker=energy.acc_area_weaker,
        zero_axis_reset=energy.b_zero_reset,
        price_zone=zone_text,
        divergence_price=divergence_price,
        divergence_time_utc=divergence_time_utc,
        impulse_price=impulse_price,
        impulse_time_utc=_close_time_to_utc(impulse_time),
        notes=(
            f"abc_valid={classification.abc_valid}, weakening={weakening_count}, "
            f"impulse={impulse_confirmed}, vel_weaker={energy.vel_weaker}, "
            f"acc_weaker={energy.acc_weaker}, acc_area_weaker={energy.acc_area_weaker}, "
            f"b_zero_reset={energy.b_zero_reset}, valid_energy_weakening={energy.valid_energy_weakening}, "
            f"impulse_grade={impulse_result.grade}, impulse_reason={impulse_result.reason}, "
            f"classifier_grade={classification.grade}, role={classification.role}, reason={classification.reason}"
        ),
    )


def _classifier_grade_to_enum(grade: str) -> DivergenceGrade:
    value = str(grade or "").strip().upper()
    if value == DivergenceGrade.ELITE.value:
        return DivergenceGrade.ELITE
    if value == DivergenceGrade.STRONG.value:
        return DivergenceGrade.STRONG
    if value == DivergenceGrade.MODERATE.value:
        return DivergenceGrade.MODERATE
    if value == DivergenceGrade.WEAK.value:
        return DivergenceGrade.WEAK
    return DivergenceGrade.INVALID


def _classifier_direction_to_enum(direction: str, fallback: DivergenceDirection) -> DivergenceDirection:
    value = str(direction or "").strip().upper()
    if value == DivergenceDirection.BULLISH.value:
        return DivergenceDirection.BULLISH
    if value == DivergenceDirection.BEARISH.value:
        return DivergenceDirection.BEARISH
    return fallback if fallback in {DivergenceDirection.BULLISH, DivergenceDirection.BEARISH} else DivergenceDirection.NONE


def _close_time_to_utc(close_time: int | None) -> str:
    """Convert millisecond epoch close time into UTC ISO string."""

    if close_time is None:
        return ""
    return datetime.fromtimestamp(close_time / 1000.0, tz=timezone.utc).isoformat()


def _close_time_from_index(candles: list[Candle], index: int | None) -> int | None:
    if index is None or index < 0 or index >= len(candles):
        return None
    return int(getattr(candles[index], "close_time", 0) or 0)
