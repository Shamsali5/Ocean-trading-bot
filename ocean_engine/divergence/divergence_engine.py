"""Divergence confirmation from A-B-C structure plus VAcc weakening."""

from __future__ import annotations

from datetime import datetime, timezone

from ocean_abc_validator import ABCValidationResult
from ocean_engine.energy.vacc_engine import (
    get_segment_acceleration_area,
    get_segment_velocity_energy,
    has_zero_axis_reset,
)
from ocean_engine.models.enums import Direction, DivergenceDirection, DivergenceGrade
from ocean_engine.models.market import ABCStructure, Candle, DivergenceState, VAccSeries


def compare_segment_energy(abc: ABCStructure, vacc_series: VAccSeries) -> dict[str, bool | int]:
    """Compare A vs C segment energy and count weakening signals."""

    if not abc.abc_valid or abc.segment_a is None or abc.segment_b is None or abc.segment_c is None:
        return {
            "velocity_weaker": False,
            "acceleration_area_weaker": False,
            "zero_axis_reset": False,
            "weakening_count": 0,
        }

    if abc.direction == DivergenceDirection.BEARISH:
        energy_direction = Direction.UP
    elif abc.direction == DivergenceDirection.BULLISH:
        energy_direction = Direction.DOWN
    else:
        return {
            "velocity_weaker": False,
            "acceleration_area_weaker": False,
            "zero_axis_reset": False,
            "weakening_count": 0,
        }

    a_velocity = get_segment_velocity_energy(
        vacc_series=vacc_series,
        start_index=abc.segment_a.start_index,
        end_index=abc.segment_a.end_index,
        direction=energy_direction,
    )
    c_velocity = get_segment_velocity_energy(
        vacc_series=vacc_series,
        start_index=abc.segment_c.start_index,
        end_index=abc.segment_c.end_index,
        direction=energy_direction,
    )
    velocity_weaker = c_velocity < a_velocity

    a_acc_area = get_segment_acceleration_area(
        vacc_series=vacc_series,
        start_index=abc.segment_a.start_index,
        end_index=abc.segment_a.end_index,
        direction=energy_direction,
    )
    c_acc_area = get_segment_acceleration_area(
        vacc_series=vacc_series,
        start_index=abc.segment_c.start_index,
        end_index=abc.segment_c.end_index,
        direction=energy_direction,
    )
    acceleration_area_weaker = c_acc_area < a_acc_area

    zero_axis_reset = has_zero_axis_reset(
        vacc_series=vacc_series,
        start_index=abc.segment_b.start_index,
        end_index=abc.segment_b.end_index,
        tolerance=0.0,
    )

    weakening_count = sum((velocity_weaker, acceleration_area_weaker, zero_axis_reset))
    return {
        "velocity_weaker": velocity_weaker,
        "acceleration_area_weaker": acceleration_area_weaker,
        "zero_axis_reset": zero_axis_reset,
        "weakening_count": weakening_count,
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
) -> DivergenceState:
    """Convert an A-B-C candidate into official divergence state."""

    if not abc.abc_valid:
        return DivergenceState(
            timeframe=abc.timeframe,
            exists=False,
            abc_valid=False,
            direction=DivergenceDirection.NONE,
            grade=DivergenceGrade.INVALID,
            notes="A-B-C candidate is invalid.",
        )
    if abc_validation is not None and not abc_validation.valid:
        return DivergenceState(
            timeframe=abc.timeframe,
            exists=False,
            abc_valid=False,
            direction=DivergenceDirection.NONE,
            grade=DivergenceGrade.INVALID,
            notes=f"A-B-C validator rejected candidate: {abc_validation.reason}",
        )

    energy = compare_segment_energy(abc=abc, vacc_series=vacc_series)
    weakening_count = int(energy["weakening_count"])
    impulse_confirmed, impulse_price, impulse_time = detect_opposite_impulse_details(candles=candles, abc=abc)
    grade = grade_divergence(
        abc_valid=abc.abc_valid,
        weakening_count=weakening_count,
        impulse_confirmed=impulse_confirmed,
    )
    exists = bool(abc.abc_valid and weakening_count >= 1 and impulse_confirmed)

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

    return DivergenceState(
        timeframe=abc.timeframe,
        exists=exists,
        abc_valid=abc.abc_valid,
        direction=abc.direction,
        grade=grade,
        weakening_count=weakening_count,
        impulse_confirmed=impulse_confirmed,
        price_zone=zone_text,
        divergence_price=divergence_price,
        divergence_time_utc=divergence_time_utc,
        impulse_price=impulse_price,
        impulse_time_utc=_close_time_to_utc(impulse_time),
        notes=(
            f"abc_valid={abc.abc_valid}, weakening={weakening_count}, "
            f"impulse={impulse_confirmed}, velocity_weaker={energy['velocity_weaker']}, "
            f"acc_area_weaker={energy['acceleration_area_weaker']}, zero_reset={energy['zero_axis_reset']}"
        ),
    )


def _close_time_to_utc(close_time: int | None) -> str:
    """Convert millisecond epoch close time into UTC ISO string."""

    if close_time is None:
        return ""
    return datetime.fromtimestamp(close_time / 1000.0, tz=timezone.utc).isoformat()
