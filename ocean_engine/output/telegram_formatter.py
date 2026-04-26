"""Telegram formatter for deterministic Ocean engine reports."""

from __future__ import annotations

from typing import Any

from ocean_engine.divergence.divergence_audit import (
    divergence_audit_summary,
    is_official_divergence,
    select_last_meaningful_divergence,
)
from ocean_engine.models.enums import FinalAction
from ocean_engine.models.market import (
    ActiveTradeAudit,
    DecisionState,
    DivergenceAudit,
    MarketReport,
    MultiLevelStory,
    SupplyDemandZone,
)
from ocean_engine.trade.active_trade_engine import active_trade_audit_summary


def format_final_action(decision: DecisionState) -> str:
    """Format final action block from decision state."""

    action = _format_enum_value(getattr(decision, "final_action", FinalAction.WAIT))
    management = _text(getattr(decision, "management_state", "N/A"))
    reason = _text(getattr(decision, "reason", "N/A"))
    lines = [f"Signal: {action}", f"Management: {management}", f"Reason: {reason}"]

    guard_reasons = getattr(decision, "guard_reasons", [])
    if guard_reasons:
        lines.append("Guards: " + " | ".join(str(item) for item in guard_reasons))
    return "\n".join(lines)


def format_market_story(report: MarketReport) -> str:
    """Format compact market story section."""

    story_state = getattr(report, "story_state", None)
    parent = _text(getattr(story_state, "parent_timeframe", "N/A"))
    parent_direction = _format_enum_value(getattr(story_state, "parent_direction", "N/A"))
    parent_state = _format_enum_value(getattr(story_state, "parent_state", "N/A"))
    current_tf = _text(getattr(story_state, "current_move_timeframe", "N/A"))
    current_direction = _format_enum_value(getattr(story_state, "current_move_direction", "N/A"))
    current_origin = _text(getattr(story_state, "current_move_origin", "N/A"))
    with_parent = getattr(story_state, "current_move_with_parent", None)
    if with_parent is True:
        alignment = "WITH_PARENT"
    elif with_parent is False:
        alignment = "AGAINST_PARENT"
    else:
        alignment = "UNCLEAR"
    return (
        f"Parent Move: {parent} {parent_direction} {parent_state}\n"
        f"Current Move: {current_tf} {current_direction} ({current_origin})\n"
        f"Current vs Parent: {alignment}"
    )


def format_divergence_audit(divergence_audit: DivergenceAudit | None) -> str:
    """Format divergence audit section safely."""

    if divergence_audit is None:
        return "Audit: N/A\nLast Meaningful: N/A\nABC: N/A\nImpulse: N/A\nGrade: N/A"

    audit_line = divergence_audit_summary(divergence_audit)
    selected = select_last_meaningful_divergence(divergence_audit)
    if selected is None:
        last_meaningful = "N/A"
        abc = "N/A"
        impulse = "N/A"
        grade = "N/A"
    else:
        direction = _format_enum_value(getattr(selected, "direction", "N/A"))
        last_meaningful = f"{_normalize_tf(selected.timeframe)} {direction}"
        if is_official_divergence(selected):
            abc = "Yes"
            impulse = "Yes"
        else:
            abc = "No"
            impulse = "No"
        grade = _format_enum_value(getattr(selected, "grade", "N/A"))
    return (
        f"Audit: {audit_line}\n"
        f"Last Meaningful: {last_meaningful}\n"
        f"ABC: {abc}\n"
        f"Impulse: {impulse}\n"
        f"Grade: {grade}"
    )


def format_carry_status(report: MarketReport) -> str:
    """Format carry section from selected active trade if available."""

    decision = getattr(report, "decision", None)
    carry_tf = _text(getattr(decision, "carrying_timeframe", "N/A")) if decision else "N/A"
    active_trade_audit = getattr(report, "active_trade_audit", None) or _latest_active_trade_audit(report)
    candidate = _selected_candidate(active_trade_audit)

    direction = _format_enum_value(getattr(candidate, "carry_direction", "N/A")) if candidate else "N/A"
    state = _format_enum_value(getattr(candidate, "carry_state", "N/A")) if candidate else "N/A"
    finished = "Yes" if getattr(candidate, "too_late_to_chase", False) and state == "EXHAUSTING" else "No"

    return f"Carry TF: {carry_tf}\nDirection: {direction}\nState: {state}\nFinished: {finished}"


def format_range_status(structures: dict[str, Any] | None) -> str:
    """Format compact range/location summary using highest useful timeframe."""

    if not structures:
        return "N/A"

    priority = ["4h", "1h", "15m", "5m", "3m"]
    for tf in priority:
        structure = structures.get(tf)
        if structure is None:
            continue
        range_state = getattr(structure, "range_state", None)
        if range_state is None:
            continue
        active = "YES" if getattr(range_state, "active", False) else "NO"
        location = _text(getattr(range_state, "price_location", "N/A"))
        status = _text(getattr(range_state, "status", "N/A"))
        ownership = _format_enum_value(getattr(range_state, "ownership", "N/A"))
        lower = getattr(range_state, "lower_edge", None)
        upper = getattr(range_state, "upper_edge", None)
        band = f"{lower:.2f}-{upper:.2f}" if isinstance(lower, (int, float)) and isinstance(upper, (int, float)) else "N/A"
        return (
            f"Timeframe: {_normalize_tf(tf)}\n"
            f"Range Active: {active}\n"
            f"Status: {status}\n"
            f"Location: {location}\n"
            f"Ownership: {ownership}\n"
            f"Band: {band}"
        )
    return "N/A"


def format_zones(zones: list[SupplyDemandZone] | None, max_zones: int = 4) -> str:
    """Format top supply/demand zones."""

    if not zones:
        return "N/A"
    lines: list[str] = []
    for zone in zones[:max_zones]:
        ztype = _format_enum_value(getattr(zone, "zone_type", "N/A"))
        band = _text(getattr(zone, "price_band", "N/A"))
        role = _text(getattr(zone, "role", "N/A"))
        strength = _format_enum_value(getattr(zone, "strength", "N/A"))
        status = _text(getattr(zone, "status", "N/A"))
        tf = _normalize_tf(_text(getattr(zone, "timeframe", "N/A")))
        lines.append(f"{tf} {ztype} {band} | {strength} | {status} | {role}")
    return "\n".join(lines)


def format_active_trade(active_trade_audit: ActiveTradeAudit | None) -> str:
    """Format selected active trade and audit rows."""

    if active_trade_audit is None:
        return "Active Trade: NO\nTrade Audit: N/A"

    selected = _selected_candidate(active_trade_audit)
    if selected is None:
        selected_text = "Active Trade: NO"
    else:
        setup = _format_enum_value(getattr(selected, "setup_type", "N/A"))
        function = _format_enum_value(getattr(selected, "trade_function", "N/A"))
        fresh = "YES" if getattr(selected, "fresh_entry_valid", False) else "NO"
        hold = "YES" if getattr(selected, "existing_hold_valid", False) else "NO"
        too_late = "YES" if getattr(selected, "too_late_to_chase", False) else "NO"
        selected_text = (
            "Active Trade: YES\n"
            f"Timeframe: {_normalize_tf(selected.origin_timeframe)}\n"
            f"Direction: {_format_enum_value(getattr(selected, 'direction', 'N/A'))}\n"
            f"Type: {setup}\n"
            f"Label: {_text(getattr(selected, 'type_label', 'N/A'))}\n"
            f"Function: {function}\n"
            f"Fresh Entry: {fresh}\n"
            f"Valid Hold: {hold}\n"
            f"Too Late: {too_late}"
        )
    return f"{selected_text}\nTrade Audit: {active_trade_audit_summary(active_trade_audit)}"


def format_multi_level_story(story: MultiLevelStory | None) -> str:
    """Format multi-level story section."""

    if story is None:
        return "N/A"
    active = "Active" if getattr(story, "active", False) else "Inactive"
    confirmed = getattr(story, "confirmed_timeframes", [])
    confirmed_text = ",".join(_normalize_tf(tf) for tf in confirmed) if confirmed else "N/A"
    direction = _format_enum_value(getattr(story, "direction", "N/A"))
    status = _text(getattr(story, "higher_tf_status", "N/A"))
    return (
        f"Status: {active}\n"
        f"Direction: {direction}\n"
        f"Confirmed TFs: {confirmed_text}\n"
        f"Higher TF Status: {status}"
    )


def format_position_management(decision: DecisionState | None) -> str:
    """Format position management guidance from decision only."""

    if decision is None:
        return "If already in: N/A\nIf not in: N/A\nStop: N/A\nProfit: N/A\nRunner: N/A"
    action = _format_enum_value(getattr(decision, "final_action", "WAIT"))
    not_in = "WAIT" if action in {"BUY", "SELL"} else action
    return (
        f"If already in: {action}\n"
        f"If not in: {not_in}\n"
        f"Stop: {_text(getattr(decision, 'reason', 'N/A'))}\n"
        f"Profit: N/A\n"
        f"Runner: N/A"
    )


def format_next_watch(report: MarketReport) -> str:
    """Format next watch section with deterministic placeholders."""

    decision = getattr(report, "decision", None)
    action = _format_enum_value(getattr(decision, "final_action", "WAIT")) if decision else "WAIT"
    pressure = _range_pressure_hint(getattr(report, "structures", None) or getattr(report, "structure", None) or {})
    return (
        f"Bullish need: Maintain bullish structure confirmation.\n"
        f"Bearish need: Maintain bearish structure confirmation.\n"
        f"Next event: {pressure} (current {action})."
    )


def format_compact_telegram_report(report: MarketReport) -> str:
    """Build compact telegram report text from deterministic report state."""

    symbol = _text(getattr(report, "symbol", "N/A"))
    timestamp = _text(getattr(report, "timestamp", "") or getattr(report, "generated_at", "N/A"))
    current_price = _safe_price(getattr(report, "current_price", None))
    decision = getattr(report, "decision", None)
    structures = getattr(report, "structures", None) or getattr(report, "structure", None) or {}
    divergence_audit = getattr(report, "divergence_audit", None) or _latest_divergence_audit(report)
    active_trade_audit = getattr(report, "active_trade_audit", None) or _latest_active_trade_audit(report)
    story = getattr(report, "multi_level_story", None) or getattr(report, "story", None)
    story_state = getattr(report, "story_state", None)
    zones = getattr(report, "zones", None)
    zone_list: list[SupplyDemandZone] = []
    if isinstance(zones, dict):
        for item in zones.values():
            if isinstance(item, list):
                zone_list.extend(item)
    elif isinstance(zones, list):
        zone_list = zones

    decision_block = format_final_action(decision) if decision is not None else "Signal: WAIT\nManagement: NONE\nReason: N/A"
    controlling_origin = _text(getattr(story_state, "controlling_origin", "N/A"), default="N/A")
    active_execution = _text(getattr(story_state, "active_execution_trade", "N/A"), default="N/A")
    carry_tf = _text(getattr(story_state, "carrying_timeframe", "N/A"), default="N/A")
    message = (
        f"🌊 OCEAN SIGNAL | {symbol}\n"
        f"Price: {current_price}\n"
        f"Time: {timestamp}\n\n"
        f"━━━━━━━━━━━━━━\n"
        f"FINAL ACTION\n{decision_block}\n\n"
        f"━━━━━━━━━━━━━━\n"
        f"MARKET STORY\n{format_market_story(report)}\n\n"
        f"━━━━━━━━━━━━━━\n"
        f"DIVERGENCE\n{format_divergence_audit(divergence_audit)}\n\n"
        f"━━━━━━━━━━━━━━\n"
        f"CARRY\n{format_carry_status(report)}\n\n"
        f"━━━━━━━━━━━━━━\n"
        f"RANGE / LOCATION\n{format_range_status(structures)}\n\n"
        f"━━━━━━━━━━━━━━\n"
        f"SUPPLY / DEMAND\n{format_zones(zone_list)}\n\n"
        f"━━━━━━━━━━━━━━\n"
        f"MULTI-LEVEL STORY\n{format_multi_level_story(story)}\n"
        f"Controlling Origin: {controlling_origin}\n"
        f"Active Execution Trade: {active_execution}\n"
        f"Carry Timeframe: {carry_tf}\n\n"
        f"━━━━━━━━━━━━━━\n"
        f"ACTIVE TRADE\n{format_active_trade(active_trade_audit)}\n\n"
        f"━━━━━━━━━━━━━━\n"
        f"POSITION MANAGEMENT\n{format_position_management(decision)}\n\n"
        f"━━━━━━━━━━━━━━\n"
        f"NEXT WATCH\n{format_next_watch(report)}\n\n"
        f"━━━━━━━━━━━━━━\n"
        f"SUMMARY\n{_text(getattr(report, 'summary', ''), default='Deterministic report generated.')}"
    )
    # Telegram limit safety.
    return message[:3900]


def _format_enum_value(value: Any) -> str:
    text = getattr(value, "value", value)
    return _text(text, default="N/A").replace("_", " ")


def _text(value: Any, default: str = "N/A") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _safe_price(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{value:,.2f}"
    return "N/A"


def _latest_divergence_audit(report: MarketReport) -> DivergenceAudit | None:
    audits = getattr(report, "divergence_audits", None)
    if isinstance(audits, list) and audits:
        return audits[-1]
    return None


def _latest_active_trade_audit(report: MarketReport) -> ActiveTradeAudit | None:
    audits = getattr(report, "active_trade_audits", None)
    if isinstance(audits, list) and audits:
        return audits[-1]
    return None


def _selected_candidate(audit: ActiveTradeAudit | None) -> ActiveTradeCandidate | None:
    if audit is None:
        return None
    tf = getattr(audit, "selected_active_trade_tf", None)
    mapping = {"4h": "tf_4h", "1h": "tf_1h", "15m": "tf_15m", "5m": "tf_5m", "3m": "tf_3m"}
    field = mapping.get(tf)
    if not field:
        return None
    candidate = getattr(audit, field, None)
    if candidate is None or not getattr(candidate, "exists", False):
        return None
    return candidate


def _normalize_tf(tf: str) -> str:
    if tf == "4h":
        return "4H"
    if tf == "1h":
        return "1H"
    return tf


def _range_pressure_hint(structures: dict[str, Any]) -> str:
    priority = ["4h", "1h", "15m", "5m", "3m"]
    for tf in priority:
        structure = structures.get(tf)
        if structure is None:
            continue
        range_state = getattr(structure, "range_state", None)
        if range_state is None:
            continue
        status = str(getattr(range_state, "status", "UNCLEAR") or "UNCLEAR").upper()
        if status in {"FAILED_BREAK_UP", "FAILED_BREAK_DOWN", "RE_ENTERED"}:
            return "return-to-range pressure"
    return "Watch for next carry/divergence transition"
