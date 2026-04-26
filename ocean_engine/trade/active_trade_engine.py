"""Active trade candidate audit and selection from per-timeframe divergence."""

from __future__ import annotations

from datetime import datetime, timezone

from ocean_engine.models.enums import CarryState, Direction, DivergenceDirection, SetupType, TradeFunction
from ocean_engine.models.market import (
    ActiveTradeAudit,
    ActiveTradeCandidate,
    DivergenceAudit,
    DivergenceState,
    StructureState,
)
from ocean_engine.trade.carry_engine import build_carry_status, get_carry_timeframe

TIMEFRAME_ORDER = ("4h", "1h", "15m", "5m", "3m")
TIMEFRAME_TO_AUDIT_FIELD = {
    "4h": "tf_4h",
    "1h": "tf_1h",
    "15m": "tf_15m",
    "5m": "tf_5m",
    "3m": "tf_3m",
}
TIMEFRAME_RANK = {"4h": 5, "1h": 4, "15m": 3, "5m": 2, "3m": 1}


def default_active_trade_candidate(timeframe: str) -> ActiveTradeCandidate:
    """Return a canonical empty candidate row for a timeframe."""

    return ActiveTradeCandidate(
        timeframe=timeframe,
        exists=False,
        origin_timeframe=timeframe,
        selection_reason="No valid Type 1 setup.",
        summary=f"{timeframe} no active trade candidate",
    )


def build_type1_candidate(
    timeframe: str,
    divergence: DivergenceState,
    structures: dict[str, StructureState],
    divergence_audit: DivergenceAudit,
) -> ActiveTradeCandidate:
    """Build a Type 1 candidate from one official same-timeframe divergence."""

    if not (
        divergence.exists
        and divergence.abc_valid
        and divergence.impulse_confirmed
        and divergence.direction in (DivergenceDirection.BULLISH, DivergenceDirection.BEARISH)
    ):
        return default_active_trade_candidate(timeframe)

    carry = build_carry_status(
        origin_tf=timeframe,
        origin_direction=divergence.direction,
        structures=structures,
        divergence_audit=divergence_audit,
    )
    carry_identifiable = carry.timeframe is not None and carry.timeframe != ""
    if not carry_identifiable:
        return default_active_trade_candidate(timeframe)

    direction = DivergenceDirection.BULLISH if divergence.direction == DivergenceDirection.BULLISH else DivergenceDirection.BEARISH
    tf_label = timeframe.upper() if timeframe in {"1h", "4h"} else timeframe
    dir_label = "Bullish" if divergence.direction == DivergenceDirection.BULLISH else "Bearish"
    type_label = f"{tf_label} {dir_label} Type 1"
    trade_function = (
        TradeFunction.HIGHER_TF_DIVERGENCE if timeframe in {"4h", "1h"} else TradeFunction.DECOMPOSITION
    )

    finished = carry.finished
    too_late = carry.state in {CarryState.MATURE, CarryState.EXHAUSTING} or finished
    fresh_entry_valid = (
        carry.state in {CarryState.FRESH, CarryState.ACTIVE}
        and not finished
        and not too_late
    )
    existing_hold_valid = carry.state in {CarryState.FRESH, CarryState.ACTIVE, CarryState.MATURE} and not finished

    origin_price_zone = divergence.price_zone
    invalidation = (
        "Break below origin zone confirms invalidation."
        if divergence.direction == DivergenceDirection.BULLISH
        else "Reclaim above origin zone confirms invalidation."
    )

    return ActiveTradeCandidate(
        timeframe=timeframe,
        exists=True,
        origin_timeframe=timeframe,
        direction=direction,
        setup_type=SetupType.TYPE_1,
        type_label=type_label,
        trade_function=trade_function,
        origin_price_zone=origin_price_zone,
        confirmation_price=None,
        confirmation_time_utc=datetime.now(timezone.utc).isoformat(),
        earliest_legal_trigger_price=None,
        carry_timeframe=carry.timeframe,
        carry_direction=carry.direction,
        carry_state=carry.state,
        fresh_entry_valid=fresh_entry_valid,
        existing_hold_valid=existing_hold_valid,
        too_late_to_chase=too_late,
        invalidation=invalidation,
        current_status="ACTIVE" if existing_hold_valid else "WATCH",
        selection_reason="Official same-timeframe Type 1 divergence setup.",
        summary=(
            f"{type_label} | carry={carry.timeframe} {carry.state.value} | "
            f"fresh={fresh_entry_valid} hold={existing_hold_valid}"
        ),
    )


def detect_type2_candidate(*_args, **_kwargs) -> ActiveTradeCandidate:
    """Placeholder for Type 2 detection in future phases."""

    timeframe = _kwargs.get("timeframe", "") if isinstance(_kwargs, dict) else ""
    return default_active_trade_candidate(timeframe or "")


def detect_type3_candidate(*_args, **_kwargs) -> ActiveTradeCandidate:
    """Build a generic Type 3 candidate from range breakout acceptance."""

    timeframe = _kwargs.get("timeframe", "") if isinstance(_kwargs, dict) else ""
    structures = _kwargs.get("structures", {}) if isinstance(_kwargs, dict) else {}
    if not timeframe:
        return default_active_trade_candidate("")
    structure = structures.get(timeframe) if isinstance(structures, dict) else None
    if structure is None or structure.range_state is None:
        candidate = default_active_trade_candidate(timeframe)
        candidate.selection_reason = "No range context for Type 3."
        return candidate

    range_state = structure.range_state
    if range_state.status in {"FAILED_BREAK_UP", "FAILED_BREAK_DOWN", "RE_ENTERED", "UPGRADE_RISK"}:
        candidate = default_active_trade_candidate(timeframe)
        candidate.selection_reason = "Failed/re-entered breakout blocks Type 3 setup."
        return candidate

    bullish_break = range_state.status == "BROKEN_UP" or (
        range_state.acceptance_confirmed and range_state.breakout_direction == Direction.UP
    )
    bearish_break = range_state.status == "BROKEN_DOWN" or (
        range_state.acceptance_confirmed and range_state.breakout_direction == Direction.DOWN
    )
    if not bullish_break and not bearish_break:
        candidate = default_active_trade_candidate(timeframe)
        candidate.selection_reason = "No accepted breakout for Type 3."
        return candidate

    if bullish_break:
        direction = DivergenceDirection.BULLISH
        type_label = f"{timeframe.upper() if timeframe in {'1h', '4h'} else timeframe} Bullish Type 3"
        breakout_level = range_state.upper_edge
        invalidation = "Accepted reclaim back inside broken range below upper edge"
        carry_direction = Direction.UP
    else:
        direction = DivergenceDirection.BEARISH
        type_label = f"{timeframe.upper() if timeframe in {'1h', '4h'} else timeframe} Bearish Type 3"
        breakout_level = range_state.lower_edge
        invalidation = "Accepted reclaim back inside broken range above lower edge"
        carry_direction = Direction.DOWN

    trigger_price = range_state.first_accepted_close or breakout_level
    breakout_band = ""
    if breakout_level is not None:
        breakout_band = f"{breakout_level:.2f}-{breakout_level:.2f}"

    carry_tf, carry_state, carry_finished = _type3_carry_context(
        timeframe=timeframe,
        carry_direction=carry_direction,
        structures=structures if isinstance(structures, dict) else {},
    )
    too_late_to_chase = carry_state in {CarryState.MATURE, CarryState.EXHAUSTING}
    fresh_entry_valid = carry_state in {CarryState.FRESH, CarryState.ACTIVE}
    existing_hold_valid = (
        carry_state in {CarryState.FRESH, CarryState.ACTIVE, CarryState.MATURE} and not carry_finished
    )

    return ActiveTradeCandidate(
        timeframe=timeframe,
        exists=True,
        origin_timeframe=timeframe,
        direction=direction,
        setup_type=SetupType.TYPE_3,
        trade_function=TradeFunction.BREAKOUT,
        type_label=type_label,
        origin_price_zone=breakout_band,
        confirmation_price=structure.current_price,
        confirmation_time_utc=datetime.now(timezone.utc).isoformat(),
        earliest_legal_trigger_price=trigger_price,
        carry_timeframe=carry_tf,
        carry_direction=carry_direction,
        carry_state=carry_state,
        fresh_entry_valid=fresh_entry_valid,
        existing_hold_valid=existing_hold_valid,
        too_late_to_chase=too_late_to_chase,
        invalidation=invalidation,
        current_status="ACTIVE" if existing_hold_valid else "WATCH",
        selection_reason="Accepted range breakout Type 3 setup.",
        summary=f"{type_label} | carry={carry_tf or 'NONE'} {carry_state.value}",
    )


def build_active_trade_audit(
    structures: dict[str, StructureState],
    divergence_audit: DivergenceAudit,
) -> ActiveTradeAudit:
    """Build active trade candidate rows per timeframe."""

    rows: dict[str, ActiveTradeCandidate] = {}
    for timeframe in TIMEFRAME_ORDER:
        divergence = getattr(divergence_audit, TIMEFRAME_TO_AUDIT_FIELD[timeframe])
        type1_candidate = build_type1_candidate(
            timeframe=timeframe,
            divergence=divergence,
            structures=structures,
            divergence_audit=divergence_audit,
        )
        type3_candidate = detect_type3_candidate(timeframe=timeframe, structures=structures)
        rows[timeframe] = type1_candidate if type1_candidate.exists else type3_candidate

    audit = ActiveTradeAudit(
        tf_4h=rows["4h"],
        tf_1h=rows["1h"],
        tf_15m=rows["15m"],
        tf_5m=rows["5m"],
        tf_3m=rows["3m"],
    )
    selected = select_active_trade(audit)
    audit.selected_active_trade_tf = selected.origin_timeframe if selected is not None else None
    audit.selection_reason = (
        selected.selection_reason if selected is not None else "No existing active trade candidate."
    )
    return audit


def select_active_trade(audit: ActiveTradeAudit) -> ActiveTradeCandidate | None:
    """Select currently meaningful active trade origin candidate."""

    candidates = [
        audit.tf_4h,
        audit.tf_1h,
        audit.tf_15m,
        audit.tf_5m,
        audit.tf_3m,
    ]
    existing = [candidate for candidate in candidates if candidate.exists]
    if not existing:
        return None

    type3_hold_valid = [
        candidate
        for candidate in existing
        if candidate.setup_type == SetupType.TYPE_3 and candidate.existing_hold_valid
    ]
    if type3_hold_valid:
        return min(type3_hold_valid, key=lambda candidate: TIMEFRAME_RANK.get(candidate.origin_timeframe, 99))

    type3_existing = [candidate for candidate in existing if candidate.setup_type == SetupType.TYPE_3]
    if type3_existing:
        return min(type3_existing, key=lambda candidate: TIMEFRAME_RANK.get(candidate.origin_timeframe, 99))

    hold_valid = [candidate for candidate in existing if candidate.existing_hold_valid]
    if hold_valid:
        return max(hold_valid, key=lambda candidate: TIMEFRAME_RANK.get(candidate.origin_timeframe, 0))
    return max(existing, key=lambda candidate: TIMEFRAME_RANK.get(candidate.origin_timeframe, 0))


def active_trade_audit_summary(audit: ActiveTradeAudit) -> str:
    """Render compact per-timeframe active trade summary."""

    labels = []
    for timeframe, candidate in (
        ("4H", audit.tf_4h),
        ("1H", audit.tf_1h),
        ("15m", audit.tf_15m),
        ("5m", audit.tf_5m),
        ("3m", audit.tf_3m),
    ):
        if candidate.exists:
            if candidate.setup_type == SetupType.TYPE_3:
                if candidate.direction == DivergenceDirection.BULLISH:
                    labels.append(f"{timeframe}:Bullish T3✓")
                elif candidate.direction == DivergenceDirection.BEARISH:
                    labels.append(f"{timeframe}:Bearish T3✓")
                else:
                    labels.append(f"{timeframe}:T3✓")
            else:
                labels.append(f"{timeframe}:{candidate.type_label}")
        else:
            labels.append(f"{timeframe}:No")
    return " | ".join(labels)


def _type3_carry_context(
    timeframe: str,
    carry_direction: Direction,
    structures: dict[str, StructureState],
) -> tuple[str, CarryState, bool]:
    """Infer carry context for Type 3 from lower timeframe structure only."""

    carry_tf = get_carry_timeframe(timeframe)
    if carry_tf is None:
        return ("", CarryState.UNCLEAR, False)

    carry_structure = structures.get(carry_tf)
    if carry_structure is None:
        return (carry_tf, CarryState.UNCLEAR, False)

    active_leg = carry_structure.active_leg
    if active_leg is None:
        return (carry_tf, CarryState.UNCLEAR, False)

    if carry_structure.range_state is not None and carry_structure.range_state.active:
        return (carry_tf, CarryState.MATURE, False)

    if active_leg.direction != carry_direction:
        return (carry_tf, CarryState.EXHAUSTING, False)

    if len(carry_structure.legs) <= 2:
        return (carry_tf, CarryState.FRESH, False)
    return (carry_tf, CarryState.ACTIVE, False)

