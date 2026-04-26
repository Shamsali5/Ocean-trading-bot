"""Tests for active trade candidate audit and selection."""

from __future__ import annotations

from ocean_engine.models.enums import CarryState, Direction, DivergenceDirection, DivergenceGrade, SetupType, TradeFunction, ZoneType
from ocean_engine.models.market import (
    ActiveTradeAudit,
    ActiveTradeCandidate,
    CarryStatus,
    Candle,
    DivergenceAudit,
    DivergenceState,
    Leg,
    RangeState,
    StructureState,
    SupplyDemandZone,
)
from ocean_engine.trade.active_trade_engine import (
    active_trade_audit_summary,
    build_active_trade_audit,
    build_type1_candidate,
    detect_range_rejection_candidate,
    detect_type2_candidate,
    detect_type3_candidate,
    detect_upgrade_candidate,
    detect_zone_reaction_candidate,
    select_active_trade,
)
from ocean_framework_v12_audit import FrameworkAuditTrace


def _structure(timeframe: str) -> StructureState:
    return StructureState(timeframe=timeframe, legs=[])


def _type3_structure(
    timeframe: str,
    *,
    status: str,
    breakout_direction: Direction,
    current_price: float,
    upper_edge: float = 100.0,
    lower_edge: float = 90.0,
    accepted_close: float = 100.5,
) -> StructureState:
    return StructureState(
        timeframe=timeframe,
        current_price=current_price,
        active_leg=Leg(
            start_index=0,
            end_index=3,
            direction=breakout_direction,
            high=max(current_price, upper_edge),
            low=min(current_price, lower_edge),
            is_active=True,
        ),
        legs=[
            Leg(start_index=0, end_index=1, direction=Direction.UP, high=upper_edge, low=lower_edge),
            Leg(start_index=1, end_index=2, direction=Direction.DOWN, high=upper_edge + 0.2, low=lower_edge - 0.2),
            Leg(start_index=2, end_index=3, direction=breakout_direction, high=upper_edge + 0.6, low=lower_edge - 0.6),
        ],
        range_state=RangeState(
            timeframe=timeframe,
            is_range=True,
            active=True,
            upper_edge=upper_edge,
            lower_edge=lower_edge,
            status=status,
            breakout_direction=breakout_direction,
            breakout_level=upper_edge if breakout_direction == Direction.UP else lower_edge,
            breakout_confirmed=True,
            acceptance_confirmed=True,
            first_accepted_close=accepted_close,
        ),
    )


def _type2_structure(
    timeframe: str,
    *,
    prior_direction: Direction,
    continuation_ok: bool = True,
    pullback_breaks_origin: bool = False,
) -> StructureState:
    if prior_direction == Direction.UP:
        impulse = Leg(start_index=0, end_index=3, direction=Direction.UP, high=112.0, low=100.0)
        if pullback_breaks_origin:
            pullback = Leg(start_index=3, end_index=5, direction=Direction.DOWN, high=111.0, low=98.0)
        else:
            pullback = Leg(start_index=3, end_index=5, direction=Direction.DOWN, high=111.0, low=102.0)
        continuation = (
            Leg(start_index=5, end_index=7, direction=Direction.UP, high=113.5, low=103.0)
            if continuation_ok
            else Leg(start_index=5, end_index=7, direction=Direction.DOWN, high=110.0, low=101.0)
        )
    else:
        impulse = Leg(start_index=0, end_index=3, direction=Direction.DOWN, high=112.0, low=100.0)
        if pullback_breaks_origin:
            pullback = Leg(start_index=3, end_index=5, direction=Direction.UP, high=114.0, low=101.0)
        else:
            pullback = Leg(start_index=3, end_index=5, direction=Direction.UP, high=110.0, low=101.0)
        continuation = (
            Leg(start_index=5, end_index=7, direction=Direction.DOWN, high=109.0, low=99.0)
            if continuation_ok
            else Leg(start_index=5, end_index=7, direction=Direction.UP, high=111.0, low=102.0)
        )
    continuation_direction = continuation.direction
    return StructureState(
        timeframe=timeframe,
        legs=[impulse, pullback, continuation],
        active_leg=Leg(
            start_index=continuation.start_index,
            end_index=continuation.end_index,
            direction=continuation_direction,
            high=continuation.high,
            low=continuation.low,
            is_active=True,
        ),
        current_price=(continuation.high if continuation_direction == Direction.UP else continuation.low),
    )


def _official_divergence(timeframe: str, direction: DivergenceDirection, zone: str = "100.00-101.00") -> DivergenceState:
    return DivergenceState(
        timeframe=timeframe,
        exists=True,
        direction=direction,
        abc_valid=True,
        grade=DivergenceGrade.STRONG,
        impulse_confirmed=True,
        price_zone=zone,
        notes="abc_valid=True",
    )


def _zone(zone_type: ZoneType, lower: float, upper: float, *, status: str = "REACTING", role: str = "impulse origin") -> SupplyDemandZone:
    return SupplyDemandZone(
        timeframe="15m",
        zone_type=zone_type,
        lower=lower,
        upper=upper,
        status=status,
        role=role,
        price_band=f"{lower:.2f}-{upper:.2f}",
    )


def _candles(closes: list[float]) -> list[Candle]:
    candles: list[Candle] = []
    for idx, close in enumerate(closes):
        candles.append(
            Candle(
                open_time=idx,
                open=close,
                high=close + 0.4,
                low=close - 0.4,
                close=close,
                volume=1.0,
                close_time=idx,
            )
        )
    return candles


def _carry_status(state: CarryState, finished: bool = False) -> CarryStatus:
    return CarryStatus(
        timeframe="x",
        direction=Direction.UP,
        state=state,
        finished=finished,
    )


def test_15m_official_divergence_creates_15m_type1_candidate(monkeypatch) -> None:
    structures = {"15m": _structure("15m"), "5m": _structure("5m")}
    divergence_audit = DivergenceAudit(tf_15m=_official_divergence("15m", DivergenceDirection.BULLISH))
    monkeypatch.setattr(
        "ocean_engine.trade.active_trade_engine.build_carry_status",
        lambda *args, **kwargs: _carry_status(CarryState.FRESH, finished=False),
    )
    candidate = build_type1_candidate("15m", divergence_audit.tf_15m, structures, divergence_audit)
    assert candidate.exists is True
    assert candidate.origin_timeframe == "15m"
    assert candidate.setup_type == SetupType.TYPE_1
    assert candidate.type_label == "15m Bullish Type 1"


def test_15m_candidate_uses_5m_carry_timeframe(monkeypatch) -> None:
    structures = {"15m": _structure("15m"), "5m": _structure("5m")}
    divergence_audit = DivergenceAudit(tf_15m=_official_divergence("15m", DivergenceDirection.BULLISH))
    monkeypatch.setattr(
        "ocean_engine.trade.active_trade_engine.build_carry_status",
        lambda *args, **kwargs: CarryStatus(timeframe="5m", direction=Direction.UP, state=CarryState.FRESH, finished=False),
    )
    candidate = build_type1_candidate("15m", divergence_audit.tf_15m, structures, divergence_audit)
    assert candidate.carry_timeframe == "5m"


def test_1h_official_divergence_creates_1h_type1_candidate(monkeypatch) -> None:
    structures = {"1h": _structure("1h"), "15m": _structure("15m")}
    divergence_audit = DivergenceAudit(tf_1h=_official_divergence("1h", DivergenceDirection.BEARISH))
    monkeypatch.setattr(
        "ocean_engine.trade.active_trade_engine.build_carry_status",
        lambda *args, **kwargs: CarryStatus(timeframe="15m", direction=Direction.DOWN, state=CarryState.ACTIVE, finished=False),
    )
    candidate = build_type1_candidate("1h", divergence_audit.tf_1h, structures, divergence_audit)
    assert candidate.exists is True
    assert candidate.origin_timeframe == "1h"
    assert candidate.type_label == "1H Bearish Type 1"


def test_bullish_range_breakout_creates_bullish_type3_candidate() -> None:
    structures = {"15m": _type3_structure("15m", status="BROKEN_UP", breakout_direction=Direction.UP, current_price=101.6)}
    structures["15m"].candles = [
        Candle(open_time=0, open=99.8, high=100.2, low=99.6, close=99.9, volume=1.0, close_time=1000),
        Candle(open_time=1, open=100.0, high=101.0, low=99.9, close=100.7, volume=1.0, close_time=2000),
        Candle(open_time=2, open=100.7, high=101.8, low=100.5, close=101.6, volume=1.0, close_time=3000),
    ]
    structures["15m"].range_state.first_break_index = 2
    candidate = detect_type3_candidate(timeframe="15m", structures=structures)
    assert candidate.exists is True
    assert candidate.setup_type == SetupType.TYPE_3
    assert candidate.direction == DivergenceDirection.BULLISH
    assert candidate.type_label == "15m Bullish Type 3"
    assert candidate.trade_function == TradeFunction.BREAKOUT
    assert candidate.confirmation_price == 100.5
    assert candidate.confirmation_time_utc == "1970-01-01T00:00:03+00:00"


def test_type1_candidate_uses_divergence_event_price_time_as_start() -> None:
    structures = {"15m": _structure("15m"), "5m": _structure("5m")}
    divergence = DivergenceState(
        timeframe="15m",
        exists=True,
        abc_valid=True,
        direction=DivergenceDirection.BULLISH,
        grade=DivergenceGrade.STRONG,
        impulse_confirmed=True,
        divergence_price=100.2,
        divergence_time_utc="2026-04-26T10:00:00Z",
        impulse_price=101.4,
        impulse_time_utc="2026-04-26T10:03:00Z",
    )
    divergence_audit = DivergenceAudit(tf_15m=divergence)
    candidate = build_type1_candidate("15m", divergence, structures, divergence_audit)
    assert candidate.exists is True
    assert candidate.confirmation_price == 101.4
    assert candidate.confirmation_time_utc == "2026-04-26T10:03:00Z"


def test_bearish_range_breakdown_creates_bearish_type3_candidate() -> None:
    structures = {"15m": _type3_structure("15m", status="BROKEN_DOWN", breakout_direction=Direction.DOWN, current_price=88.2)}
    candidate = detect_type3_candidate(timeframe="15m", structures=structures)
    assert candidate.exists is True
    assert candidate.setup_type == SetupType.TYPE_3
    assert candidate.direction == DivergenceDirection.BEARISH
    assert candidate.type_label == "15m Bearish Type 3"


def test_type3_does_not_require_divergence() -> None:
    structures = {"15m": _type3_structure("15m", status="BROKEN_UP", breakout_direction=Direction.UP, current_price=101.2)}
    audit = build_active_trade_audit(structures, DivergenceAudit())
    assert audit.tf_15m.exists is True
    assert audit.tf_15m.setup_type == SetupType.TYPE_3


def test_type3_rejected_when_breakout_has_immediate_reclaim() -> None:
    structure = _type3_structure("15m", status="BROKEN_UP", breakout_direction=Direction.UP, current_price=99.8)
    structure.range_state.acceptance_confirmed = False
    structure.range_state.retest_held = False
    structure.range_state.first_break_index = 1
    structure.candles = [
        Candle(open_time=0, open=99.5, high=99.8, low=99.2, close=99.7, volume=1.0, close_time=1000),
        Candle(open_time=1, open=99.7, high=100.5, low=99.6, close=100.3, volume=1.0, close_time=2000),
        Candle(open_time=2, open=100.3, high=100.4, low=99.7, close=99.8, volume=1.0, close_time=3000),
        Candle(open_time=3, open=99.8, high=100.0, low=99.5, close=99.9, volume=1.0, close_time=4000),
    ]
    candidate = detect_type3_candidate(timeframe="15m", structures={"15m": structure})
    assert candidate.exists is False


def test_bullish_type2_after_bullish_type1() -> None:
    structures = {
        "15m": _type2_structure("15m", prior_direction=Direction.UP),
        "5m": _type3_structure("5m", status="ACTIVE", breakout_direction=Direction.UP, current_price=101.0),
    }
    prior = ActiveTradeCandidate(
        timeframe="15m",
        exists=True,
        origin_timeframe="15m",
        direction=DivergenceDirection.BULLISH,
        setup_type=SetupType.TYPE_1,
        trade_function=TradeFunction.DECOMPOSITION,
        origin_price_zone="100.00-101.00",
        carry_timeframe="5m",
    )
    candidate = detect_type2_candidate(
        timeframe="15m",
        structures=structures,
        prior_type1=prior,
    )
    assert candidate.exists is True
    assert candidate.setup_type == SetupType.TYPE_2
    assert candidate.direction == DivergenceDirection.BULLISH
    assert candidate.origin_timeframe == "15m"
    assert candidate.carry_timeframe == "5m"
    assert candidate.type_label == "15m Bullish Type 2"


def test_bearish_type2_after_bearish_type1() -> None:
    structures = {
        "15m": _type2_structure("15m", prior_direction=Direction.DOWN),
        "5m": _type3_structure("5m", status="ACTIVE", breakout_direction=Direction.DOWN, current_price=89.0),
    }
    prior = ActiveTradeCandidate(
        timeframe="15m",
        exists=True,
        origin_timeframe="15m",
        direction=DivergenceDirection.BEARISH,
        setup_type=SetupType.TYPE_1,
        trade_function=TradeFunction.DECOMPOSITION,
        origin_price_zone="110.00-111.00",
        carry_timeframe="5m",
    )
    candidate = detect_type2_candidate(
        timeframe="15m",
        structures=structures,
        prior_type1=prior,
    )
    assert candidate.exists is True
    assert candidate.setup_type == SetupType.TYPE_2
    assert candidate.direction == DivergenceDirection.BEARISH
    assert candidate.origin_timeframe == "15m"
    assert candidate.carry_timeframe == "5m"
    assert candidate.type_label == "15m Bearish Type 2"


def test_type2_invalid_when_type1_missing() -> None:
    structures = {"15m": _type2_structure("15m", prior_direction=Direction.UP)}
    candidate = detect_type2_candidate(timeframe="15m", structures=structures, prior_type1=None)
    assert candidate.exists is False


def test_type2_invalid_when_pullback_breaks_type1_origin() -> None:
    structures = {
        "15m": _type2_structure(
            "15m",
            prior_direction=Direction.UP,
            pullback_breaks_origin=True,
        )
    }
    prior = ActiveTradeCandidate(
        timeframe="15m",
        exists=True,
        origin_timeframe="15m",
        direction=DivergenceDirection.BULLISH,
        setup_type=SetupType.TYPE_1,
        origin_price_zone="100.00-101.00",
    )
    candidate = detect_type2_candidate(
        timeframe="15m",
        structures=structures,
        prior_type1=prior,
    )
    assert candidate.exists is False


def test_type2_invalid_when_continuation_impulse_missing() -> None:
    structures = {
        "15m": _type2_structure(
            "15m",
            prior_direction=Direction.UP,
            continuation_ok=False,
        )
    }
    prior = ActiveTradeCandidate(
        timeframe="15m",
        exists=True,
        origin_timeframe="15m",
        direction=DivergenceDirection.BULLISH,
        setup_type=SetupType.TYPE_1,
        origin_price_zone="100.00-101.00",
    )
    candidate = detect_type2_candidate(
        timeframe="15m",
        structures=structures,
        prior_type1=prior,
    )
    assert candidate.exists is False


def test_type2_uses_same_origin_and_next_lower_carry() -> None:
    structures = {
        "1h": _type2_structure("1h", prior_direction=Direction.DOWN),
        "15m": _type3_structure("15m", status="ACTIVE", breakout_direction=Direction.DOWN, current_price=90.0),
    }
    prior = ActiveTradeCandidate(
        timeframe="1h",
        exists=True,
        origin_timeframe="1h",
        direction=DivergenceDirection.BEARISH,
        setup_type=SetupType.TYPE_1,
        origin_price_zone="110.00-111.00",
        carry_timeframe="15m",
    )
    candidate = detect_type2_candidate(
        timeframe="1h",
        structures=structures,
        prior_type1=prior,
    )
    assert candidate.exists is True
    assert candidate.origin_timeframe == "1h"
    assert candidate.carry_timeframe == "15m"


def test_type2_does_not_require_new_divergence_row() -> None:
    structures = {
        "15m": _type2_structure("15m", prior_direction=Direction.UP),
        "5m": _type3_structure("5m", status="ACTIVE", breakout_direction=Direction.UP, current_price=101.2),
    }
    divergence_audit = DivergenceAudit()
    divergence_audit.tf_15m.exists = False

    type1 = ActiveTradeCandidate(
        timeframe="15m",
        exists=True,
        origin_timeframe="15m",
        direction=DivergenceDirection.BULLISH,
        setup_type=SetupType.TYPE_1,
        origin_price_zone="100.00-101.00",
        carry_timeframe="5m",
    )
    candidate = detect_type2_candidate(
        timeframe="15m",
        structures=structures,
        prior_type1=type1,
        divergence=divergence_audit.tf_15m,
    )
    assert candidate.exists is True
    assert candidate.setup_type == SetupType.TYPE_2


def test_demand_zone_bullish_confirmation_creates_reaction_candidate() -> None:
    structures = {
        "15m": StructureState(
            timeframe="15m",
            current_price=100.8,
            legs=[
                Leg(start_index=0, end_index=2, direction=Direction.DOWN, high=106.0, low=99.5),
                Leg(start_index=2, end_index=4, direction=Direction.UP, high=101.2, low=99.7),
            ],
            active_leg=Leg(start_index=2, end_index=4, direction=Direction.UP, high=101.2, low=99.7, is_active=True),
            candles=_candles([102.0, 101.2, 100.4, 100.0, 100.8]),
        ),
        "5m": _type3_structure("5m", status="ACTIVE", breakout_direction=Direction.UP, current_price=100.9),
    }
    candidate = detect_zone_reaction_candidate(
        timeframe="15m",
        structures=structures,
        divergence=None,
        zones=[_zone(ZoneType.DEMAND, 99.8, 100.2, status="REACTING")],
    )
    assert candidate.exists is True
    assert candidate.trade_function == TradeFunction.SUPPLY_DEMAND_REACTION
    assert candidate.direction == DivergenceDirection.BULLISH
    assert candidate.carry_timeframe == "5m"


def test_supply_zone_bearish_confirmation_creates_reaction_candidate() -> None:
    structures = {
        "15m": StructureState(
            timeframe="15m",
            current_price=109.1,
            legs=[
                Leg(start_index=0, end_index=2, direction=Direction.UP, high=110.2, low=105.0),
                Leg(start_index=2, end_index=4, direction=Direction.DOWN, high=109.8, low=108.9),
            ],
            active_leg=Leg(start_index=2, end_index=4, direction=Direction.DOWN, high=109.8, low=108.9, is_active=True),
            candles=_candles([107.0, 108.1, 109.0, 109.5, 109.1]),
        ),
        "5m": _type3_structure("5m", status="ACTIVE", breakout_direction=Direction.DOWN, current_price=108.8),
    }
    candidate = detect_zone_reaction_candidate(
        timeframe="15m",
        structures=structures,
        divergence=None,
        zones=[_zone(ZoneType.SUPPLY, 108.9, 109.6, status="REACTING")],
    )
    assert candidate.exists is True
    assert candidate.trade_function == TradeFunction.SUPPLY_DEMAND_REACTION
    assert candidate.direction == DivergenceDirection.BEARISH
    assert candidate.carry_timeframe == "5m"


def test_zone_without_impulse_creates_no_trade() -> None:
    structures = {
        "15m": StructureState(
            timeframe="15m",
            current_price=100.2,
            legs=[Leg(start_index=0, end_index=2, direction=Direction.DOWN, high=106.0, low=100.0)],
            active_leg=Leg(start_index=0, end_index=2, direction=Direction.DOWN, high=106.0, low=100.0, is_active=True),
            candles=_candles([102.0, 101.0, 100.2]),
        ),
        "5m": _type3_structure("5m", status="ACTIVE", breakout_direction=Direction.UP, current_price=100.3),
    }
    candidate = detect_zone_reaction_candidate(
        timeframe="15m",
        structures=structures,
        divergence=None,
        zones=[_zone(ZoneType.DEMAND, 100.0, 100.4, status="REACTING")],
    )
    assert candidate.exists is False
    assert "WAIT" in candidate.selection_reason


def test_zone_without_structure_confirmation_records_zone_alone_guard() -> None:
    structures = {
        "15m": StructureState(
            timeframe="15m",
            current_price=100.2,
            legs=[Leg(start_index=0, end_index=2, direction=Direction.DOWN, high=106.0, low=100.0)],
            active_leg=Leg(start_index=0, end_index=2, direction=Direction.DOWN, high=106.0, low=100.0, is_active=True),
            candles=_candles([102.0, 101.0, 100.2]),
        ),
        "5m": _type3_structure("5m", status="ACTIVE", breakout_direction=Direction.UP, current_price=100.3),
    }
    trace = FrameworkAuditTrace(symbol="BTCUSDT", timestamp="now")
    candidate = detect_zone_reaction_candidate(
        timeframe="15m",
        structures=structures,
        divergence=None,
        zones=[_zone(ZoneType.DEMAND, 100.0, 100.4, status="REACTING")],
        trace=trace,
    )
    assert candidate.exists is False
    names = {check.name for check in trace.checks}
    assert "Zone alone cannot create trade" in names


def test_midpoint_zone_cannot_create_trade() -> None:
    structures = {
        "15m": StructureState(
            timeframe="15m",
            current_price=100.7,
            legs=[
                Leg(start_index=0, end_index=2, direction=Direction.DOWN, high=106.0, low=99.5),
                Leg(start_index=2, end_index=4, direction=Direction.UP, high=101.2, low=99.7),
            ],
            active_leg=Leg(start_index=2, end_index=4, direction=Direction.UP, high=101.2, low=99.7, is_active=True),
            candles=_candles([102.0, 101.2, 100.4, 100.0, 100.8]),
        ),
        "5m": _type3_structure("5m", status="ACTIVE", breakout_direction=Direction.UP, current_price=100.9),
    }
    candidate = detect_zone_reaction_candidate(
        timeframe="15m",
        structures=structures,
        divergence=None,
        zones=[_zone(ZoneType.DEMAND, 99.8, 100.2, status="REACTING", role="range midpoint")],
    )
    assert candidate.exists is False


def test_accepted_through_zone_cannot_create_trade() -> None:
    structures = {
        "15m": StructureState(
            timeframe="15m",
            current_price=100.7,
            legs=[
                Leg(start_index=0, end_index=2, direction=Direction.DOWN, high=106.0, low=99.5),
                Leg(start_index=2, end_index=4, direction=Direction.UP, high=101.2, low=99.7),
            ],
            active_leg=Leg(start_index=2, end_index=4, direction=Direction.UP, high=101.2, low=99.7, is_active=True),
            candles=_candles([102.0, 101.2, 100.4, 100.0, 100.8]),
        ),
        "5m": _type3_structure("5m", status="ACTIVE", breakout_direction=Direction.UP, current_price=100.9),
    }
    candidate = detect_zone_reaction_candidate(
        timeframe="15m",
        structures=structures,
        divergence=None,
        zones=[_zone(ZoneType.DEMAND, 99.8, 100.2, status="ACCEPTED_THROUGH")],
    )
    assert candidate.exists is False


def test_zone_reaction_uses_lower_timeframe_carry() -> None:
    structures = {
        "1h": StructureState(
            timeframe="1h",
            current_price=109.1,
            legs=[
                Leg(start_index=0, end_index=2, direction=Direction.UP, high=110.2, low=105.0),
                Leg(start_index=2, end_index=4, direction=Direction.DOWN, high=109.8, low=108.9),
            ],
            active_leg=Leg(start_index=2, end_index=4, direction=Direction.DOWN, high=109.8, low=108.9, is_active=True),
            candles=_candles([107.0, 108.1, 109.0, 109.5, 109.1]),
        ),
        "15m": _type3_structure("15m", status="ACTIVE", breakout_direction=Direction.DOWN, current_price=108.8),
    }
    candidate = detect_zone_reaction_candidate(
        timeframe="1h",
        structures=structures,
        divergence=None,
        zones=[SupplyDemandZone(timeframe="1h", zone_type=ZoneType.SUPPLY, lower=108.9, upper=109.6, status="REACTING", role="impulse origin", price_band="108.90-109.60")],
    )
    assert candidate.exists is True
    assert candidate.carry_timeframe == "15m"


def test_failed_breakout_blocks_type3_candidate() -> None:
    structures = {"15m": _type3_structure("15m", status="FAILED_BREAK_UP", breakout_direction=Direction.UP, current_price=99.4)}
    candidate = detect_type3_candidate(timeframe="15m", structures=structures)
    assert candidate.exists is False


def test_15m_bullish_type3_uses_5m_carry() -> None:
    structures = {
        "15m": _type3_structure("15m", status="BROKEN_UP", breakout_direction=Direction.UP, current_price=101.8),
        "5m": _type3_structure("5m", status="ACTIVE", breakout_direction=Direction.UP, current_price=101.0),
    }
    candidate = detect_type3_candidate(timeframe="15m", structures=structures)
    assert candidate.carry_timeframe == "5m"


def test_1h_bullish_type3_uses_15m_carry() -> None:
    structures = {
        "1h": _type3_structure("1h", status="BROKEN_UP", breakout_direction=Direction.UP, current_price=101.8),
        "15m": _type3_structure("15m", status="ACTIVE", breakout_direction=Direction.UP, current_price=101.0),
    }
    candidate = detect_type3_candidate(timeframe="1h", structures=structures)
    assert candidate.carry_timeframe == "15m"


def test_4h_bullish_type3_uses_1h_carry() -> None:
    structures = {
        "4h": _type3_structure("4h", status="BROKEN_UP", breakout_direction=Direction.UP, current_price=101.8),
        "1h": _type3_structure("1h", status="ACTIVE", breakout_direction=Direction.UP, current_price=101.0),
    }
    candidate = detect_type3_candidate(timeframe="4h", structures=structures)
    assert candidate.carry_timeframe == "1h"


def test_5m_bullish_type3_uses_3m_carry() -> None:
    structures = {
        "5m": _type3_structure("5m", status="BROKEN_UP", breakout_direction=Direction.UP, current_price=101.8),
        "3m": _type3_structure("3m", status="ACTIVE", breakout_direction=Direction.UP, current_price=101.0),
    }
    candidate = detect_type3_candidate(timeframe="5m", structures=structures)
    assert candidate.carry_timeframe == "3m"


def test_mature_carry_sets_type3_entry_and_hold_flags() -> None:
    structures = {
        "15m": _type3_structure("15m", status="BROKEN_UP", breakout_direction=Direction.UP, current_price=101.8),
        "5m": _type3_structure("5m", status="ACTIVE", breakout_direction=Direction.UP, current_price=100.9),
    }
    structures["5m"].range_state.active = True
    candidate = detect_type3_candidate(timeframe="15m", structures=structures)
    assert candidate.carry_state == CarryState.MATURE
    assert candidate.fresh_entry_valid is False
    assert candidate.existing_hold_valid is True
    assert candidate.too_late_to_chase is True


def test_type1_candidate_not_created_from_non_official_divergence(monkeypatch) -> None:
    structures = {"1h": _structure("1h"), "15m": _structure("15m")}
    non_official = DivergenceState(
        timeframe="1h",
        exists=True,
        abc_valid=False,
        impulse_confirmed=True,
        direction=DivergenceDirection.BEARISH,
        grade=DivergenceGrade.MODERATE,
    )
    divergence_audit = DivergenceAudit(tf_1h=non_official)
    monkeypatch.setattr(
        "ocean_engine.trade.active_trade_engine.build_carry_status",
        lambda *args, **kwargs: CarryStatus(timeframe="15m", direction=Direction.DOWN, state=CarryState.ACTIVE, finished=False),
    )
    candidate = build_type1_candidate("1h", non_official, structures, divergence_audit)
    assert candidate.exists is False


def test_5m_carry_does_not_become_5m_type1_without_5m_divergence(monkeypatch) -> None:
    structures = {"15m": _structure("15m"), "5m": _structure("5m")}
    divergence_audit = DivergenceAudit(tf_15m=_official_divergence("15m", DivergenceDirection.BULLISH))
    monkeypatch.setattr(
        "ocean_engine.trade.active_trade_engine.build_carry_status",
        lambda *args, **kwargs: CarryStatus(timeframe="5m", direction=Direction.UP, state=CarryState.FRESH, finished=False),
    )
    audit = build_active_trade_audit(structures, divergence_audit)
    assert audit.tf_15m.exists is True
    assert audit.tf_5m.exists is False


def test_15m_official_divergence_does_not_create_1h_candidate(monkeypatch) -> None:
    structures = {"15m": _structure("15m"), "5m": _structure("5m")}
    divergence_audit = DivergenceAudit(tf_15m=_official_divergence("15m", DivergenceDirection.BULLISH))
    monkeypatch.setattr(
        "ocean_engine.trade.active_trade_engine.build_carry_status",
        lambda *args, **kwargs: _carry_status(CarryState.FRESH, finished=False),
    )
    audit = build_active_trade_audit(structures, divergence_audit)
    assert audit.tf_15m.exists is True
    assert audit.tf_1h.exists is False


def test_fresh_entry_valid_true_only_for_fresh_or_active_carry(monkeypatch) -> None:
    structures = {"15m": _structure("15m"), "5m": _structure("5m")}
    divergence = _official_divergence("15m", DivergenceDirection.BULLISH)
    divergence_audit = DivergenceAudit(tf_15m=divergence)

    monkeypatch.setattr(
        "ocean_engine.trade.active_trade_engine.build_carry_status",
        lambda *args, **kwargs: _carry_status(CarryState.ACTIVE, finished=False),
    )
    active_candidate = build_type1_candidate("15m", divergence, structures, divergence_audit)
    assert active_candidate.fresh_entry_valid is True


def test_mature_carry_gives_existing_hold_true_but_fresh_false(monkeypatch) -> None:
    structures = {"15m": _structure("15m"), "5m": _structure("5m")}
    divergence = _official_divergence("15m", DivergenceDirection.BULLISH)
    divergence_audit = DivergenceAudit(tf_15m=divergence)
    monkeypatch.setattr(
        "ocean_engine.trade.active_trade_engine.build_carry_status",
        lambda *args, **kwargs: _carry_status(CarryState.MATURE, finished=False),
    )
    candidate = build_type1_candidate("15m", divergence, structures, divergence_audit)
    assert candidate.existing_hold_valid is True
    assert candidate.fresh_entry_valid is False


def test_exhausting_or_finished_carry_gives_fresh_false(monkeypatch) -> None:
    structures = {"15m": _structure("15m"), "5m": _structure("5m")}
    divergence = _official_divergence("15m", DivergenceDirection.BULLISH)
    divergence_audit = DivergenceAudit(tf_15m=divergence)
    monkeypatch.setattr(
        "ocean_engine.trade.active_trade_engine.build_carry_status",
        lambda *args, **kwargs: _carry_status(CarryState.EXHAUSTING, finished=True),
    )
    candidate = build_type1_candidate("15m", divergence, structures, divergence_audit)
    assert candidate.fresh_entry_valid is False


def test_selected_active_trade_tf_equals_true_origin_timeframe() -> None:
    audit = ActiveTradeAudit()
    audit.tf_15m.exists = True
    audit.tf_15m.origin_timeframe = "15m"
    audit.tf_15m.existing_hold_valid = True
    audit.tf_15m.selection_reason = "C ending at leg index 20"
    selected = select_active_trade(audit)
    assert selected is audit.tf_15m
    assert selected.origin_timeframe == "15m"


def test_audit_summary_prints_correct_rows() -> None:
    audit = ActiveTradeAudit()
    audit.tf_1h.exists = True
    audit.tf_1h.direction = DivergenceDirection.BEARISH
    audit.tf_1h.type_label = "1H Bearish Type 1"
    summary = active_trade_audit_summary(audit)
    assert "4H:No" in summary
    assert "1H:1H Bearish Type 1" in summary
    assert "15m:No" in summary
    assert "5m:No" in summary
    assert "3m:No" in summary


def test_active_trade_audit_summary_prints_type3_rows() -> None:
    audit = ActiveTradeAudit()
    audit.tf_4h.exists = True
    audit.tf_4h.setup_type = SetupType.TYPE_3
    audit.tf_4h.direction = DivergenceDirection.BULLISH
    audit.tf_1h.exists = True
    audit.tf_1h.setup_type = SetupType.TYPE_3
    audit.tf_1h.direction = DivergenceDirection.BULLISH
    audit.tf_15m.exists = True
    audit.tf_15m.setup_type = SetupType.TYPE_3
    audit.tf_15m.direction = DivergenceDirection.BULLISH
    audit.tf_5m.exists = True
    audit.tf_5m.setup_type = SetupType.TYPE_3
    audit.tf_5m.direction = DivergenceDirection.BULLISH
    audit.tf_3m.exists = True
    audit.tf_3m.setup_type = SetupType.TYPE_3
    audit.tf_3m.direction = DivergenceDirection.BULLISH

    summary = active_trade_audit_summary(audit)
    assert "4H:Bullish T3✓" in summary
    assert "1H:Bullish T3✓" in summary
    assert "15m:Bullish T3✓" in summary
    assert "5m:Bullish T3✓" in summary
    assert "3m:Bullish T3✓" in summary


def test_selected_active_trade_tf_type3_equals_true_origin_timeframe() -> None:
    structures = {
        "1h": _type3_structure("1h", status="BROKEN_UP", breakout_direction=Direction.UP, current_price=102.0),
        "15m": _type3_structure("15m", status="BROKEN_UP", breakout_direction=Direction.UP, current_price=101.8),
        "5m": _type3_structure("5m", status="ACTIVE", breakout_direction=Direction.UP, current_price=101.2),
        "3m": _type3_structure("3m", status="ACTIVE", breakout_direction=Direction.UP, current_price=101.0),
    }
    structures["5m"].range_state.acceptance_confirmed = False
    structures["5m"].range_state.breakout_direction = Direction.UNCLEAR
    structures["3m"].range_state.acceptance_confirmed = False
    structures["3m"].range_state.breakout_direction = Direction.UNCLEAR
    audit = build_active_trade_audit(structures, DivergenceAudit())
    selected = select_active_trade(audit)
    assert selected is not None
    assert selected.origin_timeframe == audit.selected_active_trade_tf
    assert selected.origin_timeframe in {"1h", "15m"}


def test_range_rejection_candidate_created_at_upper_edge_with_bearish_rejection() -> None:
    structure = StructureState(
        timeframe="15m",
        current_price=109.6,
        active_leg=Leg(
            start_index=5,
            end_index=8,
            direction=Direction.DOWN,
            high=110.0,
            low=109.2,
            is_active=True,
        ),
        legs=[
            Leg(start_index=0, end_index=2, direction=Direction.UP, high=110.2, low=104.0),
            Leg(start_index=2, end_index=5, direction=Direction.DOWN, high=109.9, low=108.8),
            Leg(start_index=5, end_index=8, direction=Direction.DOWN, high=110.0, low=109.2, is_active=True),
        ],
        range_state=RangeState(
            timeframe="15m",
            is_range=True,
            active=True,
            status="ACTIVE",
            price_location="UPPER_EDGE",
            upper_edge=110.0,
            lower_edge=100.0,
        ),
    )
    structures = {
        "15m": structure,
        "5m": StructureState(
            timeframe="5m",
            active_leg=Leg(start_index=0, end_index=2, direction=Direction.DOWN, high=109.5, low=108.6, is_active=True),
            legs=[Leg(start_index=0, end_index=2, direction=Direction.DOWN, high=109.5, low=108.6, is_active=True)],
        ),
    }
    candidate = detect_range_rejection_candidate(timeframe="15m", structures=structures)
    assert candidate.exists is True
    assert candidate.trade_function == TradeFunction.RANGE_REJECTION
    assert candidate.direction == Direction.DOWN


def test_upgrade_candidate_created_for_upgrade_risk_context() -> None:
    structures = {
        "15m": StructureState(
            timeframe="15m",
            current_price=100.8,
            active_leg=Leg(
                start_index=7,
                end_index=9,
                direction=Direction.UP,
                high=101.1,
                low=100.2,
                is_active=True,
            ),
            legs=[
                Leg(start_index=0, end_index=3, direction=Direction.UP, high=100.9, low=94.2),
                Leg(start_index=3, end_index=6, direction=Direction.DOWN, high=100.7, low=93.8),
                Leg(start_index=7, end_index=9, direction=Direction.UP, high=101.1, low=100.2, is_active=True),
            ],
            range_state=RangeState(
                timeframe="15m",
                is_range=True,
                active=True,
                status="UPGRADE_RISK",
                upper_edge=101.0,
                lower_edge=94.0,
            ),
        ),
        "5m": StructureState(
            timeframe="5m",
            active_leg=Leg(start_index=0, end_index=2, direction=Direction.UP, high=101.2, low=100.3, is_active=True),
            legs=[Leg(start_index=0, end_index=2, direction=Direction.UP, high=101.2, low=100.3, is_active=True)],
        ),
    }
    candidate = detect_upgrade_candidate(timeframe="15m", structures=structures)
    assert candidate.exists is True
    assert candidate.trade_function == TradeFunction.UPGRADE
    assert candidate.fresh_entry_valid is False
