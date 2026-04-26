"""Strict same-timeframe A-B-C divergence validator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ocean_engine.energy.vacc_engine import (
    get_segment_acceleration_area,
    get_segment_velocity_energy,
)
from ocean_engine.models.enums import Direction
from ocean_engine.models.market import ABCStructure, VAccSeries


@dataclass(slots=True)
class ABCSegment:
    start_index: int
    end_index: int
    start_price: float
    end_price: float
    direction: str  # "UP" or "DOWN"
    high: float
    low: float
    vacc_vel_area: float | None
    vacc_acc_area: float | None
    vacc_total_area: float | None


@dataclass(slots=True)
class ABCValidationResult:
    timeframe: str
    direction: str  # "BULLISH" or "BEARISH"
    valid: bool
    segment_a: ABCSegment | None
    segment_b: ABCSegment | None
    segment_c: ABCSegment | None
    b_reset_valid: bool
    c_test_valid: bool
    same_timeframe_valid: bool
    reason: str


def validate_abc_for_timeframe(
    candles,
    timeframe: str,
    direction: str,
    pivots=None,
    vacc=None,
    trace=None,
) -> ABCValidationResult:
    """Validate A-B-C on exactly one timeframe, with strict reset/retest rules."""

    normalized_tf = _normalize_tf(timeframe)
    normalized_direction = _normalize_direction(direction)
    if normalized_direction == "UNKNOWN":
        result = ABCValidationResult(
            timeframe=normalized_tf,
            direction=str(direction).strip().upper() or "UNKNOWN",
            valid=False,
            segment_a=None,
            segment_b=None,
            segment_c=None,
            b_reset_valid=False,
            c_test_valid=False,
            same_timeframe_valid=False,
            reason=f"Unsupported direction '{direction}'.",
        )
        _emit_checks(trace, result)
        return result

    candle_rows = _flatten_candles(candles)
    vacc_series = _coerce_vacc(vacc)
    same_timeframe_valid = _validate_same_timeframe(
        candles=candle_rows,
        timeframe=normalized_tf,
        pivots=pivots,
        vacc=vacc_series,
    )
    if not same_timeframe_valid:
        result = ABCValidationResult(
            timeframe=normalized_tf,
            direction=normalized_direction,
            valid=False,
            segment_a=None,
            segment_b=None,
            segment_c=None,
            b_reset_valid=False,
            c_test_valid=False,
            same_timeframe_valid=False,
            reason="Mixed-timeframe data detected for A-B-C validation.",
        )
        _emit_checks(trace, result)
        return result

    segment_a, segment_b, segment_c = _resolve_segments(
        candles=candle_rows,
        direction=normalized_direction,
        pivots=pivots,
        vacc=vacc_series,
    )
    if segment_a is None or segment_b is None or segment_c is None:
        result = ABCValidationResult(
            timeframe=normalized_tf,
            direction=normalized_direction,
            valid=False,
            segment_a=segment_a,
            segment_b=segment_b,
            segment_c=segment_c,
            b_reset_valid=False,
            c_test_valid=False,
            same_timeframe_valid=True,
            reason="Missing A/B/C segment.",
        )
        _emit_checks(trace, result)
        return result

    b_reset_valid = _validate_segment_b_reset(
        candles=candle_rows,
        direction=normalized_direction,
        segment_a=segment_a,
        segment_b=segment_b,
        segment_c=segment_c,
        vacc=vacc_series,
    )
    c_test_valid = _validate_segment_c_retest(
        direction=normalized_direction,
        segment_a=segment_a,
        segment_c=segment_c,
    )
    c_weaker_valid = _validate_segment_c_weaker_than_a(
        segment_a=segment_a,
        segment_c=segment_c,
    )
    valid = bool(b_reset_valid and c_test_valid and same_timeframe_valid and c_weaker_valid)
    if not b_reset_valid:
        reason = "Segment B reset is not valid."
    elif not c_test_valid:
        reason = "Segment C does not retest/break meaningful level."
    elif not c_weaker_valid:
        reason = "Segment C is not weaker than Segment A in VAcc."
    else:
        reason = "A-B-C validated."

    result = ABCValidationResult(
        timeframe=normalized_tf,
        direction=normalized_direction,
        valid=valid,
        segment_a=segment_a,
        segment_b=segment_b,
        segment_c=segment_c,
        b_reset_valid=b_reset_valid,
        c_test_valid=c_test_valid,
        same_timeframe_valid=same_timeframe_valid,
        reason=reason,
    )
    _emit_checks(trace, result)
    return result


def _flatten_candles(candles: Any) -> list[Any]:
    if isinstance(candles, dict):
        rows: list[Any] = []
        for value in candles.values():
            if isinstance(value, (list, tuple)):
                rows.extend(list(value))
        return rows
    if isinstance(candles, (list, tuple)):
        return list(candles)
    return []


def _coerce_vacc(vacc: Any) -> VAccSeries | None:
    if isinstance(vacc, VAccSeries):
        return vacc
    if vacc is None:
        return None
    points = getattr(vacc, "points", None)
    timeframe = getattr(vacc, "timeframe", "")
    if isinstance(points, list):
        return VAccSeries(timeframe=str(timeframe), points=points)
    return None


def _normalize_direction(direction: str) -> str:
    text = str(direction).strip().upper()
    if text in {"BULLISH", "UP"}:
        return "BULLISH"
    if text in {"BEARISH", "DOWN"}:
        return "BEARISH"
    return "UNKNOWN"


def _normalize_tf(label: Any) -> str:
    text = str(label).strip().lower()
    aliases = {
        "1d": "1d",
        "d": "1d",
        "daily": "1d",
        "12h": "12h",
        "4h": "4h",
        "1h": "1h",
        "60m": "1h",
        "15m": "15m",
        "5m": "5m",
        "3m": "3m",
    }
    return aliases.get(text, text)


def _validate_same_timeframe(
    candles: list[Any],
    timeframe: str,
    pivots: Any,
    vacc: VAccSeries | None,
) -> bool:
    candle_timeframes = {_normalize_tf(tf) for tf in (_extract_timeframe(item) for item in candles) if tf}
    if len(candle_timeframes) > 1:
        return False
    if candle_timeframes and timeframe not in candle_timeframes:
        return False

    pivot_tfs = _extract_pivot_timeframes(pivots)
    if len(pivot_tfs) > 1:
        return False
    if pivot_tfs and timeframe not in pivot_tfs:
        return False

    if vacc is not None and vacc.timeframe:
        if _normalize_tf(vacc.timeframe) != timeframe:
            return False
    return True


def _extract_timeframe(item: Any) -> str:
    if isinstance(item, dict):
        for key in ("timeframe", "tf", "interval"):
            value = item.get(key)
            if value:
                return str(value)
        return ""
    for attr in ("timeframe", "tf", "interval"):
        value = getattr(item, attr, "")
        if value:
            return str(value)
    return ""


def _extract_pivot_timeframes(pivots: Any) -> set[str]:
    if pivots is None:
        return set()
    if isinstance(pivots, ABCStructure):
        return {_normalize_tf(pivots.timeframe)} if pivots.timeframe else set()
    rows = pivots if isinstance(pivots, (list, tuple)) else [pivots]
    return {_normalize_tf(_extract_timeframe(item)) for item in rows if _extract_timeframe(item)}


def _resolve_segments(
    *,
    candles: list[Any],
    direction: str,
    pivots: Any,
    vacc: VAccSeries | None,
) -> tuple[ABCSegment | None, ABCSegment | None, ABCSegment | None]:
    if isinstance(pivots, ABCStructure):
        if _abc_direction(pivots) != direction:
            return (None, None, None)
        segment_a = _segment_from_leglike(pivots.segment_a, candles, vacc)
        segment_b = _segment_from_leglike(pivots.segment_b, candles, vacc)
        segment_c = _segment_from_leglike(pivots.segment_c, candles, vacc)
        return (segment_a, segment_b, segment_c)

    if isinstance(pivots, (list, tuple)) and len(pivots) >= 3:
        a_leg, b_leg, c_leg = pivots[-3], pivots[-2], pivots[-1]
        expected = ("UP", "DOWN", "UP") if direction == "BEARISH" else ("DOWN", "UP", "DOWN")
        actual = (
            _leg_direction(a_leg),
            _leg_direction(b_leg),
            _leg_direction(c_leg),
        )
        if actual != expected:
            return (None, None, None)
        return (
            _segment_from_leglike(a_leg, candles, vacc),
            _segment_from_leglike(b_leg, candles, vacc),
            _segment_from_leglike(c_leg, candles, vacc),
        )
    if isinstance(pivots, (list, tuple)):
        return (None, None, None)

    return _derive_segments_from_candles(candles=candles, direction=direction, vacc=vacc)


def _segment_from_leglike(leg: Any, candles: list[Any], vacc: VAccSeries | None) -> ABCSegment | None:
    if leg is None:
        return None
    start_index = _safe_int(getattr(leg, "start_index", None))
    end_index = _safe_int(getattr(leg, "end_index", None))
    if start_index is None or end_index is None or end_index <= start_index:
        return None

    direction = _leg_direction(leg)
    if direction not in {"UP", "DOWN"}:
        direction = "UP" if _float(getattr(leg, "end_price", 0.0)) >= _float(getattr(leg, "start_price", 0.0)) else "DOWN"

    start_price = _float(getattr(leg, "start_price", None))
    end_price = _float(getattr(leg, "end_price", None))
    high = _float(getattr(leg, "high", None))
    low = _float(getattr(leg, "low", None))
    if start_price is None or end_price is None or high is None or low is None:
        derived = _segment_from_indexes(candles, start_index, end_index, direction, vacc)
        if derived is None:
            return None
        return derived

    vel_area, acc_area, total_area = _segment_vacc_areas(vacc, start_index, end_index, direction)
    return ABCSegment(
        start_index=start_index,
        end_index=end_index,
        start_price=start_price,
        end_price=end_price,
        direction=direction,
        high=high,
        low=low,
        vacc_vel_area=vel_area,
        vacc_acc_area=acc_area,
        vacc_total_area=total_area,
    )


def _derive_segments_from_candles(
    *,
    candles: list[Any],
    direction: str,
    vacc: VAccSeries | None,
) -> tuple[ABCSegment | None, ABCSegment | None, ABCSegment | None]:
    if len(candles) < 9:
        return (None, None, None)

    highs = [_float(_candle_value(row, "high")) for row in candles]
    lows = [_float(_candle_value(row, "low")) for row in candles]
    if any(value is None for value in highs) or any(value is None for value in lows):
        return (None, None, None)

    midpoint = len(candles) // 2
    if direction == "BEARISH":
        c_end = _arg_extreme(highs, start=max(midpoint, 2), mode="max")
        a_end = _arg_extreme(highs, start=1, end=max(c_end - 1, 2), mode="max")
        if c_end <= a_end + 1:
            return (None, None, None)
        b_extreme = _arg_extreme(lows, start=a_end + 1, end=c_end, mode="min")
        a_start = _arg_extreme(lows, start=max(0, a_end - 8), end=a_end + 1, mode="min")
        if b_extreme <= a_end or b_extreme >= c_end:
            return (None, None, None)
        segment_a = _segment_from_indexes(candles, a_start, a_end, "UP", vacc)
        segment_b = _segment_from_indexes(candles, a_end, b_extreme, "DOWN", vacc)
        segment_c = _segment_from_indexes(candles, b_extreme, c_end, "UP", vacc)
    else:
        c_end = _arg_extreme(lows, start=max(midpoint, 2), mode="min")
        a_end = _arg_extreme(lows, start=1, end=max(c_end - 1, 2), mode="min")
        if c_end <= a_end + 1:
            return (None, None, None)
        b_extreme = _arg_extreme(highs, start=a_end + 1, end=c_end, mode="max")
        a_start = _arg_extreme(highs, start=max(0, a_end - 8), end=a_end + 1, mode="max")
        if b_extreme <= a_end or b_extreme >= c_end:
            return (None, None, None)
        segment_a = _segment_from_indexes(candles, a_start, a_end, "DOWN", vacc)
        segment_b = _segment_from_indexes(candles, a_end, b_extreme, "UP", vacc)
        segment_c = _segment_from_indexes(candles, b_extreme, c_end, "DOWN", vacc)

    return (segment_a, segment_b, segment_c)


def _segment_from_indexes(
    candles: list[Any],
    start_index: int,
    end_index: int,
    direction: str,
    vacc: VAccSeries | None,
) -> ABCSegment | None:
    if end_index <= start_index:
        return None
    start = max(0, start_index)
    end = min(len(candles) - 1, end_index)
    if end <= start:
        return None
    rows = candles[start : end + 1]
    if not rows:
        return None

    start_price = _float(_candle_value(rows[0], "open"))
    end_price = _float(_candle_value(rows[-1], "close"))
    highs = [_float(_candle_value(row, "high")) for row in rows]
    lows = [_float(_candle_value(row, "low")) for row in rows]
    if (
        start_price is None
        or end_price is None
        or any(value is None for value in highs)
        or any(value is None for value in lows)
    ):
        return None

    high = max(value for value in highs if value is not None)
    low = min(value for value in lows if value is not None)
    vel_area, acc_area, total_area = _segment_vacc_areas(vacc, start, end, direction)
    return ABCSegment(
        start_index=start,
        end_index=end,
        start_price=start_price,
        end_price=end_price,
        direction=direction,
        high=high,
        low=low,
        vacc_vel_area=vel_area,
        vacc_acc_area=acc_area,
        vacc_total_area=total_area,
    )


def _segment_vacc_areas(
    vacc: VAccSeries | None,
    start_index: int,
    end_index: int,
    direction: str,
) -> tuple[float | None, float | None, float | None]:
    if vacc is None:
        return (None, None, None)
    if not vacc.points:
        return (None, None, None)
    energy_direction = Direction.UP if direction == "UP" else Direction.DOWN
    vel_area = get_segment_velocity_energy(
        vacc_series=vacc,
        start_index=start_index,
        end_index=end_index,
        direction=energy_direction,
    )
    acc_area = get_segment_acceleration_area(
        vacc_series=vacc,
        start_index=start_index,
        end_index=end_index,
        direction=energy_direction,
    )
    total_area = abs(float(vel_area)) + abs(float(acc_area))
    return (float(vel_area), float(acc_area), float(total_area))


def _validate_segment_b_reset(
    *,
    candles: list[Any],
    direction: str,
    segment_a: ABCSegment,
    segment_b: ABCSegment,
    segment_c: ABCSegment,
    vacc: VAccSeries | None,
) -> bool:
    if direction == "BEARISH":
        expected = ("UP", "DOWN", "UP")
    else:
        expected = ("DOWN", "UP", "DOWN")
    if (segment_a.direction, segment_b.direction, segment_c.direction) != expected:
        return False

    clear_pullback_exists = False
    if direction == "BEARISH":
        clear_pullback_exists = segment_b.low <= (segment_a.end_price * (1.0 - 0.001))
    else:
        clear_pullback_exists = segment_b.high >= (segment_a.end_price * (1.0 + 0.001))

    b_rows = candles[segment_b.start_index : segment_b.end_index + 1]
    overlap_count = 0
    for left, right in zip(b_rows, b_rows[1:]):
        left_low = _float(_candle_value(left, "low"))
        left_high = _float(_candle_value(left, "high"))
        right_low = _float(_candle_value(right, "low"))
        right_high = _float(_candle_value(right, "high"))
        if (
            left_low is None
            or left_high is None
            or right_low is None
            or right_high is None
        ):
            continue
        overlap_low = max(left_low, right_low)
        overlap_high = min(left_high, right_high)
        if overlap_high >= overlap_low:
            overlap_count += 1
    several_overlapping_candles = overlap_count >= 2

    b_range = segment_b.high - segment_b.low
    anchor = max(abs(segment_a.end_price), 1e-9)
    small_range_zone_exists = (b_range / anchor) <= 0.02 and len(b_rows) >= 3

    vel_reset_valid = False
    if vacc is not None and vacc.points:
        velocities: list[float] = []
        start = max(0, segment_b.start_index)
        end = min(segment_b.end_index, len(vacc.points) - 1)
        if end > start:
            for idx in range(start, end + 1):
                velocities.append(float(vacc.points[idx].velocity))
            near_zero = any(abs(value) <= 1e-6 for value in velocities)
            sign_cross = any(left == 0.0 or right == 0.0 or (left > 0.0 > right) or (left < 0.0 < right) for left, right in zip(velocities, velocities[1:]))
            vel_reset_valid = near_zero or sign_cross

    pause_enough = (segment_b.end_index - segment_b.start_index) >= 2
    return any(
        (
            clear_pullback_exists,
            several_overlapping_candles,
            small_range_zone_exists,
            vel_reset_valid,
            pause_enough,
        )
    )


def _validate_segment_c_retest(
    *,
    direction: str,
    segment_a: ABCSegment,
    segment_c: ABCSegment,
) -> bool:
    if direction == "BEARISH":
        retest_or_break = segment_c.high >= (segment_a.high * (1.0 - 0.001))
        meaningful_structural_test = segment_c.end_price >= (segment_a.end_price * (1.0 - 0.002))
        return retest_or_break or meaningful_structural_test

    retest_or_break = segment_c.low <= (segment_a.low * (1.0 + 0.001))
    meaningful_structural_test = segment_c.end_price <= (segment_a.end_price * (1.0 + 0.002))
    return retest_or_break or meaningful_structural_test


def _validate_segment_c_weaker_than_a(
    *,
    segment_a: ABCSegment,
    segment_c: ABCSegment,
) -> bool:
    """Require C to be weaker than A when VAcc energy is available."""

    if segment_a.vacc_total_area is None or segment_c.vacc_total_area is None:
        return True
    return float(segment_c.vacc_total_area) < float(segment_a.vacc_total_area)


def _arg_extreme(values: list[float | None], *, start: int, mode: str, end: int | None = None) -> int:
    stop = len(values) if end is None else min(end, len(values))
    start = max(0, start)
    if stop <= start:
        return start
    best_idx = start
    best_value = values[start]
    for idx in range(start + 1, stop):
        value = values[idx]
        if value is None:
            continue
        if best_value is None:
            best_idx, best_value = idx, value
            continue
        if mode == "max" and value >= best_value:
            best_idx, best_value = idx, value
        if mode == "min" and value <= best_value:
            best_idx, best_value = idx, value
    return best_idx


def _safe_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _leg_direction(leg: Any) -> str:
    value = getattr(getattr(leg, "direction", ""), "value", getattr(leg, "direction", ""))
    return str(value).strip().upper()


def _abc_direction(abc: ABCStructure) -> str:
    raw = getattr(getattr(abc, "direction", ""), "value", getattr(abc, "direction", ""))
    text = str(raw).strip().upper()
    if text in {"BEARISH", "DOWN"}:
        return "BEARISH"
    if text in {"BULLISH", "UP"}:
        return "BULLISH"
    return "UNKNOWN"


def _float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _candle_value(candle: Any, key: str) -> Any:
    if isinstance(candle, dict):
        return candle.get(key)
    return getattr(candle, key, None)


def _emit_checks(trace: Any, result: ABCValidationResult) -> None:
    _add_check(
        trace,
        name="A-B-C same timeframe",
        passed=result.same_timeframe_valid,
        details=result.reason,
    )
    _add_check(
        trace,
        name="Segment B reset valid",
        passed=result.b_reset_valid,
        details=result.reason,
    )
    _add_check(
        trace,
        name="Segment C retest/new extreme valid",
        passed=result.c_test_valid,
        details=result.reason,
    )
    _add_check(
        trace,
        name="A-B-C valid",
        passed=result.valid,
        details=result.reason,
    )


def _add_check(trace: Any, *, name: str, passed: bool, details: str) -> None:
    if trace is None or not hasattr(trace, "add_check"):
        return
    trace.add_check(
        name=name,
        passed=passed,
        severity="INFO" if passed else "ERROR",
        details=details,
        file="ocean_abc_validator.py",
        function="validate_abc_for_timeframe",
    )
