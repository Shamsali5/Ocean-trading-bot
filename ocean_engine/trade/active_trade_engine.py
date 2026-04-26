"""Active trade candidate audit and selection from per-timeframe divergence."""

from __future__ import annotations

from datetime import datetime, timezone

from ocean_engine.models.enums import CarryState, Direction, DivergenceDirection, SetupType, TradeFunction
from ocean_engine.models.market import (
    ActiveTradeAudit,
    ActiveTradeCandidate,
    DivergenceAudit,
    DivergenceState,
    Leg,
    StructureState,
    SupplyDemandZone,
)
from ocean_engine.trade.carry_engine import build_carry_status, get_carry_timeframe
from ocean_engine.zones.supply_demand_engine import detect_supply_demand_zones

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
        selection_reason="No valid active setup.",
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

    start_price = divergence.impulse_price if divergence.impulse_price is not None else divergence.divergence_price
    start_time = divergence.impulse_time_utc or divergence.divergence_time_utc

    return ActiveTradeCandidate(
        timeframe=timeframe,
        exists=True,
        origin_timeframe=timeframe,
        direction=direction,
        setup_type=SetupType.TYPE_1,
        type_label=type_label,
        trade_function=trade_function,
        origin_price_zone=origin_price_zone,
        confirmation_price=start_price,
        confirmation_time_utc=start_time,
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
    """Build a Type 2 pullback-continuation candidate from a prior Type 1."""

    timeframe = _kwargs.get("timeframe", "") if isinstance(_kwargs, dict) else ""
    structures = _kwargs.get("structures", {}) if isinstance(_kwargs, dict) else {}
    prior_type1 = _kwargs.get("prior_type1", None) if isinstance(_kwargs, dict) else None
    if not timeframe:
        return default_active_trade_candidate("")
    if not isinstance(prior_type1, ActiveTradeCandidate):
        candidate = default_active_trade_candidate(timeframe)
        candidate.selection_reason = "Type 2 requires a prior Type 1 candidate."
        return candidate
    if not (
        prior_type1.exists
        and prior_type1.setup_type == SetupType.TYPE_1
        and prior_type1.origin_timeframe == timeframe
        and prior_type1.direction in (DivergenceDirection.BULLISH, DivergenceDirection.BEARISH)
    ):
        candidate = default_active_trade_candidate(timeframe)
        candidate.selection_reason = "Type 2 requires prior same-timeframe Type 1."
        return candidate

    structure = structures.get(timeframe) if isinstance(structures, dict) else None
    if structure is None or len(structure.legs) < 3:
        candidate = default_active_trade_candidate(timeframe)
        candidate.selection_reason = "Type 2 requires impulse, pullback, and continuation legs."
        return candidate

    legs = sorted(structure.legs, key=lambda leg: leg.end_index)
    impulse_leg = legs[-3]
    pullback_leg = legs[-2]
    continuation_leg = legs[-1]

    if prior_type1.direction == DivergenceDirection.BULLISH:
        expected_direction = Direction.UP
        pullback_direction = Direction.DOWN
        carry_direction = Direction.UP
        type_label = f"{timeframe.upper() if timeframe in {'1h', '4h'} else timeframe} Bullish Type 2"
        invalidation = "Bullish Type 2 invalidated when pullback breaks Type 1 origin low."
    else:
        expected_direction = Direction.DOWN
        pullback_direction = Direction.UP
        carry_direction = Direction.DOWN
        type_label = f"{timeframe.upper() if timeframe in {'1h', '4h'} else timeframe} Bearish Type 2"
        invalidation = "Bearish Type 2 invalidated when pullback breaks Type 1 origin high."

    if pullback_leg.direction != pullback_direction:
        candidate = default_active_trade_candidate(timeframe)
        candidate.selection_reason = "Type 2 requires pullback leg against Type 1 direction."
        return candidate
    if continuation_leg.direction != expected_direction:
        candidate = default_active_trade_candidate(timeframe)
        candidate.selection_reason = "Type 2 continuation impulse is missing."
        return candidate

    origin_low, origin_high = _parse_price_band(prior_type1.origin_price_zone)
    if expected_direction == Direction.UP and origin_low is not None and pullback_leg.low < origin_low:
        candidate = default_active_trade_candidate(timeframe)
        candidate.selection_reason = "Type 2 invalid: pullback broke Type 1 origin low."
        return candidate
    if expected_direction == Direction.DOWN and origin_high is not None and pullback_leg.high > origin_high:
        candidate = default_active_trade_candidate(timeframe)
        candidate.selection_reason = "Type 2 invalid: pullback broke Type 1 origin high."
        return candidate

    impulse_size = abs(impulse_leg.high - impulse_leg.low)
    pullback_size = abs(pullback_leg.high - pullback_leg.low)
    continuation_size = abs(continuation_leg.high - continuation_leg.low)
    if impulse_size <= 0.0 or pullback_size >= impulse_size:
        candidate = default_active_trade_candidate(timeframe)
        candidate.selection_reason = "Type 2 invalid: pullback did not weaken versus impulse."
        return candidate
    if continuation_size <= 0.0:
        candidate = default_active_trade_candidate(timeframe)
        candidate.selection_reason = "Type 2 continuation impulse is missing."
        return candidate

    carry_tf, carry_state, carry_finished = _type3_carry_context(
        timeframe=timeframe,
        carry_direction=carry_direction,
        structures=structures if isinstance(structures, dict) else {},
    )
    if carry_state == CarryState.UNCLEAR:
        candidate = default_active_trade_candidate(timeframe)
        candidate.selection_reason = "Type 2 invalid: carry did not resume."
        return candidate

    too_late_to_chase = carry_state in {CarryState.MATURE, CarryState.EXHAUSTING}
    fresh_entry_valid = carry_state in {CarryState.FRESH, CarryState.ACTIVE}
    existing_hold_valid = carry_state in {CarryState.FRESH, CarryState.ACTIVE, CarryState.MATURE} and not carry_finished

    trigger_price: float | None
    if expected_direction == Direction.UP:
        trigger_price = continuation_leg.high
    else:
        trigger_price = continuation_leg.low

    return ActiveTradeCandidate(
        timeframe=timeframe,
        exists=True,
        origin_timeframe=timeframe,
        direction=prior_type1.direction,
        setup_type=SetupType.TYPE_2,
        trade_function=TradeFunction.PULLBACK_CONTINUATION,
        type_label=type_label,
        origin_price_zone=prior_type1.origin_price_zone,
        confirmation_price=trigger_price,
        confirmation_time_utc=_leg_end_time_utc(continuation_leg),
        earliest_legal_trigger_price=trigger_price,
        carry_timeframe=carry_tf,
        carry_direction=carry_direction,
        carry_state=carry_state,
        fresh_entry_valid=fresh_entry_valid,
        existing_hold_valid=existing_hold_valid,
        too_late_to_chase=too_late_to_chase,
        invalidation=invalidation,
        current_status="ACTIVE" if existing_hold_valid else "WATCH",
        selection_reason="Type 2 continuation after valid Type 1 pullback.",
        summary=(
            f"{type_label} | pullback_weaker={pullback_size < impulse_size} | "
            f"carry={carry_tf or 'NONE'} {carry_state.value}"
        ),
    )


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

    start_time = _confirmation_time_from_candle_index(
        structure=structure,
        index=range_state.first_break_index,
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
        confirmation_price=trigger_price,
        confirmation_time_utc=start_time,
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


def detect_zone_reaction_candidate(*_args, **_kwargs) -> ActiveTradeCandidate:
    """Build supply/demand reaction candidate when confirmation appears at zone."""

    timeframe = _kwargs.get("timeframe", "") if isinstance(_kwargs, dict) else ""
    structures = _kwargs.get("structures", {}) if isinstance(_kwargs, dict) else {}
    divergence = _kwargs.get("divergence", None) if isinstance(_kwargs, dict) else None
    zones = _kwargs.get("zones", []) if isinstance(_kwargs, dict) else []
    if not timeframe:
        return default_active_trade_candidate("")
    structure = structures.get(timeframe) if isinstance(structures, dict) else None
    if structure is None or structure.current_price is None:
        candidate = default_active_trade_candidate(timeframe)
        candidate.selection_reason = "Zone reaction requires current structure context."
        return candidate

    if not isinstance(zones, list):
        zones = []
    meaningful_zones = [
        zone
        for zone in zones
        if zone.timeframe == timeframe
        and zone.status in {"REACTING", "TESTED"}
        and "midpoint" not in str(zone.role).lower()
    ]
    if not meaningful_zones:
        candidate = default_active_trade_candidate(timeframe)
        candidate.selection_reason = "No meaningful reacting/tested zone at timeframe."
        return candidate

    zone = meaningful_zones[0]
    if zone.status == "ACCEPTED_THROUGH":
        candidate = default_active_trade_candidate(timeframe)
        candidate.selection_reason = "Accepted-through zone cannot form reaction trade."
        return candidate

    direction: DivergenceDirection
    carry_direction: Direction
    needs_opposite_pull = False
    if zone.zone_type.name == "DEMAND":
        direction = DivergenceDirection.BULLISH
        carry_direction = Direction.UP
        needs_opposite_pull = True
    else:
        direction = DivergenceDirection.BEARISH
        carry_direction = Direction.DOWN
        needs_opposite_pull = True

    if len(structure.legs) < 2:
        candidate = default_active_trade_candidate(timeframe)
        candidate.selection_reason = "Zone reaction requires pullback and restart legs."
        return candidate
    legs = sorted(structure.legs, key=lambda leg: leg.end_index)
    pullback_leg = legs[-2]
    restart_leg = legs[-1]

    if needs_opposite_pull:
        expected_pull = Direction.DOWN if direction == DivergenceDirection.BULLISH else Direction.UP
        expected_restart = Direction.UP if direction == DivergenceDirection.BULLISH else Direction.DOWN
        if pullback_leg.direction != expected_pull:
            candidate = default_active_trade_candidate(timeframe)
            candidate.selection_reason = "Zone touched without weakening pullback."
            return candidate
        if restart_leg.direction != expected_restart:
            candidate = default_active_trade_candidate(timeframe)
            candidate.selection_reason = "Zone reaction missing confirmation impulse."
            return candidate

    pullback_size = abs(pullback_leg.high - pullback_leg.low)
    restart_size = abs(restart_leg.high - restart_leg.low)
    weakens = pullback_size <= restart_size
    if not weakens and structure.candles and len(structure.candles) >= 3:
        closes = [candle.close for candle in structure.candles[-3:]]
        if direction == DivergenceDirection.BULLISH:
            weakens = closes[0] > closes[1] and closes[2] > closes[1]
        else:
            weakens = closes[0] < closes[1] and closes[2] < closes[1]
    if not weakens:
        candidate = default_active_trade_candidate(timeframe)
        candidate.selection_reason = "Reaction invalid: pullback did not weaken."
        return candidate

    has_divergence_confirmation = bool(
        isinstance(divergence, DivergenceState)
        and divergence.exists
        and divergence.impulse_confirmed
        and (
            (direction == DivergenceDirection.BULLISH and divergence.direction == DivergenceDirection.BULLISH)
            or (direction == DivergenceDirection.BEARISH and divergence.direction == DivergenceDirection.BEARISH)
        )
    )
    carry_tf, carry_state, carry_finished = _type3_carry_context(
        timeframe=timeframe,
        carry_direction=carry_direction,
        structures=structures if isinstance(structures, dict) else {},
    )
    if carry_state == CarryState.UNCLEAR:
        candidate = default_active_trade_candidate(timeframe)
        candidate.selection_reason = "Zone reaction invalid: no lower-timeframe carry confirmation."
        return candidate

    too_late = carry_state in {CarryState.MATURE, CarryState.EXHAUSTING}
    fresh_entry_valid = carry_state in {CarryState.FRESH, CarryState.ACTIVE}
    existing_hold_valid = carry_state in {CarryState.FRESH, CarryState.ACTIVE, CarryState.MATURE} and not carry_finished

    if direction == DivergenceDirection.BULLISH:
        trigger = restart_leg.high
        invalidation = "Demand reaction invalidated when price re-accepts below demand zone."
        type_label = f"{timeframe.upper() if timeframe in {'1h', '4h'} else timeframe} Bullish Zone Reaction"
    else:
        trigger = restart_leg.low
        invalidation = "Supply reaction invalidated when price re-accepts above supply zone."
        type_label = f"{timeframe.upper() if timeframe in {'1h', '4h'} else timeframe} Bearish Zone Reaction"

    setup_type = SetupType.TYPE_1 if has_divergence_confirmation else SetupType.NONE
    return ActiveTradeCandidate(
        timeframe=timeframe,
        exists=True,
        origin_timeframe=timeframe,
        direction=direction,
        setup_type=setup_type,
        trade_function=TradeFunction.SUPPLY_DEMAND_REACTION,
        type_label=type_label,
        origin_price_zone=zone.price_band,
        confirmation_price=trigger,
        confirmation_time_utc=_leg_end_time_utc(restart_leg),
        earliest_legal_trigger_price=trigger,
        carry_timeframe=carry_tf,
        carry_direction=carry_direction,
        carry_state=carry_state,
        fresh_entry_valid=fresh_entry_valid,
        existing_hold_valid=existing_hold_valid,
        too_late_to_chase=too_late,
        invalidation=invalidation,
        current_status="ACTIVE" if existing_hold_valid else "WATCH",
        selection_reason="Confirmed supply/demand reaction with impulse and carry.",
        summary=(
            f"{type_label} | zone={zone.price_band} | carry={carry_tf or 'NONE'} {carry_state.value} "
            f"| pullback={pullback_size:.2f} restart={restart_size:.2f}"
        ),
    )


def detect_range_rejection_candidate(*_args, **_kwargs) -> ActiveTradeCandidate:
    """Build range-rejection candidate at a valid active range edge."""

    timeframe = _kwargs.get("timeframe", "") if isinstance(_kwargs, dict) else ""
    structures = _kwargs.get("structures", {}) if isinstance(_kwargs, dict) else {}
    if not timeframe:
        return default_active_trade_candidate("")
    structure = structures.get(timeframe) if isinstance(structures, dict) else None
    if structure is None or structure.range_state is None or structure.active_leg is None:
        candidate = default_active_trade_candidate(timeframe)
        candidate.selection_reason = "Range rejection requires active range and active leg."
        return candidate

    range_state = structure.range_state
    if not range_state.active or range_state.status not in {"ACTIVE", "RE_ENTERED"}:
        candidate = default_active_trade_candidate(timeframe)
        candidate.selection_reason = "Range rejection requires active/re-entered range context."
        return candidate
    if range_state.price_location not in {"UPPER_EDGE", "LOWER_EDGE"}:
        candidate = default_active_trade_candidate(timeframe)
        candidate.selection_reason = "Range rejection requires edge location (not midpoint)."
        return candidate

    if range_state.price_location == "UPPER_EDGE" and structure.active_leg.direction == Direction.DOWN:
        direction = Direction.DOWN
        dir_label = "Bearish"
        carry_direction = Direction.DOWN
        invalidation = "Upper-edge rejection invalidates on accepted breakout above upper edge."
        trigger = structure.active_leg.low
        edge = range_state.upper_edge
    elif range_state.price_location == "LOWER_EDGE" and structure.active_leg.direction == Direction.UP:
        direction = Direction.UP
        dir_label = "Bullish"
        carry_direction = Direction.UP
        invalidation = "Lower-edge rejection invalidates on accepted breakdown below lower edge."
        trigger = structure.active_leg.high
        edge = range_state.lower_edge
    else:
        candidate = default_active_trade_candidate(timeframe)
        candidate.selection_reason = "No rejection impulse at range edge."
        return candidate

    carry_tf, carry_state, carry_finished = _type3_carry_context(
        timeframe=timeframe,
        carry_direction=carry_direction,
        structures=structures if isinstance(structures, dict) else {},
    )
    if carry_state == CarryState.UNCLEAR:
        candidate = default_active_trade_candidate(timeframe)
        candidate.selection_reason = "Range rejection missing lower-timeframe carry."
        return candidate

    too_late = carry_state in {CarryState.MATURE, CarryState.EXHAUSTING}
    fresh_entry_valid = carry_state in {CarryState.FRESH, CarryState.ACTIVE}
    existing_hold_valid = carry_state in {CarryState.FRESH, CarryState.ACTIVE, CarryState.MATURE} and not carry_finished
    tf_label = timeframe.upper() if timeframe in {"1h", "4h"} else timeframe
    origin_band = f"{edge:.2f}-{edge:.2f}" if isinstance(edge, (int, float)) else ""
    return ActiveTradeCandidate(
        timeframe=timeframe,
        exists=True,
        origin_timeframe=timeframe,
        direction=direction,
        setup_type=SetupType.NONE,
        trade_function=TradeFunction.RANGE_REJECTION,
        type_label=f"{tf_label} {dir_label} Range Rejection",
        origin_price_zone=origin_band,
        confirmation_price=trigger,
        confirmation_time_utc=_leg_end_time_utc(structure.active_leg),
        earliest_legal_trigger_price=trigger,
        carry_timeframe=carry_tf,
        carry_direction=carry_direction,
        carry_state=carry_state,
        fresh_entry_valid=fresh_entry_valid,
        existing_hold_valid=existing_hold_valid,
        too_late_to_chase=too_late,
        invalidation=invalidation,
        current_status="ACTIVE" if existing_hold_valid else "WATCH",
        selection_reason="Range rejection confirmed at active edge with carry.",
        summary=f"{tf_label} range rejection | carry={carry_tf or 'NONE'} {carry_state.value}",
    )


def detect_upgrade_candidate(*_args, **_kwargs) -> ActiveTradeCandidate:
    """Build cautious upgrade candidate when range upgrade risk appears."""

    timeframe = _kwargs.get("timeframe", "") if isinstance(_kwargs, dict) else ""
    structures = _kwargs.get("structures", {}) if isinstance(_kwargs, dict) else {}
    if not timeframe:
        return default_active_trade_candidate("")
    structure = structures.get(timeframe) if isinstance(structures, dict) else None
    if structure is None or structure.range_state is None or structure.active_leg is None:
        candidate = default_active_trade_candidate(timeframe)
        candidate.selection_reason = "Upgrade requires range and active leg context."
        return candidate
    range_state = structure.range_state
    if range_state.status != "UPGRADE_RISK":
        candidate = default_active_trade_candidate(timeframe)
        candidate.selection_reason = "No range upgrade risk context."
        return candidate
    if structure.active_leg.direction not in {Direction.UP, Direction.DOWN}:
        candidate = default_active_trade_candidate(timeframe)
        candidate.selection_reason = "Upgrade direction is unclear."
        return candidate

    carry_direction = structure.active_leg.direction
    carry_tf, carry_state, carry_finished = _type3_carry_context(
        timeframe=timeframe,
        carry_direction=carry_direction,
        structures=structures if isinstance(structures, dict) else {},
    )
    if carry_state == CarryState.UNCLEAR:
        candidate = default_active_trade_candidate(timeframe)
        candidate.selection_reason = "Upgrade requires lower-timeframe carry context."
        return candidate

    dir_label = "Bullish" if carry_direction == Direction.UP else "Bearish"
    tf_label = timeframe.upper() if timeframe in {"1h", "4h"} else timeframe
    return ActiveTradeCandidate(
        timeframe=timeframe,
        exists=True,
        origin_timeframe=timeframe,
        direction=carry_direction,
        setup_type=SetupType.NONE,
        trade_function=TradeFunction.UPGRADE,
        type_label=f"{tf_label} {dir_label} Upgrade Attempt",
        origin_price_zone=f"{range_state.lower_edge:.2f}-{range_state.upper_edge:.2f}"
        if isinstance(range_state.lower_edge, (int, float)) and isinstance(range_state.upper_edge, (int, float))
        else "",
        confirmation_price=structure.current_price,
        confirmation_time_utc=_leg_end_time_utc(structure.active_leg),
        earliest_legal_trigger_price=structure.current_price,
        carry_timeframe=carry_tf,
        carry_direction=carry_direction,
        carry_state=carry_state,
        # Upgrade is tactical in risk context: no fresh chase entry.
        fresh_entry_valid=False,
        existing_hold_valid=carry_state in {CarryState.FRESH, CarryState.ACTIVE, CarryState.MATURE} and not carry_finished,
        too_late_to_chase=carry_state in {CarryState.MATURE, CarryState.EXHAUSTING},
        invalidation="Upgrade fails if market re-accepts inside prior unstable range balance.",
        current_status="WATCH",
        selection_reason="Upgrade-risk context with directional carry continuation.",
        summary=f"{tf_label} upgrade risk | carry={carry_tf or 'NONE'} {carry_state.value}",
    )


def build_active_trade_audit(
    structures: dict[str, StructureState],
    divergence_audit: DivergenceAudit,
) -> ActiveTradeAudit:
    """Build active trade candidate rows per timeframe."""

    zones = detect_supply_demand_zones(structures, divergence_audit)
    rows: dict[str, ActiveTradeCandidate] = {}
    for timeframe in TIMEFRAME_ORDER:
        divergence = getattr(divergence_audit, TIMEFRAME_TO_AUDIT_FIELD[timeframe])
        type1_candidate = build_type1_candidate(
            timeframe=timeframe,
            divergence=divergence,
            structures=structures,
            divergence_audit=divergence_audit,
        )
        type2_candidate = detect_type2_candidate(
            timeframe=timeframe,
            structures=structures,
            prior_type1=type1_candidate,
        )
        zone_reaction_candidate = detect_zone_reaction_candidate(
            timeframe=timeframe,
            structures=structures,
            divergence=divergence,
            zones=zones,
        )
        range_rejection_candidate = detect_range_rejection_candidate(
            timeframe=timeframe,
            structures=structures,
        )
        type3_candidate = detect_type3_candidate(timeframe=timeframe, structures=structures)
        upgrade_candidate = detect_upgrade_candidate(
            timeframe=timeframe,
            structures=structures,
        )
        if type2_candidate.exists:
            rows[timeframe] = type2_candidate
        elif type1_candidate.exists:
            rows[timeframe] = type1_candidate
        elif zone_reaction_candidate.exists:
            rows[timeframe] = zone_reaction_candidate
        elif range_rejection_candidate.exists:
            rows[timeframe] = range_rejection_candidate
        elif type3_candidate.exists:
            rows[timeframe] = type3_candidate
        else:
            rows[timeframe] = upgrade_candidate

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
                normalized_direction = _candidate_direction(candidate)
                if normalized_direction == Direction.UP:
                    labels.append(f"{timeframe}:Bullish T3✓")
                elif normalized_direction == Direction.DOWN:
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


def _parse_price_band(price_band: str) -> tuple[float | None, float | None]:
    text = price_band.strip()
    if not text:
        return (None, None)
    if "-" not in text:
        return (None, None)
    left, right = text.split("-", 1)
    try:
        lower = float(left.strip())
        upper = float(right.strip())
    except ValueError:
        return (None, None)
    return (min(lower, upper), max(lower, upper))


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


def _confirmation_time_from_candle_index(structure: StructureState, index: int | None) -> str:
    """Resolve candle close time from detected breakout index."""

    if index is None or index < 0:
        return ""
    if not structure.candles or index >= len(structure.candles):
        return ""
    close_time = getattr(structure.candles[index], "close_time", None)
    return _format_close_time_utc(close_time)


def _leg_end_time_utc(leg: Leg | None) -> str:
    """Convert leg end-time into UTC ISO string when available."""

    if leg is None:
        return ""
    return _format_close_time_utc(getattr(leg, "end_time", None))


def _format_close_time_utc(close_time_ms: int | None) -> str:
    """Format epoch-millisecond close time into UTC ISO string."""

    if close_time_ms is None:
        return ""
    return datetime.fromtimestamp(close_time_ms / 1000.0, tz=timezone.utc).isoformat()

