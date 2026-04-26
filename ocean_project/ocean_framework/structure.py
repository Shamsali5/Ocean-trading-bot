from __future__ import annotations

from dataclasses import dataclass

from .types import Candle, TimeframeAnalysis
from .vacc import vacc_series


@dataclass(frozen=True)
class SwingPoint:
    index: int
    price: float
    kind: str


def find_swings(candles: list[Candle], window: int = 2) -> list[SwingPoint]:
    swings: list[SwingPoint] = []
    if len(candles) < window * 2 + 1:
        return swings

    for idx in range(window, len(candles) - window):
        current = candles[idx]
        left = candles[idx - window : idx]
        right = candles[idx + 1 : idx + window + 1]
        if all(current.high > c.high for c in left + right):
            swings.append(SwingPoint(idx, current.high, "HIGH"))
        if all(current.low < c.low for c in left + right):
            swings.append(SwingPoint(idx, current.low, "LOW"))
    return swings


def classify_direction(candles: list[Candle], lookback: int = 60) -> str:
    sample = candles[-lookback:] if len(candles) > lookback else candles
    if len(sample) < 2:
        return "UNCLEAR"

    first = sample[0].close
    last = sample[-1].close
    change_pct = (last - first) / first if first else 0.0
    highs = [c.high for c in sample]
    lows = [c.low for c in sample]
    width_pct = (max(highs) - min(lows)) / last if last else 0.0

    if abs(change_pct) < 0.006 and width_pct < 0.035:
        return "RANGE"
    if change_pct > 0.003:
        return "UP"
    if change_pct < -0.003:
        return "DOWN"
    return "UNCLEAR"


def detect_range_state(timeframe: str, candles: list[Candle]) -> dict[str, str]:
    sample = candles[-80:] if len(candles) > 80 else candles
    if not sample:
        return {
            "active": "UNCLEAR",
            "timeframe": timeframe,
            "upper_edge": "N/A",
            "lower_edge": "N/A",
            "midpoint": "N/A",
            "price_location": "UNCLEAR",
            "parent_ownership": "UNCLEAR",
            "status": "UNCLEAR",
            "summary": "No candles available for range state.",
        }

    upper = max(c.high for c in sample)
    lower = min(c.low for c in sample)
    current = sample[-1].close
    midpoint = (upper + lower) / 2
    width_pct = (upper - lower) / current if current else 0.0
    active = "YES" if width_pct < 0.045 else "NO"

    if current >= upper - (upper - lower) * 0.25:
        location = "UPPER_EDGE"
    elif current <= lower + (upper - lower) * 0.25:
        location = "LOWER_EDGE"
    elif lower <= current <= upper:
        location = "MID"
    else:
        location = "OUTSIDE"

    owner_direction = classify_direction(sample, lookback=min(80, len(sample)))
    ownership = "BULLISH" if owner_direction == "UP" else "BEARISH" if owner_direction == "DOWN" else "NEUTRAL"
    return {
        "active": active,
        "timeframe": timeframe,
        "upper_edge": f"{upper:,.2f}",
        "lower_edge": f"{lower:,.2f}",
        "midpoint": f"{midpoint:,.2f}",
        "price_location": location,
        "parent_ownership": ownership,
        "status": "ACTIVE" if active == "YES" else "NONE",
        "summary": f"{timeframe} range {'active' if active == 'YES' else 'not active'}; price is near {location.lower().replace('_', ' ')}.",
    }


def _price_band(value: float, width: float) -> str:
    return f"{value - width:,.2f}-{value + width:,.2f}"


def detect_zones(timeframe: str, candles: list[Candle], direction: str) -> list[dict[str, str]]:
    sample = candles[-80:] if len(candles) > 80 else candles
    if len(sample) < 10:
        return []

    current = sample[-1].close
    width = max(current * 0.0025, 0.01)
    low = min(sample, key=lambda c: c.low)
    high = max(sample, key=lambda c: c.high)
    demand_alignment = "ALIGNED" if direction == "UP" else "COUNTER" if direction == "DOWN" else "NEUTRAL"
    supply_alignment = "ALIGNED" if direction == "DOWN" else "COUNTER" if direction == "UP" else "NEUTRAL"
    return [
        {
            "timeframe": timeframe,
            "type": "DEMAND",
            "price_band": _price_band(low.low, width),
            "strength": "MODERATE",
            "alignment": demand_alignment,
            "role": "Recent structural low reaction area.",
            "status": "TESTED" if current <= low.low + width * 3 else "UNTESTED",
        },
        {
            "timeframe": timeframe,
            "type": "SUPPLY",
            "price_band": _price_band(high.high, width),
            "strength": "MODERATE",
            "alignment": supply_alignment,
            "role": "Recent structural high reaction area.",
            "status": "TESTED" if current >= high.high - width * 3 else "UNTESTED",
        },
    ]


def detect_abc_divergence(timeframe: str, candles: list[Candle]) -> dict[str, str]:
    swings = find_swings(candles)
    vacc = vacc_series(candles)
    default = {
        "exists": "NO",
        "timeframe": timeframe,
        "direction": "NONE",
        "abc_valid": "NO",
        "segment_b_reset_valid": "UNCLEAR",
        "segment_c_completed": "UNCLEAR",
        "new_high_low_or_retest": "UNCLEAR",
        "vacc_confirmation": "NONE",
        "impulse_confirmed": "NO",
        "grade": "INVALID",
        "role": "NONE",
        "price_zone": "N/A",
        "summary": f"No official {timeframe} divergence confirmed.",
    }
    if len(swings) < 3 or len(vacc["velocity"]) < len(candles):
        return default

    for a, b, c in zip(swings[-8:], swings[-7:], swings[-6:]):
        if not (a.index < b.index < c.index):
            continue
        if a.kind == "HIGH" and b.kind == "LOW" and c.kind == "HIGH":
            row = _build_divergence_row(timeframe, "BEARISH", a, b, c, candles, vacc)
            if row["exists"] == "YES":
                return row
        if a.kind == "LOW" and b.kind == "HIGH" and c.kind == "LOW":
            row = _build_divergence_row(timeframe, "BULLISH", a, b, c, candles, vacc)
            if row["exists"] == "YES":
                return row
    return default


def _build_divergence_row(
    timeframe: str,
    direction: str,
    a: SwingPoint,
    b: SwingPoint,
    c: SwingPoint,
    candles: list[Candle],
    vacc: dict[str, list[float]],
) -> dict[str, str]:
    a_velocity = vacc["velocity"][a.index]
    b_velocity = vacc["velocity"][b.index]
    c_velocity = vacc["velocity"][c.index]
    a_energy = abs(a_velocity) + abs(vacc["acceleration"][a.index]) + abs(vacc["acceleration_area"][a.index])
    c_energy = abs(c_velocity) + abs(vacc["acceleration"][c.index]) + abs(vacc["acceleration_area"][c.index])
    reset_valid = abs(b_velocity) <= max(abs(a_velocity), abs(c_velocity)) * 0.65
    c_retest = c.price >= a.price * 0.998 if direction == "BEARISH" else c.price <= a.price * 1.002
    energy_weaker = c_energy < a_energy * 0.9
    impulse = _opposite_impulse(direction, c.index, candles)
    official = reset_valid and c_retest and energy_weaker and impulse
    zone_low = min(a.price, c.price)
    zone_high = max(a.price, c.price)

    return {
        "exists": "YES" if official else "NO",
        "timeframe": timeframe,
        "direction": direction if official else "NONE",
        "abc_valid": "YES" if reset_valid and c_retest else "NO",
        "segment_b_reset_valid": "YES" if reset_valid else "NO",
        "segment_c_completed": "YES" if c.index < len(candles) - 1 else "UNCLEAR",
        "new_high_low_or_retest": "YES" if c_retest else "NO",
        "vacc_confirmation": "MULTI" if energy_weaker else "NONE",
        "impulse_confirmed": "YES" if impulse else "NO",
        "grade": "STRONG" if official else "INVALID",
        "role": "ORIGIN" if official else "NONE",
        "price_zone": f"{zone_low:,.2f}-{zone_high:,.2f}" if official else "N/A",
        "summary": (
            f"{timeframe} {direction.lower()} A-B-C divergence confirmed by weaker VAcc and opposite impulse."
            if official
            else f"No official {timeframe} divergence confirmed."
        ),
    }


def _opposite_impulse(direction: str, start_index: int, candles: list[Candle], lookahead: int = 5) -> bool:
    after = candles[start_index + 1 : start_index + 1 + lookahead]
    if not after:
        return False
    recent = candles[max(0, start_index - 10) : start_index + 1]
    avg_body = sum(abs(c.close - c.open) for c in recent) / len(recent) if recent else 0.0
    for candle in after:
        body = candle.close - candle.open
        if direction == "BEARISH" and body < 0 and abs(body) > avg_body * 1.15:
            return True
        if direction == "BULLISH" and body > 0 and abs(body) > avg_body * 1.15:
            return True
    return False


def analyze_timeframe(timeframe: str, candles: list[Candle]) -> TimeframeAnalysis:
    direction = classify_direction(candles)
    vacc = vacc_series(candles)
    divergence = detect_abc_divergence(timeframe, candles)
    return TimeframeAnalysis(
        timeframe=timeframe,
        candles=candles,
        direction=direction,
        state="RANGE" if direction == "RANGE" else "TREND" if direction in {"UP", "DOWN"} else "UNCLEAR",
        velocity=vacc["velocity"],
        acceleration=vacc["acceleration"],
        acceleration_area=vacc["acceleration_area"],
        divergence=divergence,
        range_state=detect_range_state(timeframe, candles),
        zones=detect_zones(timeframe, candles, direction),
    )


def build_timeframe_analysis(timeframe: str, candles: list[Candle]) -> TimeframeAnalysis:
    return analyze_timeframe(timeframe, candles)
