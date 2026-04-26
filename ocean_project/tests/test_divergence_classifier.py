"""Tests for centralized official divergence classifier."""

from __future__ import annotations

from ocean_divergence_classifier import classify_divergence
from ocean_framework_v12_audit import FrameworkAuditTrace
from ocean_abc_validator import ABCValidationResult


def _abc_result(
    *,
    valid: bool = True,
    direction: str = "BEARISH",
    b_reset_valid: bool = True,
    c_test_valid: bool = True,
    high: float = 111.5,
    low: float = 97.0,
) -> ABCValidationResult:
    seg_a = type("SegA", (), {"start_index": 2, "end_index": 6, "high": 110.0, "low": 90.0})()
    seg_b = type("SegB", (), {"start_index": 7, "end_index": 9, "high": 109.0, "low": 98.0})()
    seg_c = type("SegC", (), {"start_index": 10, "end_index": 14, "high": high, "low": low})()
    return ABCValidationResult(
        timeframe="1h",
        direction=direction,
        valid=valid,
        segment_a=seg_a,
        segment_b=seg_b,
        segment_c=seg_c,
        b_reset_valid=b_reset_valid,
        c_test_valid=c_test_valid,
        same_timeframe_valid=True,
        reason="test",
    )


def _vacc_result(
    *,
    vel_weaker: bool,
    acc_weaker: bool,
    acc_area_weaker: bool,
    b_zero_reset: bool,
    valid_energy_weakening: bool,
) -> object:
    return type(
        "VAccResult",
        (),
        {
            "vel_weaker": vel_weaker,
            "acc_weaker": acc_weaker,
            "acc_area_weaker": acc_area_weaker,
            "b_zero_reset": b_zero_reset,
            "valid_energy_weakening": valid_energy_weakening,
        },
    )()


def test_classifier_invalid_when_abc_fails() -> None:
    result = classify_divergence(
        abc_result=_abc_result(valid=False),
        vacc_result=_vacc_result(
            vel_weaker=True,
            acc_weaker=True,
            acc_area_weaker=True,
            b_zero_reset=True,
            valid_energy_weakening=True,
        ),
        impulse_result=(True, "STRONG"),
        carry_result={"lower_tf_carry_available": True},
    )
    assert result.official is False
    assert result.grade == "INVALID"
    assert result.role == "LOCAL_NOISE"


def test_classifier_elite_when_all_gates_pass() -> None:
    result = classify_divergence(
        abc_result=_abc_result(valid=True, b_reset_valid=True, c_test_valid=True),
        vacc_result=_vacc_result(
            vel_weaker=True,
            acc_weaker=True,
            acc_area_weaker=True,
            b_zero_reset=True,
            valid_energy_weakening=True,
        ),
        impulse_result=(True, "STRONG"),
        carry_result={"lower_tf_carry_available": True},
    )
    assert result.official is True
    assert result.grade == "ELITE"
    assert result.role == "ORIGIN"


def test_classifier_strong_without_carry_upgrade() -> None:
    result = classify_divergence(
        abc_result=_abc_result(valid=True, b_reset_valid=True, c_test_valid=True),
        vacc_result=_vacc_result(
            vel_weaker=True,
            acc_weaker=True,
            acc_area_weaker=False,
            b_zero_reset=False,
            valid_energy_weakening=True,
        ),
        impulse_result=(True, "STRONG"),
        carry_result={"lower_tf_carry_available": False},
    )
    assert result.official is True
    assert result.grade == "STRONG"
    assert result.role == "SUPPORT"


def test_classifier_weak_when_impulse_missing() -> None:
    result = classify_divergence(
        abc_result=_abc_result(valid=True, b_reset_valid=True, c_test_valid=True),
        vacc_result=_vacc_result(
            vel_weaker=True,
            acc_weaker=True,
            acc_area_weaker=False,
            b_zero_reset=True,
            valid_energy_weakening=True,
        ),
        impulse_result=None,
        carry_result={"lower_tf_carry_available": True},
    )
    assert result.official is False
    assert result.grade == "WEAK"
    assert "impulse missing" in result.reason.lower()


def test_classifier_emits_required_audit_checks() -> None:
    trace = FrameworkAuditTrace(symbol="TEST", timestamp="2026-01-01T00:00:00Z")
    _ = classify_divergence(
        abc_result=_abc_result(valid=True),
        vacc_result=_vacc_result(
            vel_weaker=False,
            acc_weaker=False,
            acc_area_weaker=False,
            b_zero_reset=False,
            valid_energy_weakening=False,
        ),
        impulse_result=(False, "NONE"),
        carry_result={"lower_tf_carry_available": False},
        trace=trace,
    )
    names = {check.name for check in trace.checks}
    assert "Official divergence requires A-B-C" in names
    assert "Official divergence requires energy weakening" in names
    assert "Trade-confirmed divergence requires impulse" in names
    assert "Weak divergence cannot generate BUY/SELL" in names
