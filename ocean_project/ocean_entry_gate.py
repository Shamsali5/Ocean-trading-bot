"""Final BUY/SELL/WAIT fresh-entry gate for framework v1.2."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class EntryDecision:
    fresh_entry_valid: bool
    side: str | None  # BUY / SELL / None
    entry_zone: str | None
    invalidation: str | None
    too_late_to_chase: bool
    reason: str


def evaluate_fresh_entry(
    move_context,
    type_classification,
    trade_function_result,
    impulse_result,
    carry_result,
    range_result,
    zone_results,
    multi_level_result,
    trace=None,
) -> EntryDecision:
    """Evaluate final fresh-entry gate and return BUY/SELL/WAIT decision."""

    direction = _normalize_direction(_value(type_classification, "direction"))
    type_label = _normalize_type_label(_value(type_classification, "type_label", fallback=("setup_type",)))
    type_valid = bool(_bool(type_classification, "valid"))
    trade_function = str(_value(trade_function_result, "trade_function") or "NONE").strip().upper()
    trade_function_valid = bool(_bool(trade_function_result, "valid"))

    impulse_confirmed = bool(_bool(impulse_result, "confirmed"))
    acceptance_confirmed = bool(
        _bool(impulse_result, "acceptance_valid")
        or _bool(impulse_result, "accepted")
        or _bool(impulse_result, "breakout_accepted")
    )
    carry_state = str(_value(carry_result, "state") or "").strip().upper()
    carry_finished = bool(_bool(carry_result, "finished"))
    carry_timeframe = str(_value(carry_result, "timeframe", fallback=("carry_timeframe",)) or "")
    too_late = bool(
        _bool(type_classification, "too_late_to_chase")
        or carry_state in {"MATURE", "EXHAUSTING"}
    )
    invalidation = str(_value(type_classification, "invalidation") or "").strip() or None
    entry_zone = str(_value(type_classification, "entry_zone", fallback=("origin_price_zone",)) or "").strip() or None

    range_midpoint = bool(
        _bool(range_result, "active")
        and str(_value(range_result, "price_location") or "").strip().upper() in {"MID", "MIDPOINT"}
    )
    breakout_requires_acceptance = type_label == "TYPE_3"
    clear_carry = bool(carry_timeframe and carry_state in {"FRESH", "ACTIVE"} and not carry_finished)
    carry_exhausting = bool(carry_state == "EXHAUSTING" or carry_finished)

    move_timeframe = str(
        _value(move_context, "current_timeframe", fallback=("origin_timeframe", "timeframe"))
        or ""
    ).strip()
    move_origin = str(_value(move_context, "current_origin", fallback=("origin",)) or "").strip().upper()
    ownership_clear = bool(move_timeframe and move_timeframe != "UNCLEAR" and move_origin != "UNCLEAR")

    ml_direction = _normalize_direction(_value(multi_level_result, "direction"))
    ml_valid = bool(_bool(multi_level_result, "valid")) if _value(multi_level_result, "valid") is not None else True
    ml_status = str(
        _value(
            multi_level_result,
            "higher_tf_official_or_context",
            fallback=("higher_tf_status",),
        )
        or "NONE"
    ).strip().upper()
    ml_contradicts = bool(ml_direction in {"BULLISH", "BEARISH"} and direction in {"BULLISH", "BEARISH"} and ml_direction != direction)
    separation_clear = _multi_level_separation_is_clear(multi_level_result, move_timeframe)

    zone_info = _zone_supports_entry(zone_results, direction, move_timeframe)
    zone_blocks = bool(zone_info["blocks"])
    zone_reason = str(zone_info["reason"])

    fatal_reasons: list[str] = []
    if type_label not in {"TYPE_1", "TYPE_2", "TYPE_3"} or not type_valid:
        fatal_reasons.append("No clear Type 1/2/3 setup.")
    if trade_function == "NONE" or not trade_function_valid:
        fatal_reasons.append("Trade function not valid for fresh entry.")
    if not impulse_confirmed:
        fatal_reasons.append("No impulse blocks entry.")
    if breakout_requires_acceptance and not acceptance_confirmed:
        fatal_reasons.append("Breakout has no acceptance.")
    if carry_exhausting:
        fatal_reasons.append("No fresh entry if carry exhausting.")
    if not clear_carry:
        fatal_reasons.append("No clear carry blocks entry.")
    if range_midpoint:
        fatal_reasons.append("Range midpoint blocks fresh entry.")
    if too_late:
        fatal_reasons.append("Move mature/exhausting or too late to chase.")
    if invalidation is None:
        fatal_reasons.append("Invalidation unclear.")
    if not ownership_clear:
        fatal_reasons.append("Active trade timeframe ownership unclear.")
    if ml_contradicts:
        fatal_reasons.append("Multi-level context contradicts entry direction.")
    if not ml_valid:
        fatal_reasons.append("Multi-level ownership is invalid.")
    if not separation_clear:
        fatal_reasons.append("Controlling origin / active trade / carry cannot be separated.")
    if zone_blocks:
        fatal_reasons.append(zone_reason)

    buy_gate_passed = bool(direction == "BULLISH" and not fatal_reasons)
    sell_gate_passed = bool(direction == "BEARISH" and not fatal_reasons)
    _add_check(
        trace=trace,
        name="BUY gate checked",
        passed=buy_gate_passed if direction == "BULLISH" else True,
        severity="ERROR" if direction == "BULLISH" and not buy_gate_passed else "INFO",
        details=f"direction={direction}, failures={'; '.join(fatal_reasons) or 'none'}",
    )
    _add_check(
        trace=trace,
        name="SELL gate checked",
        passed=sell_gate_passed if direction == "BEARISH" else True,
        severity="ERROR" if direction == "BEARISH" and not sell_gate_passed else "INFO",
        details=f"direction={direction}, failures={'; '.join(fatal_reasons) or 'none'}",
    )
    _add_check(
        trace=trace,
        name="No fresh entry if carry exhausting",
        passed=not carry_exhausting,
        severity="ERROR" if carry_exhausting else "INFO",
        details=f"carry_state={carry_state}, finished={carry_finished}",
    )
    _add_check(
        trace=trace,
        name="Range midpoint blocks fresh entry",
        passed=not range_midpoint,
        severity="ERROR" if range_midpoint else "INFO",
        details=f"range_active={_bool(range_result, 'active')}, price_location={_value(range_result, 'price_location')}",
    )
    _add_check(
        trace=trace,
        name="No clear carry blocks entry",
        passed=clear_carry,
        severity="ERROR" if not clear_carry else "INFO",
        details=f"carry_timeframe={carry_timeframe}, carry_state={carry_state}, carry_finished={carry_finished}",
    )
    _add_check(
        trace=trace,
        name="No impulse blocks entry",
        passed=impulse_confirmed,
        severity="ERROR" if not impulse_confirmed else "INFO",
        details=f"impulse_confirmed={impulse_confirmed}, acceptance_confirmed={acceptance_confirmed}",
    )

    if fatal_reasons:
        return EntryDecision(
            fresh_entry_valid=False,
            side=None,
            entry_zone=entry_zone,
            invalidation=invalidation,
            too_late_to_chase=too_late,
            reason="WAIT because " + "; ".join(fatal_reasons),
        )

    if buy_gate_passed:
        return EntryDecision(
            fresh_entry_valid=True,
            side="BUY",
            entry_zone=entry_zone,
            invalidation=invalidation,
            too_late_to_chase=False,
            reason="BUY gate passed.",
        )
    if sell_gate_passed:
        return EntryDecision(
            fresh_entry_valid=True,
            side="SELL",
            entry_zone=entry_zone,
            invalidation=invalidation,
            too_late_to_chase=False,
            reason="SELL gate passed.",
        )
    return EntryDecision(
        fresh_entry_valid=False,
        side=None,
        entry_zone=entry_zone,
        invalidation=invalidation,
        too_late_to_chase=too_late,
        reason="WAIT because structure mixed.",
    )


def _multi_level_separation_is_clear(multi_level_result: Any, move_timeframe: str) -> bool:
    controlling_origin = str(_value(multi_level_result, "controlling_origin") or "").strip()
    active_execution_trade = str(_value(multi_level_result, "active_execution_trade") or "").strip()
    carrying_timeframe = str(_value(multi_level_result, "carrying_timeframe") or "").strip()
    if not active_execution_trade:
        return False
    if move_timeframe and move_timeframe != "UNCLEAR" and move_timeframe not in active_execution_trade:
        return False
    if carrying_timeframe and move_timeframe and carrying_timeframe == move_timeframe:
        return False
    if controlling_origin and active_execution_trade and carrying_timeframe:
        execution_tf = active_execution_trade.split(" ", 1)[0].strip()
        if execution_tf == carrying_timeframe:
            return False
    return True


def _zone_supports_entry(zone_results: Any, direction: str, move_timeframe: str) -> dict[str, Any]:
    zones = zone_results if isinstance(zone_results, list) else []
    if not zones:
        return {"blocks": False, "reason": ""}

    reacting = []
    for zone in zones:
        timeframe = str(_value(zone, "timeframe") or "")
        if move_timeframe and timeframe and timeframe != move_timeframe:
            continue
        status = str(_value(zone, "status") or "").strip().upper()
        if status in {"REACTING", "TESTED", "TOUCHED"}:
            reacting.append(zone)

    if not reacting:
        return {"blocks": False, "reason": ""}

    has_structure_confirmation = any(
        _bool(zone, "structure_confirmed") or _bool(zone, "impulse_confirmed") or _bool(zone, "confirmation")
        for zone in reacting
    )
    if not has_structure_confirmation:
        return {"blocks": True, "reason": "Zone exists but no structural confirmation."}

    if direction == "BULLISH":
        opposed = any(str(_value(zone, "zone_type") or "").strip().upper() == "SUPPLY" for zone in reacting)
        if opposed and not any(_bool(zone, "supports_trade") for zone in reacting):
            return {"blocks": True, "reason": "Supply zone opposes bullish fresh entry."}
    if direction == "BEARISH":
        opposed = any(str(_value(zone, "zone_type") or "").strip().upper() == "DEMAND" for zone in reacting)
        if opposed and not any(_bool(zone, "supports_trade") for zone in reacting):
            return {"blocks": True, "reason": "Demand zone opposes bearish fresh entry."}
    return {"blocks": False, "reason": ""}


def _normalize_type_label(raw: Any) -> str:
    value = str(getattr(raw, "value", raw) or "").strip().upper().replace(" ", "_")
    if value in {"TYPE_1", "TYPE_2", "TYPE_3", "NONE"}:
        return value
    return "NONE"


def _normalize_direction(raw: Any) -> str:
    value = str(getattr(raw, "value", raw) or "").strip().upper()
    if value in {"BULLISH", "UP", "BUY"}:
        return "BULLISH"
    if value in {"BEARISH", "DOWN", "SELL"}:
        return "BEARISH"
    return "NONE"


def _value(result: Any, key: str, fallback: tuple[str, ...] = ()) -> Any:
    if result is None:
        return None
    if isinstance(result, dict):
        if key in result:
            return result.get(key)
        for alt in fallback:
            if alt in result:
                return result.get(alt)
        return None
    value = getattr(result, key, None)
    if value is not None:
        return value
    for alt in fallback:
        value = getattr(result, alt, None)
        if value is not None:
            return value
    return None


def _bool(result: Any, key: str, fallback: tuple[str, ...] = ()) -> bool:
    return bool(_value(result, key, fallback))


def _add_check(
    *,
    trace: Any,
    name: str,
    passed: bool,
    severity: str,
    details: str,
) -> None:
    if trace is None or not hasattr(trace, "add_check"):
        return
    trace.add_check(
        name=name,
        passed=bool(passed),
        severity=severity,
        details=details,
        file="ocean_entry_gate.py",
        function="evaluate_fresh_entry",
    )
