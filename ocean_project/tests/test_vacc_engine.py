"""Tests for deterministic velocity-acceleration energy calculations."""

from __future__ import annotations

from ocean_engine.energy.vacc_engine import (
    calculate_acceleration,
    calculate_acceleration_clusters,
    calculate_vacc,
    calculate_velocity,
    get_segment_acceleration_area,
    has_zero_axis_reset,
)
from ocean_engine.models.enums import Direction
from ocean_engine.models.market import Candle


def _make_candles(closes: list[float]) -> list[Candle]:
    candles: list[Candle] = []
    for index, close in enumerate(closes):
        candles.append(
            Candle(
                open_time=index * 60_000,
                open=close,
                high=close,
                low=close,
                close=close,
                volume=1.0,
                close_time=(index + 1) * 60_000 - 1,
            )
        )
    return candles


def test_flat_candles_produce_near_zero_velocity_and_acceleration() -> None:
    candles = _make_candles([100.0] * 40)
    velocity = calculate_velocity(candles, period=21)
    acceleration = calculate_acceleration(velocity)
    series = calculate_vacc(candles, period=21, smooth=5)

    assert all(abs(value) < 1e-12 for value in velocity)
    assert all(abs(value) < 1e-12 for value in acceleration)
    assert all(abs(point.velocity) < 1e-12 for point in series.points)
    assert all(abs(point.acceleration) < 1e-12 for point in series.points)


def test_steady_rising_candles_produce_positive_velocity_after_period() -> None:
    closes = [100.0 + float(i) for i in range(50)]
    candles = _make_candles(closes)
    velocity = calculate_velocity(candles, period=21)

    assert all(value == 0.0 for value in velocity[:21])
    assert all(value > 0.0 for value in velocity[21:])


def test_steady_falling_candles_produce_negative_velocity_after_period() -> None:
    closes = [200.0 - float(i) for i in range(50)]
    candles = _make_candles(closes)
    velocity = calculate_velocity(candles, period=21)

    assert all(value == 0.0 for value in velocity[:21])
    assert all(value < 0.0 for value in velocity[21:])


def test_acceleration_clusters_are_detected() -> None:
    closes = [10.0, 10.0, 10.0, 12.0, 12.0, 12.0, 8.0, 8.0, 8.0]
    candles = _make_candles(closes)
    series = calculate_vacc(candles, period=1, smooth=1)
    acceleration = [point.acceleration for point in series.points]
    clusters = calculate_acceleration_clusters(acceleration)

    # close diffs: [0, 0, +2, 0, 0, -4, 0, 0]
    # acceleration: [0, 0, +2, -2, 0, -4, +4, 0, ...]
    # Should produce both UP and DOWN clusters with positive areas.
    assert clusters
    directions = {cluster.direction for cluster in clusters}
    assert Direction.UP in directions
    assert Direction.DOWN in directions
    assert all(cluster.total_area > 0.0 for cluster in clusters)


def test_segment_acceleration_area_positive_for_matching_direction() -> None:
    closes = [100.0, 102.0, 105.0, 109.0, 114.0, 120.0]
    candles = _make_candles(closes)
    series = calculate_vacc(candles, period=1, smooth=1)

    up_area = get_segment_acceleration_area(series, 0, len(series.points) - 1, Direction.UP)
    down_area = get_segment_acceleration_area(series, 0, len(series.points) - 1, Direction.DOWN)

    assert up_area > 0.0
    assert down_area == 0.0


def test_has_zero_axis_reset_true_when_velocity_crosses_zero() -> None:
    closes = [100.0, 104.0, 108.0, 104.0, 100.0, 96.0, 92.0]
    candles = _make_candles(closes)
    series = calculate_vacc(candles, period=1, smooth=1)

    assert has_zero_axis_reset(series, 0, len(series.points) - 1)
