"""Tests for structure engine wrapper orchestration."""

from __future__ import annotations

from ocean_engine.models.market import Candle, TimeframeData
from ocean_engine.structure.structure_engine import analyze_all_structures, analyze_structure


def _make_timeframe_data(timeframe: str, closes: list[float]) -> TimeframeData:
    candles: list[Candle] = []
    for idx, close in enumerate(closes):
        candles.append(
            Candle(
                open_time=idx * 60_000,
                open=close,
                high=close + 1.0,
                low=max(close - 1.0, 0.0001),
                close=close,
                volume=1.0,
                close_time=(idx + 1) * 60_000 - 1,
            )
        )
    return TimeframeData(timeframe=timeframe, candles=candles)


def test_analyze_structure_returns_structure_state() -> None:
    data = _make_timeframe_data("3m", [100.0 + float(i) for i in range(40)])
    state = analyze_structure(data, pivot_left=1, pivot_right=1, min_leg_bars=2, range_min_legs=3)
    assert state.timeframe == "3m"


def test_current_price_equals_last_candle_close() -> None:
    closes = [100.0, 101.0, 102.5]
    data = _make_timeframe_data("5m", closes)
    state = analyze_structure(data, pivot_left=1, pivot_right=1, min_leg_bars=1, range_min_legs=3)
    assert state.current_price == closes[-1]


def test_swings_and_legs_populated_for_simple_data() -> None:
    closes = [100.0, 95.0, 90.0, 94.0, 99.0, 105.0, 100.0, 95.0, 90.0, 94.0, 100.0, 106.0]
    data = _make_timeframe_data("15m", closes)
    state = analyze_structure(data, pivot_left=1, pivot_right=1, min_leg_bars=2, range_min_legs=3)
    assert len(state.swings) >= 2
    assert len(state.legs) >= 1


def test_active_leg_is_selected() -> None:
    closes = [100.0, 95.0, 90.0, 95.0, 100.0, 105.0, 100.0, 95.0, 90.0, 95.0, 100.0, 105.0]
    data = _make_timeframe_data("1h", closes)
    state = analyze_structure(data, pivot_left=1, pivot_right=1, min_leg_bars=2, range_min_legs=3)
    assert state.active_leg is not None
    assert state.active_leg.is_active is True


def test_range_state_is_included() -> None:
    closes = [100.0, 95.0, 90.0, 95.0, 100.0, 105.0, 100.0, 95.0, 90.0, 95.0, 100.0, 105.0]
    data = _make_timeframe_data("1h", closes)
    state = analyze_structure(data, pivot_left=1, pivot_right=1, min_leg_bars=2, range_min_legs=3)
    assert state.range_state is not None


def test_market_state_range_when_active_range_contains_price(monkeypatch) -> None:
    data = _make_timeframe_data("4h", [100.0, 99.0, 98.0, 99.0, 100.0, 101.0])

    class _FakeRange:
        active = True
        price_location = "MID"

    monkeypatch.setattr(
        "ocean_engine.structure.structure_engine.detect_range_from_legs",
        lambda *args, **kwargs: _FakeRange(),
    )
    state = analyze_structure(data, pivot_left=1, pivot_right=1, min_leg_bars=1, range_min_legs=3)
    assert state.market_state.name == "RANGE"


def test_market_state_transition_when_active_range_price_outside(monkeypatch) -> None:
    data = _make_timeframe_data("4h", [100.0, 99.0, 98.0, 99.0, 100.0, 101.0])

    class _FakeRange:
        active = True
        price_location = "OUTSIDE"

    monkeypatch.setattr(
        "ocean_engine.structure.structure_engine.detect_range_from_legs",
        lambda *args, **kwargs: _FakeRange(),
    )
    state = analyze_structure(data, pivot_left=1, pivot_right=1, min_leg_bars=1, range_min_legs=3)
    assert state.market_state.name == "TRANSITION"


def test_analyze_all_structures_preserves_timeframe_keys() -> None:
    market_data = {
        "3m": _make_timeframe_data("3m", [100.0, 99.0, 98.0, 99.0, 100.0, 101.0]),
        "5m": _make_timeframe_data("5m", [200.0, 198.0, 196.0, 198.0, 201.0, 203.0]),
    }
    structures = analyze_all_structures(market_data)
    assert set(structures.keys()) == {"3m", "5m"}
