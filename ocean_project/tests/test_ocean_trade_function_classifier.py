"""Tests for strict trade-function classifier."""

from __future__ import annotations

from ocean_framework_v12_audit import FrameworkAuditTrace
from ocean_trade_function_classifier import classify_trade_function


def _names(trace: FrameworkAuditTrace) -> set[str]:
    return {check.name for check in trace.checks}


def test_breakout_trade_requires_valid_type3() -> None:
    trace = FrameworkAuditTrace(symbol="BTCUSDT", timestamp="now")
    result = classify_trade_function(
        move_context=None,
        type_classification={"type_label": "TYPE_3", "valid": True},
        range_result={"timeframe": "15m", "price_location": "UPPER_EDGE"},
        zone_results=[],
        multi_level_result={
            "candidate_kind": "TYPE3",
            "impulse_confirmed": True,
            "carry_confirmed": True,
            "structure_confirmed": True,
        },
        trace=trace,
    )
    assert result.valid is True
    assert result.trade_function == "BREAKOUT_TRADE"
    assert "Trade function assigned" in _names(trace)
    assert "Trade function separate from Type label" in _names(trace)


def test_breakout_trade_requires_impulse_and_carry_confirmation() -> None:
    result = classify_trade_function(
        move_context=None,
        type_classification={"type_label": "TYPE_3", "valid": True},
        range_result={"timeframe": "15m", "price_location": "UPPER_EDGE"},
        zone_results=[],
        multi_level_result={
            "candidate_kind": "TYPE3",
            "impulse_confirmed": False,
            "carry_confirmed": True,
            "structure_confirmed": True,
        },
        trace=None,
    )
    assert result.valid is False
    assert result.trade_function == "NONE"
    assert "impulse" in result.reason.lower()


def test_pullback_continuation_trade_requires_valid_type2() -> None:
    result = classify_trade_function(
        move_context=None,
        type_classification={"type_label": "TYPE_2", "valid": True},
        range_result={"timeframe": "15m"},
        zone_results=[],
        multi_level_result={
            "candidate_kind": "TYPE2",
            "impulse_confirmed": True,
            "carry_confirmed": True,
        },
        trace=None,
    )
    assert result.valid is True
    assert result.trade_function == "PULLBACK_CONTINUATION_TRADE"


def test_higher_level_divergence_trade_requires_controlling_divergence() -> None:
    result = classify_trade_function(
        move_context=None,
        type_classification={"type_label": "TYPE_1", "valid": True},
        range_result={"timeframe": "1h"},
        zone_results=[],
        multi_level_result={
            "candidate_kind": "TYPE1",
            "controlling_level_divergence": True,
            "impulse_confirmed": True,
            "carry_confirmed": True,
        },
        trace=None,
    )
    assert result.valid is True
    assert result.trade_function == "HIGHER_LEVEL_DIVERGENCE_TRADE"


def test_decomposition_trade_for_non_controlling_type1() -> None:
    result = classify_trade_function(
        move_context=None,
        type_classification={"type_label": "TYPE_1", "valid": True},
        range_result={"timeframe": "15m"},
        zone_results=[],
        multi_level_result={
            "candidate_kind": "TYPE1",
            "controlling_level_divergence": False,
            "decomposition_context": True,
            "impulse_confirmed": True,
            "carry_confirmed": True,
        },
        trace=None,
    )
    assert result.valid is True
    assert result.trade_function == "DECOMPOSITION_TRADE"


def test_range_rejection_trade_requires_edge_divergence_impulse_and_carry() -> None:
    result = classify_trade_function(
        move_context=None,
        type_classification={"type_label": "NONE", "valid": False},
        range_result={"timeframe": "15m", "price_location": "UPPER_EDGE"},
        zone_results=[],
        multi_level_result={
            "candidate_kind": "RANGE_REJECTION",
            "range_edge_rejection": True,
            "divergence_confirmed": True,
            "impulse_confirmed": True,
            "carry_confirmed": True,
        },
        trace=None,
    )
    assert result.valid is True
    assert result.trade_function == "RANGE_REJECTION_TRADE"


def test_supply_demand_reaction_requires_full_confirmation_stack() -> None:
    trace = FrameworkAuditTrace(symbol="BTCUSDT", timestamp="now")
    result = classify_trade_function(
        move_context=None,
        type_classification={"type_label": "NONE", "valid": False},
        range_result={"timeframe": "15m"},
        zone_results=[{"zone_type": "DEMAND"}],
        multi_level_result={
            "candidate_kind": "ZONE_REACTION",
            "zone_present": True,
            "structure_confirmed": True,
            "impulse_confirmed": True,
            "carry_confirmed": True,
        },
        trace=trace,
    )
    assert result.valid is True
    assert result.trade_function == "SUPPLY_DEMAND_REACTION_TRADE"
    assert "Supply/demand reaction requires confirmation" in _names(trace)


def test_upgrade_not_assumed_early() -> None:
    trace = FrameworkAuditTrace(symbol="BTCUSDT", timestamp="now")
    result = classify_trade_function(
        move_context=None,
        type_classification={"type_label": "NONE", "valid": False},
        range_result={"timeframe": "15m"},
        zone_results=[],
        multi_level_result={
            "candidate_kind": "UPGRADE",
            "upgrade_ready": False,
            "upgrade_early": True,
        },
        trace=trace,
    )
    assert result.valid is False
    assert result.trade_function == "NONE"
    checks = {check.name: check for check in trace.checks}
    assert checks["Upgrade not assumed early"].passed is False
    assert checks["Trade function assigned"].passed is False
