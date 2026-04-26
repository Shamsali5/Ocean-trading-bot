"""Range (Zhongshu) detection from same-timeframe legs."""

from __future__ import annotations

from ocean_range_engine import detect_valid_range
from ocean_engine.models.enums import Direction
from ocean_engine.models.market import Candle, Leg, RangeState


def calculate_leg_overlap(legs: list[Leg]) -> tuple[float, float] | None:
    """Return (ZD, ZG) overlap for a group of legs, if present."""

    if not legs:
        return None
    zd = max(leg.low for leg in legs)
    zg = min(leg.high for leg in legs)
    if zd < zg:
        return (zd, zg)
    return None


def classify_price_location(current_price: float, lower_edge: float, upper_edge: float) -> str:
    """Classify current price location inside/outside the detected range."""

    if upper_edge <= lower_edge:
        return "UNCLEAR"
    if current_price > upper_edge or current_price < lower_edge:
        return "OUTSIDE"

    width = upper_edge - lower_edge
    lower_quarter = lower_edge + (0.25 * width)
    upper_quarter = upper_edge - (0.25 * width)

    if current_price <= lower_quarter:
        return "LOWER_EDGE"
    if current_price >= upper_quarter:
        return "UPPER_EDGE"
    return "MID"


def detect_range_ownership(
    *,
    ordered_legs: list[Leg],
    range_start_index: int | None,
) -> tuple[Direction, str]:
    """Infer range ownership from the immediate pre-range leg direction."""

    if range_start_index is None:
        return (Direction.UNCLEAR, "Ownership unclear: missing range start index.")

    previous_leg: Leg | None = None
    for leg in ordered_legs:
        if leg.end_index < range_start_index:
            previous_leg = leg
        else:
            break

    if previous_leg is None:
        return (Direction.UNCLEAR, "Ownership unclear: no pre-range leg found.")

    if previous_leg.direction == Direction.UP:
        return (
            Direction.UP,
            "Bullish ownership: range was entered from an immediately preceding up leg.",
        )
    if previous_leg.direction == Direction.DOWN:
        return (
            Direction.DOWN,
            "Bearish ownership: range was entered from an immediately preceding down leg.",
        )
    return (Direction.UNCLEAR, "Ownership unclear: pre-range leg direction is unclear.")


def detect_breakout_acceptance(
    range_state: RangeState,
    candles: list[Candle],
    legs: list[Leg],
    current_price: float,
    lookback: int = 20,
    retest_tolerance_pct: float = 0.0015,
) -> RangeState:
    """Classify breakout/acceptance status for an already-detected range."""

    if (
        not range_state.is_range
        or range_state.upper_edge is None
        or range_state.lower_edge is None
        or not candles
    ):
        range_state.status = "UNCLEAR"
        return range_state

    if lookback < 3:
        lookback = 3

    closes = [candle.close for candle in candles[-lookback:]]
    upper = range_state.upper_edge
    lower = range_state.lower_edge
    # Allow tolerance to scale both with range width and absolute boundary price.
    tolerance = max(
        abs(upper - lower) * retest_tolerance_pct,
        abs(upper) * retest_tolerance_pct,
        abs(lower) * retest_tolerance_pct,
        1e-9,
    )

    above_indices = [idx for idx, close in enumerate(closes) if close > upper]
    below_indices = [idx for idx, close in enumerate(closes) if close < lower]

    def _failed_break_up(first_index: int) -> bool:
        return any(close <= upper for close in closes[first_index + 1 :])

    def _failed_break_down(first_index: int) -> bool:
        return any(close >= lower for close in closes[first_index + 1 :])

    def _retest_hold_up(first_index: int) -> bool:
        for idx in range(first_index + 1, len(closes) - 1):
            retest_close = closes[idx]
            if upper <= retest_close <= (upper + tolerance):
                if closes[idx + 1] > retest_close and closes[idx + 1] > upper:
                    return True
        return False

    def _retest_hold_down(first_index: int) -> bool:
        for idx in range(first_index + 1, len(closes) - 1):
            retest_close = closes[idx]
            if (lower - tolerance) <= retest_close <= lower:
                if closes[idx + 1] < retest_close and closes[idx + 1] < lower:
                    return True
        return False

    def _upgrade_risk_status() -> str:
        has_failed_up = any(
            close > upper and any(next_close <= upper for next_close in closes[idx + 1 :])
            for idx, close in enumerate(closes)
        )
        has_failed_down = any(
            close < lower and any(next_close >= lower for next_close in closes[idx + 1 :])
            for idx, close in enumerate(closes)
        )
        if has_failed_up and has_failed_down:
            return "UPGRADE_RISK"
        return "ACTIVE"

    # Bullish break acceptance.
    if above_indices:
        first = above_indices[0]
        range_state.breakout_direction = Direction.UP
        range_state.breakout_level = upper
        range_state.breakout_confirmed = True
        range_state.first_break_index = len(candles) - len(closes) + first
        range_state.first_accepted_close = closes[first]

        if _failed_break_up(first):
            if lower <= current_price <= upper:
                range_state.status = _upgrade_risk_status()
                if range_state.status != "UPGRADE_RISK":
                    range_state.status = "RE_ENTERED"
            else:
                range_state.status = "FAILED_BREAK_UP"
            range_state.acceptance_confirmed = False
            range_state.retest_held = False
            return range_state

        retest_hold = _retest_hold_up(first)
        range_state.retest_held = retest_hold
        acceptance_two_closes = len(above_indices) >= 2
        range_state.acceptance_confirmed = acceptance_two_closes or retest_hold
        range_state.status = "BROKEN_UP" if range_state.acceptance_confirmed else "UNCLEAR"
        return range_state

    # Bearish break acceptance.
    if below_indices:
        first = below_indices[0]
        range_state.breakout_direction = Direction.DOWN
        range_state.breakout_level = lower
        range_state.breakout_confirmed = True
        range_state.first_break_index = len(candles) - len(closes) + first
        range_state.first_accepted_close = closes[first]

        if _failed_break_down(first):
            if lower <= current_price <= upper:
                range_state.status = _upgrade_risk_status()
                if range_state.status != "UPGRADE_RISK":
                    range_state.status = "RE_ENTERED"
            else:
                range_state.status = "FAILED_BREAK_DOWN"
            range_state.acceptance_confirmed = False
            range_state.retest_held = False
            return range_state

        retest_hold = _retest_hold_down(first)
        range_state.retest_held = retest_hold
        acceptance_two_closes = len(below_indices) >= 2
        range_state.acceptance_confirmed = acceptance_two_closes or retest_hold
        range_state.status = "BROKEN_DOWN" if range_state.acceptance_confirmed else "UNCLEAR"
        return range_state

    # No confirmed close outside: range stays active.
    range_state.status = _upgrade_risk_status()
    range_state.breakout_direction = Direction.UNCLEAR
    range_state.breakout_level = None
    range_state.breakout_confirmed = False
    range_state.retest_held = False
    range_state.acceptance_confirmed = False
    range_state.first_break_index = None
    range_state.first_accepted_close = None
    return range_state


def detect_range_from_legs(
    legs: list[Leg],
    current_price: float,
    candles: list[Candle] | None = None,
    timeframe: str = "",
    min_legs: int = 3,
    max_legs: int = 8,
    trace: object | None = None,
) -> RangeState:
    """Detect the most recent valid overlapping range window."""

    if min_legs < 3:
        raise ValueError("min_legs must be >= 3")
    if max_legs < min_legs:
        raise ValueError("max_legs must be >= min_legs")

    if len(legs) < min_legs:
        _add_range_trace_for_invalid_state(
            trace=trace,
            reason="Not enough legs to form a range.",
            parts_count=len(legs),
            has_bounds=False,
            midpoint_checked=False,
            parent_recorded=False,
        )
        return RangeState(
            timeframe=timeframe,
            is_range=False,
            active=False,
            price_location="UNCLEAR",
            leg_count=0,
            summary="Not enough legs to form a range.",
        )

    ordered = sorted(legs, key=lambda leg: leg.end_index)
    best_window: list[Leg] | None = None
    best_end_index = -1
    best_size = -1

    max_window_size = min(max_legs, len(ordered))
    for window_size in range(min_legs, max_window_size + 1):
        for end in range(window_size, len(ordered) + 1):
            window = ordered[end - window_size : end]
            overlap = calculate_leg_overlap(window)
            if overlap is None:
                continue

            window_end_index = window[-1].end_index
            if window_end_index > best_end_index:
                best_window = window
                best_end_index = window_end_index
                best_size = window_size
            elif window_end_index == best_end_index and window_size > best_size:
                best_window = window
                best_size = window_size

    if best_window is None:
        _add_range_trace_for_invalid_state(
            trace=trace,
            reason="No overlapping leg window found.",
            parts_count=len(ordered),
            has_bounds=False,
            midpoint_checked=False,
            parent_recorded=False,
        )
        return RangeState(
            timeframe=timeframe,
            is_range=False,
            active=False,
            price_location="UNCLEAR",
            leg_count=0,
            summary="No overlapping leg window found.",
        )

    strict_range = detect_valid_range(
        candles=candles or [],
        timeframe=timeframe,
        swings=best_window,
        trace=trace,
    )
    if not strict_range.valid:
        _add_range_trace_for_invalid_state(
            trace=trace,
            reason=f"Invalid strict range: {strict_range.reason}",
            parts_count=len(best_window),
            has_bounds=bool(
                strict_range.upper_edge is not None
                and strict_range.lower_edge is not None
                and strict_range.midpoint is not None
            ),
            midpoint_checked=True,
            parent_recorded=bool(strict_range.parent_move_direction),
        )
        return RangeState(
            timeframe=timeframe,
            is_range=False,
            active=False,
            price_location="UNCLEAR",
            leg_count=len(best_window),
            summary=f"Invalid strict range: {strict_range.reason}",
        )

    pivot_low = strict_range.pivot_zone_low
    pivot_high = strict_range.pivot_zone_high
    outer_lower_edge = strict_range.lower_edge
    outer_upper_edge = strict_range.upper_edge
    midpoint = strict_range.midpoint
    if (
        pivot_low is None
        or pivot_high is None
        or outer_lower_edge is None
        or outer_upper_edge is None
        or midpoint is None
    ):
        _add_range_trace_for_invalid_state(
            trace=trace,
            reason="Strict range did not provide complete boundaries.",
            parts_count=len(best_window),
            has_bounds=False,
            midpoint_checked=False,
            parent_recorded=bool(strict_range.parent_move_direction),
        )
        return RangeState(
            timeframe=timeframe,
            is_range=False,
            active=False,
            price_location="UNCLEAR",
            leg_count=len(best_window),
            summary="Strict range did not provide complete boundaries.",
        )

    price_location = classify_price_location(
        current_price=current_price,
        lower_edge=outer_lower_edge,
        upper_edge=outer_upper_edge,
    )
    ownership, ownership_reason = detect_range_ownership(
        ordered_legs=ordered,
        range_start_index=best_window[0].start_index if best_window else None,
    )

    state = RangeState(
        timeframe=timeframe,
        is_range=True,
        high=outer_upper_edge,
        low=outer_lower_edge,
        mid=midpoint,
        active=True,
        upper_edge=outer_upper_edge,
        lower_edge=outer_lower_edge,
        midpoint=midpoint,
        pivot_low=pivot_low,
        pivot_high=pivot_high,
        price_location=price_location,
        leg_count=len(best_window),
        start_index=best_window[0].start_index,
        end_index=best_window[-1].end_index,
        ownership=ownership,
        ownership_reason=ownership_reason,
        summary=(
            f"Range detected with {len(best_window)} legs, "
            f"ZD={pivot_low:.6f}, ZG={pivot_high:.6f}. "
            f"Ownership={ownership.value}."
        ),
    )
    state.status = "ACTIVE"
    if candles:
        state = detect_breakout_acceptance(
            range_state=state,
            candles=candles,
            legs=ordered,
            current_price=current_price,
        )
        state.summary = (
            f"Range detected with {len(best_window)} legs, "
            f"ZD={pivot_low:.6f}, ZG={pivot_high:.6f}. "
            f"Ownership={ownership.value}. "
            f"Status={state.status}."
        )
    return state


def _add_range_trace_for_invalid_state(
    *,
    trace: object | None,
    reason: str,
    parts_count: int,
    has_bounds: bool,
    midpoint_checked: bool,
    parent_recorded: bool,
) -> None:
    if trace is None or not hasattr(trace, "add_check"):
        return
    trace.add_check(
        name="Range requires at least three sub-level moves",
        passed=parts_count >= 3,
        severity="ERROR" if parts_count < 3 else "INFO",
        details=f"parts_count={parts_count}; {reason}",
        file=__file__,
        function="detect_range_from_legs",
    )
    trace.add_check(
        name="Range has upper/lower/midpoint",
        passed=has_bounds,
        severity="ERROR" if not has_bounds else "INFO",
        details=reason,
        file=__file__,
        function="detect_range_from_legs",
    )
    trace.add_check(
        name="Range midpoint WAIT rule checked",
        passed=midpoint_checked,
        severity="ERROR" if not midpoint_checked else "INFO",
        details=(
            "Midpoint WAIT rule unavailable because strict range is invalid."
            if not midpoint_checked
            else "Midpoint WAIT rule evaluated in strict range flow."
        ),
        file=__file__,
        function="detect_range_from_legs",
    )
    trace.add_check(
        name="Range parent move recorded",
        passed=parent_recorded,
        severity="ERROR" if not parent_recorded else "INFO",
        details=(
            "Parent move direction unavailable because strict range is invalid."
            if not parent_recorded
            else "Parent move direction provided by strict range result."
        ),
        file=__file__,
        function="detect_range_from_legs",
    )

