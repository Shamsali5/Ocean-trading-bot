"""Tests for deterministic supply/demand zone location detection."""

from __future__ import annotations

from ocean_engine.models.enums import Direction, DivergenceDirection, DivergenceGrade, ZoneStrength, ZoneType
from ocean_engine.models.market import (
    Candle,
    DivergenceAudit,
    DivergenceState,
    Leg,
    RangeState,
    StructureState,
    SupplyDemandZone,
)
from ocean_engine.zones.supply_demand_engine import (
    classify_zone_status,
    deduplicate_zones,
    detect_divergence_zones,
    detect_impulse_origin_zones,
    detect_range_edge_zones,
)


def _candle(close: float, idx: int) -> Candle:
    return Candle(
        open_time=idx * 60_000,
        open=close,
        high=close + 1.0,
        low=close - 1.0,
        close=close,
        volume=1.0,
        close_time=(idx + 1) * 60_000 - 1,
    )


def _structure_with_range(timeframe: str, lower: float, upper: float, current: float) -> StructureState:
    return StructureState(
        timeframe=timeframe,
        candles=[_candle(current, 0)],
        range_state=RangeState(
            timeframe=timeframe,
            active=True,
            lower_edge=lower,
            upper_edge=upper,
            midpoint=(lower + upper) / 2.0,
            is_range=True,
        ),
        current_price=current,
    )


def _leg(start: int, end: int, direction: Direction, low: float, high: float) -> Leg:
    return Leg(
        start_index=start,
        end_index=end,
        direction=direction,
        low=low,
        high=high,
        start_price=low if direction == Direction.UP else high,
        end_price=high if direction == Direction.UP else low,
        start_time=start,
        end_time=end,
        is_active=True,
    )


def test_range_upper_edge_creates_supply_zone() -> None:
    structures = {"1h": _structure_with_range("1h", lower=90.0, upper=110.0, current=100.0)}
    zones = detect_range_edge_zones(structures)
    supply = [zone for zone in zones if zone.zone_type == ZoneType.SUPPLY]
    assert supply
    assert supply[0].strength == ZoneStrength.STRONG
    assert supply[0].role == "range edge"


def test_range_lower_edge_creates_demand_zone() -> None:
    structures = {"5m": _structure_with_range("5m", lower=90.0, upper=110.0, current=100.0)}
    zones = detect_range_edge_zones(structures)
    demand = [zone for zone in zones if zone.zone_type == ZoneType.DEMAND]
    assert demand
    assert demand[0].strength == ZoneStrength.MODERATE
    assert demand[0].role == "range edge"


def test_bearish_divergence_creates_supply_zone() -> None:
    audit = DivergenceAudit(
        tf_15m=DivergenceState(
            timeframe="15m",
            exists=True,
            direction=DivergenceDirection.BEARISH,
            grade=DivergenceGrade.STRONG,
            price_zone="111.00-112.00",
        )
    )
    zones = detect_divergence_zones(audit)
    assert len(zones) == 1
    assert zones[0].zone_type == ZoneType.SUPPLY
    assert zones[0].role == "bearish divergence origin"


def test_bullish_divergence_creates_demand_zone() -> None:
    audit = DivergenceAudit(
        tf_5m=DivergenceState(
            timeframe="5m",
            exists=True,
            direction=DivergenceDirection.BULLISH,
            grade=DivergenceGrade.MODERATE,
            price_zone="88.50-89.00",
        )
    )
    zones = detect_divergence_zones(audit)
    assert len(zones) == 1
    assert zones[0].zone_type == ZoneType.DEMAND
    assert zones[0].role == "bullish divergence origin"


def test_active_up_leg_creates_demand_impulse_origin_zone() -> None:
    structure = StructureState(
        timeframe="15m",
        candles=[_candle(100.0, 0)],
        current_price=100.0,
        active_leg=_leg(0, 5, Direction.UP, low=90.0, high=110.0),
    )
    zones = detect_impulse_origin_zones({"15m": structure})
    assert len(zones) == 1
    assert zones[0].zone_type == ZoneType.DEMAND
    assert zones[0].role == "bullish impulse origin"


def test_active_down_leg_creates_supply_impulse_origin_zone() -> None:
    structure = StructureState(
        timeframe="1h",
        candles=[_candle(100.0, 0)],
        current_price=100.0,
        active_leg=_leg(0, 5, Direction.DOWN, low=92.0, high=114.0),
    )
    zones = detect_impulse_origin_zones({"1h": structure})
    assert len(zones) == 1
    assert zones[0].zone_type == ZoneType.SUPPLY
    assert zones[0].role == "bearish impulse origin"


def test_classify_zone_status_returns_reacting_when_price_inside_band() -> None:
    status = classify_zone_status(100.0, "99.50-100.50", [_candle(98.0, 0), _candle(99.0, 1)])
    assert status == "REACTING"


def test_classify_zone_status_returns_accepted_through_when_price_clearly_passes() -> None:
    candles = [_candle(100.0, 0), _candle(101.0, 1), _candle(109.0, 2), _candle(112.0, 3)]
    status = classify_zone_status(112.0, "99.00-100.00", candles)
    assert status == "ACCEPTED_THROUGH"


def test_deduplicate_keeps_stronger_overlapping_zone() -> None:
    weaker = SupplyDemandZone(
        timeframe="5m",
        zone_type=ZoneType.SUPPLY,
        lower=100.0,
        upper=101.0,
        strength=ZoneStrength.MODERATE,
        price_band="100.00-101.00",
        role="range edge",
    )
    stronger = SupplyDemandZone(
        timeframe="1h",
        zone_type=ZoneType.SUPPLY,
        lower=100.1,
        upper=101.1,
        strength=ZoneStrength.STRONG,
        price_band="100.10-101.10",
        role="bearish divergence origin",
    )
    zones = deduplicate_zones([weaker, stronger])
    assert len(zones) == 1
    assert zones[0].strength == ZoneStrength.STRONG
    assert zones[0].timeframe == "1h"


def test_zones_do_not_create_trade_decision_or_final_action() -> None:
    structures = {"1h": _structure_with_range("1h", lower=90.0, upper=110.0, current=100.0)}
    zones = detect_range_edge_zones(structures)
    for zone in zones:
        assert not hasattr(zone, "action")
        assert not hasattr(zone, "final_action")
