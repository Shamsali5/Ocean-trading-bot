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
    assert report.framework_audit_trace is not None
    failed_names = {check.name for check in report.framework_audit_trace.failed_checks()}
    assert "Analysis starts from highest timeframe" not in failed_names


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


def test_buy_forced_to_wait_when_high_timeframe_context_missing(tmp_path: Path) -> None:
    config = _config(tmp_path)
    market_data = _market_data(["5m", "3m"])
    report = telegram_runner.build_market_report("BTCUSDT", market_data, config)
    report.decision.final_action = FinalAction.BUY
    report.decision.action = FinalAction.BUY
    report.decision.reason = "Synthetic buy for guard test."

    trace = report.framework_audit_trace
    assert trace is not None
    conditions = telegram_runner.verify_timeframe_order(market_data.keys(), trace)
    telegram_runner.apply_htf_first_guard(report.decision, conditions, trace)

    assert report.decision.final_action == FinalAction.WAIT
    assert report.decision.action == FinalAction.WAIT
    assert "Higher-timeframe context missing; framework v1.2 requires highest-timeframe-first reading." in report.decision.reason


def test_wait_action_not_overridden_when_high_timeframe_context_missing(tmp_path: Path) -> None:
    config = _config(tmp_path)
    market_data = _market_data(["5m", "3m"])
    report = telegram_runner.build_market_report("BTCUSDT", market_data, config)
    report.decision.final_action = FinalAction.WAIT
    report.decision.action = FinalAction.WAIT
    report.decision.reason = "No executable setup."

    trace = report.framework_audit_trace
    assert trace is not None
    conditions = telegram_runner.verify_timeframe_order(market_data.keys(), trace)
    telegram_runner.apply_htf_first_guard(report.decision, conditions, trace)

    assert report.decision.final_action == FinalAction.WAIT
    assert report.decision.reason == "No executable setup."


def test_buy_forced_to_wait_when_parent_current_separation_is_unclear(tmp_path: Path) -> None:
    config = _config(tmp_path)
    market_data = _market_data(config.intervals)
    report = telegram_runner.build_market_report("BTCUSDT", market_data, config)
    report.decision.final_action = FinalAction.BUY
    report.decision.action = FinalAction.BUY
    report.decision.reason = "Synthetic buy for move-separation guard test."

    report.move_context = report.move_context.__class__(
        parent_direction="UP",
        parent_timeframe="4h",
        parent_state="TREND",
        parent_active=True,
        current_direction="UP",
        current_timeframe="15m",
        current_state="TREND",
        current_origin="UNCLEAR",
        current_origin_price_zone=None,
        current_with_parent=None,
        summary="Parent/current separation unclear.",
    )
    trace = report.framework_audit_trace
    assert trace is not None

    telegram_runner.apply_parent_current_separation_guard(
        decision=report.decision,
        move_context=report.move_context,
        trace=trace,
    )

    assert report.decision.final_action == FinalAction.WAIT
    assert report.decision.action == FinalAction.WAIT
    assert "Parent/current move separation unclear" in report.decision.reason


def test_build_market_report_records_range_audit_checks(tmp_path: Path) -> None:
    config = _config(tmp_path)
    market_data = _market_data(config.intervals)
    report = telegram_runner.build_market_report("BTCUSDT", market_data, config)
    trace = report.framework_audit_trace
    assert trace is not None
    names = {check.name for check in trace.checks}
    assert "Range requires at least three sub-level moves" in names
    assert "Range has upper/lower/midpoint" in names
    assert "Range midpoint WAIT rule checked" in names
    assert "Range parent move recorded" in names


def test_build_market_report_records_zone_audit_checks(tmp_path: Path) -> None:
    config = _config(tmp_path)
    market_data = _market_data(config.intervals)
    report = telegram_runner.build_market_report("BTCUSDT", market_data, config)
    trace = report.framework_audit_trace
    assert trace is not None
    names = {check.name for check in trace.checks}
    assert "Supply/demand checked after structure" in names
    assert "Zone status classified" in names
    assert "Zone alignment classified" in names
