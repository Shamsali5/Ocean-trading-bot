from __future__ import annotations

from .types import Candle


def sma(values: list[float], period: int) -> list[float | None]:
    if period <= 0:
        raise ValueError("period must be positive")

    out: list[float | None] = []
    window_sum = 0.0
    for idx, value in enumerate(values):
        window_sum += value
        if idx >= period:
            window_sum -= values[idx - period]
        if idx + 1 < period:
            out.append(None)
        else:
            out.append(window_sum / period)
    return out


def calculate_vacc(candles: list[Candle], velocity_period: int = 21, smooth_period: int = 5) -> dict[str, list[float]]:
    closes = [c.close for c in candles]
    raw_velocity: list[float] = []
    for idx, close in enumerate(closes):
        if idx < velocity_period:
            raw_velocity.append(0.0)
        else:
            raw_velocity.append(close - closes[idx - velocity_period])

    smoothed_velocity = sma(raw_velocity, smooth_period)
    velocity = [0.0 if value is None else value for value in smoothed_velocity]

    acceleration: list[float] = []
    for idx, value in enumerate(velocity):
        prev = velocity[idx - 1] if idx else value
        acceleration.append(value - prev)

    acceleration_area: list[float] = []
    running = 0.0
    side = 0
    for value in acceleration:
        current_side = 1 if value > 0 else -1 if value < 0 else side
        if current_side != side:
            running = 0.0
            side = current_side
        running += value
        acceleration_area.append(running)

    return {
        "velocity": velocity,
        "acceleration": acceleration,
        "acceleration_area": acceleration_area,
    }


def vacc_series(candles: list[Candle], velocity_period: int = 21, smooth_period: int = 5) -> dict[str, list[float]]:
    return calculate_vacc(candles, velocity_period, smooth_period)
