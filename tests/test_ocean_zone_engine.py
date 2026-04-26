"""Tests for strict standalone ocean zone engine."""

from __future__ import annotations

from ocean_zone_engine import ZoneResult, detect_supply_demand_zones, zone_allows_trade
from ocean_framework_v12_audit import FrameworkAuditTrace
from ocean_engine.models.enums import Direction, DivergenceDirection, DivergenceGrade
from ocean_engine.models.market import Candle, DivergenceAudit, DivergenceState, Leg, RangeState, StructureState


def _candle(close: float, idx: int) -> Candle:
    return Candle(
        open_time=idx * 60_000,
        open=close,
        high=close + 0.8,
        low=close - 0.8,
        close=close,
        volume=1.0,
        close_time=(idx + 1) * 60_000 - 1,
    )


def _structure(timeframe: str) -> StructureState:
    legs = [
        Leg(start_index=0, end_index=2, direction=Direction.DOWN, high=110.0, low=100.0),
        Leg(start_index=2, end_index=4, direction=Direction.UP, high=107.0, low=101.0),
    ]
    return StructureState(
        timeframe=timeframe,
        current_price=102.0,
        direction=Direction.UP,
        candles=[_candle(100.5, 0), _candle(101.0, 1), _candle(101.6, 2), _candle(102.0, 3)],
        legs=legs,
        active_leg=legs[-1],
        range_state=RangeState(
            timeframe=timeframe,
            is_range=True,
            active=True,
            lower_edge=100.0,
            upper_edge=110.0,
            breakout_direction=Direction.DOWN,
            status="RE_ENTERED",
        ),
    )


def test_detect_supply_demand_zones_emits_required_audit_checks() -> None:
    structures = {"15m": _structure("15m")}
    divergence_audit = DivergenceAudit(
        tf_15m=DivergenceState(
            timeframe="15m",
            exists=True,
            direction=DivergenceDirection.BULLISH,
            grade=DivergenceGrade.STRONG,
            price_zone="100.50-101.50",
        )
    )
    trace = FrameworkAuditTrace(symbol="BTCUSDT", timestamp="now")

    zones = detect_supply_demand_zones(
        context={"structures": structures, "divergence_audit": divergence_audit},
        candles_by_tf={"15m": structures["15m"].candles},
        trace=trace,
    )

    assert zones
    names = {check.name for check in trace.checks}
    assert "Supply/demand checked after structure" in names
    assert "Zone status classified" in names
    assert "Zone alignment classified" in names


def test_zone_allows_trade_rejects_demand_touch_only_without_confirmations() -> None:
    trace = FrameworkAuditTrace(symbol="BTCUSDT", timestamp="now")
    zone = ZoneResult(
        timeframe="15m",
        zone_type="DEMAND",
        price_low=100.0,
        price_high=101.0,
        strength="MODERATE",
        alignment="ALIGNED",
        structural_role="bullish impulse origin",
        status="REACTING",
        reason="demand touch",
    )

    allowed = zone_allows_trade(
        zone_result=zone,
        setup_result={"downside_weakening": False, "reclaim": False, "restart": False},
        impulse_result={"confirmed": False, "direction": "UP"},
        carry_result={"state": "ACTIVE", "direction": "UP", "finished": False},
        trace=trace,
    )

    assert allowed is False
    names = {check.name for check in trace.checks}
    assert "Zone alone cannot create trade" in names


def test_zone_allows_trade_rejects_supply_touch_only_without_confirmations() -> None:
    zone = ZoneResult(
        timeframe="15m",
        zone_type="SUPPLY",
        price_low=109.0,
        price_high=110.0,
        strength="MODERATE",
        alignment="ALIGNED",
        structural_role="bearish impulse origin",
        status="REACTING",
        reason="supply touch",
    )

    allowed = zone_allows_trade(
        zone_result=zone,
        setup_result={"upside_weakening": False, "rejection": False, "restart": False},
        impulse_result={"confirmed": False, "direction": "DOWN"},
        carry_result={"state": "ACTIVE", "direction": "DOWN", "finished": False},
        trace=None,
    )

    assert allowed is False

