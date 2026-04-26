"""Strict pivot-overlap range validator for framework v1.2."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class RangeResult:
    timeframe: str
    active: bool
    upper_edge: float | None
    lower_edge: float | None
    midpoint: float | None
    pivot_zone_high: float | None
    pivot_zone_low: float | None
    parts_count: int
    repeated_overlap: bool
    parent_move_direction: str | None
    current_location: str  # UPPER / LOWER / MID / OUTSIDE / UNCLEAR
    valid: bool
    reason: str


def detect_valid_range(candles, timeframe, swings=None, trace=None) -> RangeResult:
    """Detect strict valid range from movement parts and overlap pivots."""

    parts = _normalize_parts(swings)
    parts_count = len(parts)
    _add_check(
        trace=trace,
        name="Range requires at least three sub-level moves",
        passed=parts_count >= 3,
        severity="ERROR" if parts_count < 3 else "INFO",
        details=f"timeframe={timeframe}, parts_count={parts_count}",
        function="detect_valid_range",
    )
    if parts_count < 3:
        _add_check(
            trace=trace,
            name="Range has upper/lower/midpoint",
            passed=False,
            severity="ERROR",
            details="Range parts insufficient to form strict boundaries.",
            function="detect_valid_range",
        )
        _add_check(
            trace=trace,
            name="Range parent move recorded",
            passed=False,
            severity="ERROR",
            details="No parent move can be inferred without valid range window.",
            function="detect_valid_range",
        )
        _add_check(
            trace=trace,
            name="Range midpoint WAIT rule checked",
            passed=False,
            severity="ERROR",
            details="Midpoint rule cannot be evaluated for invalid range.",
            function="detect_valid_range",
        )
        return RangeResult(
            timeframe=str(timeframe or ""),
            active=False,
            upper_edge=None,
            lower_edge=None,
            midpoint=None,
            pivot_zone_high=None,
            pivot_zone_low=None,
            parts_count=parts_count,
            repeated_overlap=False,
            parent_move_direction=None,
            current_location="UNCLEAR",
            valid=False,
            reason="Need at least three sub-level movement parts.",
        )

    window = _best_overlap_window(parts)
    if window is None:
        _add_check(
            trace=trace,
            name="Range has upper/lower/midpoint",
            passed=False,
            severity="ERROR",
            details="No shared overlap area / pivot zone found.",
            function="detect_valid_range",
        )
        _add_check(
            trace=trace,
            name="Range parent move recorded",
            passed=False,
            severity="ERROR",
            details="No valid range window found for parent move inference.",
            function="detect_valid_range",
        )
        _add_check(
            trace=trace,
            name="Range midpoint WAIT rule checked",
            passed=False,
            severity="ERROR",
            details="Midpoint rule cannot be evaluated for invalid range.",
            function="detect_valid_range",
        )
        return RangeResult(
            timeframe=str(timeframe or ""),
            active=False,
            upper_edge=None,
            lower_edge=None,
            midpoint=None,
            pivot_zone_high=None,
            pivot_zone_low=None,
            parts_count=parts_count,
            repeated_overlap=False,
            parent_move_direction=None,
            current_location="UNCLEAR",
            valid=False,
            reason="No repeated overlap / pivot zone found.",
        )

    start, end, pivot_low, pivot_high = window
    window_parts = parts[start : end + 1]
    lower_edge = min(part["low"] for part in window_parts)
    upper_edge = max(part["high"] for part in window_parts)
    midpoint = (upper_edge + lower_edge) / 2.0
    repeated_rotation = _rotation_count(window_parts) >= 2
    repeated_overlap = pivot_low < pivot_high
    sustained_outside = _sustained_continuation_outside(
        candles=candles or [],
        upper_edge=upper_edge,
        lower_edge=lower_edge,
    )
    parent_direction = _parent_move_direction(parts, start)
    current_price = _last_close(candles)
    current_location = classify_range_location(
        price=current_price,
        range_result=RangeResult(
            timeframe=str(timeframe or ""),
            active=False,
            upper_edge=upper_edge,
            lower_edge=lower_edge,
            midpoint=midpoint,
            pivot_zone_high=pivot_high,
            pivot_zone_low=pivot_low,
            parts_count=len(window_parts),
            repeated_overlap=repeated_overlap,
            parent_move_direction=parent_direction,
            current_location="UNCLEAR",
            valid=False,
            reason="",
        ),
    )

    has_bounds = upper_edge is not None and lower_edge is not None and midpoint is not None
    _add_check(
        trace=trace,
        name="Range has upper/lower/midpoint",
        passed=has_bounds,
        severity="ERROR" if not has_bounds else "INFO",
        details=(
            f"upper={upper_edge}, lower={lower_edge}, midpoint={midpoint}"
            if has_bounds
            else "Range boundaries are incomplete."
        ),
        function="detect_valid_range",
    )
    parent_recorded = parent_direction is not None
    _add_check(
        trace=trace,
        name="Range parent move recorded",
        passed=parent_recorded,
        severity="ERROR" if not parent_recorded else "INFO",
        details=f"parent_move_direction={parent_direction}",
        function="detect_valid_range",
    )
    midpoint_checked = True
    _add_check(
        trace=trace,
        name="Range midpoint WAIT rule checked",
        passed=midpoint_checked,
        severity="INFO",
        details=(
            "Price in midpoint: fresh trade defaults to WAIT unless structure is extremely clear."
            if current_location == "MID"
            else f"Current location={current_location}."
        ),
        function="detect_valid_range",
    )

    valid = bool(
        has_bounds
        and repeated_rotation
        and repeated_overlap
        and len(window_parts) >= 3
        and not sustained_outside
    )
    reason = (
        "Valid pivot-overlap range with repeated rotation and no sustained continuation outside."
        if valid
        else (
            "Invalid range: sustained continuation outside boundaries."
            if sustained_outside
            else "Invalid range: missing repeated rotation/overlap structure."
        )
    )
    return RangeResult(
        timeframe=str(timeframe or ""),
        active=valid,
        upper_edge=float(upper_edge),
        lower_edge=float(lower_edge),
        midpoint=float(midpoint),
        pivot_zone_high=float(pivot_high),
        pivot_zone_low=float(pivot_low),
        parts_count=len(window_parts),
        repeated_overlap=repeated_overlap,
        parent_move_direction=parent_direction,
        current_location=current_location,
        valid=valid,
        reason=reason,
    )


def classify_range_location(price, range_result):
    """Classify price location inside strict range result."""

    if range_result is None:
        return "UNCLEAR"
    upper = getattr(range_result, "upper_edge", None)
    lower = getattr(range_result, "lower_edge", None)
    if price is None or upper is None or lower is None:
        return "UNCLEAR"
    upper_f = float(upper)
    lower_f = float(lower)
    if upper_f <= lower_f:
        return "UNCLEAR"
    value = float(price)
    if value > upper_f or value < lower_f:
        return "OUTSIDE"

    width = upper_f - lower_f
    lower_quarter = lower_f + 0.25 * width
    upper_quarter = upper_f - 0.25 * width
    if value <= lower_quarter:
        return "LOWER"
    if value >= upper_quarter:
        return "UPPER"
    return "MID"


def _normalize_parts(swings: Any) -> list[dict[str, Any]]:
    if not swings:
        return []
    parts: list[dict[str, Any]] = []
    for idx, item in enumerate(swings):
        low = _coerce_float(getattr(item, "low", None))
        high = _coerce_float(getattr(item, "high", None))
        if low is None or high is None or high <= low:
            continue
        direction = _normalize_direction(getattr(item, "direction", "UNCLEAR"))
        start_index = _coerce_int(getattr(item, "start_index", idx))
        end_index = _coerce_int(getattr(item, "end_index", idx))
        parts.append(
            {
                "low": low,
                "high": high,
                "direction": direction,
                "start_index": start_index if start_index is not None else idx,
                "end_index": end_index if end_index is not None else idx,
            }
        )
    parts.sort(key=lambda part: part["end_index"])
    return parts


def _best_overlap_window(parts: list[dict[str, Any]]) -> tuple[int, int, float, float] | None:
    best: tuple[int, int, float, float] | None = None
    for start in range(0, len(parts) - 2):
        for end in range(start + 2, len(parts)):
            window = parts[start : end + 1]
            pivot_low = max(part["low"] for part in window)
            pivot_high = min(part["high"] for part in window)
            if pivot_low >= pivot_high:
                continue
            if best is None:
                best = (start, end, pivot_low, pivot_high)
                continue
            best_start, best_end, _, _ = best
            if end > best_end or (end == best_end and (end - start) > (best_end - best_start)):
                best = (start, end, pivot_low, pivot_high)
    return best


def _rotation_count(parts: list[dict[str, Any]]) -> int:
    if len(parts) < 2:
        return 0
    rotations = 0
    previous = parts[0]["direction"]
    for part in parts[1:]:
        current = part["direction"]
        if current == "UNCLEAR":
            continue
        if previous != "UNCLEAR" and current != previous:
            rotations += 1
        previous = current
    return rotations


def _sustained_continuation_outside(candles: list[Any], upper_edge: float, lower_edge: float) -> bool:
    if not candles:
        return False
    closes = [float(getattr(candle, "close", 0.0)) for candle in candles[-20:]]
    if len(closes) < 3:
        return False

    run_up = 0
    run_down = 0
    for close in closes:
        if close > upper_edge:
            run_up += 1
            run_down = 0
        elif close < lower_edge:
            run_down += 1
            run_up = 0
        else:
            run_up = 0
            run_down = 0
        if run_up >= 3 or run_down >= 3:
            return True
    return False


def _parent_move_direction(parts: list[dict[str, Any]], window_start: int) -> str | None:
    if window_start <= 0:
        return parts[0]["direction"] if parts else None
    parent = parts[window_start - 1]["direction"]
    return parent if parent in {"UP", "DOWN"} else None


def _last_close(candles: list[Any] | None) -> float | None:
    if not candles:
        return None
    return _coerce_float(getattr(candles[-1], "close", None))


def _normalize_direction(direction: Any) -> str:
    value = str(getattr(direction, "value", direction)).strip().upper()
    if value in {"UP", "BULLISH"}:
        return "UP"
    if value in {"DOWN", "BEARISH"}:
        return "DOWN"
    return "UNCLEAR"


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


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
        file="ocean_range_engine.py",
        function=function,
    )
