"""Strict supply/demand location layer for framework v1.2."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ZoneResult:
    timeframe: str
    zone_type: str  # SUPPLY / DEMAND / NONE
    price_low: float | None
    price_high: float | None
    strength: str  # STRONG / MODERATE / WEAK / INVALID / NONE
    alignment: str  # ALIGNED / COUNTER / NEUTRAL / NONE
    structural_role: str
    status: str  # UNTESTED / TESTED / REACTING / FAILED / ACCEPTED_THROUGH / NONE
    reason: str


_HIGHER_TIMEFRAMES = {"4h", "1h"}
_DEMAND_ROLES = {
    "bullish impulse origin",
    "bullish divergence origin",
    "lower range-edge rejection",
    "type2 bullish restart area",
    "breakout retest support",
    "failed breakdown recovery zone",
}
_SUPPLY_ROLES = {
    "bearish impulse origin",
    "bearish divergence origin",
    "upper range-edge rejection",
    "type2 bearish restart area",
    "breakdown retest resistance",
    "failed breakout rejection zone",
}


def detect_supply_demand_zones(context, candles_by_tf, trace=None) -> list[ZoneResult]:
    """Detect strict supply/demand zones as location-only evidence."""

    structures = _get_context_value(context, "structures", default={})
    divergence_audit = _get_context_value(context, "divergence_audit", default=None)
    zones: list[ZoneResult] = []
    _add_check(
        trace=trace,
        name="Supply/demand checked after structure",
        passed=bool(structures),
        severity="INFO",
        details=f"structure_timeframes={list(structures.keys()) if isinstance(structures, dict) else []}",
        function="detect_supply_demand_zones",
    )
    _add_check(
        trace=trace,
        name="Zone status classified",
        passed=True,
        severity="INFO",
        details="Zone status classification process initialized.",
        function="detect_supply_demand_zones",
    )
    _add_check(
        trace=trace,
        name="Zone alignment classified",
        passed=True,
        severity="INFO",
        details="Zone alignment classification process initialized.",
        function="detect_supply_demand_zones",
    )

    for timeframe, structure in (structures.items() if isinstance(structures, dict) else []):
        candles = _candles_for_tf(candles_by_tf, timeframe, structure)
        current_price = _coerce_float(getattr(structure, "current_price", None))
        current_direction = _normalize_direction(getattr(structure, "direction", "UNCLEAR"))

        active_leg = getattr(structure, "active_leg", None)
        if active_leg is not None:
            leg_dir = _normalize_direction(getattr(active_leg, "direction", "UNCLEAR"))
            start_price = _coerce_float(getattr(active_leg, "start_price", None))
            if leg_dir == "UP" and start_price is not None:
                zones.append(
                    _build_zone(
                        timeframe=timeframe,
                        zone_type="DEMAND",
                        price_low=start_price * 0.9985,
                        price_high=start_price * 1.0015,
                        structural_role="bullish impulse origin",
                        current_direction=current_direction,
                        current_price=current_price,
                        candles=candles,
                        divergence_rows=_divergence_rows_for_tf(divergence_audit, timeframe),
                        structure=structure,
                        trace=trace,
                    )
                )
            elif leg_dir == "DOWN" and start_price is not None:
                zones.append(
                    _build_zone(
                        timeframe=timeframe,
                        zone_type="SUPPLY",
                        price_low=start_price * 0.9985,
                        price_high=start_price * 1.0015,
                        structural_role="bearish impulse origin",
                        current_direction=current_direction,
                        current_price=current_price,
                        candles=candles,
                        divergence_rows=_divergence_rows_for_tf(divergence_audit, timeframe),
                        structure=structure,
                        trace=trace,
                    )
                )

        range_state = getattr(structure, "range_state", None)
        if range_state is not None and bool(getattr(range_state, "active", False)):
            lower_edge = _coerce_float(getattr(range_state, "lower_edge", None))
            upper_edge = _coerce_float(getattr(range_state, "upper_edge", None))
            status = str(getattr(range_state, "status", "")).upper()
            breakout_dir = _normalize_direction(getattr(range_state, "breakout_direction", "UNCLEAR"))
            if lower_edge is not None:
                zones.append(
                    _build_zone(
                        timeframe=timeframe,
                        zone_type="DEMAND",
                        price_low=lower_edge * 0.9985,
                        price_high=lower_edge * 1.0015,
                        structural_role="lower range-edge rejection",
                        current_direction=current_direction,
                        current_price=current_price,
                        candles=candles,
                        divergence_rows=_divergence_rows_for_tf(divergence_audit, timeframe),
                        structure=structure,
                        trace=trace,
                    )
                )
            if upper_edge is not None:
                zones.append(
                    _build_zone(
                        timeframe=timeframe,
                        zone_type="SUPPLY",
                        price_low=upper_edge * 0.9985,
                        price_high=upper_edge * 1.0015,
                        structural_role="upper range-edge rejection",
                        current_direction=current_direction,
                        current_price=current_price,
                        candles=candles,
                        divergence_rows=_divergence_rows_for_tf(divergence_audit, timeframe),
                        structure=structure,
                        trace=trace,
                    )
                )
            if status == "BROKEN_UP":
                level = _coerce_float(getattr(range_state, "upper_edge", None))
                if level is not None:
                    zones.append(
                        _build_zone(
                            timeframe=timeframe,
                            zone_type="DEMAND",
                            price_low=level * 0.9985,
                            price_high=level * 1.0015,
                            structural_role="breakout retest support",
                            current_direction=current_direction,
                            current_price=current_price,
                            candles=candles,
                            divergence_rows=_divergence_rows_for_tf(divergence_audit, timeframe),
                            structure=structure,
                            trace=trace,
                        )
                    )
            if status == "BROKEN_DOWN":
                level = _coerce_float(getattr(range_state, "lower_edge", None))
                if level is not None:
                    zones.append(
                        _build_zone(
                            timeframe=timeframe,
                            zone_type="SUPPLY",
                            price_low=level * 0.9985,
                            price_high=level * 1.0015,
                            structural_role="breakdown retest resistance",
                            current_direction=current_direction,
                            current_price=current_price,
                            candles=candles,
                            divergence_rows=_divergence_rows_for_tf(divergence_audit, timeframe),
                            structure=structure,
                            trace=trace,
                        )
                    )
            if status in {"FAILED_BREAK_DOWN", "RE_ENTERED"} and breakout_dir == "DOWN":
                level = _coerce_float(getattr(range_state, "lower_edge", None))
                if level is not None:
                    zones.append(
                        _build_zone(
                            timeframe=timeframe,
                            zone_type="DEMAND",
                            price_low=level * 0.9985,
                            price_high=level * 1.0015,
                            structural_role="failed breakdown recovery zone",
                            current_direction=current_direction,
                            current_price=current_price,
                            candles=candles,
                            divergence_rows=_divergence_rows_for_tf(divergence_audit, timeframe),
                            structure=structure,
                            trace=trace,
                        )
                    )
            if status in {"FAILED_BREAK_UP", "RE_ENTERED"} and breakout_dir == "UP":
                level = _coerce_float(getattr(range_state, "upper_edge", None))
                if level is not None:
                    zones.append(
                        _build_zone(
                            timeframe=timeframe,
                            zone_type="SUPPLY",
                            price_low=level * 0.9985,
                            price_high=level * 1.0015,
                            structural_role="failed breakout rejection zone",
                            current_direction=current_direction,
                            current_price=current_price,
                            candles=candles,
                            divergence_rows=_divergence_rows_for_tf(divergence_audit, timeframe),
                            structure=structure,
                            trace=trace,
                        )
                    )

        last_two = _last_two_legs(structure)
        if last_two is not None:
            pullback_leg, restart_leg = last_two
            pull_dir = _normalize_direction(getattr(pullback_leg, "direction", "UNCLEAR"))
            restart_dir = _normalize_direction(getattr(restart_leg, "direction", "UNCLEAR"))
            restart_low = _coerce_float(getattr(restart_leg, "low", None))
            restart_high = _coerce_float(getattr(restart_leg, "high", None))
            if pull_dir == "DOWN" and restart_dir == "UP" and restart_low is not None:
                zones.append(
                    _build_zone(
                        timeframe=timeframe,
                        zone_type="DEMAND",
                        price_low=restart_low,
                        price_high=restart_high if restart_high is not None else restart_low,
                        structural_role="type2 bullish restart area",
                        current_direction=current_direction,
                        current_price=current_price,
                        candles=candles,
                        divergence_rows=_divergence_rows_for_tf(divergence_audit, timeframe),
                        structure=structure,
                        trace=trace,
                    )
                )
            if pull_dir == "UP" and restart_dir == "DOWN" and restart_high is not None:
                zones.append(
                    _build_zone(
                        timeframe=timeframe,
                        zone_type="SUPPLY",
                        price_low=restart_low if restart_low is not None else restart_high,
                        price_high=restart_high,
                        structural_role="type2 bearish restart area",
                        current_direction=current_direction,
                        current_price=current_price,
                        candles=candles,
                        divergence_rows=_divergence_rows_for_tf(divergence_audit, timeframe),
                        structure=structure,
                        trace=trace,
                    )
                )

    zones.extend(_divergence_origin_zones(divergence_audit, structures, candles_by_tf, trace))
    return _deduplicate_zone_results([zone for zone in zones if zone.zone_type in {"SUPPLY", "DEMAND"}])


def zone_allows_trade(zone_result, setup_result, impulse_result, carry_result, trace=None) -> bool:
    """Return whether zone is tradable after mandatory structure/impulse/carry gates."""

    zone_type = str(getattr(zone_result, "zone_type", zone_result.zone_type if hasattr(zone_result, "zone_type") else "")).upper()
    status = str(getattr(zone_result, "status", "")).upper()
    role = str(getattr(zone_result, "structural_role", "")).lower()

    if "midpoint" in role:
        _add_check(
            trace=trace,
            name="Zone alone cannot create trade",
            passed=True,
            severity="INFO",
            details="Midpoint micro zone has weak authority and cannot trigger trade.",
            function="zone_allows_trade",
        )
        return False
    if status in {"FAILED", "ACCEPTED_THROUGH", "NONE"}:
        _add_check(
            trace=trace,
            name="Zone alone cannot create trade",
            passed=True,
            severity="INFO",
            details=f"Zone status={status} is not tradable and is reclassified as location-only.",
            function="zone_allows_trade",
        )
        return False

    downside_weakening = _bool_from_result(setup_result, "downside_weakening", fallback_keys=("weakening",))
    upside_weakening = _bool_from_result(setup_result, "upside_weakening", fallback_keys=("weakening",))
    bullish_structure = any(
        _bool_from_result(setup_result, key)
        for key in ("bullish_divergence", "reclaim", "restart", "bullish_restart")
    )
    bearish_structure = any(
        _bool_from_result(setup_result, key)
        for key in ("bearish_divergence", "rejection", "restart", "bearish_restart")
    )

    impulse_confirmed = bool(
        _bool_from_result(impulse_result, "confirmed", fallback_keys=("impulse_confirmed",))
    )
    impulse_direction = _normalize_direction(
        _value_from_result(impulse_result, "direction", fallback_keys=("impulse_direction",))
    )

    carry_direction = _normalize_direction(
        _value_from_result(carry_result, "direction", fallback_keys=("carry_direction",))
    )
    carry_state = str(_value_from_result(carry_result, "state")).upper()
    carry_finished = bool(_bool_from_result(carry_result, "finished", fallback_keys=("carry_finished",)))
    carry_valid = carry_state in {"FRESH", "ACTIVE", "MATURE"} and not carry_finished

    demand_allowed = bool(
        zone_type == "DEMAND"
        and downside_weakening
        and bullish_structure
        and impulse_confirmed
        and impulse_direction == "UP"
        and carry_valid
        and carry_direction == "UP"
    )
    supply_allowed = bool(
        zone_type == "SUPPLY"
        and upside_weakening
        and bearish_structure
        and impulse_confirmed
        and impulse_direction == "DOWN"
        and carry_valid
        and carry_direction == "DOWN"
    )
    allowed = demand_allowed or supply_allowed
    _add_check(
        trace=trace,
        name="Zone alone cannot create trade",
        passed=not (not allowed and impulse_confirmed is False and carry_valid is False),
        severity="INFO",
        details=(
            f"zone_type={zone_type}, allowed={allowed}, downside_weakening={downside_weakening}, "
            f"upside_weakening={upside_weakening}, bullish_structure={bullish_structure}, "
            f"bearish_structure={bearish_structure}, impulse_confirmed={impulse_confirmed}, "
            f"impulse_direction={impulse_direction}, carry_direction={carry_direction}, carry_state={carry_state}"
        ),
        function="zone_allows_trade",
    )
    return allowed


def _divergence_origin_zones(
    divergence_audit: Any,
    structures: Any,
    candles_by_tf: Any,
    trace: Any,
) -> list[ZoneResult]:
    zones: list[ZoneResult] = []
    if divergence_audit is None:
        return zones
    for field_name, timeframe in (
        ("tf_4h", "4h"),
        ("tf_1h", "1h"),
        ("tf_15m", "15m"),
        ("tf_5m", "5m"),
        ("tf_3m", "3m"),
    ):
        state = getattr(divergence_audit, field_name, None)
        if state is None or not bool(getattr(state, "exists", False)):
            continue
        direction = _normalize_direction(getattr(state, "direction", "NONE"))
        zone_band = str(getattr(state, "price_zone", "") or "")
        parsed = _parse_price_band(zone_band)
        if parsed is None:
            continue
        low, high = parsed
        zone_type = "DEMAND" if direction == "UP" else "SUPPLY" if direction == "DOWN" else "NONE"
        role = "bullish divergence origin" if zone_type == "DEMAND" else "bearish divergence origin"
        structure = structures.get(timeframe) if isinstance(structures, dict) else None
        current_direction = _normalize_direction(getattr(structure, "direction", "UNCLEAR"))
        current_price = _coerce_float(getattr(structure, "current_price", None))
        candles = _candles_for_tf(candles_by_tf, timeframe, structure)
        zones.append(
            _build_zone(
                timeframe=timeframe,
                zone_type=zone_type,
                price_low=low,
                price_high=high,
                structural_role=role,
                current_direction=current_direction,
                current_price=current_price,
                candles=candles,
                divergence_rows=_divergence_rows_for_tf(divergence_audit, timeframe),
                structure=structure,
                trace=trace,
            )
        )
    return zones


def _build_zone(
    *,
    timeframe: str,
    zone_type: str,
    price_low: float | None,
    price_high: float | None,
    structural_role: str,
    current_direction: str,
    current_price: float | None,
    candles: list[Any],
    divergence_rows: list[tuple[float, float]],
    structure: Any,
    trace: Any,
) -> ZoneResult:
    low, high = _normalize_bounds(price_low, price_high)
    if low is None or high is None:
        result = ZoneResult(
            timeframe=timeframe,
            zone_type="NONE",
            price_low=None,
            price_high=None,
            strength="INVALID",
            alignment="NONE",
            structural_role=structural_role,
            status="NONE",
            reason="Zone bounds are invalid.",
        )
        _add_check(
            trace=trace,
            name="Zone status classified",
            passed=True,
            severity="INFO",
            details=f"{timeframe} {structural_role}: status={result.status}",
            function="_build_zone",
        )
        _add_check(
            trace=trace,
            name="Zone alignment classified",
            passed=True,
            severity="INFO",
            details=f"{timeframe} {structural_role}: alignment={result.alignment}",
            function="_build_zone",
        )
        return result

    status = _classify_zone_status(
        zone_type=zone_type,
        price_low=low,
        price_high=high,
        current_price=current_price,
        candles=candles,
    )
    if status == "ACCEPTED_THROUGH":
        status = "FAILED"

    alignment = _classify_alignment(zone_type=zone_type, current_direction=current_direction, role=structural_role)
    strength = _classify_strength(
        timeframe=timeframe,
        zone_type=zone_type,
        price_low=low,
        price_high=high,
        current_price=current_price,
        candles=candles,
        structural_role=structural_role,
        divergence_rows=divergence_rows,
        structure=structure,
        status=status,
    )
    reason = f"{structural_role}; status={status}; alignment={alignment}; strength={strength}"
    result = ZoneResult(
        timeframe=timeframe,
        zone_type=zone_type,
        price_low=low,
        price_high=high,
        strength=strength,
        alignment=alignment,
        structural_role=structural_role,
        status=status,
        reason=reason,
    )
    _add_check(
        trace=trace,
        name="Zone status classified",
        passed=True,
        severity="INFO",
        details=f"{timeframe} {structural_role}: status={status}",
        function="_build_zone",
    )
    _add_check(
        trace=trace,
        name="Zone alignment classified",
        passed=True,
        severity="INFO",
        details=f"{timeframe} {structural_role}: alignment={alignment}",
        function="_build_zone",
    )
    return result


def _classify_strength(
    *,
    timeframe: str,
    zone_type: str,
    price_low: float,
    price_high: float,
    current_price: float | None,
    candles: list[Any],
    structural_role: str,
    divergence_rows: list[tuple[float, float]],
    structure: Any,
    status: str,
) -> str:
    impulse_departure = _strong_departure_from_zone(zone_type, price_low, price_high, candles)
    structural_consequence = _has_structural_consequence(structure)
    aligns_with_pivot_edge = "range-edge" in structural_role or "retest" in structural_role
    overlaps_divergence = any(_ranges_overlap(price_low, price_high, d_low, d_high) for d_low, d_high in divergence_rows)
    higher_timeframe = timeframe in _HIGHER_TIMEFRAMES
    not_over_tested = status in {"UNTESTED", "REACTING"}
    structural_room = _has_structural_room(zone_type, price_low, price_high, current_price, structure)

    score = sum(
        (
            impulse_departure,
            structural_consequence,
            aligns_with_pivot_edge,
            overlaps_divergence,
            higher_timeframe,
            not_over_tested,
            structural_room,
        )
    )
    if score >= 5:
        return "STRONG"
    if score >= 3:
        return "MODERATE"
    return "WEAK"


def _classify_zone_status(
    *,
    zone_type: str,
    price_low: float,
    price_high: float,
    current_price: float | None,
    candles: list[Any],
) -> str:
    if current_price is None:
        return "UNTESTED"
    if price_low <= current_price <= price_high:
        return "REACTING"

    touched_before = any(
        _ranges_overlap(price_low, price_high, _coerce_float(getattr(c, "low", None)), _coerce_float(getattr(c, "high", None)))
        for c in candles[:-1]
    )
    if touched_before:
        if zone_type == "DEMAND" and current_price < price_low:
            return "ACCEPTED_THROUGH"
        if zone_type == "SUPPLY" and current_price > price_high:
            return "ACCEPTED_THROUGH"
        return "TESTED"
    return "UNTESTED"


def _classify_alignment(*, zone_type: str, current_direction: str, role: str) -> str:
    if "midpoint" in role.lower():
        return "NONE"
    if current_direction == "UNCLEAR":
        return "NEUTRAL"
    if zone_type == "DEMAND":
        return "ALIGNED" if current_direction == "UP" else "COUNTER"
    if zone_type == "SUPPLY":
        return "ALIGNED" if current_direction == "DOWN" else "COUNTER"
    return "NONE"


def _strong_departure_from_zone(zone_type: str, price_low: float, price_high: float, candles: list[Any]) -> bool:
    if len(candles) < 3:
        return False
    zone_mid = (price_low + price_high) / 2.0
    closes = [_coerce_float(getattr(candle, "close", None)) for candle in candles[-3:]]
    if any(close is None for close in closes):
        return False
    if zone_type == "DEMAND":
        return bool(closes[-1] > zone_mid and closes[-1] > closes[-2] > closes[-3])
    if zone_type == "SUPPLY":
        return bool(closes[-1] < zone_mid and closes[-1] < closes[-2] < closes[-3])
    return False


def _has_structural_consequence(structure: Any) -> bool:
    if structure is None:
        return False
    range_state = getattr(structure, "range_state", None)
    if range_state is not None:
        status = str(getattr(range_state, "status", "")).upper()
        if status in {"BROKEN_UP", "BROKEN_DOWN", "FAILED_BREAK_UP", "FAILED_BREAK_DOWN"}:
            return True
    legs = list(getattr(structure, "legs", []) or [])
    return len(legs) >= 3


def _has_structural_room(
    zone_type: str,
    price_low: float,
    price_high: float,
    current_price: float | None,
    structure: Any,
) -> bool:
    if current_price is None:
        return True
    range_state = getattr(structure, "range_state", None) if structure is not None else None
    if range_state is not None and bool(getattr(range_state, "active", False)):
        upper = _coerce_float(getattr(range_state, "upper_edge", None))
        lower = _coerce_float(getattr(range_state, "lower_edge", None))
        if upper is not None and lower is not None:
            width = max(upper - lower, 1e-9)
            if zone_type == "DEMAND":
                return (upper - current_price) > 0.2 * width
            if zone_type == "SUPPLY":
                return (current_price - lower) > 0.2 * width
    zone_mid = (price_low + price_high) / 2.0
    if zone_type == "DEMAND":
        return current_price >= zone_mid
    if zone_type == "SUPPLY":
        return current_price <= zone_mid
    return False


def _divergence_rows_for_tf(divergence_audit: Any, timeframe: str) -> list[tuple[float, float]]:
    if divergence_audit is None:
        return []
    field = {
        "4h": "tf_4h",
        "1h": "tf_1h",
        "15m": "tf_15m",
        "5m": "tf_5m",
        "3m": "tf_3m",
    }.get(timeframe)
    if field is None:
        return []
    row = getattr(divergence_audit, field, None)
    if row is None:
        return []
    parsed = _parse_price_band(str(getattr(row, "price_zone", "") or ""))
    return [parsed] if parsed is not None else []


def _deduplicate_zone_results(zones: list[ZoneResult]) -> list[ZoneResult]:
    kept: list[ZoneResult] = []
    for zone in zones:
        replaced = False
        for idx, existing in enumerate(kept):
            if zone.timeframe != existing.timeframe or zone.zone_type != existing.zone_type:
                continue
            if not _ranges_overlap(zone.price_low, zone.price_high, existing.price_low, existing.price_high):
                continue
            if _zone_rank(zone) >= _zone_rank(existing):
                kept[idx] = zone
            replaced = True
            break
        if not replaced:
            kept.append(zone)
    return kept


def _zone_rank(zone: ZoneResult) -> tuple[int, int]:
    strength_score = {"STRONG": 4, "MODERATE": 3, "WEAK": 2, "INVALID": 1, "NONE": 0}.get(zone.strength, 0)
    tf_score = {"4h": 5, "1h": 4, "15m": 3, "5m": 2, "3m": 1}.get(zone.timeframe, 0)
    return (strength_score, tf_score)


def _candles_for_tf(candles_by_tf: Any, timeframe: str, structure: Any) -> list[Any]:
    if isinstance(candles_by_tf, dict):
        candles = candles_by_tf.get(timeframe)
        if isinstance(candles, list):
            return candles
    structure_candles = getattr(structure, "candles", None)
    return list(structure_candles or [])


def _last_two_legs(structure: Any) -> tuple[Any, Any] | None:
    legs = list(getattr(structure, "legs", []) or [])
    if len(legs) < 2:
        return None
    ordered = sorted(legs, key=lambda leg: getattr(leg, "end_index", 0))
    return (ordered[-2], ordered[-1])


def _parse_price_band(text: str) -> tuple[float, float] | None:
    if "-" not in text:
        return None
    left, right = text.split("-", 1)
    low = _coerce_float(left)
    high = _coerce_float(right)
    if low is None or high is None:
        return None
    return (low, high) if low <= high else (high, low)


def _normalize_bounds(low: float | None, high: float | None) -> tuple[float | None, float | None]:
    low_val = _coerce_float(low)
    high_val = _coerce_float(high)
    if low_val is None or high_val is None:
        return (None, None)
    return (low_val, high_val) if low_val <= high_val else (high_val, low_val)


def _ranges_overlap(a_low, a_high, b_low, b_high) -> bool:
    a = _normalize_bounds(a_low, a_high)
    b = _normalize_bounds(b_low, b_high)
    if a[0] is None or b[0] is None:
        return False
    return max(a[0], b[0]) <= min(a[1], b[1])


def _normalize_direction(raw: Any) -> str:
    value = str(getattr(raw, "value", raw)).strip().upper()
    if value in {"UP", "BULLISH"}:
        return "UP"
    if value in {"DOWN", "BEARISH"}:
        return "DOWN"
    return "UNCLEAR"


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _get_context_value(context: Any, key: str, default: Any) -> Any:
    if isinstance(context, dict):
        return context.get(key, default)
    return getattr(context, key, default)


def _value_from_result(result: Any, key: str, fallback_keys: tuple[str, ...] = ()) -> Any:
    if result is None:
        return None
    if isinstance(result, dict):
        if key in result:
            return result.get(key)
        for alt in fallback_keys:
            if alt in result:
                return result.get(alt)
        return None
    value = getattr(result, key, None)
    if value is not None:
        return value
    for alt in fallback_keys:
        value = getattr(result, alt, None)
        if value is not None:
            return value
    return None


def _bool_from_result(result: Any, key: str, fallback_keys: tuple[str, ...] = ()) -> bool:
    return bool(_value_from_result(result, key, fallback_keys))


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
        file="ocean_zone_engine.py",
        function=function,
    )

