"""Active trade candidate audit and selection from per-timeframe divergence."""

from __future__ import annotations

from datetime import datetime, timezone

from ocean_engine.models.enums import (
    CarryState,
    Direction,
    DivergenceDirection,
    SetupType,
    TradeFunction,
)
from ocean_engine.models.market import (
    ActiveTradeAudit,
    ActiveTradeCandidate,
    DivergenceAudit,
    DivergenceState,
    StructureState,
)
from ocean_engine.trade.carry_engine import build_carry_status

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
        symbol="",
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

    direction = Direction.UP if divergence.direction == DivergenceDirection.BULLISH else Direction.DOWN
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
        symbol="",
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
    """Placeholder for Type 3 detection in future phases."""

    timeframe = _kwargs.get("timeframe", "") if isinstance(_kwargs, dict) else ""
    return default_active_trade_candidate(timeframe or "")


def build_active_trade_audit(
    structures: dict[str, StructureState],
    divergence_audit: DivergenceAudit,
) -> ActiveTradeAudit:
    """Build active trade candidate rows per timeframe."""

    rows: dict[str, ActiveTradeCandidate] = {}
    for timeframe in TIMEFRAME_ORDER:
        divergence = getattr(divergence_audit, TIMEFRAME_TO_AUDIT_FIELD[timeframe])
        rows[timeframe] = build_type1_candidate(
            timeframe=timeframe,
            divergence=divergence,
            structures=structures,
            divergence_audit=divergence_audit,
        )

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
            labels.append(f"{timeframe}:{candidate.type_label}")
        else:
            labels.append(f"{timeframe}:No")
    return " | ".join(labels)

