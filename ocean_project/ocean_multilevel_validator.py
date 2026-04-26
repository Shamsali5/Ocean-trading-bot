"""Strict multi-level same-story validator for framework v1.2."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

TIMEFRAME_ORDER = ("4h", "1h", "15m", "5m", "3m")
TIMEFRAME_RANK = {"4h": 5, "1h": 4, "15m": 3, "5m": 2, "3m": 1}


@dataclass(slots=True)
class MultiLevelStoryResult:
    active: bool
    direction: str | None
    confirmed_timeframes: list[str]
    controlling_origin: str | None
    active_execution_trade: str | None
    carrying_timeframe: str | None
    higher_tf_official_or_context: str
    explanation: str
    valid: bool


def validate_multi_level_same_story(
    divergence_results_by_tf,
    type_results_by_tf,
    carry_results_by_tf,
    trace=None,
) -> MultiLevelStoryResult:
    """Validate multi-level ownership with anti-drift protections."""

    timeframe_rows: dict[str, dict[str, Any]] = {}
    all_timeframes = _ordered_timeframes(
        divergence_results_by_tf,
        type_results_by_tf,
        carry_results_by_tf,
    )
    for timeframe in all_timeframes:
        divergence_row = _row_for_timeframe(divergence_results_by_tf, timeframe)
        type_row = _row_for_timeframe(type_results_by_tf, timeframe)
        carry_row = _row_for_timeframe(carry_results_by_tf, timeframe)
        timeframe_rows[timeframe] = _audit_timeframe(
            timeframe=timeframe,
            divergence_row=divergence_row,
            type_row=type_row,
            carry_row=carry_row,
        )

    grouped = {"BULLISH": [], "BEARISH": []}
    for timeframe in all_timeframes:
        row = timeframe_rows[timeframe]
        if row["official"] and row["direction"] in {"BULLISH", "BEARISH"}:
            grouped[row["direction"]].append(row)

    selected_direction = _select_direction(grouped)
    selected_rows = grouped[selected_direction] if selected_direction in grouped else []
    confirmed_timeframes = sorted(
        [row["timeframe"] for row in selected_rows],
        key=lambda tf: TIMEFRAME_RANK.get(tf, 0),
        reverse=True,
    )

    active = len(confirmed_timeframes) >= 2
    if confirmed_timeframes:
        higher_tf_status = "OFFICIAL_MULTI_LEVEL" if active else "WEAKENING_CONTEXT_ONLY"
    else:
        higher_tf_status = "NONE"

    controlling_origin, controlling_tf = _resolve_controlling_origin(selected_rows)
    active_execution_trade, execution_tf = _resolve_active_execution_trade(selected_rows, confirmed_timeframes)
    carrying_timeframe = _resolve_carrying_timeframe(timeframe_rows, execution_tf)

    independent_audit_passed = len(timeframe_rows) == len(all_timeframes)
    no_copied_divergence = not any(
        row["type_valid"] and row["origin_timeframe"] not in {"", row["timeframe"]}
        for row in timeframe_rows.values()
    )
    controlling_origin_separated = controlling_origin is not None and (controlling_tf in confirmed_timeframes if controlling_tf else True)
    execution_trade_separated = (
        active_execution_trade is not None and (execution_tf in confirmed_timeframes if execution_tf else True)
    ) if confirmed_timeframes else True
    carry_timeframe_separated = carrying_timeframe is None or execution_tf is None or carrying_timeframe != execution_tf
    anti_drift_passed = bool(
        independent_audit_passed
        and no_copied_divergence
        and controlling_origin_separated
        and execution_trade_separated
        and carry_timeframe_separated
    )
    valid = anti_drift_passed and bool(not confirmed_timeframes or (controlling_origin and active_execution_trade))

    if confirmed_timeframes:
        explanation = (
            f"{selected_direction.title()} confirmation on {', '.join(_display_tf(tf) for tf in confirmed_timeframes)}; "
            f"controlling={controlling_origin or 'None'}; execution={active_execution_trade or 'None'}; "
            f"carry={carrying_timeframe or 'None'}."
        )
    elif any(row["context"] for row in timeframe_rows.values()):
        explanation = (
            "No official multi-level confirmation; higher timeframe remains context-only until "
            "same-timeframe A-B-C + energy weakening + opposite impulse + carry are all present."
        )
    else:
        explanation = "No same-story confirmations across audited timeframes."

    if not valid:
        explanation = (
            "Timeframe ownership unclear; anti-drift protections require WAIT for fresh entries. "
            + explanation
        )

    _add_check(
        trace=trace,
        name="Each timeframe audited independently",
        passed=independent_audit_passed,
        severity="ERROR" if not independent_audit_passed else "INFO",
        details=f"Audited {len(timeframe_rows)} rows across {len(all_timeframes)} timeframes.",
    )
    _add_check(
        trace=trace,
        name="No divergence copied across timeframes",
        passed=no_copied_divergence,
        severity="ERROR" if not no_copied_divergence else "INFO",
        details="Type ownership must match each timeframe's own divergence context.",
    )
    _add_check(
        trace=trace,
        name="Controlling origin separated",
        passed=controlling_origin_separated,
        severity="ERROR" if not controlling_origin_separated else "INFO",
        details=f"controlling_origin={controlling_origin}, controlling_tf={controlling_tf}",
    )
    _add_check(
        trace=trace,
        name="Active execution trade separated",
        passed=execution_trade_separated,
        severity="ERROR" if not execution_trade_separated else "INFO",
        details=f"active_execution_trade={active_execution_trade}, execution_tf={execution_tf}",
    )
    _add_check(
        trace=trace,
        name="Carry timeframe separated",
        passed=carry_timeframe_separated,
        severity="ERROR" if not carry_timeframe_separated else "INFO",
        details=f"execution_tf={execution_tf}, carrying_timeframe={carrying_timeframe}",
    )
    _add_check(
        trace=trace,
        name="Anti-drift rule passed",
        passed=anti_drift_passed,
        severity="ERROR" if not anti_drift_passed else "INFO",
        details=(
            f"independent={independent_audit_passed}, no_copy={no_copied_divergence}, "
            f"control_sep={controlling_origin_separated}, exec_sep={execution_trade_separated}, "
            f"carry_sep={carry_timeframe_separated}"
        ),
    )

    return MultiLevelStoryResult(
        active=active,
        direction=selected_direction if confirmed_timeframes else None,
        confirmed_timeframes=confirmed_timeframes,
        controlling_origin=controlling_origin,
        active_execution_trade=active_execution_trade,
        carrying_timeframe=carrying_timeframe,
        higher_tf_official_or_context=higher_tf_status,
        explanation=explanation,
        valid=valid,
    )


def _ordered_timeframes(
    divergence_results_by_tf: Any,
    type_results_by_tf: Any,
    carry_results_by_tf: Any,
) -> list[str]:
    keys: set[str] = set(TIMEFRAME_ORDER)
    for bucket in (divergence_results_by_tf, type_results_by_tf, carry_results_by_tf):
        if isinstance(bucket, dict):
            keys.update(str(key) for key in bucket.keys())
    ordered = sorted(keys, key=lambda tf: TIMEFRAME_RANK.get(tf, 0), reverse=True)
    return [tf for tf in ordered if tf in TIMEFRAME_RANK]


def _row_for_timeframe(container: Any, timeframe: str) -> Any:
    if isinstance(container, dict):
        return container.get(timeframe)
    return None


def _audit_timeframe(
    *,
    timeframe: str,
    divergence_row: Any,
    type_row: Any,
    carry_row: Any,
) -> dict[str, Any]:
    direction = _normalize_direction(
        _value(type_row, "direction")
        or _value(divergence_row, "direction")
        or _value(carry_row, "direction")
    )
    type_label = _normalize_type_label(_value(type_row, "type_label", fallback=("setup_type",)))
    type_valid = bool(_bool(type_row, "valid", fallback=("exists",)))
    full_label = str(_value(type_row, "full_label", fallback=("type_label",)) or "").strip()
    origin_timeframe = str(_value(type_row, "origin_timeframe", fallback=("timeframe",)) or "")

    has_same_tf_abc = bool(_bool(divergence_row, "abc_valid"))
    has_energy_weakening = _has_energy_weakening(divergence_row)
    has_opposite_impulse = bool(
        _bool(divergence_row, "impulse_confirmed")
        or _bool(type_row, "impulse_confirmed")
    )

    carry_timeframe = str(_value(carry_row, "timeframe", fallback=("carry_timeframe",)) or "")
    carry_state = str(_value(carry_row, "state", fallback=("carry_state",)) or "").upper()
    carry_finished = bool(_bool(carry_row, "finished", fallback=("carry_finished",)))
    has_lower_tf_carry = bool(
        carry_timeframe
        and carry_timeframe != timeframe
        and carry_state not in {"", "NONE", "UNCLEAR"}
        and not carry_finished
    )

    official = bool(
        type_valid
        and type_label in {"TYPE_1", "TYPE_2", "TYPE_3"}
        and origin_timeframe == timeframe
        and direction in {"BULLISH", "BEARISH"}
        and has_lower_tf_carry
        and (
            (
                type_label == "TYPE_1"
                and has_same_tf_abc
                and has_energy_weakening
                and has_opposite_impulse
            )
            or (
                type_label == "TYPE_2"
                and has_opposite_impulse
            )
            or (
                type_label == "TYPE_3"
                and bool(
                    _bool(type_row, "breakout_acceptance_valid")
                    or _bool(type_row, "breakout_confirmed")
                    or _bool(type_row, "range_acceptance_valid")
                )
            )
        )
    )
    context = bool(_bool(divergence_row, "exists") or type_valid)

    if not full_label and direction in {"BULLISH", "BEARISH"} and type_label != "NONE":
        side = "Bullish" if direction == "BULLISH" else "Bearish"
        full_label = f"{_display_tf(timeframe)} {side} Type {type_label.split('_')[-1]}"
    if not full_label and direction in {"BULLISH", "BEARISH"}:
        side = "Bullish" if direction == "BULLISH" else "Bearish"
        full_label = f"{_display_tf(timeframe)} {side} Type 1"

    return {
        "timeframe": timeframe,
        "direction": direction,
        "type_label": type_label,
        "type_valid": type_valid,
        "full_label": full_label or None,
        "origin_timeframe": origin_timeframe,
        "official": official,
        "context": context,
        "carry_timeframe": carry_timeframe or None,
        "fresh_entry_valid": bool(_bool(type_row, "fresh_entry_valid")),
        "existing_hold_valid": bool(_bool(type_row, "existing_hold_valid")),
        "has_same_tf_abc": has_same_tf_abc,
        "has_energy_weakening": has_energy_weakening,
        "has_opposite_impulse": has_opposite_impulse,
        "has_lower_tf_carry": has_lower_tf_carry,
    }


def _select_direction(grouped: dict[str, list[dict[str, Any]]]) -> str | None:
    bullish = grouped.get("BULLISH", [])
    bearish = grouped.get("BEARISH", [])
    if not bullish and not bearish:
        return None
    if len(bullish) > len(bearish):
        return "BULLISH"
    if len(bearish) > len(bullish):
        return "BEARISH"
    best_bullish = max((TIMEFRAME_RANK.get(row["timeframe"], 0) for row in bullish), default=0)
    best_bearish = max((TIMEFRAME_RANK.get(row["timeframe"], 0) for row in bearish), default=0)
    return "BULLISH" if best_bullish >= best_bearish else "BEARISH"


def _resolve_controlling_origin(rows: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    if not rows:
        return (None, None)
    controlling_row = max(rows, key=lambda row: TIMEFRAME_RANK.get(row["timeframe"], 0))
    return (str(controlling_row["full_label"]) if controlling_row.get("full_label") else None, controlling_row["timeframe"])


def _resolve_active_execution_trade(
    rows: list[dict[str, Any]],
    confirmed_timeframes: list[str],
) -> tuple[str | None, str | None]:
    if not rows or not confirmed_timeframes:
        return (None, None)
    by_tf = {row["timeframe"]: row for row in rows}
    eligible = [
        row
        for row in rows
        if row["timeframe"] in confirmed_timeframes
        and (row["fresh_entry_valid"] or row["existing_hold_valid"])
    ]
    if not eligible:
        eligible = [by_tf[tf] for tf in confirmed_timeframes if tf in by_tf]
    if not eligible:
        return (None, None)
    execution_row = min(eligible, key=lambda row: TIMEFRAME_RANK.get(row["timeframe"], 0))
    return (str(execution_row["full_label"]) if execution_row.get("full_label") else None, execution_row["timeframe"])


def _resolve_carrying_timeframe(
    timeframe_rows: dict[str, dict[str, Any]],
    execution_tf: str | None,
) -> str | None:
    if execution_tf is None:
        return None
    row = timeframe_rows.get(execution_tf)
    if not row:
        return None
    carry_tf = row.get("carry_timeframe")
    return str(carry_tf) if carry_tf else None


def _normalize_type_label(raw: Any) -> str:
    value = str(getattr(raw, "value", raw) or "").strip().upper().replace(" ", "_")
    if value in {"TYPE_1", "TYPE_2", "TYPE_3", "NONE"}:
        return value
    return "NONE"


def _normalize_direction(raw: Any) -> str:
    value = str(getattr(raw, "value", raw) or "").strip().upper()
    if value in {"BULLISH", "UP"}:
        return "BULLISH"
    if value in {"BEARISH", "DOWN"}:
        return "BEARISH"
    return "NONE"


def _has_energy_weakening(row: Any) -> bool:
    if bool(_bool(row, "valid_energy_weakening")):
        return True
    weakening_count = _value(row, "weakening_count")
    try:
        if weakening_count is not None and int(weakening_count) >= 2:
            return True
    except (TypeError, ValueError):
        pass
    flags = [
        _bool(row, "velocity_weaker", fallback=("vel_divergence",)),
        _bool(row, "acceleration_weaker", fallback=("acc_divergence",)),
        _bool(row, "acceleration_area_weaker", fallback=("acc_area_divergence",)),
    ]
    return sum(bool(flag) for flag in flags) >= 2


def _display_tf(timeframe: str) -> str:
    if timeframe == "4h":
        return "4H"
    if timeframe == "1h":
        return "1H"
    return timeframe


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
        file="ocean_multilevel_validator.py",
        function="validate_multi_level_same_story",
    )
