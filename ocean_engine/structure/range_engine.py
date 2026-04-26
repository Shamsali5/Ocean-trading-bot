"""Range (Zhongshu) detection from same-timeframe legs."""

from __future__ import annotations

from ocean_engine.models.market import Leg, RangeState


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


def detect_range_from_legs(
    legs: list[Leg],
    current_price: float,
    timeframe: str = "",
    min_legs: int = 3,
    max_legs: int = 8,
) -> RangeState:
    """Detect the most recent valid overlapping range window."""

    if min_legs < 3:
        raise ValueError("min_legs must be >= 3")
    if max_legs < min_legs:
        raise ValueError("max_legs must be >= min_legs")

    if len(legs) < min_legs:
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
        return RangeState(
            timeframe=timeframe,
            is_range=False,
            active=False,
            price_location="UNCLEAR",
            leg_count=0,
            summary="No overlapping leg window found.",
        )

    overlap = calculate_leg_overlap(best_window)
    if overlap is None:
        return RangeState(
            timeframe=timeframe,
            is_range=False,
            active=False,
            price_location="UNCLEAR",
            leg_count=0,
            summary="No overlapping leg window found.",
        )
    pivot_low, pivot_high = overlap
    outer_lower_edge = min(leg.low for leg in best_window)
    outer_upper_edge = max(leg.high for leg in best_window)
    midpoint = (outer_upper_edge + outer_lower_edge) / 2.0
    price_location = classify_price_location(
        current_price=current_price,
        lower_edge=outer_lower_edge,
        upper_edge=outer_upper_edge,
    )

    return RangeState(
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
        summary=(
            f"Range detected with {len(best_window)} legs, "
            f"ZD={pivot_low:.6f}, ZG={pivot_high:.6f}."
        ),
    )
