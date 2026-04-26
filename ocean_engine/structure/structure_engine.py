"""Coordinator that assembles swings, legs, and range into structure state."""

from __future__ import annotations

from ocean_engine.models.enums import MarketState
from ocean_engine.models.market import StructureState, TimeframeData
from ocean_engine.structure.leg_engine import detect_legs
from ocean_engine.structure.range_engine import detect_range_from_legs
from ocean_engine.structure.swing_engine import detect_swings


def analyze_structure(
    timeframe_data: TimeframeData,
    pivot_left: int = 2,
    pivot_right: int = 2,
    min_leg_bars: int = 5,
    min_move_pct: float = 0.001,
    range_min_legs: int = 3,
) -> StructureState:
    """Analyze one timeframe and return a complete StructureState snapshot."""

    candles = timeframe_data.candles
    current_price = candles[-1].close if candles else None

    swings = detect_swings(candles, pivot_left=pivot_left, pivot_right=pivot_right) if candles else []
    legs = detect_legs(
        candles,
        swings=swings,
        pivot_left=pivot_left,
        pivot_right=pivot_right,
        min_leg_bars=min_leg_bars,
        min_move_pct=min_move_pct,
    ) if candles else []

    active_leg = None
    if legs:
        flagged = [leg for leg in legs if getattr(leg, "is_active", False)]
        active_leg = flagged[-1] if flagged else legs[-1]

    range_state = None
    if current_price is not None:
        range_state = detect_range_from_legs(
            legs=legs,
            current_price=current_price,
            timeframe=timeframe_data.timeframe,
            min_legs=range_min_legs,
        )

    market_state = MarketState.UNCLEAR
    if range_state and range_state.active:
        if range_state.price_location == "OUTSIDE":
            market_state = MarketState.TRANSITION
        else:
            market_state = MarketState.RANGE
    elif active_leg is not None:
        market_state = MarketState.TREND

    summary = (
        f"Structure {timeframe_data.timeframe}: swings={len(swings)}, "
        f"legs={len(legs)}, state={market_state.value}"
    )

    return StructureState(
        timeframe=timeframe_data.timeframe,
        candles=list(candles),
        swings=swings,
        legs=legs,
        active_leg=active_leg,
        range_state=range_state,
        current_price=current_price,
        market_state=market_state,
        summary=summary,
    )


def analyze_all_structures(market_data: dict[str, TimeframeData]) -> dict[str, StructureState]:
    """Analyze all provided timeframes while preserving input keys."""

    return {timeframe: analyze_structure(data) for timeframe, data in market_data.items()}
