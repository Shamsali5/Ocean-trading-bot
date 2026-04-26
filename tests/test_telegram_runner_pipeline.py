"""Tests for deterministic Telegram runner pipeline orchestration."""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

import pytest

from ocean_engine.config import OceanConfig
from ocean_engine.models.enums import FinalAction
from ocean_engine.models.market import Candle, DecisionState, MarketReport, TimeframeData, VAccSeries
from ocean_engine.runners import telegram_runner


def _timeframe_minutes(label: str) -> int:
    if label.endswith("m"):
        return int(label[:-1])
    if label.endswith("h"):
        return int(label[:-1]) * 60
    return 1


def _candles(count: int, timeframe: str, base: float = 100.0) -> list[Candle]:
    interval_ms = _timeframe_minutes(timeframe) * 60_000
    candles: list[Candle] = []
    for idx in range(count):
        close = base + idx * 0.35 + (0.25 if idx % 2 else -0.20)
        open_price = close - 0.10
        high = max(open_price, close) + 0.20
        low = min(open_price, close) - 0.20
        open_time = idx * interval_ms
        close_time = open_time + interval_ms - 1
        candles.append(
            Candle(
                open_time=open_time,
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=1000.0 + idx,
                close_time=close_time,
            )
        )
    return candles


def _market_data(intervals: list[str]) -> dict[str, TimeframeData]:
    return {tf: TimeframeData(timeframe=tf, candles=_candles(64, tf, base=100.0 + len(tf))) for tf in intervals}


def _config(tmp_path: Path) -> OceanConfig:
    intervals = ["3m", "5m", "15m", "1h", "4h"]
    return OceanConfig(
        symbols=["BTCUSDT"],
        intervals=intervals,
        candle_limits={tf: 100 for tf in intervals},
        data_dir=tmp_path / "ohlcv_data",
        results_dir=tmp_path / "analysis_results",
        vacc_period=21,
        vacc_smooth=5,
        telegram_mode="compact",
        run_every_half_hour=False,
        position_mode="UNKNOWN",
    )


def test_build_vacc_map_returns_series_per_timeframe(tmp_path: Path) -> None:
    config = _config(tmp_path)
    market_data = _market_data(config.intervals)

    vacc_map = telegram_runner.build_vacc_map(market_data, period=5, smooth=3)

    assert set(vacc_map.keys()) == set(config.intervals)
    for timeframe, series in vacc_map.items():
        assert isinstance(series, VAccSeries)
        assert series.timeframe == timeframe
        assert len(series.points) == len(market_data[timeframe].candles)


def test_build_market_report_contains_pipeline_outputs(tmp_path: Path) -> None:
    config = _config(tmp_path)
    market_data = _market_data(config.intervals)

    report = telegram_runner.build_market_report("BTCUSDT", market_data, config)

    assert isinstance(report, MarketReport)
    assert report.structures
    assert report.divergence_audit is not None
    assert report.active_trade_audit is not None
    assert report.multi_level_story is not None
    assert report.decision is not None
    assert report.current_price == market_data["3m"].candles[-1].close


def test_run_once_with_mocked_fetch_and_sender_returns_reports(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    sent_messages: list[str] = []
    market_data = _market_data(config.intervals)

    monkeypatch.setattr(telegram_runner, "load_config", lambda: config)
    monkeypatch.setattr(telegram_runner, "fetch_all_timeframes", lambda *_args, **_kwargs: market_data)
    monkeypatch.setattr(telegram_runner, "save_all_timeframes", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(telegram_runner, "format_compact_telegram_report", lambda *_args, **_kwargs: "formatted-report")
    monkeypatch.setattr(
        telegram_runner,
        "send_telegram_message",
        lambda message, *_args, **_kwargs: sent_messages.append(message) or [{"ok": True}],
    )

    reports = telegram_runner.run_once(send_telegram=True)

    assert len(reports) == 1
    assert isinstance(reports[0], MarketReport)
    assert sent_messages == ["formatted-report"]


def test_run_once_without_telegram_does_not_send(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    market_data = _market_data(config.intervals)

    monkeypatch.setattr(telegram_runner, "load_config", lambda: config)
    monkeypatch.setattr(telegram_runner, "fetch_all_timeframes", lambda *_args, **_kwargs: market_data)
    monkeypatch.setattr(telegram_runner, "save_all_timeframes", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(telegram_runner, "format_compact_telegram_report", lambda *_args, **_kwargs: "formatted-report")

    def _must_not_send(*_args, **_kwargs):
        raise AssertionError("send_telegram_message must not be called when send_telegram=False")

    monkeypatch.setattr(telegram_runner, "send_telegram_message", _must_not_send)

    reports = telegram_runner.run_once(send_telegram=False)
    assert len(reports) == 1


def test_save_market_report_writes_json_file(tmp_path: Path) -> None:
    report = MarketReport(
        symbol="BTCUSDT",
        timestamp="2026-04-26T07:00:00Z",
        summary="deterministic summary",
        decision=DecisionState(symbol="BTCUSDT", final_action=FinalAction.WAIT),
    )

    output_path = telegram_runner.save_market_report(report, tmp_path)
    assert output_path.exists()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["symbol"] == "BTCUSDT"
    assert payload["decision"]["final_action"] == "WAIT"


def test_runner_module_does_not_import_openai() -> None:
    source = inspect.getsource(telegram_runner)
    tree = ast.parse(source)

    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])

    assert "openai" not in imported_roots
    assert "import openai" not in source.lower()


def test_openai_api_key_not_required_for_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    market_data = _market_data(config.intervals)

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(telegram_runner, "load_config", lambda: config)
    monkeypatch.setattr(telegram_runner, "fetch_all_timeframes", lambda *_args, **_kwargs: market_data)
    monkeypatch.setattr(telegram_runner, "save_all_timeframes", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(telegram_runner, "format_compact_telegram_report", lambda *_args, **_kwargs: "formatted-report")
    monkeypatch.setattr(telegram_runner, "send_telegram_message", lambda *_args, **_kwargs: [{"ok": True}])

    reports = telegram_runner.run_once(send_telegram=False)
    assert len(reports) == 1
