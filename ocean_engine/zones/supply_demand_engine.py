"""Supply-demand zone location detection without trade permissions."""

from __future__ import annotations

from ocean_engine.models.enums import Direction, DivergenceDirection, ZoneAlignment, ZoneStrength, ZoneType
from ocean_engine.models.market import Candle, DivergenceAudit, StructureState, SupplyDemandZone

TIMEFRAME_STRENGTH = {"4h": ZoneStrength.STRONG, "1h": ZoneStrength.STRONG}
TIMEFRAME_PRIORITY = {"4h": 5, "1h": 4, "15m": 3, "5m": 2, "3m": 1}


def make_price_band(center_price: float, pct: float = 0.0015) -> str:
    """Create a symmetric price band around a center price."""

    width = abs(center_price) * pct
    lower = center_price - width
    upper = center_price + width
    return f"{lower:.2f}-{upper:.2f}"


def parse_price_band(band: str) -> tuple[float, float] | None:
    """Parse a string like ``77100-77300`` into a numeric tuple."""

    if "-" not in band:
        return None
    left, right = band.split("-", maxsplit=1)
    try:
        lower = float(left.strip())
        upper = float(right.strip())
    except ValueError:
        return None
    if lower > upper:
        lower, upper = upper, lower
    return (lower, upper)


def classify_zone_status(current_price: float, band: str, candles: list[Candle]) -> str:
    """Classify zone status with simple deterministic touch/through logic."""

    parsed = parse_price_band(band)
    if parsed is None:
        return "UNTESTED"
    lower, upper = parsed
    if lower <= current_price <= upper:
        return "REACTING"
    band_width = max(upper - lower, 1e-12)

    if current_price > upper and any(lower <= candle.close <= upper for candle in candles[:-1]):
        if (current_price - upper) >= (0.5 * band_width):
            return "ACCEPTED_THROUGH"
    if current_price < lower and any(lower <= candle.close <= upper for candle in candles[:-1]):
        if (lower - current_price) >= (0.5 * band_width):
            return "ACCEPTED_THROUGH"

    closes = [candle.close for candle in candles]
    if len(closes) >= 2:
        if closes[-2] <= upper and closes[-1] > upper and any(candle.close <= upper for candle in candles[:-1]):
            return "ACCEPTED_THROUGH"
        if closes[-2] >= lower and closes[-1] < lower and any(candle.close >= lower for candle in candles[:-1]):
            return "ACCEPTED_THROUGH"

    if current_price > upper and any(candle.close < lower for candle in candles):
        return "ACCEPTED_THROUGH"
    if current_price < lower and any(candle.close > upper for candle in candles):
        return "ACCEPTED_THROUGH"

    touched_before = any(
        max(candle.low, lower) <= min(candle.high, upper) for candle in candles[:-1]
    )
    if touched_before:
        return "TESTED"
    return "UNTESTED"


def detect_range_edge_zones(structures: dict[str, StructureState]) -> list[SupplyDemandZone]:
    """Detect supply/demand zones from active range edges only."""

    zones: list[SupplyDemandZone] = []
    for timeframe, structure in structures.items():
        range_state = structure.range_state
        if range_state is None or not range_state.active:
            continue
        if range_state.upper_edge is None or range_state.lower_edge is None:
            continue
        strength = TIMEFRAME_STRENGTH.get(timeframe, ZoneStrength.MODERATE)
        current_price = structure.current_price if structure.current_price is not None else 0.0
        candles = structure.candles

        upper_band = make_price_band(range_state.upper_edge, pct=0.0015)
        lower_band = make_price_band(range_state.lower_edge, pct=0.0015)
        zones.append(
            SupplyDemandZone(
                timeframe=timeframe,
                zone_type=ZoneType.SUPPLY,
                lower=range_state.upper_edge,
                upper=range_state.upper_edge,
                price_band=upper_band,
                strength=strength,
                alignment=ZoneAlignment.NEUTRAL,
                role="range edge",
                status=classify_zone_status(current_price, upper_band, candles),
                summary=f"{timeframe} range upper edge supply",
            )
        )
        zones.append(
            SupplyDemandZone(
                timeframe=timeframe,
                zone_type=ZoneType.DEMAND,
                lower=range_state.lower_edge,
                upper=range_state.lower_edge,
                price_band=lower_band,
                strength=strength,
                alignment=ZoneAlignment.NEUTRAL,
                role="range edge",
                status=classify_zone_status(current_price, lower_band, candles),
                summary=f"{timeframe} range lower edge demand",
            )
        )
    return zones


def detect_divergence_zones(divergence_audit: DivergenceAudit) -> list[SupplyDemandZone]:
    """Detect divergence-origin zones from official divergence rows."""

    zones: list[SupplyDemandZone] = []
    for field_name, timeframe in (
        ("tf_4h", "4h"),
        ("tf_1h", "1h"),
        ("tf_15m", "15m"),
        ("tf_5m", "5m"),
        ("tf_3m", "3m"),
    ):
        state = getattr(divergence_audit, field_name)
        if not state.exists:
            continue
        strength = TIMEFRAME_STRENGTH.get(timeframe, ZoneStrength.MODERATE)
        band = state.price_zone or ""
        if not band:
            continue

        if state.direction == DivergenceDirection.BEARISH:
            zone_type = ZoneType.SUPPLY
            role = "bearish divergence origin"
        elif state.direction == DivergenceDirection.BULLISH:
            zone_type = ZoneType.DEMAND
            role = "bullish divergence origin"
        else:
            continue
        parsed = parse_price_band(band)
        if parsed is None:
            continue
        lower, upper = parsed
        zones.append(
            SupplyDemandZone(
                timeframe=timeframe,
                zone_type=zone_type,
                lower=lower,
                upper=upper,
                price_band=band,
                strength=strength,
                alignment=ZoneAlignment.NEUTRAL,
                role=role,
                status="UNTESTED",
                summary=f"{timeframe} {role}",
            )
        )
    return zones


def detect_impulse_origin_zones(structures: dict[str, StructureState]) -> list[SupplyDemandZone]:
    """Detect zones around active leg origin points."""

    zones: list[SupplyDemandZone] = []
    for timeframe, structure in structures.items():
        active_leg = structure.active_leg
        if active_leg is None or active_leg.start_price is None:
            continue
        strength = TIMEFRAME_STRENGTH.get(timeframe, ZoneStrength.MODERATE)
        start_price = active_leg.start_price
        band = make_price_band(start_price, pct=0.0015)
        parsed = parse_price_band(band)
        if parsed is None:
            continue
        lower, upper = parsed

        if active_leg.direction == Direction.UP:
            zone_type = ZoneType.DEMAND
            role = "bullish impulse origin"
            alignment = ZoneAlignment.ALIGNED
        elif active_leg.direction == Direction.DOWN:
            zone_type = ZoneType.SUPPLY
            role = "bearish impulse origin"
            alignment = ZoneAlignment.ALIGNED
        else:
            continue

        current_price = structure.current_price if structure.current_price is not None else start_price
        status = classify_zone_status(current_price, band, structure.candles)
        zones.append(
            SupplyDemandZone(
                timeframe=timeframe,
                zone_type=zone_type,
                lower=lower,
                upper=upper,
                price_band=band,
                strength=strength,
                alignment=alignment,
                role=role,
                status=status,
                summary=f"{timeframe} {role}",
            )
        )
    return zones


def detect_supply_demand_zones(
    structures: dict[str, StructureState],
    divergence_audit: DivergenceAudit,
) -> list[SupplyDemandZone]:
    """Aggregate range, divergence, and impulse zones and deduplicate."""

    zones: list[SupplyDemandZone] = []
    zones.extend(detect_range_edge_zones(structures))
    zones.extend(detect_divergence_zones(divergence_audit))
    zones.extend(detect_impulse_origin_zones(structures))
    return deduplicate_zones(zones)


def deduplicate_zones(zones: list[SupplyDemandZone]) -> list[SupplyDemandZone]:
    """Deduplicate heavily-overlapping zones by strength/timeframe priority."""

    kept: list[SupplyDemandZone] = []
    for zone in zones:
        replaced = False
        for idx, existing in enumerate(kept):
            if zone.zone_type != existing.zone_type:
                continue
            if not _bands_overlap_heavily(zone.price_band, existing.price_band):
                continue
            if _zone_rank(zone) > _zone_rank(existing):
                kept[idx] = zone
            replaced = True
            break
        if not replaced:
            kept.append(zone)
    return kept


def is_tradeable_reaction_zone(zone: SupplyDemandZone, structure: StructureState | None) -> bool:
    """Return whether a zone can be considered for reaction-trade confirmation."""

    if structure is None:
        return False
    if zone.status in {"ACCEPTED_THROUGH", "UNTESTED"}:
        return False
    if zone.zone_type not in {ZoneType.DEMAND, ZoneType.SUPPLY}:
        return False

    range_state = structure.range_state
    if range_state is not None and str(range_state.price_location).upper() == "MID":
        return False

    parsed = parse_price_band(zone.price_band)
    if parsed is None:
        return False
    current_price = structure.current_price
    if current_price is None:
        return False
    lower, upper = parsed
    return lower <= current_price <= upper


def _zone_rank(zone: SupplyDemandZone) -> tuple[int, int]:
    strength_score = {
        ZoneStrength.STRONG: 3,
        ZoneStrength.MODERATE: 2,
        ZoneStrength.WEAK: 1,
    }[zone.strength]
    tf_score = TIMEFRAME_PRIORITY.get(zone.timeframe, 0)
    return (strength_score, tf_score)


def _bands_overlap_heavily(left_band: str, right_band: str) -> bool:
    left = parse_price_band(left_band)
    right = parse_price_band(right_band)
    if left is None or right is None:
        return False
    left_low, left_high = left
    right_low, right_high = right
    overlap = min(left_high, right_high) - max(left_low, right_low)
    if overlap <= 0.0:
        return False
    smaller_width = min(left_high - left_low, right_high - right_low)
    if smaller_width <= 0.0:
        return False
    return (overlap / smaller_width) >= 0.6
