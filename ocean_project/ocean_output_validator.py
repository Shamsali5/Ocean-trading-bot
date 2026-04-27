"""Validate and render required framework output sections A-R."""

from __future__ import annotations

from typing import Any

from ocean_framework_v12_contract import REQUIRED_OUTPUT_SECTIONS

_SECTION_ORDER: list[tuple[str, str, str]] = [
    (chr(ord("A") + index), section, section.replace("_", " "))
    for index, section in enumerate(REQUIRED_OUTPUT_SECTIONS)
]

_FINAL_EXECUTION_FIELDS = [
    "Signal",
    "Trade Function",
    "Type Label",
    "Controlling Origin",
    "Active Execution Trade",
    "Entry Zone",
    "Stop / Invalidation",
    "Carrying TF",
    "Management State",
    "Reason",
]

_IMPORTANT_FIELDS: dict[str, list[str]] = {
    "META": ["symbol", "timestamp"],
    "HIGHER_TIMEFRAME_CONTEXT": ["highest_tf"],
    "CURRENT_MOVE": ["timeframe", "direction"],
    "STRUCTURE_STATE": ["state"],
    "DIVERGENCE_STATE": ["direction"],
    "LAST_MEANINGFUL_DIVERGENCE": ["timeframe", "direction"],
    "IMPULSE_ACCEPTANCE": ["impulse_confirmed"],
    "SUPPLY_DEMAND_ZONE_MAP": ["zones"],
    "CARRY_STATUS": ["state", "carrying_tf"],
    "MULTI_LEVEL_STORY": ["controlling_origin"],
    "TRADE_CLASSIFICATION": ["trade_function", "type_label"],
    "MANAGEMENT_STATE": ["management_state"],
    "CURRENT_ACTIVE_MEANINGFUL_TRADE": ["exists"],
    "POSITION_MANAGEMENT_FOR_ACTIVE_TRADE": ["already_in_status", "not_in_status"],
    "MARKET_HIERARCHY": ["controlling_origin", "active_execution_trade"],
    "WHAT_TO_WATCH_NEXT": ["next_event"],
    "CURRENT_MOVE_SUMMARY": ["summary"],
    "FINAL_EXECUTION_BLOCK": _FINAL_EXECUTION_FIELDS,
}


def validate_required_output_sections(output_dict, trace=None):
    """Validate required framework sections/fields and emit audit checks."""

    payload = output_dict if isinstance(output_dict, dict) else {}
    missing_sections: list[str] = []
    missing_fields: dict[str, list[str]] = {}

    for letter, section, _ in _SECTION_ORDER:
        section_value = _get_section_value(payload, f"{letter} {section}")
        if section_value is None:
            section_value = _get_section_value(payload, section)
        display_section = f"{letter} {section}"
        present = section_value is not None
        if not present:
            missing_sections.append(display_section)
        _add_check(
            trace=trace,
            name="Required output section exists",
            passed=present,
            severity="ERROR" if not present else "INFO",
            details=section,
        )
        _add_check(
            trace=trace,
            name=f"Section {display_section} exists",
            passed=present,
            severity="ERROR" if not present else "INFO",
            details=display_section,
        )
        if not present:
            continue

        section_missing: list[str] = []
        required_fields = _IMPORTANT_FIELDS.get(section, [])
        for field in required_fields:
            if not _field_exists(section_value, field):
                section_missing.append(field)
            if section == "FINAL_EXECUTION_BLOCK":
                _add_check(
                    trace=trace,
                    name=f"FINAL_EXECUTION_BLOCK field '{field}' exists",
                    passed=field not in section_missing,
                    severity="ERROR" if field in section_missing else "INFO",
                    details=field,
                )
        if section_missing:
            missing_fields[display_section] = section_missing
            _add_check(
                trace=trace,
                name="Required output section fields exist",
                passed=False,
                severity="ERROR" if section == "FINAL_EXECUTION_BLOCK" else "WARNING",
                details=f"{display_section} -> missing: {', '.join(section_missing)}",
            )
        else:
            _add_check(
                trace=trace,
                name="Required output section fields exist",
                passed=True,
                severity="INFO",
                details=f"{display_section} -> all required fields present.",
            )

    valid = not missing_sections and not missing_fields
    return {
        "valid": valid,
        "missing_sections": missing_sections,
        "missing_fields": missing_fields,
    }


def render_framework_output(output_dict):
    """Render deterministic telegram-safe framework text from section dict."""

    payload = output_dict if isinstance(output_dict, dict) else {}
    final_block = _get_section_value(payload, "R FINAL_EXECUTION_BLOCK")
    if not isinstance(final_block, dict):
        final_block = _get_section_value(payload, "FINAL_EXECUTION_BLOCK")
    if not isinstance(final_block, dict):
        final_block = {}
        payload["R FINAL_EXECUTION_BLOCK"] = final_block
    for field in _FINAL_EXECUTION_FIELDS:
        final_block.setdefault(field, "N/A")

    meta = _get_section_value(payload, "A META")
    if not isinstance(meta, dict):
        meta = _get_section_value(payload, "META")
    meta = meta if isinstance(meta, dict) else {}
    symbol = _safe_value(_get_field_value(meta, "symbol"))
    price = _safe_value(_get_field_value(meta, "current_price"))
    timestamp = _safe_value(_get_field_value(meta, "timestamp"))

    lines = [
        f"🌊 OCEAN SIGNAL | {symbol}",
        f"Price: {price}",
        f"Time: {timestamp}",
    ]

    for letter, section, _ in _SECTION_ORDER:
        lines.append("")
        lines.append("━━━━━━━━━━━━━━")
        lines.append(f"{letter} {section}")
        section_value = _get_section_value(payload, f"{letter} {section}")
        if section_value is None:
            section_value = _get_section_value(payload, section)
        lines.extend(_render_section_lines(section, section_value))
    return "\n".join(lines)[:3900]


def _render_section_lines(section: str, value: Any) -> list[str]:
    if value is None:
        return ["N/A"]

    field_order = _IMPORTANT_FIELDS.get(section, [])
    if isinstance(value, dict):
        lines: list[str] = []
        seen: set[str] = set()
        for field in field_order:
            found = _get_field_key(value, field)
            if found is not None:
                label = field if section == "FINAL_EXECUTION_BLOCK" else found
                lines.append(f"{label}: {_safe_value(value.get(found))}")
                seen.add(found)
        for field in sorted(value.keys()):
            if field in seen:
                continue
            lines.append(f"{field}: {_safe_value(value.get(field))}")
        return lines or ["N/A"]

    if isinstance(value, list):
        if not value:
            return ["N/A"]
        return [f"- {_safe_value(item)}" for item in value]

    text = _safe_value(value)
    return [text if text else "N/A"]


def _field_exists(section_value: Any, field: str) -> bool:
    if isinstance(section_value, dict):
        found = _get_field_key(section_value, field)
        if found is None:
            return False
        value = section_value.get(found)
        if isinstance(value, str):
            return bool(value.strip())
        return True
    return _is_non_empty(section_value)


def _is_non_empty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _safe_value(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, str):
        text = value.strip()
        return text if text else "N/A"
    if isinstance(value, dict):
        parts = [f"{key}={_safe_value(inner)}" for key, inner in sorted(value.items())]
        return ", ".join(parts) if parts else "N/A"
    if isinstance(value, (list, tuple, set)):
        if not value:
            return "N/A"
        return " | ".join(_safe_value(item) for item in value)
    return str(value)


def _normalize_key(value: str) -> str:
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


def _section_aliases(section: str) -> list[str]:
    aliases = [section]
    parts = section.split(" ", 1)
    if len(parts) == 2:
        aliases.append(parts[1])
    # Include no-underscore alias because section names are often passed as
    # e.g. "FINAL_EXECUTION_BLOCK" while canonical key is "R FINAL_EXECUTION_BLOCK".
    no_underscore = section.replace("_", "")
    aliases.append(no_underscore)
    if len(parts) == 2:
        aliases.append(parts[1].replace("_", ""))
    return aliases


def _get_section_value(payload: dict[str, Any], section: str) -> Any:
    aliases = {_normalize_key(item) for item in _section_aliases(section)}
    for key, value in payload.items():
        normalized_key = _normalize_key(key)
        if normalized_key in aliases:
            return value
    for key, value in payload.items():
        normalized_key = _normalize_key(key)
        if any(normalized_key.endswith(alias) for alias in aliases if alias):
            return value
    return None


def _get_field_key(section_value: dict[str, Any], field: str) -> str | None:
    target = _normalize_key(field)
    for key in section_value.keys():
        if _normalize_key(key) == target:
            return str(key)
    return None


def _get_field_value(section_value: dict[str, Any], field: str) -> Any:
    key = _get_field_key(section_value, field)
    if key is None:
        return None
    return section_value.get(key)


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
        file="ocean_output_validator.py",
        function="validate_required_output_sections",
    )
