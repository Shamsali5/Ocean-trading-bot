"""Tests for strict standalone type classifier."""

from __future__ import annotations

from ocean_framework_v12_audit import FrameworkAuditTrace
from ocean_type_classifier import classify_type_1, classify_type_2, classify_type_3


def test_type1_requires_fresh_or_active_carry_not_mature() -> None:
    result = classify_type_1(
        divergence_result={
            "timeframe": "15m",
            "direction": "BULLISH",
            "official": True,
            "valid_energy_weakening": True,
        },
        impulse_result={"confirmed": True, "direction": "BULLISH"},
        carry_result={"state": "MATURE", "direction": "UP", "finished": False},
        trace=None,
    )
    assert result.valid is False
    assert result.type_label == "NONE"


def test_classify_type1_returns_full_label_with_timeframe_and_direction() -> None:
    trace = FrameworkAuditTrace(symbol="BTCUSDT", timestamp="now")
    result = classify_type_1(
        divergence_result={
            "timeframe": "15m",
            "direction": "BULLISH",
            "official": True,
            "valid_energy_weakening": True,
        },
        impulse_result={"confirmed": True, "direction": "BULLISH"},
        carry_result={"state": "ACTIVE", "direction": "UP", "finished": False},
        trace=trace,
    )
    assert result.valid is True
    assert result.type_label == "TYPE_1"
    assert result.full_label == "15m Bullish Type 1"
    names = {check.name for check in trace.checks}
    assert "Type label includes timeframe" in names
    assert "Type label includes direction" in names
    assert "Type 1 requires divergence + impulse + carry" in names


def test_classify_type1_rejects_vacc_only_without_impulse_or_carry() -> None:
    result = classify_type_1(
        divergence_result={"timeframe": "15m", "direction": "BULLISH", "official": False, "valid_energy_weakening": True},
        impulse_result={"confirmed": False, "direction": "BULLISH"},
        carry_result={"state": "UNCLEAR", "direction": "UP", "finished": False},
        trace=None,
    )
    assert result.valid is False
    assert result.type_label == "NONE"
    assert result.full_label == "NONE"


def test_classify_type2_returns_full_label_when_all_conditions_hold() -> None:
    result = classify_type_2(
        prior_type_1={"valid": True, "type_label": "TYPE_1", "timeframe": "1h", "direction": "BEARISH"},
        pullback_context={"pulled_back": True, "not_invalidated": True, "weakens": True},
        continuation_impulse={"confirmed": True, "direction": "BEARISH"},
        carry_result={"state": "ACTIVE", "direction": "DOWN", "finished": False},
        trace=None,
    )
    assert result.valid is True
    assert result.type_label == "TYPE_2"
    assert result.full_label == "1H Bearish Type 2"


def test_classify_type3_requires_breakout_acceptance() -> None:
    trace = FrameworkAuditTrace(symbol="BTCUSDT", timestamp="now")
    result = classify_type_3(
        range_result={"timeframe": "15m", "valid": True, "upper_edge": 101.0, "lower_edge": 99.0},
        breakout_acceptance_result={
            "accepted": False,
            "boundary_broken": True,
            "retest_or_acceptance": True,
            "continuation_outside": True,
            "direction": "UP",
        },
        carry_result={"state": "ACTIVE", "direction": "UP", "finished": False},
        trace=trace,
    )
    assert result.valid is False
    assert result.type_label == "NONE"
    names = {check.name for check in trace.checks}
    assert "Type 3 requires breakout acceptance" in names


def test_classify_type3_valid_output_never_generic_type_only() -> None:
    result = classify_type_3(
        range_result={"timeframe": "5m", "valid": True, "upper_edge": 101.0, "lower_edge": 99.0},
        breakout_acceptance_result={
            "accepted": True,
            "boundary_broken": True,
            "retest_or_acceptance": True,
            "continuation_outside": True,
            "direction": "DOWN",
        },
        carry_result={"state": "ACTIVE", "direction": "DOWN", "finished": False},
        trace=None,
    )
    assert result.valid is True
    assert result.type_label == "TYPE_3"
    assert result.full_label == "5m Bearish Type 3"
    assert result.full_label != "Type 3"
