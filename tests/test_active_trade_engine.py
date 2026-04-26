"""Tests for active trade candidate audit and selection."""

from __future__ import annotations

from ocean_engine.models.enums import CarryState, Direction, DivergenceDirection, DivergenceGrade, SetupType
from ocean_engine.models.market import (
    ActiveTradeAudit,
    CarryStatus,
    DivergenceAudit,
    DivergenceState,
    Leg,
    RangeState,
    StructureState,
)
from ocean_engine.trade.active_trade_engine import (
    active_trade_audit_summary,
    build_active_trade_audit,
    build_type1_candidate,
    select_active_trade,
)


def _structure(timeframe: str) -> StructureState:
    return StructureState(timeframe=timeframe, legs=[])


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
    assert "Type 1" in candidate.type_label


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
    assert candidate.type_label.startswith("1H")


def test_type3_bullish_breakout_detected_on_1h_without_official_divergence() -> None:
    structure_1h = StructureState(
        timeframe="1h",
        current_price=102.5,
        range_state=RangeState(
            timeframe="1h",
            is_range=True,
            active=True,
            upper_edge=100.0,
            lower_edge=90.0,
            price_location="OUTSIDE",
        ),
    )
    structures = {"1h": structure_1h}
    audit = build_active_trade_audit(structures, DivergenceAudit())
    assert audit.tf_1h.exists is True
    assert audit.tf_1h.setup_type == SetupType.TYPE_3
    assert audit.tf_1h.direction == Direction.UP
    assert audit.tf_1h.type_label == "1H Bullish Type 3"


def test_type3_bearish_breakdown_detected_on_15m_without_official_divergence() -> None:
    structure_15m = StructureState(
        timeframe="15m",
        current_price=87.0,
        range_state=RangeState(
            timeframe="15m",
            is_range=True,
            active=True,
            upper_edge=100.0,
            lower_edge=90.0,
            price_location="OUTSIDE",
        ),
    )
    structures = {"15m": structure_15m}
    audit = build_active_trade_audit(structures, DivergenceAudit())
    assert audit.tf_15m.exists is True
    assert audit.tf_15m.setup_type == SetupType.TYPE_3
    assert audit.tf_15m.direction == Direction.DOWN
    assert audit.tf_15m.type_label == "15m Bearish Type 3"


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
