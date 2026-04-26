"""Tests for divergence audit engine timeframe-isolated behavior."""

from __future__ import annotations

from ocean_engine.divergence.divergence_audit import (
    audit_timeframe_divergence,
    audit_timeframe_divergence_with_validator,
    build_divergence_audit,
    default_divergence_state,
    divergence_audit_summary,
    select_last_meaningful_divergence,
)
from ocean_engine.models.enums import DivergenceDirection, DivergenceGrade
from ocean_engine.models.market import Candle, DivergenceState, StructureState, VAccSeries


def _structure(timeframe: str, close: float = 100.0) -> StructureState:
    candle = Candle(
        open_time=0,
        open=close,
        high=close + 1.0,
        low=close - 1.0,
        close=close,
        volume=1.0,
        close_time=60_000 - 1,
    )
    return StructureState(timeframe=timeframe, candles=[candle], legs=[])


def _vacc(timeframe: str) -> VAccSeries:
    return VAccSeries(timeframe=timeframe, points=[])


def _official_state(timeframe: str, direction: DivergenceDirection, c_end_index: int) -> DivergenceState:
    return DivergenceState(
        timeframe=timeframe,
        exists=True,
        abc_valid=True,
        impulse_confirmed=True,
        direction=direction,
        grade=DivergenceGrade.STRONG,
        notes=f"c_end_index={c_end_index}",
    )


def test_each_timeframe_audit_uses_only_its_own_structure_and_vacc(monkeypatch) -> None:
    structures = {
        "4h": _structure("4h"),
        "1h": _structure("1h"),
    }
    vacc_map = {
        "4h": _vacc("4h"),
        "1h": _vacc("1h"),
    }
    seen: list[tuple[str, str]] = []

    def _fake_find_abc_candidates(structure):
        seen.append((structure.timeframe, "find"))
        return []

    def _fake_select_latest(candidates):
        return None

    monkeypatch.setattr("ocean_engine.divergence.divergence_audit.find_abc_candidates", _fake_find_abc_candidates)
    monkeypatch.setattr(
        "ocean_engine.divergence.divergence_audit.select_latest_abc_candidate",
        _fake_select_latest,
    )

    _ = build_divergence_audit(structures, vacc_map)
    assert ("4h", "find") in seen
    assert ("1h", "find") in seen


def test_15m_official_divergence_does_not_create_1h_official_divergence() -> None:
    structures = {
        "15m": _structure("15m"),
        "1h": _structure("1h"),
    }
    vacc_map = {
        "15m": _vacc("15m"),
        "1h": _vacc("1h"),
    }
    audit = build_divergence_audit(structures, vacc_map)
    assert audit.tf_15m.exists is False
    assert audit.tf_1h.exists is False


def test_selected_last_meaningful_tf_points_only_to_official_row() -> None:
    audit = build_divergence_audit({}, {})
    audit.tf_1h = _official_state("1h", DivergenceDirection.BEARISH, c_end_index=10)
    audit.tf_15m = _official_state("15m", DivergenceDirection.BULLISH, c_end_index=20)
    audit.selected_last_meaningful_tf = "15m"
    selected = select_last_meaningful_divergence(audit)
    assert selected is audit.tf_15m


def test_if_selected_row_is_not_official_selection_becomes_none() -> None:
    audit = build_divergence_audit({}, {})
    audit.tf_1h = default_divergence_state("1h")
    audit.selected_last_meaningful_tf = "1h"
    selected = select_last_meaningful_divergence(audit)
    assert selected is None


def test_no_official_divergences_gives_selected_last_meaningful_none() -> None:
    audit = build_divergence_audit({}, {})
    assert audit.selected_last_meaningful_tf is None


def test_summary_prints_correct_per_timeframe_labels() -> None:
    audit = build_divergence_audit({}, {})
    audit.tf_15m = _official_state("15m", DivergenceDirection.BEARISH, c_end_index=3)
    summary = divergence_audit_summary(audit)
    assert "4H:No" in summary
    assert "1H:No" in summary
    assert "15m:Bearish" in summary
    assert "5m:No" in summary
    assert "3m:No" in summary


def test_summary_never_prints_checkmark_when_abc_invalid() -> None:
    audit = build_divergence_audit({}, {})
    audit.tf_1h = DivergenceState(
        timeframe="1h",
        exists=True,
        abc_valid=False,
        impulse_confirmed=True,
        direction=DivergenceDirection.BEARISH,
    )
    summary = divergence_audit_summary(audit)
    assert "1H:Bearish✓" not in summary
    assert "1H:Warning" in summary


def test_selected_last_meaningful_ignores_non_official_exists_rows() -> None:
    audit = build_divergence_audit({}, {})
    audit.tf_1h = DivergenceState(
        timeframe="1h",
        exists=True,
        abc_valid=False,
        impulse_confirmed=True,
        direction=DivergenceDirection.BEARISH,
        notes="c_end_index=99",
    )
    audit.tf_15m = _official_state("15m", DivergenceDirection.BULLISH, c_end_index=10)
    selected = select_last_meaningful_divergence(audit)
    assert selected is audit.tf_15m


def test_if_1h_and_15m_are_both_official_both_rows_remain_official() -> None:
    audit = build_divergence_audit({}, {})
    audit.tf_1h = _official_state("1h", DivergenceDirection.BEARISH, c_end_index=10)
    audit.tf_15m = _official_state("15m", DivergenceDirection.BULLISH, c_end_index=11)
    assert audit.tf_1h.exists is True
    assert audit.tf_15m.exists is True


def test_audit_timeframe_divergence_returns_default_when_no_candidate(monkeypatch) -> None:
    structure = _structure("5m")
    vacc = _vacc("5m")

    monkeypatch.setattr("ocean_engine.divergence.divergence_audit.find_abc_candidates", lambda *_: [])
    monkeypatch.setattr("ocean_engine.divergence.divergence_audit.select_latest_abc_candidate", lambda *_: None)

    result = audit_timeframe_divergence("5m", structure, vacc)
    assert result.exists is False
    assert result.grade == DivergenceGrade.INVALID
    assert result.timeframe == "5m"


def test_strict_abc_validator_rejects_official_when_b_reset_fails(monkeypatch) -> None:
    structure = _structure("1h")
    vacc = _vacc("1h")
    fake_candidate = type(
        "FakeABC",
        (),
        {
            "timeframe": "1h",
            "direction": DivergenceDirection.BEARISH,
            "segment_c": None,
            "c_index": 0,
            "abc_valid": True,
        },
    )()

    class _FakeValidation:
        valid = False
        reason = "Segment B reset is not valid."

    monkeypatch.setattr(
        "ocean_engine.divergence.divergence_audit.find_abc_candidates",
        lambda *_args, **_kwargs: [fake_candidate],
    )
    monkeypatch.setattr(
        "ocean_engine.divergence.divergence_audit.select_latest_abc_candidate",
        lambda *_args, **_kwargs: fake_candidate,
    )
    monkeypatch.setattr(
        "ocean_engine.divergence.divergence_audit.validate_abc_for_timeframe",
        lambda *args, **kwargs: _FakeValidation(),
    )

    result = audit_timeframe_divergence_with_validator("1h", structure, vacc)
    assert result.exists is False
    assert result.abc_valid is False
    assert "Strict ABC validator failed" in result.notes
