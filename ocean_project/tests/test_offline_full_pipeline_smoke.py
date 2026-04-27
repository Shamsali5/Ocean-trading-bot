"""Offline full-pipeline deterministic smoke test (no Binance/Telegram/OpenAI)."""

from __future__ import annotations

import json
from pathlib import Path

from ocean_engine.config import OceanConfig
from ocean_engine.models.enums import FinalAction
from ocean_engine.models.market import Candle, MarketReport, TimeframeData
from ocean_engine.output.telegram_formatter import format_compact_telegram_report
from ocean_engine.runners.telegram_runner import build_market_report, save_market_report


def _tf_minutes(label: str) -> int:
    if label.endswith("m"):
        return int(label[:-1])
    if label.endswith("h"):
        return int(label[:-1]) * 60
    return 1


def _synthetic_candles(timeframe: str, count: int, base: float) -> list[Candle]:
    interval_ms = _tf_minutes(timeframe) * 60_000
    candles: list[Candle] = []
    for idx in range(count):
        wave = 0.9 if idx % 6 in (0, 1, 2) else -0.7
        close = base + idx * 0.18 + wave
        open_price = close - 0.12
        high = max(open_price, close) + 0.25
        low = min(open_price, close) - 0.25
        open_time = idx * interval_ms
        close_time = open_time + interval_ms - 1
        candles.append(
            Candle(
                open_time=open_time,
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=1_000.0 + idx,
                close_time=close_time,
            )
        )
    return candles


def _offline_market_data() -> dict[str, TimeframeData]:
    timeframes = ["3m", "5m", "15m", "1h", "4h"]
    return {
        timeframe: TimeframeData(
            timeframe=timeframe,
            candles=_synthetic_candles(timeframe=timeframe, count=96, base=100.0 + rank * 10.0),
        )
        for rank, timeframe in enumerate(timeframes, start=1)
    }


def _offline_config(tmp_path: Path) -> OceanConfig:
    intervals = ["3m", "5m", "15m", "1h", "4h"]
    return OceanConfig(
        symbols=["BTCUSDT"],
        intervals=intervals,
        candle_limits={tf: 96 for tf in intervals},
        data_dir=tmp_path / "ohlcv_data",
        results_dir=tmp_path / "analysis_results",
        vacc_period=21,
        vacc_smooth=5,
        telegram_mode="compact",
        run_every_half_hour=False,
        position_mode="UNKNOWN",
    )


def test_offline_full_pipeline_smoke(tmp_path: Path) -> None:
    config = _offline_config(tmp_path)
    market_data = _offline_market_data()

    report = build_market_report(symbol="BTCUSDT", market_data=market_data, config=config)
    assert isinstance(report, MarketReport)
    assert report.decision is not None
    assert isinstance(report.decision.final_action, FinalAction)
    assert report.structures
    assert report.divergence_audit is not None
    assert report.active_trade_audit is not None
    assert report.multi_level_story is not None

    compact = format_compact_telegram_report(report)
    assert "A META" in compact
    assert "C CURRENT_MOVE" in compact
    assert "Q CURRENT_MOVE_SUMM" in compact

    saved_path = save_market_report(report, config.results_dir)
    assert saved_path.exists()
    payload = json.loads(saved_path.read_text(encoding="utf-8"))
    assert payload["symbol"] == "BTCUSDT"
    assert payload["decision"]["final_action"] == report.decision.final_action.value
