from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .types import TIMEFRAME_LABELS, TIMEFRAMES_HIGH_TO_LOW, TimeframeAnalysis


def tf_key(timeframe: str) -> str:
    return f"tf_{timeframe.lower().replace('h', 'h')}"


def next_lower_timeframe(timeframe: str) -> str | None:
    try:
        idx = TIMEFRAMES_HIGH_TO_LOW.index(timeframe)
    except ValueError:
        return None
    if idx + 1 >= len(TIMEFRAMES_HIGH_TO_LOW):
        return None
    return TIMEFRAMES_HIGH_TO_LOW[idx + 1]


@dataclass(frozen=True)
class TradeSetup:
    timeframe: str
    direction: str
    type_label: str
    price_zone: str
    confirmation_price: str
    invalidation: str
    carry_timeframe: str


def classify_parent_move(market: dict[str, TimeframeAnalysis]) -> dict[str, str]:
    for timeframe in TIMEFRAMES_HIGH_TO_LOW:
        analysis = market[timeframe]
        if analysis.direction != "UNCLEAR":
            return {
                "timeframe": timeframe,
                "direction": analysis.direction,
                "state": analysis.state,
                "still_active": "YES" if analysis.state in {"TREND", "RANGE"} else "UNCLEAR",
                "summary": f"{timeframe} parent context is {analysis.direction} / {analysis.state}.",
            }
    return {
        "timeframe": "N/A",
        "direction": "UNCLEAR",
        "state": "UNCLEAR",
        "still_active": "UNCLEAR",
        "summary": "No parent context confirmed locally.",
    }


def detect_trade_setup(market: dict[str, TimeframeAnalysis]) -> TradeSetup | None:
    for timeframe in TIMEFRAMES_HIGH_TO_LOW:
        row = market[timeframe].divergence
        if row["exists"] != "YES":
            continue
        direction = row["direction"]
        if direction not in {"BULLISH", "BEARISH"}:
            continue
        latest = market[timeframe].candles[-1] if market[timeframe].candles else None
        label_direction = "Bullish" if direction == "BULLISH" else "Bearish"
        return TradeSetup(
            timeframe=timeframe,
            direction=direction,
            type_label=f"{timeframe} {label_direction} Type 1",
            price_zone=row["price_zone"],
            confirmation_price=f"{latest.close:,.2f}" if latest else "N/A",
            invalidation=row["price_zone"],
            carry_timeframe=next_lower_timeframe(timeframe) or timeframe,
        )
    return None


def build_divergence_audit(market: dict[str, TimeframeAnalysis]) -> tuple[dict[str, Any], str | None]:
    audit: dict[str, Any] = {}
    selected: str | None = None
    for timeframe in TIMEFRAMES_HIGH_TO_LOW:
        key = tf_key(timeframe)
        row = dict(market[timeframe].divergence)
        audit[key] = row
        if selected is None and row["exists"] == "YES":
            selected = key
    audit["selected_last_meaningful_tf"] = selected or "none"
    audit["selection_reason"] = (
        f"Selected {TIMEFRAME_LABELS[selected]} as highest official local divergence." if selected else "No official local divergence selected."
    )
    return audit, selected


def build_active_trade_audit(market: dict[str, TimeframeAnalysis], trade: TradeSetup | None) -> dict[str, Any]:
    audit: dict[str, Any] = {}
    for timeframe in TIMEFRAMES_HIGH_TO_LOW:
        key = tf_key(timeframe)
        exists = trade is not None and trade.timeframe == timeframe
        direction = trade.direction if exists and trade else "NONE"
        carry = build_carry(market, trade) if exists else {"timeframe": "N/A", "direction": "UNCLEAR", "state": "UNCLEAR"}
        audit[key] = {
            "exists": "YES" if exists else "NO",
            "origin_timeframe": timeframe,
            "direction": direction,
            "setup_type": "TYPE_1" if exists else "NONE",
            "type_label": trade.type_label if exists and trade else "NONE",
            "trade_function": "HIGHER_TF_DIVERGENCE" if exists and timeframe in {"4h", "1h"} else "DECOMPOSITION" if exists else "NONE",
            "origin_price_zone": trade.price_zone if exists and trade else "N/A",
            "confirmation_price": trade.confirmation_price if exists and trade else "N/A",
            "confirmation_time_utc": "N/A",
            "earliest_legal_trigger_price": trade.confirmation_price if exists and trade else "N/A",
            "carry_timeframe": carry["timeframe"],
            "carry_direction": carry["direction"],
            "carry_state": carry["state"],
            "fresh_entry_valid": "YES" if exists and carry["state"] in {"FRESH", "ACTIVE"} else "NO",
            "existing_hold_valid": "YES" if exists and carry["state"] in {"FRESH", "ACTIVE", "MATURE"} else "NO",
            "too_late_to_chase": "NO" if exists and carry["state"] in {"FRESH", "ACTIVE"} else "YES" if exists else "UNCLEAR",
            "invalidation": trade.invalidation if exists and trade else "N/A",
            "current_status": carry["state"] if exists else "NONE",
            "selection_reason": "Selected by highest official same-timeframe local divergence." if exists else f"No official {timeframe} trade origin confirmed locally.",
            "summary": f"{trade.type_label} selected locally." if exists and trade else f"No active trade origin confirmed on {timeframe}.",
        }
    audit["selected_active_trade_tf"] = tf_key(trade.timeframe) if trade else "none"
    audit["selection_reason"] = "Selected active trade by true local setup origin." if trade else "No local active trade selected."
    return audit


def build_carry(market: dict[str, TimeframeAnalysis], trade: TradeSetup | None) -> dict[str, str]:
    if trade is None:
        return {
            "timeframe": "N/A",
            "direction": "UNCLEAR",
            "state": "UNCLEAR",
            "cycle_complete": "UNCLEAR",
            "opposite_divergence": "UNCLEAR",
            "opposite_impulse": "UNCLEAR",
            "finished": "UNCLEAR",
            "summary": "No carry without a local active trade.",
        }
    carry_tf = trade.carry_timeframe
    analysis = market.get(carry_tf)
    direction = "UP" if trade.direction == "BULLISH" else "DOWN"
    state = "ACTIVE"
    if analysis and analysis.direction == direction:
        state = "FRESH" if analysis.divergence["exists"] == "YES" else "ACTIVE"
    elif analysis and analysis.direction == "RANGE":
        state = "MATURE"
    return {
        "timeframe": carry_tf,
        "direction": direction,
        "state": state,
        "cycle_complete": "PARTIAL",
        "opposite_divergence": "NO",
        "opposite_impulse": "NO",
        "finished": "NO",
        "summary": f"{carry_tf} carries the {trade.timeframe} setup as {state}.",
    }


def build_range_state(market: dict[str, TimeframeAnalysis], parent: dict[str, str]) -> dict[str, str]:
    timeframe = parent["timeframe"] if parent["timeframe"] in market else "1h"
    return dict(market.get(timeframe, market["1h"]).range_state)


def build_zones(market: dict[str, TimeframeAnalysis]) -> list[dict[str, str]]:
    zones: list[dict[str, str]] = []
    for timeframe in TIMEFRAMES_HIGH_TO_LOW:
        zones.extend(market[timeframe].zones[:2])
    return zones[:6]


def multi_level_story(
    divergence_audit: dict[str, Any],
    active_trade_audit: dict[str, Any],
    carry: dict[str, str],
    trade: TradeSetup | None,
) -> dict[str, Any]:
    if trade is None:
        return {
            "active": "NO",
            "direction": "NONE",
            "confirmed_timeframes": [],
            "controlling_origin": "N/A",
            "active_execution_trade": "N/A",
            "carrying_timeframe": "N/A",
            "higher_tf_status": "NONE",
            "explanation": "No local active trade, so no multi-level story.",
        }
    confirmed = [
        TIMEFRAME_LABELS[key]
        for key in [tf_key(tf) for tf in TIMEFRAMES_HIGH_TO_LOW]
        if divergence_audit.get(key, {}).get("exists") == "YES"
        and divergence_audit.get(key, {}).get("direction") == trade.direction
    ]
    active = len(confirmed) >= 2
    return {
        "active": "YES" if active else "NO",
        "direction": trade.direction,
        "confirmed_timeframes": confirmed,
        "controlling_origin": f"{confirmed[0]} {trade.direction.title()} Type 1" if confirmed else trade.type_label,
        "active_execution_trade": trade.type_label,
        "carrying_timeframe": f"{carry['timeframe']} {carry['direction']}",
        "higher_tf_status": "OFFICIAL" if active else "NONE",
        "explanation": "Local multi-level confirmation requires at least two independent official same-direction divergence rows.",
    }
