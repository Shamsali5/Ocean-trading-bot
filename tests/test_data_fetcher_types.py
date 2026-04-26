"""Type-focused tests for Binance OHLCV conversion helpers."""

from ocean_engine.data.binance_fetcher import fetch_timeframe, kline_to_candle
from ocean_engine.models.market import Candle


def test_kline_to_candle_converts_binance_row_types() -> None:
    """The converter should cast Binance kline fields to typed Candle values."""

    fake_row = [
        "1714000000000",
        "65321.10",
        "65444.00",
        "65000.50",
        "65210.20",
        "1234.567",
        "1714000179999",
    ]
    candle = kline_to_candle(fake_row)

    assert isinstance(candle, Candle)
    assert candle.open_time == 1714000000000
    assert candle.open == 65321.10
    assert candle.high == 65444.00
    assert candle.low == 65000.50
    assert candle.close == 65210.20
    assert candle.volume == 1234.567
    assert candle.close_time == 1714000179999


def test_fetch_timeframe_wraps_candles(monkeypatch) -> None:
    """Fetcher should return TimeframeData populated with Candle objects."""

    fake_payload = [
        ["1714000000000", "100", "110", "90", "105", "10", "1714000179999"],
        ["1714000180000", "105", "120", "100", "118", "12", "1714000359999"],
    ]

    def _fake_fetch_futures_klines(symbol: str, interval: str, limit: int) -> list[list]:
        assert symbol == "BTCUSDT"
        assert interval == "3m"
        assert limit == 2
        return fake_payload

    monkeypatch.setattr(
        "ocean_engine.data.binance_fetcher.fetch_futures_klines",
        _fake_fetch_futures_klines,
    )

    timeframe_data = fetch_timeframe(symbol="BTCUSDT", interval="3m", limit=2)
    assert timeframe_data.timeframe == "3m"
    assert len(timeframe_data.candles) == 2
    assert all(isinstance(candle, Candle) for candle in timeframe_data.candles)
