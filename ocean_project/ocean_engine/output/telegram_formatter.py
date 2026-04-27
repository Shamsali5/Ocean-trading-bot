"""Telegram formatter for deterministic Ocean engine reports."""

from __future__ import annotations

from typing import Any

from ocean_engine.divergence.divergence_audit import (
    divergence_audit_summary,
    is_official_divergence,
    select_last_meaningful_divergence,
)
from ocean_engine.models.enums import Direction, FinalAction
from ocean_engine.models.market import (
    ActiveTradeCandidate,
    ActiveTradeAudit,
    DecisionState,
    DivergenceAudit,
    MarketReport,
    MultiLevelStory,
    SupplyDemandZone,
)
from ocean_engine.trade.active_trade_engine import active_trade_audit_summary
from ocean_output_validator import render_framework_output, validate_required_output_sections

TIMEFRAME_ORDER = ("4h", "1h", "15m", "5m", "3m")
TIMEFRAME_RANK = {"4h": 5, "1h": 4, "15m": 3, "5m": 2, "3m": 1}
RANGE_SECTION_ORDER = ("4h", "1h", "15m")


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
    """Format market story as what each timeframe is currently doing."""

    move_context = getattr(report, "move_context", None)
    parent_line = ""
    current_line = ""
    if move_context is not None:
        parent_line = (
            "Parent Move: "
            f"{_normalize_tf(_text(getattr(move_context, 'parent_timeframe', ''), default='UNCLEAR'))} "
            f"{_text(getattr(move_context, 'parent_direction', 'UNCLEAR'), default='UNCLEAR')} "
            f"{_text(getattr(move_context, 'parent_state', 'UNCLEAR'), default='UNCLEAR')}"
        )
        current_line = (
            "Current Move: "
            f"{_normalize_tf(_text(getattr(move_context, 'current_timeframe', ''), default='UNCLEAR'))} "
            f"{_text(getattr(move_context, 'current_direction', 'UNCLEAR'), default='UNCLEAR')} "
            f"{_text(getattr(move_context, 'current_state', 'UNCLEAR'), default='UNCLEAR')} "
            f"| Origin: {_text(getattr(move_context, 'current_origin', 'UNCLEAR'), default='UNCLEAR')}"
        )

    structures = getattr(report, "structures", None) or getattr(report, "structure", None) or {}
    story_parts: list[str] = []
    for tf in TIMEFRAME_ORDER:
        structure = structures.get(tf)
        if structure is None:
            continue
        direction = _format_enum_value(getattr(structure, "direction", "UNCLEAR"))
        market_state = _format_enum_value(getattr(structure, "market_state", "UNCLEAR"))
        story_parts.append(f"{_normalize_tf(tf)} {direction} {market_state}")

    if not story_parts:
        story_line = "Timeframe Story: N/A"
    else:
        story_line = "Timeframe Story: " + " | ".join(story_parts)

    counter_move = _format_counter_move(report)
    lines = [story_line, counter_move]
    if parent_line:
        lines.insert(0, parent_line)
    if current_line:
        lines.insert(1 if parent_line else 0, current_line)
    return "\n".join(lines)


def format_divergence_audit(divergence_audit: DivergenceAudit | None) -> str:
    """Format divergence audit section safely."""

    if divergence_audit is None:
        return (
            "Audit: N/A\nLast Meaningful: N/A\nABC: N/A\nImpulse: N/A\n"
            "Divergence Price: N/A\nImpulse Price: N/A\nPer-TF Price: N/A\nGrade: N/A"
        )

    audit_line = divergence_audit_summary(divergence_audit)
    selected = select_last_meaningful_divergence(divergence_audit)
    if selected is None:
        last_meaningful = "N/A"
        abc = "N/A"
        impulse = "N/A"
        divergence_price_time = "N/A"
        impulse_price_time = "N/A"
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
        divergence_price_time = _format_price_only(
            price=getattr(selected, "divergence_price", None),
        )
        impulse_price_time = _format_price_only(
            price=getattr(selected, "impulse_price", None),
        )
        grade = _format_enum_value(getattr(selected, "grade", "N/A"))
    per_tf_details = _format_per_tf_divergence_price(divergence_audit)
    return (
        f"Audit: {audit_line}\n"
        f"Last Meaningful: {last_meaningful}\n"
        f"ABC: {abc}\n"
        f"Impulse: {impulse}\n"
        f"Divergence Price: {divergence_price_time}\n"
        f"Impulse Price: {impulse_price_time}\n"
        f"{per_tf_details}\n"
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
    """Format range/location with upper and lower boundaries only."""

    if not structures:
        return "N/A"

    range_rows: list[tuple[str, Any]] = []
    for tf in RANGE_SECTION_ORDER:
        structure = structures.get(tf)
        if structure is None:
            continue
        range_state = getattr(structure, "range_state", None)
        if range_state is None:
            continue
        range_rows.append((tf, range_state))

    if not range_rows:
        return "N/A"

    active_rows = [(tf, state) for tf, state in range_rows if bool(getattr(state, "active", False))]
    rows = active_rows if active_rows else range_rows[:1]
    lines: list[str] = []
    for tf, range_state in rows:
        lower = getattr(range_state, "lower_edge", None)
        upper = getattr(range_state, "upper_edge", None)
        upper_text = f"{upper:.2f}" if isinstance(upper, (int, float)) else "N/A"
        lower_text = f"{lower:.2f}" if isinstance(lower, (int, float)) else "N/A"
        lines.append(f"{_normalize_tf(tf)} | Upper: {upper_text} | Lower: {lower_text}")
    return "\n".join(lines)


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
        start_price_time = _format_price_time(
            price=getattr(selected, "confirmation_price", None),
            timestamp=getattr(selected, "confirmation_time_utc", ""),
        )
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
            f"Start Price/Time: {start_price_time}\n"
            f"Fresh Entry: {fresh}\n"
            f"Valid Hold: {hold}\n"
            f"Too Late: {too_late}"
        )
    return f"{selected_text}\nTrade Audit: {active_trade_audit_summary(active_trade_audit)}"


def _selected_opposite_candidate(audit: ActiveTradeAudit | None) -> ActiveTradeCandidate | None:
    """Return opposite-direction fresh candidate when available."""

    selected = _selected_candidate(audit)
    if selected is None:
        return None
    selected_direction = _candidate_direction(selected)
    if selected_direction not in {Direction.UP, Direction.DOWN}:
        return None
    opposite_direction = Direction.DOWN if selected_direction == Direction.UP else Direction.UP
    for field in ("tf_4h", "tf_1h", "tf_15m", "tf_5m", "tf_3m"):
        candidate = getattr(audit, field, None)
        if candidate is None or not getattr(candidate, "exists", False):
            continue
        if candidate.origin_timeframe == selected.origin_timeframe:
            continue
        if _candidate_direction(candidate) != opposite_direction:
            continue
        if not getattr(candidate, "fresh_entry_valid", False):
            continue
        return candidate
    return None


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


def format_hierarchy(report: MarketReport) -> str:
    """Format parent/execution/carry hierarchy section."""

    story_state = getattr(report, "story_state", None)
    parent_tf = _text(getattr(story_state, "parent_timeframe", "N/A"))
    parent_direction = _format_enum_value(getattr(story_state, "parent_direction", "N/A"))
    controlling_origin = _text(getattr(story_state, "controlling_origin", "N/A"))
    execution = _text(getattr(story_state, "active_execution_trade", "N/A"))
    carry = _text(getattr(story_state, "carrying_timeframe", "N/A"))
    smallest_internal = _smallest_active_internal_move(report)
    return (
        f"Parent Move: {parent_tf} {parent_direction}\n"
        f"Controlling Origin: {controlling_origin}\n"
        f"Active Execution Trade: {execution}\n"
        f"Current Carrying Move: {carry}\n"
        f"Smallest Active Internal Move: {smallest_internal}"
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
    """Build canonical Patch-0 telegram report from deterministic report state."""

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

    output_dict = _build_framework_output_dict(
        report=report,
        symbol=symbol,
        timestamp=timestamp,
        current_price=current_price,
        structures=structures,
        divergence_audit=divergence_audit,
        active_trade_audit=active_trade_audit,
        story=story,
        story_state=story_state,
        zones=zone_list,
        decision=decision,
    )
    validate_required_output_sections(
        output_dict=output_dict,
        trace=getattr(report, "framework_audit_trace", None),
    )
    return render_framework_output(output_dict)


def _build_framework_output_dict(
    *,
    report: MarketReport,
    symbol: str,
    timestamp: str,
    current_price: str,
    structures: dict[str, Any],
    divergence_audit: DivergenceAudit | None,
    active_trade_audit: ActiveTradeAudit | None,
    story: MultiLevelStory | None,
    story_state: Any,
    zones: list[SupplyDemandZone],
    decision: DecisionState | None,
) -> dict[str, Any]:
    """Build canonical Patch-0 section payload (A-R)."""

    action_text = _format_enum_value(getattr(decision, "final_action", "WAIT")) if decision is not None else "WAIT"
    selected = _selected_candidate(active_trade_audit)
    trade_function = _format_enum_value(getattr(selected, "trade_function", "NONE")) if selected is not None else "NONE"
    type_label = _text(getattr(selected, "type_label", ""), default="N/A") if selected is not None else "N/A"
    entry_zone = _text(getattr(selected, "origin_price_zone", ""), default="N/A") if selected is not None else "N/A"
    stop_invalid = _text(getattr(selected, "invalidation", ""), default="N/A") if selected is not None else "N/A"
    carrying_tf = (
        _text(getattr(decision, "carrying_timeframe", ""), default="N/A")
        if decision is not None
        else "N/A"
    )
    highest_tf = _highest_available_timeframe(structures)
    move_context = getattr(report, "move_context", None)
    selected_divergence = select_last_meaningful_divergence(divergence_audit) if divergence_audit is not None else None
    divergence_tf = _text(getattr(selected_divergence, "timeframe", ""), default="N/A")
    divergence_direction = _format_enum_value(getattr(selected_divergence, "direction", "N/A"))
    current_tf = _text(getattr(move_context, "current_timeframe", ""), default="N/A")
    current_direction = _text(getattr(move_context, "current_direction", ""), default="N/A")
    current_state = _text(getattr(move_context, "current_state", ""), default="N/A")
    current_origin = _text(getattr(move_context, "current_origin", ""), default="N/A")
    selected_exists = selected is not None
    if_already_in = action_text if action_text in {"HOLD LONG", "HOLD SHORT", "CLOSE LONG", "CLOSE SHORT", "CLOSE AND FLIP"} else "WAIT"
    if_not_in = action_text if action_text in {"BUY", "SELL"} else "WAIT"
    summary_text = _text(getattr(report, "summary", ""), default="Deterministic report generated.")
    hierarchy_text = format_hierarchy(report)
    story_text = format_market_story(report)
    divergence_text = format_divergence_audit(divergence_audit)
    carry_text = format_carry_status(report)
    range_text = format_range_status(structures)
    zones_text = format_zones(zones)
    multi_level_text = format_multi_level_story(story)
    active_trade_text = format_active_trade(active_trade_audit)
    position_management_text = format_position_management(decision)
    next_watch_text = format_next_watch(report)
    zone_rows = _compact_zone_rows(zones, max_rows=6)
    controlling_origin = "N/A"
    active_execution_trade = "N/A"
    if story_state is not None:
        controlling_origin = _text(getattr(story_state, "controlling_origin", ""), default="N/A")
        active_execution_trade = _text(getattr(story_state, "active_execution_trade", ""), default="N/A")
    if controlling_origin == "N/A" and story is not None:
        controlling_origin = _text(getattr(story, "controlling_origin", ""), default="N/A")
    if active_execution_trade == "N/A" and story is not None:
        active_execution_trade = _text(getattr(story, "active_execution_trade", ""), default="N/A")
    management_state = _text(getattr(decision, "management_state", "N/A")) if decision is not None else "N/A"
    reason = _text(getattr(decision, "reason", "N/A")) if decision is not None else "N/A"
    guard_reasons = list(getattr(decision, "guard_reasons", []) or []) if decision is not None else []
    guards_text = " | ".join(str(item) for item in guard_reasons).strip() or "N/A"
    opposite_candidate = _selected_opposite_candidate(active_trade_audit)
    flip_to = "N/A"
    flip_carry = "N/A"
    if action_text == "CLOSE AND FLIP" and opposite_candidate is not None:
        flip_to = _text(getattr(opposite_candidate, "type_label", ""), default="N/A")
        flip_carry = _text(getattr(opposite_candidate, "carry_timeframe", ""), default="N/A")

    return {
        "A META": {
            "symbol": symbol,
            "timestamp": timestamp,
            "current_price": current_price,
        },
        "B HIGHER_TIMEFRAME_CONTEXT": {
            "highest_tf": highest_tf,
            "details": hierarchy_text,
        },
        "C CURRENT_MOVE": {
            "timeframe": current_tf,
            "direction": current_direction,
            "origin": current_origin,
            "details": story_text,
        },
        "D STRUCTURE_STATE": {
            "state": current_state,
            "details": range_text,
        },
        "E DIVERGENCE_STATE": {
            "direction": divergence_direction,
            "details": divergence_text,
        },
        "F LAST_MEANINGFUL_DIVERGENCE": {
            "timeframe": divergence_tf,
            "direction": divergence_direction,
        },
        "G IMPULSE_ACCEPTANCE": {
            "impulse_confirmed": bool(getattr(selected_divergence, "impulse_confirmed", False)),
            "details": divergence_text,
        },
        "H SUPPLY_DEMAND_ZONE_MAP": {
            "zones": zone_rows,
            "details": zones_text,
        },
        "I CARRY_STATUS": {
            "state": _format_enum_value(getattr(selected, "carry_state", "N/A")) if selected_exists else "N/A",
            "carrying_tf": carrying_tf,
            "details": carry_text,
        },
        "J MULTI_LEVEL_STORY": {
            "active": bool(getattr(story, "active", False)) if story is not None else False,
            "direction": _format_enum_value(getattr(story, "direction", "N/A")) if story is not None else "N/A",
            "confirmed_timeframes": list(getattr(story, "confirmed_timeframes", []) or []),
            "controlling_origin": controlling_origin,
            "details": multi_level_text,
        },
        "K TRADE_CLASSIFICATION": {
            "trade_function": trade_function,
            "type_label": type_label,
        },
        "L MANAGEMENT_STATE": {
            "management_state": management_state,
        },
        "M CURRENT_ACTIVE_MEANINGFUL_TRADE": {
            "exists": selected_exists,
            "details": active_trade_text,
        },
        "N POSITION_MANAGEMENT_FOR_ACTIVE_TRADE": {
            "if_already_in": if_already_in,
            "if_not_in": if_not_in,
            "flip_to": flip_to,
            "flip_carry": flip_carry,
            "details": position_management_text,
        },
        "O MARKET_HIERARCHY": {
            "controlling_origin": controlling_origin,
            "active_execution_trade": active_execution_trade,
            "details": hierarchy_text,
        },
        "P WHAT_TO_WATCH_NEXT": {
            "next_event": reason,
            "details": next_watch_text,
        },
        "Q CURRENT_MOVE_SUMMARY": {
            "summary": summary_text,
        },
        "R FINAL_EXECUTION_BLOCK": {
            "Signal": action_text,
            "Trade Function": trade_function,
            "Type Label": type_label,
            "Controlling Origin": controlling_origin,
            "Active Execution Trade": active_execution_trade,
            "Entry Zone": entry_zone,
            "Stop / Invalidation": stop_invalid,
            "Carrying TF": carrying_tf,
            "Management State": management_state,
            "Reason": reason,
            "Guards": guards_text,
        },
    }


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


def _format_price_time(price: Any, timestamp: Any) -> str:
    if isinstance(price, (int, float)):
        price_text = f"{float(price):,.2f}"
    else:
        price_text = "N/A"
    time_text = _text(timestamp, default="N/A")
    return f"{price_text} @ {time_text}"


def _format_price_only(price: Any) -> str:
    """Format price only, intentionally omitting timestamp."""

    if isinstance(price, (int, float)):
        return f"{float(price):,.2f}"
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


def _iter_divergence_rows(audit: DivergenceAudit | None) -> list[tuple[str, Any]]:
    if audit is None:
        return []
    mapping = {"4h": "tf_4h", "1h": "tf_1h", "15m": "tf_15m", "5m": "tf_5m", "3m": "tf_3m"}
    rows: list[tuple[str, Any]] = []
    for tf in TIMEFRAME_ORDER:
        field = mapping.get(tf)
        if not field:
            continue
        rows.append((tf, getattr(audit, field)))
    return rows


def _flatten_zones(report: MarketReport) -> list[SupplyDemandZone]:
    zones = getattr(report, "zones", None)
    zone_list: list[SupplyDemandZone] = []
    if isinstance(zones, dict):
        for item in zones.values():
            if isinstance(item, list):
                zone_list.extend(item)
    elif isinstance(zones, list):
        zone_list = zones
    return zone_list


def _parse_band(band: str) -> tuple[float, float] | None:
    text = str(band).strip()
    if "-" not in text:
        return None
    left, right = text.split("-", 1)
    try:
        a = float(left.strip())
        b = float(right.strip())
    except ValueError:
        return None
    return (min(a, b), max(a, b))


def _price_in_range_bottom(price: float | None, ranges: list[tuple[str, Any]]) -> bool:
    if price is None:
        return False
    for _, state in ranges:
        if not getattr(state, "active", False):
            continue
        lower = getattr(state, "lower_edge", None)
        upper = getattr(state, "upper_edge", None)
        if not isinstance(lower, (int, float)) or not isinstance(upper, (int, float)):
            continue
        width = max(upper - lower, 1e-9)
        bottom_threshold = lower + (0.25 * width)
        if lower <= price <= bottom_threshold:
            return True
    return False


def _price_in_range_top(price: float | None, ranges: list[tuple[str, Any]]) -> bool:
    if price is None:
        return False
    for _, state in ranges:
        if not getattr(state, "active", False):
            continue
        lower = getattr(state, "lower_edge", None)
        upper = getattr(state, "upper_edge", None)
        if not isinstance(lower, (int, float)) or not isinstance(upper, (int, float)):
            continue
        width = max(upper - lower, 1e-9)
        top_threshold = upper - (0.25 * width)
        if top_threshold <= price <= upper:
            return True
    return False


def _zone_supports_counter(price: float | None, zones: list[SupplyDemandZone], bullish: bool) -> bool:
    zone_type_text = "DEMAND" if bullish else "SUPPLY"
    for zone in zones:
        if _format_enum_value(getattr(zone, "zone_type", "")).upper() != zone_type_text:
            continue
        band = _parse_band(getattr(zone, "price_band", ""))
        if band is None:
            continue
        if price is None:
            return True
        if band[0] <= price <= band[1]:
            return True
    return False


def _format_counter_move(report: MarketReport) -> str:
    """Describe lower-level counter move when opposite official divergence appears."""

    divergence_audit = getattr(report, "divergence_audit", None) or _latest_divergence_audit(report)
    rows = _iter_divergence_rows(divergence_audit)
    active_trade_audit = getattr(report, "active_trade_audit", None) or _latest_active_trade_audit(report)
    selected = _selected_candidate(active_trade_audit)
    active_direction = _candidate_direction(selected) if selected is not None else Direction.UNCLEAR
    if active_direction not in {Direction.UP, Direction.DOWN}:
        return "Counter Move: None"

    target_text = "BULLISH" if active_direction == Direction.DOWN else "BEARISH"
    counter_rows: list[tuple[str, Any]] = []
    for tf, state in rows:
        if not is_official_divergence(state):
            continue
        direction_text = _format_enum_value(getattr(state, "direction", "")).upper()
        if direction_text == target_text:
            counter_rows.append((tf, state))
    if not counter_rows:
        return "Counter Move: None"

    # Prefer the lowest (most internal) official counter row.
    counter_rows.sort(key=lambda row: TIMEFRAME_RANK.get(row[0], 0))
    tf, state = counter_rows[0]
    price = getattr(state, "divergence_price", None)

    structures = getattr(report, "structures", None) or getattr(report, "structure", None) or {}
    ranges: list[tuple[str, Any]] = []
    for range_tf in TIMEFRAME_ORDER:
        structure = structures.get(range_tf)
        if structure is None:
            continue
        range_state = getattr(structure, "range_state", None)
        if range_state is not None:
            ranges.append((range_tf, range_state))
    zones = _flatten_zones(report)

    parent_range_tf = ""
    if target_text == "BULLISH":
        from_range = _price_in_range_bottom(price, ranges)
        zone_support = _zone_supports_counter(price, zones, bullish=True)
        context_bits: list[str] = []
        if from_range:
            parent_range_tf = _first_matching_range_tf(price, ranges, bottom=True)
            range_label = f"{_normalize_tf(parent_range_tf)} range lower boundary" if parent_range_tf else "range lower boundary"
            context_bits.append(range_label)
        if zone_support:
            zone_tf = _first_matching_zone_tf(price, zones, bullish=True)
            zone_label = f"{_normalize_tf(zone_tf)} demand" if zone_tf else "demand zone"
            context_bits.append(zone_label)
    else:
        from_range = _price_in_range_top(price, ranges)
        zone_support = _zone_supports_counter(price, zones, bullish=False)
        context_bits = []
        if from_range:
            parent_range_tf = _first_matching_range_tf(price, ranges, bottom=False)
            range_label = f"{_normalize_tf(parent_range_tf)} range upper boundary" if parent_range_tf else "range upper boundary"
            context_bits.append(range_label)
        if zone_support:
            zone_tf = _first_matching_zone_tf(price, zones, bullish=False)
            zone_label = f"{_normalize_tf(zone_tf)} supply" if zone_tf else "supply zone"
            context_bits.append(zone_label)

    setup_label = _infer_counter_setup_label(
        active_trade_audit=active_trade_audit,
        tf=tf,
        bullish=(target_text == "BULLISH"),
    )
    setup_display = _counter_setup_display(setup_label)
    tactical_label = "tactical" if target_text != _direction_text_from_active(active_direction) else "aligned"
    direction_text = "Bullish" if target_text == "BULLISH" else "Bearish"
    base = f"Counter Move: {_normalize_tf(tf)} {direction_text} {setup_display} ({tactical_label})"
    trigger_line = _format_counter_trigger_line(state)
    if context_bits:
        context_text = " + ".join(context_bits)
        return f"{base} from {context_text}.\n{trigger_line}"
    return f"{base}.\n{trigger_line}"


def _format_counter_trigger_line(state: Any) -> str:
    """Render counter-move trigger price from divergence metadata."""

    trigger = _format_price_only(getattr(state, "divergence_price", None))
    return f"Counter Trigger Price: {trigger}"


def _infer_counter_setup_label(
    active_trade_audit: ActiveTradeAudit | None,
    tf: str,
    bullish: bool,
) -> str | None:
    if active_trade_audit is None:
        return None
    mapping = {"4h": "tf_4h", "1h": "tf_1h", "15m": "tf_15m", "5m": "tf_5m", "3m": "tf_3m"}
    field = mapping.get(tf)
    if not field:
        return None
    candidate = getattr(active_trade_audit, field, None)
    if candidate is None or not getattr(candidate, "exists", False):
        return None
    direction = _candidate_direction(candidate)
    if bullish and direction != Direction.UP:
        return None
    if (not bullish) and direction != Direction.DOWN:
        return None
    setup = _format_enum_value(getattr(candidate, "setup_type", "")).strip()
    if setup:
        return setup.title().replace(" ", " ")
    return None


def _counter_setup_display(setup_label: str | None) -> str:
    if not setup_label:
        return "Divergence"
    normalized = setup_label.upper().replace(" ", "_")
    if normalized == "TYPE_1":
        return "Type 1"
    if normalized == "TYPE_2":
        return "Type 2"
    if normalized == "TYPE_3":
        return "Type 3"
    return setup_label


def _direction_text_from_active(direction: Direction) -> str:
    if direction == Direction.UP:
        return "BULLISH"
    if direction == Direction.DOWN:
        return "BEARISH"
    return "UNCLEAR"


def _first_matching_range_tf(price: float | None, ranges: list[tuple[str, Any]], *, bottom: bool) -> str:
    if price is None:
        return ""
    for tf, state in ranges:
        if not getattr(state, "active", False):
            continue
        lower = getattr(state, "lower_edge", None)
        upper = getattr(state, "upper_edge", None)
        if not isinstance(lower, (int, float)) or not isinstance(upper, (int, float)):
            continue
        width = max(upper - lower, 1e-9)
        threshold = lower + (0.25 * width) if bottom else upper - (0.25 * width)
        if bottom and lower <= price <= threshold:
            return tf
        if (not bottom) and threshold <= price <= upper:
            return tf
    return ""


def _first_matching_zone_tf(price: float | None, zones: list[SupplyDemandZone], *, bullish: bool) -> str:
    zone_type_text = "DEMAND" if bullish else "SUPPLY"
    for zone in zones:
        if _format_enum_value(getattr(zone, "zone_type", "")).upper() != zone_type_text:
            continue
        band = _parse_band(getattr(zone, "price_band", ""))
        if band is None:
            continue
        if price is None or (band[0] <= price <= band[1]):
            return str(getattr(zone, "timeframe", "") or "")
    return ""


def _candidate_direction(candidate: ActiveTradeCandidate) -> Direction:
    value = getattr(candidate.direction, "value", candidate.direction)
    if value in (Direction.UP, Direction.DOWN):
        return value
    text = str(value).upper()
    if text == "BULLISH":
        return Direction.UP
    if text == "BEARISH":
        return Direction.DOWN
    if candidate.carry_direction in {Direction.UP, Direction.DOWN}:
        return candidate.carry_direction
    return Direction.UNCLEAR


def _smallest_active_internal_move(report: MarketReport) -> str:
    """Return the lowest-timeframe active trade row when available."""

    active_trade_audit = getattr(report, "active_trade_audit", None) or _latest_active_trade_audit(report)
    if active_trade_audit is not None:
        mapping = {"4h": "tf_4h", "1h": "tf_1h", "15m": "tf_15m", "5m": "tf_5m", "3m": "tf_3m"}
        existing_tfs: list[str] = []
        for tf in TIMEFRAME_ORDER:
            candidate = getattr(active_trade_audit, mapping[tf], None)
            if candidate is not None and getattr(candidate, "exists", False):
                existing_tfs.append(tf)
        if existing_tfs:
            smallest = min(existing_tfs, key=lambda tf: TIMEFRAME_RANK.get(tf, 99))
            return _normalize_tf(smallest)

    story_state = getattr(report, "story_state", None)
    fallback = _text(getattr(story_state, "current_move_timeframe", ""), default="N/A")
    if fallback == "N/A":
        return fallback
    return _normalize_tf(fallback)


def _format_per_tf_divergence_price(divergence_audit: DivergenceAudit) -> str:
    """Render per-timeframe divergence/impulse price lines for active rows."""

    lines: list[str] = []
    for tf, state in _iter_divergence_rows(divergence_audit):
        if not getattr(state, "exists", False):
            continue
        div_text = _format_price_only(getattr(state, "divergence_price", None))
        imp_text = _format_price_only(getattr(state, "impulse_price", None))
        lines.append(f"{_normalize_tf(tf)} Div: {div_text} | Imp: {imp_text}")
    if not lines:
        return "Per-TF Price: N/A"
    return "Per-TF Price:\n" + "\n".join(lines)


def _normalize_tf(tf: str) -> str:
    if tf == "4h":
        return "4H"
    if tf == "1h":
        return "1H"
    return tf


def _highest_available_timeframe(structures: dict[str, Any]) -> str:
    for timeframe in TIMEFRAME_ORDER:
        if timeframe in structures:
            return _normalize_tf(timeframe)
    return "N/A"


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


def _compact_zone_rows(zones: list[SupplyDemandZone], max_rows: int) -> list[str]:
    rows: list[str] = []
    for zone in zones[:max_rows]:
        timeframe = _normalize_tf(_text(getattr(zone, "timeframe", ""), default="N/A"))
        zone_type = _format_enum_value(getattr(zone, "zone_type", "N/A"))
        band = _text(getattr(zone, "price_band", ""), default="N/A")
        status = _text(getattr(zone, "status", ""), default="N/A")
        rows.append(f"{timeframe} {zone_type} {band} {status}".strip())
    if len(zones) > max_rows:
        rows.append(f"+{len(zones) - max_rows} more")
    return rows


