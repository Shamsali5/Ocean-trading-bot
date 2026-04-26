from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .signals import (
    TradeSetup,
    build_active_trade_audit,
    build_carry,
    build_divergence_audit,
    build_range_state,
    build_zones,
    classify_parent_move,
    detect_trade_setup,
    multi_level_story,
    next_lower_timeframe,
    tf_key,
)
from .structure import build_timeframe_analysis
from .types import TIMEFRAMES_HIGH_TO_LOW, Candle, format_price, parse_candles


@dataclass
class FrameworkEngine:
    """Deterministic implementation of the Ocean Natural Chanlun reading order."""

    def analyze(
        self,
        symbol: str,
        raw_market_data: dict[str, list[list[Any]]],
        ts_utc: str,
        position_side: str = "NONE",
    ) -> dict[str, Any]:
        position_side = position_side.upper().strip()
        if position_side not in {"NONE", "LONG", "SHORT"}:
            position_side = "NONE"

        market = {
            tf: build_timeframe_analysis(tf, parse_candles(raw_market_data.get(tf, [])))
            for tf in TIMEFRAMES_HIGH_TO_LOW
        }
        current_price = self._current_price(market)

        parent = classify_parent_move(market)
        trade = detect_trade_setup(market)
        divergence_audit, selected_div_key = build_divergence_audit(market)
        active_trade_audit = build_active_trade_audit(market, trade)
        carry = build_carry(market, trade)
        range_state = build_range_state(market, parent)
        zones = build_zones(market)
        story = multi_level_story(divergence_audit, active_trade_audit, carry, trade)

        result = {
            "symbol": symbol,
            "timestamp": ts_utc,
            "current_price": format_price(current_price),
            "position_side": position_side,
            "final_action": self._final_action(trade, range_state, carry, position_side),
            "management_state": self._management_state(trade, carry, position_side),
            "signal_side": self._signal_side(trade, position_side),
            "parent_move": parent,
            "current_move": self._current_move(trade, parent),
            "divergence_audit": divergence_audit,
            "last_meaningful_divergence": (
                divergence_audit[selected_div_key] if selected_div_key else self._empty_divergence()
            ),
            "carry": carry,
            "range_state": range_state,
            "zones": zones,
            "active_trade_audit": active_trade_audit,
            "multi_level_story": story,
            "trade_classification": self._trade_classification(trade),
            "position_management": self._position_management(trade, carry, position_side),
            "what_to_watch_next": self._watch_next(trade, zones, range_state),
            "one_line_reason": self._reason(trade, range_state, carry, position_side),
            "current_move_summary": self._summary(trade, parent, carry, range_state),
        }
        return result

    @staticmethod
    def _current_price(market: dict[str, Any]) -> float | None:
        for tf in ("3m", "5m", "15m", "1h", "4h"):
            candles: list[Candle] = market[tf].candles
            if candles:
                return candles[-1].close
        return None

    @staticmethod
    def _empty_divergence() -> dict[str, Any]:
        return {
            "exists": "NO",
            "timeframe": "N/A",
            "direction": "NONE",
            "abc_valid": "NO",
            "segment_b_reset_valid": "UNCLEAR",
            "segment_c_completed": "UNCLEAR",
            "new_high_low_or_retest": "UNCLEAR",
            "vacc_confirmation": "NONE",
            "impulse_confirmed": "NO",
            "grade": "INVALID",
            "role": "NONE",
            "price_zone": "N/A",
            "summary": "No official timeframe-owned divergence selected from local framework analysis.",
        }

    @staticmethod
    def _final_action(
        trade: TradeSetup | None,
        range_state: dict[str, Any],
        carry: dict[str, Any],
        position_side: str,
    ) -> str:
        if position_side == "LONG":
            if trade and trade.direction == "BEARISH" and carry["state"] in {"FRESH", "ACTIVE"}:
                return "CLOSE LONG"
            return "HOLD LONG"
        if position_side == "SHORT":
            if trade and trade.direction == "BULLISH" and carry["state"] in {"FRESH", "ACTIVE"}:
                return "CLOSE SHORT"
            return "HOLD SHORT"

        if trade is None:
            return "WAIT"
        if range_state["active"] == "YES" and range_state["price_location"] == "MID":
            return "WAIT"
        if carry["state"] not in {"FRESH", "ACTIVE"}:
            return "WAIT"
        return "BUY" if trade.direction == "BULLISH" else "SELL"

    @staticmethod
    def _management_state(trade: TradeSetup | None, carry: dict[str, Any], position_side: str) -> str:
        if position_side in {"LONG", "SHORT"} and trade:
            if (
                position_side == "LONG"
                and trade.direction == "BEARISH"
                or position_side == "SHORT"
                and trade.direction == "BULLISH"
            ) and carry["state"] in {"FRESH", "ACTIVE"}:
                return "FULL_CLOSE"
        if position_side in {"LONG", "SHORT"}:
            return "HOLD"
        if trade is None:
            return "NONE"
        if carry["state"] in {"FRESH", "ACTIVE"}:
            return "HOLD"
        if carry["state"] == "MATURE":
            return "HOLD_WITH_CAUTION"
        if carry["state"] == "EXHAUSTING":
            return "CLOSE_WATCH"
        return "NONE"

    @staticmethod
    def _signal_side(trade: TradeSetup | None, position_side: str) -> str:
        if position_side in {"LONG", "SHORT"}:
            return position_side
        if trade is None:
            return "NONE"
        return "BUY" if trade.direction == "BULLISH" else "SELL"

    @staticmethod
    def _current_move(trade: TradeSetup | None, parent: dict[str, Any]) -> dict[str, Any]:
        if trade is None:
            return {
                "timeframe": parent["timeframe"],
                "direction": parent["direction"],
                "origin_type": "UNCLEAR",
                "origin_price_zone": "N/A",
                "confirmed_at_price": "N/A",
                "with_or_against_parent": "UNCLEAR",
                "summary": "No executable current move confirmed by local framework analysis.",
            }
        direction = "UP" if trade.direction == "BULLISH" else "DOWN"
        parent_direction = parent.get("direction", "UNCLEAR")
        return {
            "timeframe": trade.timeframe,
            "direction": direction,
            "origin_type": "DIVERGENCE",
            "origin_price_zone": trade.price_zone,
            "confirmed_at_price": trade.confirmation_price,
            "with_or_against_parent": "WITH_PARENT" if direction == parent_direction else "AGAINST_PARENT",
            "summary": f"{trade.type_label} confirmed locally from same-timeframe A-B-C divergence and impulse.",
        }

    @staticmethod
    def _trade_classification(trade: TradeSetup | None) -> dict[str, Any]:
        if trade is None:
            return {
                "active_trade_exists": "NO",
                "type_label": "NONE",
                "trade_function": "NONE",
                "fresh_entry_valid": "NO",
                "existing_hold_valid": "NO",
                "too_late_to_chase": "UNCLEAR",
                "earliest_legal_trigger_price": "N/A",
                "invalidation": "N/A",
                "summary": "No local framework trade setup confirmed.",
            }
        return {
            "active_trade_exists": "YES",
            "type_label": trade.type_label,
            "trade_function": "DECOMPOSITION" if trade.timeframe in {"15m", "5m", "3m"} else "HIGHER_TF_DIVERGENCE",
            "fresh_entry_valid": "YES",
            "existing_hold_valid": "YES",
            "too_late_to_chase": "NO",
            "earliest_legal_trigger_price": trade.confirmation_price,
            "invalidation": trade.invalidation,
            "summary": f"{trade.type_label} is the active local framework setup.",
        }

    @staticmethod
    def _position_management(
        trade: TradeSetup | None,
        carry: dict[str, Any],
        position_side: str,
    ) -> dict[str, Any]:
        if trade is None:
            if position_side in {"LONG", "SHORT"}:
                return {
                    "if_already_in": "HOLD",
                    "if_not_in": "WAIT",
                    "stop_action": "KEEP",
                    "profit_action": "NONE",
                    "runner_logic": "KEEP",
                    "summary": f"Existing {position_side.lower()} position has no opposite local close signal.",
                }
            return {
                "if_already_in": "NONE",
                "if_not_in": "WAIT",
                "stop_action": "NONE",
                "profit_action": "NONE",
                "runner_logic": "NONE",
                "summary": "No position management action without active local setup.",
            }
        if position_side == "LONG" and trade.direction == "BEARISH":
            if_already = "FULL_CLOSE" if carry["state"] in {"FRESH", "ACTIVE"} else "CLOSE_WATCH"
        elif position_side == "SHORT" and trade.direction == "BULLISH":
            if_already = "FULL_CLOSE" if carry["state"] in {"FRESH", "ACTIVE"} else "CLOSE_WATCH"
        else:
            if_already = "HOLD_WITH_CAUTION" if carry["state"] == "MATURE" else "HOLD"

        if_not_in = "BUY" if trade.direction == "BULLISH" else "SELL"
        return {
            "if_already_in": if_already,
            "if_not_in": if_not_in if carry["state"] in {"FRESH", "ACTIVE"} else "WAIT",
            "stop_action": "MOVE_TO_STRUCTURE",
            "profit_action": "NONE",
            "runner_logic": "KEEP" if carry["state"] in {"FRESH", "ACTIVE"} else "REDUCE",
            "summary": f"Manage against invalidation {trade.invalidation}; carry state is {carry['state']}.",
        }

    @staticmethod
    def _watch_next(trade: TradeSetup | None, zones: list[Any], range_state: dict[str, Any]) -> dict[str, Any]:
        demand = next((z for z in zones if z.get("type") == "DEMAND"), None)
        supply = next((z for z in zones if z.get("type") == "SUPPLY"), None)
        if trade is None:
            next_event = "Wait for same-timeframe A-B-C divergence plus impulse."
        else:
            carry_tf = next_lower_timeframe(trade.timeframe) or "lower timeframe"
            next_event = f"Watch {carry_tf} carry for continuation or opposite divergence plus impulse."
        return {
            "bullish_confirmation_needed": "Bullish A-B-C divergence plus upward impulse.",
            "bearish_confirmation_needed": "Bearish A-B-C divergence plus downward impulse.",
            "key_demand_zone": f"{demand.get('timeframe')} {demand.get('price_band')}" if demand else "N/A",
            "key_supply_zone": f"{supply.get('timeframe')} {supply.get('price_band')}" if supply else "N/A",
            "key_range_zone": range_state["midpoint"] if range_state["active"] == "YES" else "N/A",
            "next_structural_event": next_event,
        }

    @staticmethod
    def _reason(
        trade: TradeSetup | None,
        range_state: dict[str, Any],
        carry: dict[str, Any],
        position_side: str,
    ) -> str:
        if position_side == "LONG":
            if trade and trade.direction == "BEARISH" and carry["state"] in {"FRESH", "ACTIVE"}:
                return "CLOSE LONG because local framework found an opposite bearish setup with active carry."
            return "HOLD LONG because no opposite bearish close condition is confirmed locally."
        if position_side == "SHORT":
            if trade and trade.direction == "BULLISH" and carry["state"] in {"FRESH", "ACTIVE"}:
                return "CLOSE SHORT because local framework found an opposite bullish setup with active carry."
            return "HOLD SHORT because no opposite bullish close condition is confirmed locally."

        if trade is None:
            return "WAIT because local framework analysis found no same-timeframe divergence setup with impulse."
        if range_state["active"] == "YES" and range_state["price_location"] == "MID":
            return "WAIT because price is inside active range midpoint."
        if carry["state"] not in {"FRESH", "ACTIVE"}:
            return "WAIT because carry is not Fresh or Active."
        side = "BUY" if trade.direction == "BULLISH" else "SELL"
        return f"{side} because {trade.type_label} has same-timeframe A-B-C divergence, impulse, and {carry['state']} carry."

    @staticmethod
    def _summary(
        trade: TradeSetup | None,
        parent: dict[str, Any],
        carry: dict[str, Any],
        range_state: dict[str, Any],
    ) -> str:
        if trade is None:
            return (
                f"Parent move is {parent['timeframe']} {parent['direction']} / {parent['state']}. "
                "No active execution trade is confirmed locally, so fresh action waits."
            )
        return (
            f"Current move is {trade.direction.lower()}, started from {trade.type_label} near {trade.price_zone}. "
            f"Parent move is {parent['timeframe']} {parent['direction']}. "
            f"It is being carried by {carry['timeframe']} {carry['direction']} and range location is {range_state['price_location']}."
        )


def analyze_market(
    symbol: str,
    raw_market_data: dict[str, list[list[Any]]],
    ts_utc: str,
    position_side: str = "NONE",
) -> dict[str, Any]:
    return FrameworkEngine().analyze(symbol, raw_market_data, ts_utc, position_side)
