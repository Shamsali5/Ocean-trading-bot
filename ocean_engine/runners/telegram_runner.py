"""Deterministic Telegram runner for the full market pipeline."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from ocean_engine.config import OceanConfig, load_config
from ocean_engine.data.binance_fetcher import fetch_all_timeframes
from ocean_engine.data.ohlcv_store import save_all_timeframes
from ocean_engine.divergence.divergence_audit import build_divergence_audit
from ocean_engine.energy.vacc_engine import calculate_vacc
from ocean_engine.models.market import (
    ActiveTradeAudit,
    ActiveTradeCandidate,
    DivergenceAudit,
    MarketReport,
    TimeframeData,
    VAccSeries,
)
from ocean_engine.output.telegram_formatter import format_compact_telegram_report
from ocean_engine.output.telegram_sender import send_telegram_message
from ocean_engine.structure.structure_engine import analyze_all_structures
from ocean_engine.trade.active_trade_engine import build_active_trade_audit
from ocean_engine.trade.decision_engine import build_decision_state
from ocean_engine.trade.multi_level_engine import build_multi_level_story
from ocean_engine.zones.supply_demand_engine import detect_supply_demand_zones

_TF_TO_FIELD = {
    "4h": "tf_4h",
    "1h": "tf_1h",
    "15m": "tf_15m",
    "5m": "tf_5m",
    "3m": "tf_3m",
}


def build_vacc_map(
    market_data: dict[str, TimeframeData],
    period: int,
    smooth: int,
) -> dict[str, VAccSeries]:
    """Build per-timeframe VAcc series from fetched candles."""

    vacc_map: dict[str, VAccSeries] = {}
    for timeframe, timeframe_data in market_data.items():
        series = calculate_vacc(timeframe_data.candles, period=period, smooth=smooth)
        series.timeframe = timeframe
        vacc_map[timeframe] = series
    return vacc_map


def build_market_report(
    symbol: str,
    market_data: dict[str, TimeframeData],
    config: OceanConfig,
) -> MarketReport:
    """Run full deterministic analysis pipeline for one symbol."""

    timestamp = datetime.now(timezone.utc).isoformat()
    current_price = _resolve_current_price(market_data)

    structures = analyze_all_structures(market_data)
    vacc_map = build_vacc_map(market_data, config.vacc_period, config.vacc_smooth)
    divergence_audit = build_divergence_audit(structures, vacc_map)
    zones = detect_supply_demand_zones(structures, divergence_audit)
    active_trade_audit = build_active_trade_audit(structures, divergence_audit)
    multi_level_story = build_multi_level_story(divergence_audit, active_trade_audit)
    decision = build_decision_state(
        structures=structures,
        divergence_audit=divergence_audit,
        active_trade_audit=active_trade_audit,
        multi_level_story=multi_level_story,
        zones=zones,
    )

    selected = _selected_active_trade(active_trade_audit)
    selected_label = selected.type_label if selected is not None else "None"
    summary = f"{symbol} {decision.final_action.value} | active={selected_label} | reason={decision.reason or 'N/A'}"

    return MarketReport(
        symbol=symbol,
        generated_at=timestamp,
        timestamp=timestamp,
        current_price=current_price,
        timeframe_data=market_data,
        structure=structures,
        structures=structures,
        ranges={tf: state.range_state for tf, state in structures.items() if state.range_state is not None},
        vacc=vacc_map,
        divergences=_divergence_rows(divergence_audit),
        divergence_audit=divergence_audit,
        divergence_audits=[divergence_audit],
        zones=zones,
        active_trade_audit=active_trade_audit,
        active_trade_audits=[active_trade_audit],
        multi_level_story=multi_level_story,
        story=multi_level_story,
        decision=decision,
        summary=summary,
    )


def run_once(send_telegram: bool = True) -> list[MarketReport]:
    """Fetch data, build reports, optionally send Telegram output once."""

    config = load_config()
    reports: list[MarketReport] = []
    for symbol in config.symbols:
        market_data = fetch_all_timeframes(symbol, config.intervals, config.candle_limits)
        save_all_timeframes(symbol, market_data, config.data_dir)

        report = build_market_report(symbol, market_data, config)
        rendered = format_compact_telegram_report(report)
        if send_telegram:
            send_telegram_message(rendered)
        save_market_report(report, config.results_dir)
        reports.append(report)
    return reports


def save_market_report(report: MarketReport, results_dir: Path) -> Path:
    """Persist one market report into ``results_dir/{symbol}`` as JSON."""

    symbol = report.symbol.upper().strip() or "UNKNOWN"
    safe_timestamp = (report.timestamp or report.generated_at or datetime.now(timezone.utc).isoformat()).replace(":", "-")
    symbol_dir = results_dir / symbol
    symbol_dir.mkdir(parents=True, exist_ok=True)
    output_path = symbol_dir / f"{safe_timestamp}_report.json"
    payload = _json_safe(report)
    output_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    return output_path


def main() -> None:
    """Run deterministic runner once or every 30 minutes."""

    config = load_config()
    if config.run_every_half_hour:
        while True:
            reports = run_once(send_telegram=True)
            _print_console_summary(reports)
            print("Sleeping 30 minutes before next deterministic run.")
            time.sleep(30 * 60)

    reports = run_once(send_telegram=True)
    _print_console_summary(reports)


def _resolve_current_price(market_data: dict[str, TimeframeData]) -> float | None:
    candidates: list[tuple[int, float]] = []
    for timeframe, timeframe_data in market_data.items():
        if not timeframe_data.candles:
            continue
        candidates.append((_timeframe_minutes(timeframe), timeframe_data.candles[-1].close))
    if not candidates:
        return None
    candidates.sort(key=lambda row: row[0])
    return candidates[0][1]


def _timeframe_minutes(label: str) -> int:
    text = label.strip().lower()
    if text.endswith("m"):
        return int(text[:-1])
    if text.endswith("h"):
        return int(text[:-1]) * 60
    if text.endswith("d"):
        return int(text[:-1]) * 60 * 24
    return 10_000


def _selected_active_trade(audit: ActiveTradeAudit) -> ActiveTradeCandidate | None:
    timeframe = audit.selected_active_trade_tf
    if timeframe is None:
        return None
    field = _TF_TO_FIELD.get(timeframe)
    if field is None:
        return None
    candidate = getattr(audit, field)
    return candidate if candidate.exists else None


def _divergence_rows(audit: DivergenceAudit) -> dict[str, Any]:
    return {tf: getattr(audit, field) for tf, field in _TF_TO_FIELD.items()}


def _json_safe(value: Any) -> Any:
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(inner) for key, inner in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return value


def _print_console_summary(reports: list[MarketReport]) -> None:
    if not reports:
        print("No reports produced.")
        return
    print(f"Deterministic runner produced {len(reports)} report(s).")
    for report in reports:
        action = report.decision.final_action.value if report.decision is not None else "WAIT"
        print(f"- {report.symbol}: {action} | {report.summary}")


if __name__ == "__main__":
    main()
