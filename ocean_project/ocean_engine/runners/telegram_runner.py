"""Deterministic Telegram runner for the full market pipeline."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from ocean_framework_v12_audit import FrameworkAuditTrace
from ocean_engine.config import OceanConfig, load_config
from ocean_engine.data.binance_fetcher import fetch_all_timeframes
from ocean_engine.data.ohlcv_store import save_all_timeframes
from ocean_engine.divergence.divergence_audit import build_divergence_audit
from ocean_engine.energy.vacc_engine import calculate_vacc
from ocean_engine.models.enums import FinalAction
from ocean_engine.models.market import (
    ActiveTradeAudit,
    ActiveTradeCandidate,
    DivergenceAudit,
    MarketReport,
    MoveContext,
    TimeframeData,
    VAccSeries,
)
from ocean_output_validator import validate_required_output_sections
from ocean_engine.output.telegram_formatter import format_compact_telegram_report
from ocean_engine.output.telegram_sender import send_telegram_message
from ocean_engine.structure.structure_engine import analyze_all_structures
from ocean_engine.trade.active_trade_engine import build_active_trade_audit
from ocean_engine.trade.decision_engine import build_decision_state
from ocean_engine.trade.multi_level_engine import build_multi_level_story
from ocean_engine.trade.story_engine import build_story_state
from ocean_engine.zones.supply_demand_engine import detect_supply_demand_zones

_TF_TO_FIELD = {
    "4h": "tf_4h",
    "1h": "tf_1h",
    "15m": "tf_15m",
    "5m": "tf_5m",
    "3m": "tf_3m",
}
_FRAMEWORK_TF_PRIORITY = ("1d", "12h", "4h", "1h", "15m", "5m", "3m")
_FRAMEWORK_ACTIONS_REQUIRING_CONTEXT = {
    FinalAction.BUY,
    FinalAction.SELL,
    FinalAction.CLOSE_LONG,
    FinalAction.CLOSE_SHORT,
    FinalAction.CLOSE_AND_FLIP,
}
_FRESH_ENTRY_ACTIONS = {FinalAction.BUY, FinalAction.SELL}


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
    trace = FrameworkAuditTrace(symbol=symbol, timestamp=timestamp)
    analysis_timeframes = _ordered_timeframes_for_analysis(market_data.keys())
    ordered_tfs, highest_tf, htf_start_ok, parent_context_available = verify_timeframe_order(
        available_timeframes=analysis_timeframes,
        trace=trace,
    )
    trace.add_check(
        name="Analysis starts from highest timeframe",
        passed=htf_start_ok,
        severity="ERROR" if not htf_start_ok else "INFO",
        details=(
            f"Pipeline order: {', '.join(ordered_tfs)}"
            if ordered_tfs
            else "No timeframe data provided."
        ),
        file=__file__,
        function="build_market_report",
    )

    ordered_market_data = {
        tf: market_data[tf]
        for tf in ordered_tfs
        if tf in market_data
    }
    if not ordered_market_data:
        ordered_market_data = dict(market_data)
    current_price = _resolve_current_price(market_data)

    structures = analyze_all_structures(ordered_market_data, trace=trace)
    vacc_map = build_vacc_map(ordered_market_data, config.vacc_period, config.vacc_smooth)
    divergence_audit = build_divergence_audit(structures, vacc_map, trace=trace)
    zones = detect_supply_demand_zones(structures, divergence_audit, trace=trace)
    active_trade_audit = build_active_trade_audit(structures, divergence_audit, trace=trace)
    multi_level_story = build_multi_level_story(
        divergence_audit,
        active_trade_audit,
        trace=trace,
    )
    story_state = build_story_state(
        structures=structures,
        divergence_audit=divergence_audit,
        active_trade_audit=active_trade_audit,
        multi_level_story=multi_level_story,
        range_states={tf: state.range_state for tf, state in structures.items()},
        zones=zones if isinstance(zones, list) else [],
    )
    move_context = story_state.move_context or MoveContext()
    _add_move_context_checks(trace, move_context)
    decision = build_decision_state(
        structures=structures,
        divergence_audit=divergence_audit,
        active_trade_audit=active_trade_audit,
        multi_level_story=multi_level_story,
        zones=zones,
        position_mode=config.position_mode,
        move_context=move_context,
    )
    apply_htf_first_guard(
        decision=decision,
        conditions=(ordered_tfs, highest_tf, htf_start_ok, parent_context_available),
        trace=trace,
    )
    apply_parent_current_separation_guard(
        decision=decision,
        move_context=move_context,
        trace=trace,
    )

    selected = _selected_active_trade(active_trade_audit)
    selected_divergence = _selected_meaningful_divergence(divergence_audit)
    selected_divergence_tf = _text_or_na(getattr(selected_divergence, "timeframe", None))
    selected_divergence_direction = _text_or_na(
        getattr(getattr(selected_divergence, "direction", None), "value", getattr(selected_divergence, "direction", None))
    )
    selected_divergence_impulse = bool(getattr(selected_divergence, "impulse_confirmed", False))
    selected_carry_state = _text_or_na(
        getattr(getattr(selected, "carry_state", None), "value", getattr(selected, "carry_state", None))
    )
    selected_carry_tf = _text_or_na(
        getattr(selected, "carry_timeframe", None) or getattr(story_state, "carrying_timeframe", None)
    )
    selected_trade_function = _text_or_na(
        getattr(getattr(selected, "trade_function", None), "value", getattr(selected, "trade_function", None)),
        default="NONE",
    )
    selected_type_label = _text_or_na(getattr(selected, "type_label", None))
    selected_entry_zone = _text_or_na(getattr(selected, "origin_price_zone", None))
    selected_invalidation = _text_or_na(getattr(selected, "invalidation", None))
    controlling_origin = _text_or_na(getattr(story_state, "controlling_origin", None))
    active_execution_trade = _text_or_na(getattr(story_state, "active_execution_trade", None))
    carrying_timeframe = _text_or_na(getattr(story_state, "carrying_timeframe", None))
    management_state = _text_or_na(decision.management_state)
    decision_reason = _text_or_na(decision.reason)
    final_action_text = decision.final_action.value.replace("_", " ")
    selected_label = selected.type_label if selected is not None else "None"
    summary = f"{symbol} {decision.final_action.value} | active={selected_label} | reason={decision.reason or 'N/A'}"

    output_snapshot = {
        "A META": {
            "symbol": symbol,
            "timestamp": timestamp,
            "current_price": current_price,
        },
        "B HIGHER_TIMEFRAME_CONTEXT": {
            "highest_tf": _text_or_na(highest_tf),
            "highest_timeframe": _text_or_na(highest_tf),
            "ordered_timeframes": ordered_tfs,
            "htf_start_ok": htf_start_ok,
            "parent_context_available": parent_context_available,
        },
        "C CURRENT_MOVE": {
            "timeframe": _text_or_na(move_context.current_timeframe),
            "direction": _text_or_na(move_context.current_direction),
            "origin": _text_or_na(move_context.current_origin),
        },
        "D STRUCTURE_STATE": {
            "state": _text_or_na(move_context.current_state),
            "structures": structures,
        },
        "E DIVERGENCE_STATE": {
            "direction": selected_divergence_direction,
            "divergence_audit": divergence_audit,
        },
        "F LAST_MEANINGFUL_DIVERGENCE": {
            "timeframe": selected_divergence_tf,
            "direction": selected_divergence_direction,
            "selected_last_meaningful_tf": _text_or_na(divergence_audit.selected_last_meaningful_tf),
        },
        "G IMPULSE_ACCEPTANCE": {
            "impulse_confirmed": selected_divergence_impulse,
            "decision_action": decision.final_action.value,
        },
        "H SUPPLY_DEMAND_ZONE_MAP": {"zones": zones},
        "I CARRY_STATUS": {
            "state": selected_carry_state,
            "carrying_tf": selected_carry_tf,
            "selected_carrying_timeframe": _text_or_na(decision.carrying_timeframe),
        },
        "J MULTI_LEVEL_STORY": {
            "controlling_origin": controlling_origin,
            "multi_level_story": multi_level_story,
        },
        "K TRADE_CLASSIFICATION": {
            "trade_function": selected_trade_function,
            "type_label": selected_type_label,
            "active_trade_label": _text_or_na(decision.active_trade_label),
        },
        "L MANAGEMENT_STATE": {"management_state": management_state},
        "M CURRENT_ACTIVE_MEANINGFUL_TRADE": {
            "exists": selected is not None,
            "selected_active_trade_tf": _text_or_na(active_trade_audit.selected_active_trade_tf),
        },
        "N POSITION_MANAGEMENT_FOR_ACTIVE_TRADE": {
            "already_in_status": _position_action_if_already_in(final_action_text),
            "not_in_status": _position_action_if_not_in(final_action_text),
            "final_action": final_action_text,
        },
        "O MARKET_HIERARCHY": {
            "controlling_origin": controlling_origin,
            "active_execution_trade": active_execution_trade,
            "carrying_timeframe": carrying_timeframe,
        },
        "P WHAT_TO_WATCH_NEXT": {
            "next_event": _text_or_na(decision.reason),
            "summary": summary,
        },
        "Q CURRENT_MOVE_SUMMARY": {"summary": summary},
        "R FINAL_EXECUTION_BLOCK": {
            "Signal": final_action_text,
            "Trade Function": selected_trade_function,
            "Type Label": selected_type_label,
            "Controlling Origin": controlling_origin,
            "Active Execution Trade": active_execution_trade,
            "Entry Zone": selected_entry_zone,
            "Stop / Invalidation": selected_invalidation,
            "Carrying TF": carrying_timeframe,
            "Management State": management_state,
            "Reason": decision_reason,
        },
    }
    validate_required_output_sections(output_snapshot, trace=trace)

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
        story_state=story_state,
        move_context=move_context,
        decision=decision,
        framework_audit_trace=trace,
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


def verify_timeframe_order(
    available_timeframes: list[str],
    trace: FrameworkAuditTrace,
) -> tuple[list[str], str | None, bool, bool]:
    """Validate highest-timeframe-first ordering against framework priority."""

    normalized_unique: list[str] = []
    seen: set[str] = set()
    for raw in available_timeframes:
        normalized = _normalize_timeframe_label(raw)
        if normalized in _FRAMEWORK_TF_PRIORITY and normalized not in seen:
            normalized_unique.append(normalized)
            seen.add(normalized)

    ordered = [tf for tf in _FRAMEWORK_TF_PRIORITY if tf in seen]
    highest = ordered[0] if ordered else None
    trace.add_check(
        name="Highest timeframe detected",
        passed=highest is not None,
        severity="ERROR" if highest is None else "INFO",
        details=f"Highest relevant timeframe: {highest}" if highest else "No framework timeframe detected.",
        file=__file__,
        function="verify_timeframe_order",
    )

    starts_from_highest = not ordered or normalized_unique[:1] == ordered[:1]
    if len(ordered) >= 2:
        lowest = ordered[-1]
        highest_idx = normalized_unique.index(ordered[0]) if ordered[0] in normalized_unique else 0
        lowest_idx = normalized_unique.index(lowest) if lowest in normalized_unique else 0
        starts_from_highest = starts_from_highest and highest_idx <= lowest_idx

    parent_context_available = _has_parent_context(ordered)
    return (ordered, highest, starts_from_highest, parent_context_available)


def apply_htf_first_guard(
    decision: Any,
    conditions: tuple[list[str], str | None, bool, bool],
    trace: FrameworkAuditTrace,
) -> None:
    """Downgrade executable actions to WAIT when HTF context is missing."""

    _ordered, _highest, _htf_start_ok, parent_context_available = conditions
    if parent_context_available:
        return
    if decision.final_action not in _FRAMEWORK_ACTIONS_REQUIRING_CONTEXT:
        return

    decision.final_action = FinalAction.WAIT
    decision.action = FinalAction.WAIT
    decision.reason = (
        "Higher-timeframe context missing; framework v1.2 requires highest-timeframe-first reading."
    )
    decision.management_state = "NONE"
    trace.add_check(
        name="Lower timeframe not allowed to decide before higher context",
        passed=False,
        severity="ERROR",
        details=(
            "Final action downgraded to WAIT due to missing higher-timeframe context "
            "for executable signal."
        ),
        file=__file__,
        function="apply_htf_first_guard",
    )


def _add_move_context_checks(trace: FrameworkAuditTrace, move_context: MoveContext) -> None:
    """Record required move-context separation checks on audit trace."""

    parent_identified = bool(move_context.parent_timeframe) and move_context.parent_direction not in {"", "UNCLEAR"}
    trace.add_check(
        name="Parent move identified",
        passed=parent_identified,
        severity="ERROR" if not parent_identified else "INFO",
        details=(
            f"Parent: {move_context.parent_timeframe} {move_context.parent_direction} {move_context.parent_state}"
            if parent_identified
            else "Unable to identify parent move context."
        ),
        file=__file__,
        function="_add_move_context_checks",
    )

    current_identified = bool(move_context.current_timeframe) and move_context.current_direction not in {"", "UNCLEAR"}
    trace.add_check(
        name="Current move identified",
        passed=current_identified,
        severity="ERROR" if not current_identified else "INFO",
        details=(
            f"Current: {move_context.current_timeframe} {move_context.current_direction} {move_context.current_state}"
            if current_identified
            else "Unable to identify current move context."
        ),
        file=__file__,
        function="_add_move_context_checks",
    )

    separated = (
        parent_identified
        and current_identified
        and (
            move_context.parent_timeframe != move_context.current_timeframe
            or move_context.parent_direction != move_context.current_direction
            or move_context.parent_state != move_context.current_state
        )
    )
    trace.add_check(
        name="Parent/current move separated",
        passed=separated,
        severity="ERROR" if not separated else "INFO",
        details=(
            "Parent and current moves are independently identified."
            if separated
            else "Parent/current move collapsed into same context."
        ),
        file=__file__,
        function="_add_move_context_checks",
    )

    origin_identified = (
        current_identified
        and move_context.current_origin not in {"", "UNCLEAR"}
    )
    trace.add_check(
        name="Current move origin identified",
        passed=origin_identified,
        severity="ERROR" if not origin_identified else "INFO",
        details=(
            f"Current origin: {move_context.current_origin}"
            if origin_identified
            else "Current move origin is unclear."
        ),
        file=__file__,
        function="_add_move_context_checks",
    )


def apply_parent_current_separation_guard(
    decision: Any,
    move_context: MoveContext,
    trace: FrameworkAuditTrace,
) -> None:
    """Force WAIT for fresh BUY/SELL when parent/current separation is unclear."""

    separation_unclear = (
        move_context.current_origin == "UNCLEAR"
        or move_context.current_timeframe == ""
        or move_context.parent_timeframe == ""
    )
    if not separation_unclear:
        return
    if decision.final_action not in _FRESH_ENTRY_ACTIONS:
        return

    decision.final_action = FinalAction.WAIT
    decision.action = FinalAction.WAIT
    decision.reason = "Parent/current move separation unclear; framework v1.2 requires current move origin for fresh entry."
    decision.management_state = "NONE"
    trace.add_check(
        name="Parent/current move separated",
        passed=False,
        severity="ERROR",
        details="Final action downgraded to WAIT because parent/current separation is unclear for fresh entry.",
        file=__file__,
        function="apply_parent_current_separation_guard",
    )


def _normalize_timeframe_label(label: str) -> str:
    text = str(label).strip().lower()
    if text in {"1d", "1day", "d", "daily"}:
        return "1d"
    if text in {"12h", "12hour", "12hours"}:
        return "12h"
    if text in {"4h", "4hour", "4hours"}:
        return "4h"
    if text in {"1h", "60m", "60min", "60minutes"}:
        return "1h"
    if text in {"15m", "15min", "15minutes"}:
        return "15m"
    if text in {"5m", "5min", "5minutes"}:
        return "5m"
    if text in {"3m", "3min", "3minutes"}:
        return "3m"
    return text


def _ordered_timeframes_for_analysis(available_timeframes: Any) -> list[str]:
    """Return framework-priority timeframe order from available keys."""

    normalized_seen: set[str] = set()
    for raw in available_timeframes:
        normalized = _normalize_timeframe_label(raw)
        if normalized in _FRAMEWORK_TF_PRIORITY:
            normalized_seen.add(normalized)
    return [tf for tf in _FRAMEWORK_TF_PRIORITY if tf in normalized_seen]


def _has_parent_context(ordered_timeframes: list[str]) -> bool:
    """Return true when lower-level analysis has at least one parent timeframe."""

    if not ordered_timeframes:
        return False
    has_lower = any(tf in {"5m", "3m"} for tf in ordered_timeframes)
    if not has_lower:
        return True
    return any(tf in {"1d", "12h", "4h", "1h"} for tf in ordered_timeframes)


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


def _selected_meaningful_divergence(audit: DivergenceAudit) -> Any:
    timeframe = getattr(audit, "selected_last_meaningful_tf", None)
    if timeframe is None:
        return None
    field = _TF_TO_FIELD.get(timeframe)
    if field is None:
        return None
    return getattr(audit, field, None)


def _text_or_na(value: Any, default: str = "N/A") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _position_action_if_already_in(final_action_text: str) -> str:
    action = final_action_text.strip().upper()
    if action in {"HOLD LONG", "HOLD SHORT", "CLOSE LONG", "CLOSE SHORT", "CLOSE AND FLIP"}:
        return final_action_text
    return "WAIT"


def _position_action_if_not_in(final_action_text: str) -> str:
    action = final_action_text.strip().upper()
    if action in {"BUY", "SELL"}:
        return final_action_text
    return "WAIT"


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
