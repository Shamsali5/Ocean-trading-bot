"""Strict trade-function classifier for framework v1.2."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class TradeFunctionResult:
    trade_function: str
    valid: bool
    reason: str


_TRADE_FUNCTIONS = {
    "HIGHER_LEVEL_DIVERGENCE_TRADE",
    "DECOMPOSITION_TRADE",
    "RANGE_REJECTION_TRADE",
    "BREAKOUT_TRADE",
    "PULLBACK_CONTINUATION_TRADE",
    "SUPPLY_DEMAND_REACTION_TRADE",
    "UPGRADE_TRADE",
    "NONE",
}


def classify_trade_function(
    move_context,
    type_classification,
    range_result,
    zone_results,
    multi_level_result,
    trace=None,
) -> TradeFunctionResult:
    """Classify trade function while keeping Type label separate."""

    del move_context  # Reserved for future deeper context checks.
    type_label = _normalize_type_label(_value(type_classification, "type_label", fallback=("setup_type",)))
    type_valid = bool(_bool(type_classification, "valid", fallback=("exists",)))
    candidate_kind = str(_value(multi_level_result, "candidate_kind") or "").strip().upper()

    controlling_level_divergence = bool(
        _bool(multi_level_result, "controlling_level_divergence", fallback=("higher_level_divergence",))
    )
    decomposition_context = bool(_bool(multi_level_result, "decomposition_context"))
    divergence_confirmed = bool(_bool(multi_level_result, "divergence_confirmed"))
    impulse_confirmed = bool(_bool(multi_level_result, "impulse_confirmed"))
    carry_confirmed = bool(_bool(multi_level_result, "carry_confirmed"))

    range_edge_rejection = bool(
        _bool(multi_level_result, "range_edge_rejection")
        or _is_range_edge(range_result)
    )
    zone_present = bool(zone_results) or bool(_bool(multi_level_result, "zone_present"))
    structure_confirmed = bool(_bool(multi_level_result, "structure_confirmed"))
    supply_demand_confirmed = bool(
        zone_present and structure_confirmed and impulse_confirmed and carry_confirmed
    )

    upgrade_ready = bool(_bool(multi_level_result, "upgrade_ready"))
    upgrade_early = bool(_bool(multi_level_result, "upgrade_early"))

    trade_function = "NONE"
    valid = False
    reason = "No trade function context."

    if type_label == "TYPE_3" or candidate_kind == "TYPE3":
        valid = bool(type_valid and impulse_confirmed and carry_confirmed)
        trade_function = "BREAKOUT_TRADE" if valid else "NONE"
        reason = (
            "Breakout Trade requires valid Type 3 with impulse and carry confirmation."
            if valid
            else "Breakout Trade invalid: Type 3, impulse, or carry confirmation is missing."
        )
    elif type_label == "TYPE_2" or candidate_kind == "TYPE2":
        valid = bool(type_valid and impulse_confirmed and carry_confirmed)
        trade_function = "PULLBACK_CONTINUATION_TRADE" if valid else "NONE"
        reason = (
            "Pullback Continuation Trade requires valid Type 2 with continuation impulse and carry."
            if valid
            else "Pullback Continuation Trade invalid: Type 2, impulse, or carry confirmation is missing."
        )
    elif candidate_kind == "RANGE_REJECTION":
        valid = bool(range_edge_rejection and divergence_confirmed and impulse_confirmed and carry_confirmed)
        trade_function = "RANGE_REJECTION_TRADE" if valid else "NONE"
        reason = (
            "Range Rejection Trade requires range edge + divergence + impulse + carry."
            if valid
            else "Range Rejection Trade invalid: missing edge/divergence/impulse/carry confirmation."
        )
    elif candidate_kind == "ZONE_REACTION":
        valid = bool(supply_demand_confirmed)
        trade_function = "SUPPLY_DEMAND_REACTION_TRADE" if valid else "NONE"
        reason = (
            "Supply/Demand Reaction Trade requires zone + structure + impulse + carry."
            if valid
            else "Supply/Demand Reaction Trade invalid: missing zone reaction confirmation stack."
        )
    elif candidate_kind == "UPGRADE":
        valid = bool(upgrade_ready)
        trade_function = "UPGRADE_TRADE" if valid else "NONE"
        reason = (
            "Upgrade Trade requires lower-level expansion replacing higher-level structure."
            if valid
            else "Upgrade Trade invalid: upgrade not structurally confirmed yet."
        )
    elif type_label == "TYPE_1" or candidate_kind == "TYPE1":
        if controlling_level_divergence:
            valid = bool(type_valid and impulse_confirmed and carry_confirmed)
            trade_function = "HIGHER_LEVEL_DIVERGENCE_TRADE" if valid else "NONE"
            reason = (
                "Higher-Level Divergence Trade requires controlling-level divergence + impulse + carry."
                if valid
                else "Higher-Level Divergence Trade invalid: controlling divergence/impulse/carry missing."
            )
        else:
            valid = bool(type_valid and decomposition_context and impulse_confirmed and carry_confirmed)
            trade_function = "DECOMPOSITION_TRADE" if valid else "NONE"
            reason = (
                "Decomposition Trade requires lower-level decomposition against/inside parent with impulse + carry."
                if valid
                else "Decomposition Trade invalid: decomposition/impulse/carry requirements not met."
            )

    if trade_function not in _TRADE_FUNCTIONS:
        trade_function = "NONE"
        valid = False
        reason = "Trade function invalid: unrecognized function label."

    _add_check(
        trace=trace,
        name="Trade function assigned",
        passed=trade_function != "NONE",
        severity="ERROR" if trade_function == "NONE" else "INFO",
        details=f"trade_function={trade_function}, type_label={type_label}, reason={reason}",
        function="classify_trade_function",
    )
    separation_passed = trade_function not in {"TYPE_1", "TYPE_2", "TYPE_3"}
    _add_check(
        trace=trace,
        name="Trade function separate from Type label",
        passed=separation_passed,
        severity="ERROR" if not separation_passed else "INFO",
        details=f"type_label={type_label}, trade_function={trade_function}",
        function="classify_trade_function",
    )
    _add_check(
        trace=trace,
        name="Upgrade not assumed early",
        passed=not upgrade_early,
        severity="ERROR" if upgrade_early else "INFO",
        details=(
            "Upgrade attempted before lower-level expansion confirmed."
            if upgrade_early
            else "Upgrade classification waits for structural replacement confirmation."
        ),
        function="classify_trade_function",
    )
    _add_check(
        trace=trace,
        name="Supply/demand reaction requires confirmation",
        passed=(supply_demand_confirmed if candidate_kind == "ZONE_REACTION" else True),
        severity=(
            "ERROR"
            if candidate_kind == "ZONE_REACTION" and not supply_demand_confirmed
            else "INFO"
        ),
        details=(
            "zone_present="
            f"{zone_present}, structure_confirmed={structure_confirmed}, "
            f"impulse_confirmed={impulse_confirmed}, carry_confirmed={carry_confirmed}"
        ),
        function="classify_trade_function",
    )
    return TradeFunctionResult(trade_function=trade_function, valid=bool(valid), reason=reason)


def _is_range_edge(range_result: Any) -> bool:
    location = str(_value(range_result, "price_location") or "").strip().upper()
    if location in {"UPPER_EDGE", "LOWER_EDGE"}:
        return True
    role = str(_value(range_result, "status") or "").strip().upper()
    return role in {"RE_ENTERED", "ACTIVE"}


def _normalize_type_label(raw: Any) -> str:
    value = str(getattr(raw, "value", raw) or "").strip().upper().replace(" ", "_")
    if value in {"TYPE_1", "TYPE_2", "TYPE_3", "NONE"}:
        return value
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
    function: str,
) -> None:
    if trace is None or not hasattr(trace, "add_check"):
        return
    trace.add_check(
        name=name,
        passed=bool(passed),
        severity=severity,
        details=details,
        file="ocean_trade_function_classifier.py",
        function=function,
    )
