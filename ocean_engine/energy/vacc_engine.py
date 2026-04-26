"""Deterministic velocity/acceleration (VAcc) signal utilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ocean_engine.models.enums import Direction
from ocean_engine.models.market import Candle, VAccPoint, VAccSeries


@dataclass(slots=True)
class AccelerationCluster:
    """Consecutive acceleration bars with the same sign."""

    start_index: int
    end_index: int
    direction: Direction
    total_area: float


def calculate_velocity(candles: Sequence[Candle], period: int = 21) -> list[float]:
    """Compute price-change velocity over a fixed lookback period."""

    if period <= 0:
        raise ValueError("period must be greater than 0")
    velocity: list[float] = []
    for idx, candle in enumerate(candles):
        if idx < period:
            velocity.append(0.0)
            continue
        previous_close = candles[idx - period].close
        velocity.append((candle.close - previous_close) / float(period))
    return velocity


def ema(values: Sequence[float], smooth: int = 5) -> list[float]:
    """Compute an exponential moving average for a float series."""

    if smooth <= 1:
        return [float(value) for value in values]
    if not values:
        return []
    alpha = 2.0 / float(smooth + 1)
    ema_values: list[float] = [float(values[0])]
    for value in values[1:]:
        ema_values.append(alpha * float(value) + (1.0 - alpha) * ema_values[-1])
    return ema_values


def calculate_acceleration(velocity: Sequence[float]) -> list[float]:
    """Compute first derivative of velocity values."""

    if not velocity:
        return []
    acceleration: list[float] = [0.0]
    for idx in range(1, len(velocity)):
        acceleration.append(float(velocity[idx]) - float(velocity[idx - 1]))
    return acceleration


def calculate_acceleration_clusters(acceleration: Sequence[float]) -> list[AccelerationCluster]:
    """Group contiguous non-zero acceleration bars by sign."""

    clusters: list[AccelerationCluster] = []
    start_index: int | None = None
    direction: Direction | None = None
    total_area = 0.0

    def _flush_cluster(end_index: int) -> None:
        nonlocal start_index, direction, total_area
        if start_index is None or direction is None:
            return
        clusters.append(
            AccelerationCluster(
                start_index=start_index,
                end_index=end_index,
                direction=direction,
                total_area=total_area,
            )
        )
        start_index = None
        direction = None
        total_area = 0.0

    for idx, value in enumerate(acceleration):
        current = float(value)
        if current == 0.0:
            _flush_cluster(idx - 1)
            continue

        current_direction = Direction.UP if current > 0.0 else Direction.DOWN
        if start_index is None:
            start_index = idx
            direction = current_direction
            total_area = abs(current)
            continue

        if current_direction == direction:
            total_area += abs(current)
            continue

        _flush_cluster(idx - 1)
        start_index = idx
        direction = current_direction
        total_area = abs(current)

    _flush_cluster(len(acceleration) - 1)
    return clusters


def calculate_vacc(candles: Sequence[Candle], period: int = 21, smooth: int = 5) -> VAccSeries:
    """Build a VAccSeries by smoothing velocity and acceleration."""

    raw_velocity = calculate_velocity(candles, period=period)
    smoothed_velocity = ema(raw_velocity, smooth=smooth)
    raw_acceleration = calculate_acceleration(smoothed_velocity)
    smoothed_acceleration = ema(raw_acceleration, smooth=smooth)
    # Cluster information is derived from acceleration and can be queried via
    # helper functions without extending model dataclasses yet.
    _ = calculate_acceleration_clusters(smoothed_acceleration)

    points: list[VAccPoint] = []
    for idx, candle in enumerate(candles):
        points.append(
            VAccPoint(
                timestamp=candle.close_time,
                velocity=smoothed_velocity[idx] if idx < len(smoothed_velocity) else 0.0,
                acceleration=smoothed_acceleration[idx] if idx < len(smoothed_acceleration) else 0.0,
            )
        )
    return VAccSeries(timeframe="", points=points)


def get_segment_velocity_energy(
    vacc_series: VAccSeries,
    start_index: int,
    end_index: int,
    direction: Direction | str,
) -> float:
    """Sum directional velocity magnitude for a segment."""

    points = _segment_points(vacc_series, start_index, end_index)
    direction_value = _normalize_direction(direction)
    energy = 0.0
    for point in points:
        energy += _directional_value(point.velocity, direction_value)
    return energy


def get_segment_acceleration_area(
    vacc_series: VAccSeries,
    start_index: int,
    end_index: int,
    direction: Direction | str,
) -> float:
    """Sum directional acceleration magnitude for a segment."""

    points = _segment_points(vacc_series, start_index, end_index)
    direction_value = _normalize_direction(direction)
    area = 0.0
    for point in points:
        area += _directional_value(point.acceleration, direction_value)
    return area


def has_zero_axis_reset(
    vacc_series: VAccSeries,
    start_index: int,
    end_index: int,
    tolerance: float = 0.0,
) -> bool:
    """Detect whether velocity touches/crosses zero in a segment."""

    points = _segment_points(vacc_series, start_index, end_index)
    if not points:
        return False
    threshold = abs(float(tolerance))
    previous_velocity: float | None = None

    for point in points:
        velocity = float(point.velocity)
        if abs(velocity) <= threshold:
            return True
        if previous_velocity is not None:
            crossed = (previous_velocity < -threshold and velocity > threshold) or (
                previous_velocity > threshold and velocity < -threshold
            )
            if crossed:
                return True
        previous_velocity = velocity
    return False


def _normalize_direction(direction: Direction | str) -> Direction:
    if isinstance(direction, Direction):
        normalized = direction
    else:
        normalized = Direction[direction.strip().upper()]
    if normalized not in (Direction.UP, Direction.DOWN):
        raise ValueError("direction must be UP or DOWN")
    return normalized


def _directional_value(value: float, direction: Direction) -> float:
    numeric = float(value)
    if direction == Direction.UP:
        return numeric if numeric > 0.0 else 0.0
    return abs(numeric) if numeric < 0.0 else 0.0


def _segment_points(vacc_series: VAccSeries, start_index: int, end_index: int) -> list[VAccPoint]:
    points = vacc_series.points
    if start_index < 0 or end_index < 0:
        raise ValueError("segment indexes must be non-negative")
    if end_index < start_index:
        raise ValueError("end_index must be greater than or equal to start_index")
    if end_index >= len(points):
        raise ValueError("segment indexes exceed available VAcc points")
    return points[start_index : end_index + 1]
