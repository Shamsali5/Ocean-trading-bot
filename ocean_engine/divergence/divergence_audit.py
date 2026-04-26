"""Per-timeframe divergence audit without cross-timeframe promotion."""

from __future__ import annotations

from ocean_framework_v12_audit import FrameworkAuditTrace
from ocean_abc_validator import validate_abc_for_timeframe
from ocean_engine.divergence.abc_engine import find_abc_candidates, select_latest_abc_candidate
from ocean_engine.divergence.divergence_engine import detect_divergence_from_abc
from ocean_engine.models.enums import DivergenceDirection
from ocean_engine.models.market import DivergenceAudit, DivergenceState, StructureState, VAccSeries

TIMEFRAME_ORDER = ("4h", "1h", "15m", "5m", "3m")
TIMEFRAME_TO_FIELD = {
    "4h": "tf_4h",
    "1h": "tf_1h",
    "15m": "tf_15m",
    "5m": "tf_5m",
    "3m": "tf_3m",
}
FIELD_TO_LABEL = {
    "tf_4h": "4H",
    "tf_1h": "1H",
    "tf_15m": "15m",
    "tf_5m": "5m",
    "tf_3m": "3m",
}


def default_divergence_state(timeframe: str) -> DivergenceState:
    """Return a canonical non-official divergence row for one timeframe."""

    return DivergenceState(timeframe=timeframe, notes="No valid A-B-C candidate.")


def audit_timeframe_divergence(timeframe: str, structure: StructureState, vacc: VAccSeries) -> DivergenceState:
    """Audit exactly one timeframe using only that timeframe inputs."""

    if structure.timeframe and structure.timeframe != timeframe:
        raise ValueError(f"Structure timeframe mismatch: expected {timeframe}, got {structure.timeframe}")
    if vacc.timeframe and vacc.timeframe != timeframe:
        raise ValueError(f"VAcc timeframe mismatch: expected {timeframe}, got {vacc.timeframe}")

    candidates = find_abc_candidates(structure)
    latest = select_latest_abc_candidate(candidates)
    if latest is None:
        return default_divergence_state(timeframe)

    state = detect_divergence_from_abc(
        abc=latest,
        candles=structure.candles,
        vacc_series=vacc,
    )
    c_end = latest.segment_c.end_index if latest.segment_c is not None else latest.c_index
    state.notes = f"{state.notes}; C ending at leg index {c_end}".strip("; ").strip()
    state.timeframe = timeframe
    return state


def audit_timeframe_divergence_with_validator(
    timeframe: str,
    structure: StructureState,
    vacc: VAccSeries,
    trace: FrameworkAuditTrace | None = None,
) -> DivergenceState:
    """Audit one timeframe while enforcing strict same-timeframe A-B-C validation."""

    if structure.timeframe and structure.timeframe != timeframe:
        raise ValueError(f"Structure timeframe mismatch: expected {timeframe}, got {structure.timeframe}")
    if vacc.timeframe and vacc.timeframe != timeframe:
        raise ValueError(f"VAcc timeframe mismatch: expected {timeframe}, got {vacc.timeframe}")

    candidates = find_abc_candidates(structure)
    latest = select_latest_abc_candidate(candidates)
    if latest is None:
        state = default_divergence_state(timeframe)
        state.notes = "No valid A-B-C candidate."
        return state

    direction_hint = "BEARISH" if latest.direction == DivergenceDirection.BEARISH else "BULLISH"
    validation = validate_abc_for_timeframe(
        candles=structure.candles,
        timeframe=timeframe,
        direction=direction_hint,
        pivots=latest,
        vacc=vacc,
        trace=trace,
    )
    if not validation.valid:
        state = default_divergence_state(timeframe)
        state.notes = f"Strict ABC validator failed: {validation.reason}"
        return state

    state = detect_divergence_from_abc(
        abc=latest,
        candles=structure.candles,
        vacc_series=vacc,
        abc_validation=validation,
    )
    c_end = latest.segment_c.end_index if latest.segment_c is not None else latest.c_index
    state.notes = f"{state.notes}; C ending at leg index {c_end}; abc_reason={validation.reason}".strip("; ").strip()
    state.timeframe = timeframe
    if not state.abc_valid:
        state.exists = False
        state.impulse_confirmed = False
        state.direction = DivergenceDirection.NONE
        state.notes = f"{state.notes}; strict_abc_failed_after_base_audit".strip("; ").strip()
        return state
    return state


def build_divergence_audit(
    structures: dict[str, StructureState],
    vacc_map: dict[str, VAccSeries],
    trace: FrameworkAuditTrace | None = None,
) -> DivergenceAudit:
    """Build full divergence audit rows for canonical timeframes."""

    rows: dict[str, DivergenceState] = {}
    for timeframe in TIMEFRAME_ORDER:
        structure = structures.get(timeframe)
        vacc = vacc_map.get(timeframe)
        if structure is None or vacc is None:
            rows[timeframe] = default_divergence_state(timeframe)
            continue
        rows[timeframe] = audit_timeframe_divergence_with_validator(
            timeframe=timeframe,
            structure=structure,
            vacc=vacc,
            trace=trace,
        )

    audit = DivergenceAudit(
        tf_4h=rows["4h"],
        tf_1h=rows["1h"],
        tf_15m=rows["15m"],
        tf_5m=rows["5m"],
        tf_3m=rows["3m"],
    )
    selected = select_last_meaningful_divergence(audit)
    audit.selected_last_meaningful_tf = selected.timeframe if selected is not None else None
    if selected is None:
        audit.selection_reason = "No official divergence exists in audited timeframes."
    else:
        audit.selection_reason = f"Selected latest official divergence from {selected.timeframe}."
    return audit


def select_last_meaningful_divergence(audit: DivergenceAudit) -> DivergenceState | None:
    """Select latest official divergence by C-end index from audit rows."""

    official_rows: list[tuple[int, DivergenceState]] = []
    for field_name in TIMEFRAME_TO_FIELD.values():
        state = getattr(audit, field_name)
        if not is_official_divergence(state):
            continue
        c_end = _extract_c_end_index(state)
        official_rows.append((c_end, state))

    if not official_rows:
        return None
    official_rows.sort(key=lambda item: item[0])
    return official_rows[-1][1]


def divergence_audit_summary(audit: DivergenceAudit) -> str:
    """Render compact summary text per timeframe row."""

    labels: list[str] = []
    for field_name in ("tf_4h", "tf_1h", "tf_15m", "tf_5m", "tf_3m"):
        state: DivergenceState = getattr(audit, field_name)
        label = FIELD_TO_LABEL[field_name]
        if is_official_divergence(state):
            direction = (
                "Bearish"
                if state.direction.value == "BEARISH"
                else "Bullish"
                if state.direction.value == "BULLISH"
                else "Official"
            )
            labels.append(f"{label}:{direction}\u2713")
        elif state.exists:
            labels.append(f"{label}:Warning")
        else:
            labels.append(f"{label}:No")
    return " | ".join(labels)


def is_official_divergence(state: DivergenceState) -> bool:
    """Return true only for framework-valid official divergence rows."""

    return bool(
        state.exists
        and state.abc_valid
        and state.impulse_confirmed
        and state.direction in (DivergenceDirection.BULLISH, DivergenceDirection.BEARISH)
    )


def _extract_c_end_index(state: DivergenceState) -> int:
    """Extract C-end index from notes payload; fallback to -1 when unknown."""

    for marker in ("C ending at leg index ", "c_end_index="):
        if marker not in state.notes:
            continue
        suffix = state.notes.split(marker, maxsplit=1)[1]
        digits = []
        for char in suffix:
            if char.isdigit():
                digits.append(char)
            else:
                break
        if digits:
            return int("".join(digits))
    # Fallback when notes do not include segment index metadata.
    return -1
