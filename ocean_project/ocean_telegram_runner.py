from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Literal

import requests
from openai import OpenAI

from ocean_framework import FrameworkEngine

# ============================================================
# OCEAN × NATURAL CHANLUN TELEGRAM RUNNER v1.4
# Structure -> A-B-C -> VAcc Energy -> Divergence -> Zone -> Impulse -> Carry -> Multi-Level Context -> Action
# ============================================================

# =========================
# USER CONFIG
# =========================
MODEL = os.getenv("OCEAN_OPENAI_MODEL", "gpt-5.4")
REASONING_EFFORT = os.getenv("OCEAN_REASONING_EFFORT", "high")
ANALYSIS_MODE = os.getenv("OCEAN_ANALYSIS_MODE", "local").lower().strip()

SYMBOLS = [s.strip().upper() for s in os.getenv("OCEAN_SYMBOLS", "BTCUSDT").split(",") if s.strip()]
INTERVALS = ["3m", "5m", "15m", "1h", "4h"]

# Telegram output mode: compact is recommended for live alerts.
TELEGRAM_MODE = os.getenv("OCEAN_TELEGRAM_MODE", "compact").lower().strip()

# Canonical timeframe keys used for strict divergence and active-trade ownership.
# A divergence or active trade may only be called official on the timeframe whose own row proves it.
TF_AUDIT_KEYS = ["tf_4h", "tf_1h", "tf_15m", "tf_5m", "tf_3m"]
TF_KEY_TO_LABEL = {"tf_4h": "4H", "tf_1h": "1H", "tf_15m": "15m", "tf_5m": "5m", "tf_3m": "3m"}
TF_LABEL_TO_KEY = {v.upper(): k for k, v in TF_KEY_TO_LABEL.items()}

# Fetch limits from Binance Futures.
LIMITS = {
    "3m": int(os.getenv("OCEAN_LIMIT_3M", "240")),
    "5m": int(os.getenv("OCEAN_LIMIT_5M", "240")),
    "15m": int(os.getenv("OCEAN_LIMIT_15M", "300")),
    "1h": int(os.getenv("OCEAN_LIMIT_1H", "300")),
    "4h": int(os.getenv("OCEAN_LIMIT_4H", "240")),
}

# Prompt payload size sent to OpenAI.
PROMPT_KEEP_LAST_N = {
    "3m": int(os.getenv("OCEAN_PROMPT_3M", str(LIMITS["3m"]))),
    "5m": int(os.getenv("OCEAN_PROMPT_5M", str(LIMITS["5m"]))),
    "15m": int(os.getenv("OCEAN_PROMPT_15M", str(LIMITS["15m"]))),
    "1h": int(os.getenv("OCEAN_PROMPT_1H", str(LIMITS["1h"]))),
    "4h": int(os.getenv("OCEAN_PROMPT_4H", str(LIMITS["4h"]))),
}

FRAMEWORK_FILE = Path(os.getenv("OCEAN_FRAMEWORK_FILE", "framework_runtime.txt"))
DATA_DIR = Path(os.getenv("OCEAN_DATA_DIR", "ohlcv_data"))
RESULTS_DIR = Path(os.getenv("OCEAN_RESULTS_DIR", "analysis_results"))
BINANCE_FUTURES_KLINES_URL = "https://fapi.binance.com/fapi/v1/klines"
TELEGRAM_CHUNK_SIZE = int(os.getenv("OCEAN_TELEGRAM_CHUNK_SIZE", "3500"))
REQUEST_TIMEOUT = int(os.getenv("OCEAN_REQUEST_TIMEOUT", "30"))
RUN_EVERY_HALF_HOUR = os.getenv("OCEAN_RUN_EVERY_HALF_HOUR", "1") == "1"
SEND_TELEGRAM = os.getenv("OCEAN_SEND_TELEGRAM", "1") == "1"

# =========================
# ENV VARS
# =========================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if ANALYSIS_MODE == "openai" and not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY is not set.")
if SEND_TELEGRAM and not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is not set.")
if SEND_TELEGRAM and not TELEGRAM_CHAT_ID:
    raise RuntimeError("TELEGRAM_CHAT_ID is not set.")

client = OpenAI(api_key=OPENAI_API_KEY) if ANALYSIS_MODE == "openai" else None
framework_engine = FrameworkEngine()


# =========================
# BASIC HELPERS
# =========================
def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ms_to_utc(ms: Any) -> str:
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return "N/A"


def fetch_futures_klines(symbol: str, interval: str, limit: int) -> list[list[Any]]:
    params = {"symbol": symbol.upper(), "interval": interval, "limit": limit}
    response = requests.get(BINANCE_FUTURES_KLINES_URL, params=params, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, list):
        raise RuntimeError(f"Unexpected Binance response for {symbol} {interval}: {data}")
    return data


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def trim_klines(data: list[list[Any]], n: int) -> list[list[Any]]:
    if not isinstance(data, list):
        raise ValueError("Expected Binance kline JSON to be a list of arrays.")
    return data[-n:] if len(data) > n else data


def fetch_all_symbol_data(symbol: str) -> dict[str, list[list[Any]]]:
    payload: dict[str, list[list[Any]]] = {}
    symbol_dir = DATA_DIR / symbol
    symbol_dir.mkdir(parents=True, exist_ok=True)

    for tf in INTERVALS:
        klines = fetch_futures_klines(symbol, tf, LIMITS[tf])
        payload[tf] = klines
        save_json(symbol_dir / f"{symbol}_{tf}_futures.json", klines)
    return payload


def build_prompt_payload(raw_market_data: dict[str, list[list[Any]]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for tf, data in raw_market_data.items():
        keep_n = PROMPT_KEEP_LAST_N.get(tf, len(data))
        trimmed = trim_klines(data, keep_n)
        payload[tf] = {
            "rows": trimmed,
            "first_open_time_utc": ms_to_utc(trimmed[0][0]) if trimmed else "N/A",
            "last_close_time_utc": ms_to_utc(trimmed[-1][6]) if trimmed else "N/A",
        }
    return payload


def derive_current_price(raw_market_data: dict[str, list[list[Any]]]) -> float | None:
    for tf in ("3m", "5m", "15m", "1h", "4h"):
        data = raw_market_data.get(tf, [])
        if not data:
            continue
        try:
            return float(data[-1][4])
        except (IndexError, TypeError, ValueError):
            continue
    return None


def format_price(value: Any) -> str:
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return "N/A"


def text(value: Any, default: str = "N/A") -> str:
    if value is None:
        return default
    out = str(value).strip()
    return out if out else default


def load_framework() -> str:
    if not FRAMEWORK_FILE.exists():
        raise FileNotFoundError(
            f"Missing runtime framework file: {FRAMEWORK_FILE}\n"
            f"Create {FRAMEWORK_FILE.name} first and paste Ocean × Natural Chanlun Framework v1.2 into it."
        )
    content = FRAMEWORK_FILE.read_text(encoding="utf-8").strip()
    if not content:
        raise RuntimeError(f"Framework file is empty: {FRAMEWORK_FILE}")
    return content


# =========================
# JSON SCHEMA HELPERS
# =========================
def enum_schema(values: list[str]) -> dict[str, Any]:
    return {"type": "string", "enum": values}


def parent_move_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "timeframe": {"type": "string"},
            "direction": enum_schema(["UP", "DOWN", "RANGE", "TRANSITION", "UNCLEAR"]),
            "state": enum_schema(["TREND", "RANGE", "TRANSITION", "UNCLEAR"]),
            "still_active": enum_schema(["YES", "NO", "UNCLEAR"]),
            "summary": {"type": "string"},
        },
        "required": ["timeframe", "direction", "state", "still_active", "summary"],
    }


def current_move_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "timeframe": {"type": "string"},
            "direction": enum_schema(["UP", "DOWN", "RANGE", "TRANSITION", "UNCLEAR"]),
            "origin_type": enum_schema([
                "DIVERGENCE",
                "BREAKOUT",
                "RANGE_REJECTION",
                "SUPPLY_DEMAND_REACTION",
                "PULLBACK_RESTART",
                "UNCLEAR",
            ]),
            "origin_price_zone": {"type": "string"},
            "confirmed_at_price": {"type": "string"},
            "with_or_against_parent": enum_schema(["WITH_PARENT", "AGAINST_PARENT", "INTERNAL", "UNCLEAR"]),
            "summary": {"type": "string"},
        },
        "required": [
            "timeframe",
            "direction",
            "origin_type",
            "origin_price_zone",
            "confirmed_at_price",
            "with_or_against_parent",
            "summary",
        ],
    }


def divergence_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "exists": enum_schema(["YES", "NO"]),
            "timeframe": {"type": "string"},
            "direction": enum_schema(["BULLISH", "BEARISH", "NONE"]),
            "abc_valid": enum_schema(["YES", "NO", "UNCLEAR"]),
            "segment_b_reset_valid": enum_schema(["YES", "NO", "UNCLEAR"]),
            "segment_c_completed": enum_schema(["YES", "NO", "UNCLEAR"]),
            "new_high_low_or_retest": enum_schema(["YES", "NO", "UNCLEAR"]),
            "vacc_confirmation": enum_schema(["VEL", "ACC", "ACC_AREA", "MULTI", "STRUCTURAL_ONLY", "NONE"]),
            "impulse_confirmed": enum_schema(["YES", "NO", "UNCLEAR"]),
            "grade": enum_schema(["ELITE", "STRONG", "MODERATE", "WEAK", "INVALID"]),
            "role": enum_schema(["ORIGIN", "SUPPORT", "FINISH_WARNING", "LOCAL_NOISE", "NONE"]),
            "price_zone": {"type": "string"},
            "summary": {"type": "string"},
        },
        "required": [
            "exists",
            "timeframe",
            "direction",
            "abc_valid",
            "segment_b_reset_valid",
            "segment_c_completed",
            "new_high_low_or_retest",
            "vacc_confirmation",
            "impulse_confirmed",
            "grade",
            "role",
            "price_zone",
            "summary",
        ],
    }


def divergence_audit_schema() -> dict[str, Any]:
    tf_div = divergence_schema()
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "tf_4h": tf_div,
            "tf_1h": tf_div,
            "tf_15m": tf_div,
            "tf_5m": tf_div,
            "tf_3m": tf_div,
            "selected_last_meaningful_tf": enum_schema(["tf_4h", "tf_1h", "tf_15m", "tf_5m", "tf_3m", "none"]),
            "selection_reason": {"type": "string"},
        },
        "required": [
            "tf_4h",
            "tf_1h",
            "tf_15m",
            "tf_5m",
            "tf_3m",
            "selected_last_meaningful_tf",
            "selection_reason",
        ],
    }


def carry_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "timeframe": {"type": "string"},
            "direction": enum_schema(["UP", "DOWN", "NONE", "UNCLEAR"]),
            "state": enum_schema(["FRESH", "ACTIVE", "MATURE", "EXHAUSTING", "UNCLEAR"]),
            "cycle_complete": enum_schema(["YES", "NO", "PARTIAL", "UNCLEAR"]),
            "opposite_divergence": enum_schema(["YES", "NO", "UNCLEAR"]),
            "opposite_impulse": enum_schema(["YES", "NO", "UNCLEAR"]),
            "finished": enum_schema(["YES", "NO", "UNCLEAR"]),
            "summary": {"type": "string"},
        },
        "required": [
            "timeframe",
            "direction",
            "state",
            "cycle_complete",
            "opposite_divergence",
            "opposite_impulse",
            "finished",
            "summary",
        ],
    }


def range_state_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "active": enum_schema(["YES", "NO", "UNCLEAR"]),
            "timeframe": {"type": "string"},
            "upper_edge": {"type": "string"},
            "lower_edge": {"type": "string"},
            "midpoint": {"type": "string"},
            "price_location": enum_schema(["UPPER_EDGE", "LOWER_EDGE", "MID", "OUTSIDE", "UNCLEAR"]),
            "parent_ownership": enum_schema(["BULLISH", "BEARISH", "NEUTRAL", "UNCLEAR"]),
            "status": enum_schema(["ACTIVE", "BROKEN", "FAILED_BREAK", "RE_ENTERED", "UPGRADING", "NONE", "UNCLEAR"]),
            "summary": {"type": "string"},
        },
        "required": [
            "active",
            "timeframe",
            "upper_edge",
            "lower_edge",
            "midpoint",
            "price_location",
            "parent_ownership",
            "status",
            "summary",
        ],
    }


def zone_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "timeframe": {"type": "string"},
            "type": enum_schema(["SUPPLY", "DEMAND"]),
            "price_band": {"type": "string"},
            "strength": enum_schema(["STRONG", "MODERATE", "WEAK"]),
            "alignment": enum_schema(["ALIGNED", "COUNTER", "NEUTRAL"]),
            "role": {"type": "string"},
            "status": enum_schema(["UNTESTED", "TESTED", "REACTING", "FAILED", "ACCEPTED_THROUGH"]),
        },
        "required": ["timeframe", "type", "price_band", "strength", "alignment", "role", "status"],
    }



def active_trade_candidate_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "exists": enum_schema(["YES", "NO"]),
            "origin_timeframe": {"type": "string"},
            "direction": enum_schema(["BULLISH", "BEARISH", "NONE"]),
            "setup_type": enum_schema(["TYPE_1", "TYPE_2", "TYPE_3", "NONE"]),
            "type_label": {"type": "string"},
            "trade_function": enum_schema([
                "HIGHER_TF_DIVERGENCE",
                "DECOMPOSITION",
                "RANGE_REJECTION",
                "BREAKOUT",
                "SUPPLY_DEMAND_REACTION",
                "PULLBACK_CONTINUATION",
                "UPGRADE",
                "NONE",
            ]),
            "origin_price_zone": {"type": "string"},
            "confirmation_price": {"type": "string"},
            "confirmation_time_utc": {"type": "string"},
            "earliest_legal_trigger_price": {"type": "string"},
            "carry_timeframe": {"type": "string"},
            "carry_direction": enum_schema(["UP", "DOWN", "NONE", "UNCLEAR"]),
            "carry_state": enum_schema(["FRESH", "ACTIVE", "MATURE", "EXHAUSTING", "UNCLEAR"]),
            "fresh_entry_valid": enum_schema(["YES", "NO", "UNCLEAR"]),
            "existing_hold_valid": enum_schema(["YES", "NO", "UNCLEAR"]),
            "too_late_to_chase": enum_schema(["YES", "NO", "UNCLEAR"]),
            "invalidation": {"type": "string"},
            "current_status": enum_schema(["FRESH", "ACTIVE", "MATURE", "EXHAUSTING", "INVALIDATED", "NONE", "UNCLEAR"]),
            "selection_reason": {"type": "string"},
            "summary": {"type": "string"},
        },
        "required": [
            "exists",
            "origin_timeframe",
            "direction",
            "setup_type",
            "type_label",
            "trade_function",
            "origin_price_zone",
            "confirmation_price",
            "confirmation_time_utc",
            "earliest_legal_trigger_price",
            "carry_timeframe",
            "carry_direction",
            "carry_state",
            "fresh_entry_valid",
            "existing_hold_valid",
            "too_late_to_chase",
            "invalidation",
            "current_status",
            "selection_reason",
            "summary",
        ],
    }


def active_trade_audit_schema() -> dict[str, Any]:
    candidate = active_trade_candidate_schema()
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "tf_4h": candidate,
            "tf_1h": candidate,
            "tf_15m": candidate,
            "tf_5m": candidate,
            "tf_3m": candidate,
            "selected_active_trade_tf": enum_schema(["tf_4h", "tf_1h", "tf_15m", "tf_5m", "tf_3m", "none"]),
            "selection_reason": {"type": "string"},
        },
        "required": [
            "tf_4h",
            "tf_1h",
            "tf_15m",
            "tf_5m",
            "tf_3m",
            "selected_active_trade_tf",
            "selection_reason",
        ],
    }


def multi_level_story_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "active": enum_schema(["YES", "NO"]),
            "direction": enum_schema(["BULLISH", "BEARISH", "NONE", "UNCLEAR"]),
            "confirmed_timeframes": {
                "type": "array",
                "items": {"type": "string"},
            },
            "controlling_origin": {"type": "string"},
            "active_execution_trade": {"type": "string"},
            "carrying_timeframe": {"type": "string"},
            "higher_tf_status": enum_schema(["OFFICIAL", "WEAKENING_CONTEXT_ONLY", "NONE", "UNCLEAR"]),
            "explanation": {"type": "string"},
        },
        "required": [
            "active",
            "direction",
            "confirmed_timeframes",
            "controlling_origin",
            "active_execution_trade",
            "carrying_timeframe",
            "higher_tf_status",
            "explanation",
        ],
    }

def trade_classification_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "active_trade_exists": enum_schema(["YES", "NO"]),
            "type_label": {"type": "string"},
            "trade_function": enum_schema([
                "HIGHER_TF_DIVERGENCE",
                "DECOMPOSITION",
                "RANGE_REJECTION",
                "BREAKOUT",
                "SUPPLY_DEMAND_REACTION",
                "PULLBACK_CONTINUATION",
                "UPGRADE",
                "NONE",
            ]),
            "fresh_entry_valid": enum_schema(["YES", "NO", "UNCLEAR"]),
            "existing_hold_valid": enum_schema(["YES", "NO", "UNCLEAR"]),
            "too_late_to_chase": enum_schema(["YES", "NO", "UNCLEAR"]),
            "earliest_legal_trigger_price": {"type": "string"},
            "invalidation": {"type": "string"},
            "summary": {"type": "string"},
        },
        "required": [
            "active_trade_exists",
            "type_label",
            "trade_function",
            "fresh_entry_valid",
            "existing_hold_valid",
            "too_late_to_chase",
            "earliest_legal_trigger_price",
            "invalidation",
            "summary",
        ],
    }


def position_management_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "if_already_in": enum_schema([
                "HOLD",
                "HOLD_WITH_CAUTION",
                "CLOSE_WATCH",
                "PARTIAL_CLOSE",
                "FULL_CLOSE",
                "CLOSE_AND_FLIP",
                "NONE",
            ]),
            "if_not_in": enum_schema(["BUY", "SELL", "WAIT"]),
            "stop_action": enum_schema(["KEEP", "MOVE_TO_STRUCTURE", "MOVE_TO_BREAKEVEN", "TRAIL", "NONE"]),
            "profit_action": enum_schema(["NONE", "PARTIAL", "FULL"]),
            "runner_logic": enum_schema(["KEEP", "REDUCE", "REMOVE", "NONE"]),
            "summary": {"type": "string"},
        },
        "required": ["if_already_in", "if_not_in", "stop_action", "profit_action", "runner_logic", "summary"],
    }


def watch_next_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "bullish_confirmation_needed": {"type": "string"},
            "bearish_confirmation_needed": {"type": "string"},
            "key_demand_zone": {"type": "string"},
            "key_supply_zone": {"type": "string"},
            "key_range_zone": {"type": "string"},
            "next_structural_event": {"type": "string"},
        },
        "required": [
            "bullish_confirmation_needed",
            "bearish_confirmation_needed",
            "key_demand_zone",
            "key_supply_zone",
            "key_range_zone",
            "next_structural_event",
        ],
    }


def analysis_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "symbol": {"type": "string"},
            "timestamp": {"type": "string"},
            "current_price": {"type": "string"},
            "final_action": enum_schema([
                "BUY",
                "SELL",
                "HOLD LONG",
                "HOLD SHORT",
                "CLOSE LONG",
                "CLOSE SHORT",
                "CLOSE AND FLIP",
                "WAIT",
            ]),
            "management_state": enum_schema([
                "HOLD",
                "HOLD_WITH_CAUTION",
                "CLOSE_WATCH",
                "PARTIAL_CLOSE",
                "FULL_CLOSE",
                "CLOSE_AND_FLIP",
                "NONE",
            ]),
            "signal_side": enum_schema(["BUY", "SELL", "LONG", "SHORT", "NONE"]),
            "parent_move": parent_move_schema(),
            "current_move": current_move_schema(),
            "divergence_audit": divergence_audit_schema(),
            "last_meaningful_divergence": divergence_schema(),
            "carry": carry_schema(),
            "range_state": range_state_schema(),
            "zones": {"type": "array", "items": zone_schema()},
            "active_trade_audit": active_trade_audit_schema(),
            "multi_level_story": multi_level_story_schema(),
            "trade_classification": trade_classification_schema(),
            "position_management": position_management_schema(),
            "what_to_watch_next": watch_next_schema(),
            "one_line_reason": {"type": "string"},
            "current_move_summary": {"type": "string"},
        },
        "required": [
            "symbol",
            "timestamp",
            "current_price",
            "final_action",
            "management_state",
            "signal_side",
            "parent_move",
            "current_move",
            "divergence_audit",
            "last_meaningful_divergence",
            "carry",
            "range_state",
            "zones",
            "active_trade_audit",
            "multi_level_story",
            "trade_classification",
            "position_management",
            "what_to_watch_next",
            "one_line_reason",
            "current_move_summary",
        ],
    }


# =========================
# PROMPT
# =========================
def build_prompt(symbol: str, framework: str, market_data: dict[str, Any], ts_utc: str, current_price: float | None) -> str:
    return f"""
RUNTIME CONSTITUTION:
{framework}

MARKET INPUT:
symbol: {symbol}
analysis_timestamp_utc: {ts_utc}
current_price: {format_price(current_price)}
input_type: OHLCV
available_timeframes: {', '.join(INTERVALS)}

OHLCV DATA:
{json.dumps(market_data, ensure_ascii=False)}

MANDATORY TASK:
Return JSON only using the provided schema.

You must read the market using Ocean × Natural Chanlun Framework v1.2.
Use this exact reading order:
Structure -> Level -> A-B-C -> VAcc Energy -> Divergence -> Supply/Demand Zone -> Impulse/Acceptance -> Carry -> Multi-Level Context -> Action.

Hard rules:
- Use only the supplied OHLCV and runtime constitution.
- Ignore all previous chats, prior analyses, memories, and assumptions.
- Never predict. Only state what structure has proven.
- Start from highest timeframe: 4H -> 1H -> 15m -> 5m -> 3m.
- 4H is parent context unless the supplied data clearly proves otherwise.
- 1H is the main decision/range layer unless the supplied data clearly proves otherwise.
- 15m is active decomposition/execution structure.
- 5m is carry / execution timing.
- 3m is micro confirmation only.
- Level is structural, not only timeframe. Do not call a timeframe official unless that same timeframe has its own structure.
- DIVERGENCE TIMEFRAME LOCK: First fill divergence_audit for tf_4h, tf_1h, tf_15m, tf_5m, tf_3m independently.
- Each divergence_audit row must judge only that timeframe's own OHLCV. Do not use 5m A-B-C to declare 15m divergence. Do not use 15m A-B-C to declare 1H divergence.
- A timeframe row may set exists=YES only if that same timeframe has valid A-B-C, Segment B reset, Segment C retest/new extreme, energy weakness, and opposite impulse.
- selected_last_meaningful_tf must be one of the audited timeframe keys only, and it must point to an exists=YES row. If no audited row is official, selected_last_meaningful_tf=none.
- last_meaningful_divergence must be copied from the selected divergence_audit row. Never relabel or promote it to another timeframe.
- ACTIVE TRADE TIMEFRAME LOCK: First fill active_trade_audit for tf_4h, tf_1h, tf_15m, tf_5m, tf_3m independently.
- Each active_trade_audit row must judge only that timeframe's own setup origin. Do not use 15m Type 1 to declare 1H Type 1. Do not use 5m carry to declare 5m Type 1 unless 5m itself has its own legal setup.
- selected_active_trade_tf must identify the TRUE ORIGIN timeframe of the current active meaningful trade, not the timeframe currently carrying it and not the higher timeframe containing it.
- If 15m divergence/rejection created the trade and 5m is carrying it, selected_active_trade_tf=tf_15m and carry.timeframe=5m.
- If 1H structure only contains the move but did not itself form same-timeframe A-B-C + impulse or Type 3 acceptance, the active trade must not be labeled 1H.
- trade_classification must be copied from selected_active_trade_tf only. Never relabel or promote the same trade to another timeframe.
- current_move.timeframe must equal the selected active trade origin timeframe when active_trade_audit selected_active_trade_tf is not none. carry.timeframe must remain the lower carrying timeframe.
- MULTI-LEVEL SAME-STORY RULE: If two or more timeframes independently show same-direction official setups, do not treat it as drift; label multi_level_story.active=YES.
- Multi-level confirmation is valid only if each listed timeframe independently has its own same-timeframe A-B-C, energy weakening, and impulse.
- If only the lower timeframe is official and the higher timeframe only looks weak, set higher_tf_status=WEAKENING_CONTEXT_ONLY and do not promote the higher timeframe to official.
- Always separate: controlling_origin = highest official timeframe still structurally active; active_execution_trade = most recent legal executable setup currently being managed; carrying_timeframe = lower timeframe managing the active execution trade.
- Example: if 1H and 15m are both official bearish, output controlling_origin=1H Bearish Type 1, active_execution_trade=15m Bearish Type 1 if 15m gave the latest executable entry, carrying_timeframe=5m DOWN.
- Example: if only 15m is official and 1H only contains/weakens, output multi_level_story.active=NO or higher_tf_status=WEAKENING_CONTEXT_ONLY; active trade remains 15m, not 1H.
- Divergence requires same-timeframe A-B-C: A first directional move, B real reset/pullback/range, C second same-direction test.
- No A-B-C on that exact timeframe = no official divergence on that timeframe.
- Segment B should ideally reset Vel near zero. If not, downgrade divergence.
- Segment C must retest or break the prior extreme and show weaker energy than A.
- VAcc confirmation can be Vel, Acc, Acc-area, Multi, Structural-only, or None.
- Divergence without impulse is warning only, not a confirmed trade.
- Supply/demand zones are location references only. They cannot create BUY/SELL/CLOSE/FLIP by themselves.
- A zone becomes tradable only if structure confirms there through divergence/restart/rejection/reclaim/breakout plus impulse/acceptance and carry.
- If 1H or higher range is active and price is in MID, fresh BUY/SELL must be WAIT.
- A valid fresh BUY/SELL requires Type 1, Type 2, or Type 3 logic and Fresh/Active carry.
- If carry is already EXHAUSTING, do not output fresh BUY/SELL.
- HOLD is different from fresh entry. No fresh entry does not mean close.
- CLOSE requires opposite divergence + opposite impulse on the carrying timeframe.
- CLOSE AND FLIP requires close conditions plus new opposite authority and structural room.
- If any critical layer is unclear, final_action must be WAIT.

OHLCV rows are Binance futures klines:
[open_time, open, high, low, close, volume, close_time, quote_asset_volume,
 number_of_trades, taker_buy_base_volume, taker_buy_quote_volume, ignore]
open_time and close_time are milliseconds since Unix epoch.
""".strip()


# =========================
# NORMALIZATION / GUARDS
# =========================
def normalize_enum(value: Any, allowed: set[str], default: str) -> str:
    v = text(value, default).upper().replace("-", "_").replace(" ", " ")
    return v if v in allowed else default


def default_divergence_row(tf_label: str) -> dict[str, Any]:
    return {
        "exists": "NO",
        "timeframe": tf_label,
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
        "summary": f"No official {tf_label} divergence confirmed.",
    }


def normalize_divergence_row(value: Any, tf_label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}
    row = default_divergence_row(tf_label)
    row.update(value)
    row["timeframe"] = tf_label

    # Strict official divergence lock: official divergence requires same-TF A-B-C and same-TF impulse.
    if not (
        text(row.get("exists")).upper() == "YES"
        and text(row.get("abc_valid")).upper() == "YES"
        and text(row.get("impulse_confirmed")).upper() == "YES"
    ):
        row["exists"] = "NO"
        if text(row.get("grade")).upper() in {"ELITE", "STRONG"}:
            row["grade"] = "MODERATE" if text(row.get("abc_valid")).upper() == "YES" else "INVALID"
    return row


def is_official_divergence(row: dict[str, Any]) -> bool:
    return (
        text(row.get("exists")).upper() == "YES"
        and text(row.get("abc_valid")).upper() == "YES"
        and text(row.get("impulse_confirmed")).upper() == "YES"
        and text(row.get("direction")).upper() in {"BULLISH", "BEARISH"}
    )


def normalize_divergence_audit(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}

    audit: dict[str, Any] = {}
    for key in TF_AUDIT_KEYS:
        audit[key] = normalize_divergence_row(value.get(key), TF_KEY_TO_LABEL[key])

    selected = text(value.get("selected_last_meaningful_tf"), "none").lower()
    if selected not in {*TF_AUDIT_KEYS, "none"}:
        selected = "none"
    audit["selected_last_meaningful_tf"] = selected
    audit["selection_reason"] = text(value.get("selection_reason"), "No official divergence selected.")
    return audit


def no_meaningful_divergence() -> dict[str, Any]:
    row = default_divergence_row("N/A")
    row["summary"] = "No official timeframe-owned divergence selected from the divergence audit."
    return row


def select_locked_last_divergence(audit: dict[str, Any]) -> dict[str, Any]:
    selected = text(audit.get("selected_last_meaningful_tf"), "none").lower()
    if selected in TF_AUDIT_KEYS and is_official_divergence(audit[selected]):
        return dict(audit[selected])

    # Conservative fallback: if the model selected a non-official row, do not relabel another timeframe.
    # This prevents 1H/15m drift between runs.
    return no_meaningful_divergence()


def divergence_audit_summary(audit: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in TF_AUDIT_KEYS:
        row = audit.get(key, {})
        label = TF_KEY_TO_LABEL[key]
        if is_official_divergence(row):
            parts.append(f"{label}:{text(row.get('direction')).title()}✓")
        elif text(row.get("abc_valid")).upper() == "YES":
            parts.append(f"{label}:ABC only")
        else:
            parts.append(f"{label}:No")
    return " | ".join(parts)


def default_active_trade_row(tf_label: str) -> dict[str, Any]:
    return {
        "exists": "NO",
        "origin_timeframe": tf_label,
        "direction": "NONE",
        "setup_type": "NONE",
        "type_label": "NONE",
        "trade_function": "NONE",
        "origin_price_zone": "N/A",
        "confirmation_price": "N/A",
        "confirmation_time_utc": "N/A",
        "earliest_legal_trigger_price": "N/A",
        "carry_timeframe": "N/A",
        "carry_direction": "UNCLEAR",
        "carry_state": "UNCLEAR",
        "fresh_entry_valid": "NO",
        "existing_hold_valid": "NO",
        "too_late_to_chase": "UNCLEAR",
        "invalidation": "N/A",
        "current_status": "NONE",
        "selection_reason": f"No official {tf_label} active trade origin confirmed.",
        "summary": f"No active trade origin confirmed on {tf_label}.",
    }


def normalize_active_trade_row(value: Any, tf_label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}
    row = default_active_trade_row(tf_label)
    row.update(value)
    row["origin_timeframe"] = tf_label

    # A row can only be active if it identifies an actual same-timeframe origin setup.
    # This prevents a carrying TF or containing TF from being reported as the trade origin.
    if text(row.get("exists")).upper() != "YES" or text(row.get("setup_type")).upper() == "NONE":
        row["exists"] = "NO"
        row["type_label"] = "NONE"
        row["trade_function"] = "NONE"
    else:
        direction_word = "Bullish" if text(row.get("direction")).upper() == "BULLISH" else "Bearish"
        setup_word = text(row.get("setup_type")).upper().replace("TYPE_", "Type ")
        # Force label to audited origin timeframe. This blocks labels like 1H Type 1 inside tf_15m row.
        row["type_label"] = f"{tf_label} {direction_word} {setup_word}"
    return row


def is_active_trade_row(row: dict[str, Any]) -> bool:
    return (
        text(row.get("exists")).upper() == "YES"
        and text(row.get("setup_type")).upper() in {"TYPE_1", "TYPE_2", "TYPE_3"}
        and text(row.get("direction")).upper() in {"BULLISH", "BEARISH"}
    )


def normalize_active_trade_audit(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}
    audit: dict[str, Any] = {}
    for key in TF_AUDIT_KEYS:
        audit[key] = normalize_active_trade_row(value.get(key), TF_KEY_TO_LABEL[key])

    selected = text(value.get("selected_active_trade_tf"), "none").lower()
    if selected not in {*TF_AUDIT_KEYS, "none"}:
        selected = "none"
    audit["selected_active_trade_tf"] = selected
    audit["selection_reason"] = text(value.get("selection_reason"), "No active trade selected.")
    return audit


def no_active_trade_classification() -> dict[str, Any]:
    return {
        "active_trade_exists": "NO",
        "type_label": "NONE",
        "trade_function": "NONE",
        "fresh_entry_valid": "NO",
        "existing_hold_valid": "NO",
        "too_late_to_chase": "UNCLEAR",
        "earliest_legal_trigger_price": "N/A",
        "invalidation": "N/A",
        "summary": "No timeframe-owned active meaningful trade selected from the active trade audit.",
    }


def trade_classification_from_active_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "active_trade_exists": "YES",
        "type_label": text(row.get("type_label"), "NONE"),
        "trade_function": text(row.get("trade_function"), "NONE"),
        "fresh_entry_valid": text(row.get("fresh_entry_valid"), "NO"),
        "existing_hold_valid": text(row.get("existing_hold_valid"), "UNCLEAR"),
        "too_late_to_chase": text(row.get("too_late_to_chase"), "UNCLEAR"),
        "earliest_legal_trigger_price": text(row.get("earliest_legal_trigger_price"), "N/A"),
        "invalidation": text(row.get("invalidation"), "N/A"),
        "summary": text(row.get("summary"), "Active trade selected from audit."),
    }


def select_locked_active_trade(audit: dict[str, Any]) -> dict[str, Any]:
    selected = text(audit.get("selected_active_trade_tf"), "none").lower()
    if selected in TF_AUDIT_KEYS and is_active_trade_row(audit[selected]):
        return dict(audit[selected])

    # Conservative fallback: do not choose another TF automatically.
    # This prevents 1H/15m active trade drift between runs.
    return default_active_trade_row("N/A")


def selected_active_trade_key(audit: dict[str, Any]) -> str | None:
    selected = text(audit.get("selected_active_trade_tf"), "none").lower()
    if selected in TF_AUDIT_KEYS and is_active_trade_row(audit[selected]):
        return selected
    return None


def active_trade_carry_state(active_trade: dict[str, Any], carry: dict[str, Any]) -> str:
    row_state = text(active_trade.get("carry_state"), "UNCLEAR").upper()
    if row_state != "UNCLEAR":
        return row_state
    return text(carry.get("state"), "UNCLEAR").upper()


def active_trade_has_same_tf_type1_divergence(
    active_trade: dict[str, Any],
    active_trade_key: str | None,
    divergence_audit: dict[str, Any],
) -> bool:
    if text(active_trade.get("setup_type")).upper() != "TYPE_1":
        return True
    if active_trade_key not in TF_AUDIT_KEYS:
        return False

    div_row = divergence_audit.get(active_trade_key, {})
    return (
        is_official_divergence(div_row)
        and text(div_row.get("direction")).upper() == text(active_trade.get("direction")).upper()
    )


def active_trade_audit_summary(audit: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in TF_AUDIT_KEYS:
        row = audit.get(key, {})
        label = TF_KEY_TO_LABEL[key]
        if is_active_trade_row(row):
            setup = text(row.get("setup_type")).replace("TYPE_", "T")
            direction = text(row.get("direction")).title()
            parts.append(f"{label}:{direction} {setup}✓")
        else:
            parts.append(f"{label}:No")
    return " | ".join(parts)



def official_divergence_timeframes_by_direction(audit: dict[str, Any]) -> dict[str, list[str]]:
    out = {"BULLISH": [], "BEARISH": []}
    for key in TF_AUDIT_KEYS:
        row = audit.get(key, {})
        direction = text(row.get("direction")).upper()
        if is_official_divergence(row) and direction in out:
            out[direction].append(key)
    return out


def normalize_multi_level_story(
    value: Any,
    divergence_audit: dict[str, Any],
    active_trade_audit: dict[str, Any],
    selected_active_trade: dict[str, Any],
    carry: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}

    official_by_dir = official_divergence_timeframes_by_direction(divergence_audit)

    # Prefer active trade direction, then selected divergence direction, then model-provided direction.
    active_direction = text(selected_active_trade.get("direction"), "NONE").upper()
    if active_direction not in {"BULLISH", "BEARISH"}:
        selected_div_tf = text(divergence_audit.get("selected_last_meaningful_tf"), "none").lower()
        if selected_div_tf in TF_AUDIT_KEYS:
            active_direction = text(divergence_audit[selected_div_tf].get("direction"), "NONE").upper()
    if active_direction not in {"BULLISH", "BEARISH"}:
        active_direction = text(value.get("direction"), "NONE").upper()
    if active_direction not in {"BULLISH", "BEARISH"}:
        active_direction = "NONE"

    official_keys = official_by_dir.get(active_direction, []) if active_direction in {"BULLISH", "BEARISH"} else []
    confirmed_labels = [TF_KEY_TO_LABEL[k] for k in official_keys]

    # Highest official timeframe comes first because TF_AUDIT_KEYS is ordered high -> low.
    controlling_origin = "N/A"
    higher_tf_status = "NONE"
    if official_keys:
        top_key = official_keys[0]
        top_row = divergence_audit[top_key]
        controlling_origin = f"{TF_KEY_TO_LABEL[top_key]} {text(top_row.get('direction')).title()} Type 1"
        higher_tf_status = "OFFICIAL"

    selected_trade_label = text(selected_active_trade.get("type_label"), "N/A") if is_active_trade_row(selected_active_trade) else "N/A"
    carry_tf = text(selected_active_trade.get("carry_timeframe"), text(carry.get("timeframe"), "N/A"))
    carry_dir = text(selected_active_trade.get("carry_direction"), text(carry.get("direction"), "UNCLEAR"))
    carrying_timeframe = f"{carry_tf} {carry_dir}".strip()

    supported_multi = len(official_keys) >= 2

    # If the model claimed multi-level but audit does not support it, downgrade to context-only/none.
    if supported_multi:
        active = "YES"
        direction = active_direction
        explanation = text(
            value.get("explanation"),
            f"Multi-level {direction.lower()} confirmation: {', '.join(confirmed_labels)} are official; controlling origin is {controlling_origin}, active execution trade is {selected_trade_label}, and carry is {carrying_timeframe}.",
        )
    else:
        active = "NO"
        direction = active_direction if active_direction in {"BULLISH", "BEARISH"} else "NONE"
        # Higher timeframe can be weakening context only when only one lower TF is official and model says there is HTF context.
        model_status = text(value.get("higher_tf_status"), "NONE").upper()
        higher_tf_status = "WEAKENING_CONTEXT_ONLY" if model_status == "WEAKENING_CONTEXT_ONLY" else higher_tf_status
        if not official_keys:
            higher_tf_status = "NONE"
        explanation = text(
            value.get("explanation"),
            "No audited multi-level same-direction confirmation. Do not promote lower timeframe structure to higher timeframe.",
        )

    return {
        "active": active,
        "direction": direction,
        "confirmed_timeframes": confirmed_labels,
        "controlling_origin": controlling_origin,
        "active_execution_trade": selected_trade_label,
        "carrying_timeframe": carrying_timeframe,
        "higher_tf_status": higher_tf_status,
        "explanation": explanation,
    }


def multi_level_line(story: dict[str, Any]) -> str:
    frames = "+".join(story.get("confirmed_timeframes", [])) or "None"
    return (
        f"{text(story.get('active'), 'NO')} | {text(story.get('direction'), 'NONE')} | TFs: {frames} | "
        f"Control: {text(story.get('controlling_origin'))} | Exec: {text(story.get('active_execution_trade'))} | Carry: {text(story.get('carrying_timeframe'))}"
    )

def first_zone_by_type(zones: list[dict[str, Any]], zone_type: str) -> str:
    for z in zones:
        if text(z.get("type")).upper() == zone_type:
            tf = text(z.get("timeframe"))
            band = text(z.get("price_band"))
            strength = text(z.get("strength"))
            role = text(z.get("role"))
            status = text(z.get("status"))
            return f"{tf} {zone_type.title()} {band} | {strength.title()} | {role} | {status.title()}"
    return "N/A"


def normalize_analysis(result: dict[str, Any], symbol: str, ts_utc: str, current_price: float | None) -> dict[str, Any]:
    """Fill defensive defaults and apply hard action guards before Telegram formatting."""
    if not isinstance(result, dict):
        result = {}

    result["symbol"] = symbol
    result["timestamp"] = ts_utc
    result["current_price"] = format_price(current_price)

    result.setdefault("final_action", "WAIT")
    result.setdefault("management_state", "NONE")
    result.setdefault("signal_side", "NONE")

    result.setdefault("parent_move", {})
    result["parent_move"].setdefault("timeframe", "N/A")
    result["parent_move"].setdefault("direction", "UNCLEAR")
    result["parent_move"].setdefault("state", "UNCLEAR")
    result["parent_move"].setdefault("still_active", "UNCLEAR")
    result["parent_move"].setdefault("summary", "Parent move unclear.")

    result.setdefault("current_move", {})
    result["current_move"].setdefault("timeframe", "N/A")
    result["current_move"].setdefault("direction", "UNCLEAR")
    result["current_move"].setdefault("origin_type", "UNCLEAR")
    result["current_move"].setdefault("origin_price_zone", "N/A")
    result["current_move"].setdefault("confirmed_at_price", "N/A")
    result["current_move"].setdefault("with_or_against_parent", "UNCLEAR")
    result["current_move"].setdefault("summary", "Current move unclear.")

    # Normalize the per-timeframe divergence audit first, then lock last_meaningful_divergence
    # to the selected audited timeframe row only. This prevents timeframe drift such as
    # 1H bearish divergence in one run becoming 15m bearish divergence in the next.
    result["divergence_audit"] = normalize_divergence_audit(result.get("divergence_audit"))
    result["last_meaningful_divergence"] = select_locked_last_divergence(result["divergence_audit"])
    div = result["last_meaningful_divergence"]

    result.setdefault("carry", {})
    carry = result["carry"]
    carry.setdefault("timeframe", "N/A")
    carry.setdefault("direction", "UNCLEAR")
    carry.setdefault("state", "UNCLEAR")
    carry.setdefault("cycle_complete", "UNCLEAR")
    carry.setdefault("opposite_divergence", "UNCLEAR")
    carry.setdefault("opposite_impulse", "UNCLEAR")
    carry.setdefault("finished", "UNCLEAR")
    carry.setdefault("summary", "Carry unclear.")

    result.setdefault("range_state", {})
    rng = result["range_state"]
    rng.setdefault("active", "UNCLEAR")
    rng.setdefault("timeframe", "N/A")
    rng.setdefault("upper_edge", "N/A")
    rng.setdefault("lower_edge", "N/A")
    rng.setdefault("midpoint", "N/A")
    rng.setdefault("price_location", "UNCLEAR")
    rng.setdefault("parent_ownership", "UNCLEAR")
    rng.setdefault("status", "UNCLEAR")
    rng.setdefault("summary", "Range state unclear.")

    if not isinstance(result.get("zones"), list):
        result["zones"] = []

    # Normalize active trade audit and lock trade_classification to selected origin timeframe.
    # Active trade TF = setup origin timeframe. Carry TF remains separate.
    result["active_trade_audit"] = normalize_active_trade_audit(result.get("active_trade_audit"))
    active_trade_key = selected_active_trade_key(result["active_trade_audit"])
    active_trade = select_locked_active_trade(result["active_trade_audit"])
    if is_active_trade_row(active_trade):
        result["trade_classification"] = trade_classification_from_active_row(active_trade)

        # Lock current move to the active trade origin to prevent 1H/15m drift.
        result["current_move"]["timeframe"] = text(active_trade.get("origin_timeframe"), result["current_move"].get("timeframe"))
        result["current_move"]["direction"] = "UP" if text(active_trade.get("direction")).upper() == "BULLISH" else "DOWN"
        result["current_move"]["origin_price_zone"] = text(active_trade.get("origin_price_zone"), result["current_move"].get("origin_price_zone"))
        result["current_move"]["confirmed_at_price"] = text(active_trade.get("confirmation_price"), result["current_move"].get("confirmed_at_price"))
        setup = text(active_trade.get("setup_type")).upper()
        if setup == "TYPE_1":
            result["current_move"]["origin_type"] = "DIVERGENCE"
        elif setup == "TYPE_2":
            result["current_move"]["origin_type"] = "PULLBACK_RESTART"
        elif setup == "TYPE_3":
            result["current_move"]["origin_type"] = "BREAKOUT"
    else:
        result["trade_classification"] = no_active_trade_classification()

    result["multi_level_story"] = normalize_multi_level_story(
        result.get("multi_level_story"),
        result["divergence_audit"],
        result["active_trade_audit"],
        active_trade,
        carry,
    )

    tc = result["trade_classification"]

    result.setdefault("position_management", {})
    pm = result["position_management"]
    pm.setdefault("if_already_in", "NONE")
    pm.setdefault("if_not_in", "WAIT")
    pm.setdefault("stop_action", "NONE")
    pm.setdefault("profit_action", "NONE")
    pm.setdefault("runner_logic", "NONE")
    pm.setdefault("summary", "No position management action confirmed.")

    result.setdefault("what_to_watch_next", {})
    nxt = result["what_to_watch_next"]
    nxt.setdefault("bullish_confirmation_needed", "N/A")
    nxt.setdefault("bearish_confirmation_needed", "N/A")
    nxt.setdefault("key_demand_zone", first_zone_by_type(result["zones"], "DEMAND"))
    nxt.setdefault("key_supply_zone", first_zone_by_type(result["zones"], "SUPPLY"))
    nxt.setdefault("key_range_zone", "N/A")
    nxt.setdefault("next_structural_event", "Wait for confirmed structure.")

    result.setdefault("one_line_reason", "WAIT because structure is not sufficiently proven.")
    result.setdefault("current_move_summary", "Current move is unclear. If already in position, manage only after carry confirms. If not in position, wait for valid structure.")

    # Hard guard A: range midpoint blocks fresh BUY/SELL and flip.
    if (
        text(rng.get("active")).upper() == "YES"
        and text(rng.get("price_location")).upper() == "MID"
        and result.get("final_action") in {"BUY", "SELL", "CLOSE AND FLIP"}
    ):
        result["final_action"] = "WAIT"
        result["management_state"] = "NONE"
        pm["if_not_in"] = "WAIT"
        result["one_line_reason"] = "WAIT because price is inside active higher-timeframe range midpoint; fresh directional action is invalid."

    # Hard guard B: fresh BUY/SELL requires a locked active trade, fresh-entry permission, and Fresh/Active carry.
    if result.get("final_action") in {"BUY", "SELL"}:
        carry_state = active_trade_carry_state(active_trade, carry)
        if text(tc.get("active_trade_exists")).upper() != "YES":
            result["final_action"] = "WAIT"
            result["management_state"] = "NONE"
            pm["if_not_in"] = "WAIT"
            result["one_line_reason"] = "WAIT because fresh entry requires a timeframe-owned active trade origin."
        elif text(tc.get("fresh_entry_valid")).upper() != "YES":
            result["final_action"] = "WAIT"
            result["management_state"] = "NONE"
            pm["if_not_in"] = "WAIT"
            result["one_line_reason"] = "WAIT because the selected active trade is not marked valid for fresh entry."
        elif carry_state not in {"FRESH", "ACTIVE"}:
            result["final_action"] = "WAIT"
            result["management_state"] = "NONE"
            pm["if_not_in"] = "WAIT"
            result["one_line_reason"] = "WAIT because fresh entry requires Fresh or Active carry."

    # Hard guard C: exhausting carry blocks fresh BUY/SELL even if the selected row omitted carry_state.
    if text(carry.get("state")).upper() == "EXHAUSTING" and result.get("final_action") in {"BUY", "SELL"}:
        result["final_action"] = "WAIT"
        result["management_state"] = "NONE"
        pm["if_not_in"] = "WAIT"
        result["one_line_reason"] = "WAIT because carry is already exhausting; fresh entry is invalid."

    # Hard guard D: Type 1 fresh entry must have same-timeframe official divergence.
    if result.get("final_action") in {"BUY", "SELL"} and "TYPE 1" in text(tc.get("type_label")).upper():
        if not active_trade_has_same_tf_type1_divergence(active_trade, active_trade_key, result["divergence_audit"]):
            result["final_action"] = "WAIT"
            result["management_state"] = "NONE"
            pm["if_not_in"] = "WAIT"
            result["one_line_reason"] = "WAIT because Type 1 requires official same-timeframe A-B-C divergence plus confirmed impulse."

    # Hard guard E: HOLD requires a locked active trade origin.
    if result.get("final_action") in {"HOLD LONG", "HOLD SHORT"} and text(tc.get("active_trade_exists")).upper() != "YES":
        result["final_action"] = "WAIT"
        result["management_state"] = "NONE"
        pm["if_already_in"] = "NONE"
        pm["if_not_in"] = "WAIT"
        result["one_line_reason"] = "WAIT because no timeframe-owned active trade origin was selected from the active trade audit."


    # Hard guard F: multi-level active story requires at least two independently official same-direction divergence rows.
    ml_story = result.get("multi_level_story", {})
    if text(ml_story.get("active")).upper() == "YES" and len(ml_story.get("confirmed_timeframes", [])) < 2:
        ml_story["active"] = "NO"
        ml_story["explanation"] = "Multi-level story downgraded because fewer than two same-direction official timeframe audits were confirmed."

    return result


# =========================
# OPENAI ANALYSIS
# =========================
def analyze_symbol(symbol: str, framework: str, market_data: dict[str, Any]) -> dict[str, Any]:
    ts_utc = utc_now_iso()
    current_price = derive_current_price(market_data)
    prompt_payload = build_prompt_payload(market_data)
    prompt = build_prompt(symbol, framework, prompt_payload, ts_utc, current_price)

    response = client.responses.create(
        model=MODEL,
        reasoning={"effort": REASONING_EFFORT},
        instructions=(
            "You are the OCEAN × Natural Chanlun AI market-reading engine. "
            "Use only the supplied OHLCV and runtime constitution. Ignore previous chats. "
            "Never predict. Read structure first, energy second, zone third, signal last. "
            "Apply strict divergence timeframe ownership: fill divergence_audit independently for each timeframe, "
            "and make last_meaningful_divergence a copy of selected_last_meaningful_tf only. "
            "Apply strict active-trade timeframe ownership: fill active_trade_audit independently, "
            "select the true origin timeframe, and make trade_classification/current_move follow that selected origin. "
            "Never promote 15m divergence/trade into 1H or 5m carry into a 5m origin trade. "
            "If two timeframes independently confirm the same directional story, fill multi_level_story and separate controlling origin, active execution trade, and carrying timeframe. "
            "If the higher timeframe only contains lower-timeframe structure, mark it as weakening context only, not official. "
            "Return only valid JSON matching the schema."
        ),
        text={
            "format": {
                "type": "json_schema",
                "name": "ocean_chanlun_telegram_v1_4",
                "strict": True,
                "schema": analysis_schema(),
            }
        },
        input=prompt,
    )

    parsed = json.loads(response.output_text)
    return normalize_analysis(parsed, symbol, ts_utc, current_price)


def save_analysis(symbol: str, result: dict[str, Any]) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts_safe = result["timestamp"].replace(":", "-")
    out_path = RESULTS_DIR / f"{symbol}_{ts_safe}.json"
    save_json(out_path, result)
    save_json(RESULTS_DIR / f"{symbol}_latest.json", result)
    return out_path


# =========================
# TELEGRAM FORMATTERS
# =========================
def zone_text(result: dict[str, Any], zone_type: str) -> str:
    return first_zone_by_type(result.get("zones", []), zone_type)


def format_compact_telegram(result: dict[str, Any]) -> str:
    parent = result["parent_move"]
    current = result["current_move"]
    div = result["last_meaningful_divergence"]
    carry = result["carry"]
    rng = result["range_state"]
    ml = result.get("multi_level_story", {})
    tc = result["trade_classification"]
    pm = result["position_management"]
    nxt = result["what_to_watch_next"]

    lines = [
        f"🌊 OCEAN SIGNAL | {text(result.get('symbol'))}",
        f"Price: {text(result.get('current_price'))}",
        f"Time: {text(result.get('timestamp'))}",
        "",
        f"ACTION: {text(result.get('final_action'), 'WAIT')}",
        f"Management: {text(result.get('management_state'), 'NONE')}",
        "",
        f"Parent: {text(parent.get('timeframe'))} {text(parent.get('direction'))} | {text(parent.get('state'))}",
        f"Current: {text(current.get('timeframe'))} {text(current.get('direction'))}",
        f"Origin: {text(current.get('origin_type'))} @ {text(current.get('origin_price_zone'))}",
        f"Multi-Level: {multi_level_line(ml)}",
        "",
        f"Divergence: {text(div.get('timeframe'))} {text(div.get('direction'))}",
        f"Audit: {divergence_audit_summary(result.get('divergence_audit', {}))}",
        f"ABC: {text(div.get('abc_valid'))} | VAcc: {text(div.get('vacc_confirmation'))} | Impulse: {text(div.get('impulse_confirmed'))}",
        f"Grade: {text(div.get('grade'))} | Role: {text(div.get('role'))}",
        "",
        f"Carry: {text(carry.get('timeframe'))} {text(carry.get('direction'))} | {text(carry.get('state'))}",
        f"Carry Finished: {text(carry.get('finished'))}",
        f"Opp Div+Impulse: {text(carry.get('opposite_divergence'))}/{text(carry.get('opposite_impulse'))}",
        "",
        f"Range: {text(rng.get('active'))} | {text(rng.get('timeframe'))} | {text(rng.get('price_location'))}",
        f"Upper/Mid/Lower: {text(rng.get('upper_edge'))} / {text(rng.get('midpoint'))} / {text(rng.get('lower_edge'))}",
        f"Demand: {zone_text(result, 'DEMAND')}",
        f"Supply: {zone_text(result, 'SUPPLY')}",
        "",
        f"Active Trade: {text(tc.get('type_label'))}",
        f"Trade Audit: {active_trade_audit_summary(result.get('active_trade_audit', {}))}",
        f"Function: {text(tc.get('trade_function'))}",
        f"Trigger: {text(tc.get('earliest_legal_trigger_price'))}",
        f"Invalidation: {text(tc.get('invalidation'))}",
        "",
        f"Already In: {text(pm.get('if_already_in'))}",
        f"Not In: {text(pm.get('if_not_in'))}",
        f"Stop: {text(pm.get('stop_action'))} | Profit: {text(pm.get('profit_action'))} | Runner: {text(pm.get('runner_logic'))}",
        "",
        f"Next: {text(nxt.get('next_structural_event'))}",
        "",
        f"Reason: {text(result.get('one_line_reason'))}",
    ]
    return "\n".join(lines)


def format_full_telegram(result: dict[str, Any]) -> str:
    parent = result["parent_move"]
    current = result["current_move"]
    div = result["last_meaningful_divergence"]
    carry = result["carry"]
    rng = result["range_state"]
    ml = result.get("multi_level_story", {})
    tc = result["trade_classification"]
    pm = result["position_management"]
    nxt = result["what_to_watch_next"]

    zone_lines = []
    if result.get("zones"):
        for z in result["zones"][:5]:
            zone_lines.append(
                f"• {text(z.get('timeframe'))} {text(z.get('type'))}: {text(z.get('price_band'))} | "
                f"{text(z.get('strength'))} | {text(z.get('alignment'))} | {text(z.get('role'))} | {text(z.get('status'))}"
            )
    else:
        zone_lines.append("• No strong nearby supply/demand zone.")

    lines = [
        f"🌊 OCEAN × CHANLUN SIGNAL",
        f"Symbol: {text(result.get('symbol'))}",
        f"Price: {text(result.get('current_price'))}",
        f"Time: {text(result.get('timestamp'))}",
        "",
        "━━━━━━━━━━━━━━",
        "FINAL ACTION",
        f"Signal: {text(result.get('final_action'))}",
        f"Management: {text(result.get('management_state'))}",
        f"Reason: {text(result.get('one_line_reason'))}",
        "",
        "━━━━━━━━━━━━━━",
        "MARKET STORY",
        f"Parent: {text(parent.get('timeframe'))} {text(parent.get('direction'))} | {text(parent.get('state'))}",
        f"Parent active: {text(parent.get('still_active'))}",
        f"Current Move: {text(current.get('timeframe'))} {text(current.get('direction'))}",
        f"Origin: {text(current.get('origin_type'))} @ {text(current.get('origin_price_zone'))}",
        f"Confirmed at: {text(current.get('confirmed_at_price'))}",
        text(current.get("summary")),
        "",
        "━━━━━━━━━━━━━━",
        "DIVERGENCE",
        f"Last Meaningful: {text(div.get('timeframe'))} {text(div.get('direction'))}",
        f"TF Audit: {divergence_audit_summary(result.get('divergence_audit', {}))}",
        f"Selected TF: {text(result.get('divergence_audit', {}).get('selected_last_meaningful_tf', 'none'))}",
        f"Selection: {text(result.get('divergence_audit', {}).get('selection_reason', 'N/A'))}",
        f"A-B-C: {text(div.get('abc_valid'))}",
        f"B Reset: {text(div.get('segment_b_reset_valid'))}",
        f"C Complete: {text(div.get('segment_c_completed'))}",
        f"Retest/New Extreme: {text(div.get('new_high_low_or_retest'))}",
        f"VAcc: {text(div.get('vacc_confirmation'))}",
        f"Impulse: {text(div.get('impulse_confirmed'))}",
        f"Grade: {text(div.get('grade'))}",
        f"Role: {text(div.get('role'))}",
        "",
        "━━━━━━━━━━━━━━",
        "CARRY",
        f"Carry TF: {text(carry.get('timeframe'))}",
        f"Direction: {text(carry.get('direction'))}",
        f"State: {text(carry.get('state'))}",
        f"Cycle Complete: {text(carry.get('cycle_complete'))}",
        f"Opposite Div+Impulse: {text(carry.get('opposite_divergence'))} / {text(carry.get('opposite_impulse'))}",
        f"Finished: {text(carry.get('finished'))}",
        "",
        "━━━━━━━━━━━━━━",
        "RANGE / LOCATION",
        f"Range Active: {text(rng.get('active'))}",
        f"Range TF: {text(rng.get('timeframe'))}",
        f"Location: {text(rng.get('price_location'))}",
        f"Upper: {text(rng.get('upper_edge'))}",
        f"Mid: {text(rng.get('midpoint'))}",
        f"Lower: {text(rng.get('lower_edge'))}",
        f"Ownership: {text(rng.get('parent_ownership'))}",
        "",
        "━━━━━━━━━━━━━━",
        "SUPPLY / DEMAND",
        *zone_lines,
        "",
        "━━━━━━━━━━━━━━",
        "MULTI-LEVEL STORY",
        f"Active: {text(result.get('multi_level_story', {}).get('active'))}",
        f"Direction: {text(result.get('multi_level_story', {}).get('direction'))}",
        f"Confirmed TFs: {', '.join(result.get('multi_level_story', {}).get('confirmed_timeframes', [])) or 'None'}",
        f"Controlling Origin: {text(result.get('multi_level_story', {}).get('controlling_origin'))}",
        f"Active Execution Trade: {text(result.get('multi_level_story', {}).get('active_execution_trade'))}",
        f"Carrying Timeframe: {text(result.get('multi_level_story', {}).get('carrying_timeframe'))}",
        f"Higher TF Status: {text(result.get('multi_level_story', {}).get('higher_tf_status'))}",
        f"Explanation: {text(result.get('multi_level_story', {}).get('explanation'))}",
        "",
        "━━━━━━━━━━━━━━",
        "ACTIVE TRADE",
        f"Exists: {text(tc.get('active_trade_exists'))}",
        f"TF Audit: {active_trade_audit_summary(result.get('active_trade_audit', {}))}",
        f"Selected TF: {text(result.get('active_trade_audit', {}).get('selected_active_trade_tf', 'none'))}",
        f"Selection: {text(result.get('active_trade_audit', {}).get('selection_reason', 'N/A'))}",
        f"Type: {text(tc.get('type_label'))}",
        f"Function: {text(tc.get('trade_function'))}",
        f"Fresh Entry: {text(tc.get('fresh_entry_valid'))}",
        f"Valid Hold: {text(tc.get('existing_hold_valid'))}",
        f"Too Late: {text(tc.get('too_late_to_chase'))}",
        f"Trigger: {text(tc.get('earliest_legal_trigger_price'))}",
        f"Invalidation: {text(tc.get('invalidation'))}",
        "",
        "━━━━━━━━━━━━━━",
        "POSITION MANAGEMENT",
        f"If already in: {text(pm.get('if_already_in'))}",
        f"If not in: {text(pm.get('if_not_in'))}",
        f"Stop: {text(pm.get('stop_action'))}",
        f"Profit: {text(pm.get('profit_action'))}",
        f"Runner: {text(pm.get('runner_logic'))}",
        text(pm.get("summary")),
        "",
        "━━━━━━━━━━━━━━",
        "NEXT WATCH",
        f"Bullish need: {text(nxt.get('bullish_confirmation_needed'))}",
        f"Bearish need: {text(nxt.get('bearish_confirmation_needed'))}",
        f"Key Demand: {text(nxt.get('key_demand_zone'))}",
        f"Key Supply: {text(nxt.get('key_supply_zone'))}",
        f"Key Range: {text(nxt.get('key_range_zone'))}",
        f"Next event: {text(nxt.get('next_structural_event'))}",
        "",
        "━━━━━━━━━━━━━━",
        "SUMMARY",
        text(result.get("current_move_summary")),
    ]
    return "\n".join(lines)


def format_telegram_message(result: dict[str, Any]) -> str:
    if TELEGRAM_MODE == "full":
        return format_full_telegram(result)
    return format_compact_telegram(result)


# =========================
# TELEGRAM SEND
# =========================
def split_text_for_telegram(message: str, chunk_size: int = TELEGRAM_CHUNK_SIZE) -> list[str]:
    if len(message) <= chunk_size:
        return [message]

    chunks: list[str] = []
    current = ""
    for block in message.split("\n\n"):
        candidate = block if not current else current + "\n\n" + block
        if len(candidate) <= chunk_size:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = ""
        while len(block) > chunk_size:
            chunks.append(block[:chunk_size])
            block = block[chunk_size:]
        current = block
    if current:
        chunks.append(current)
    return chunks


def send_telegram_message(message: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    chunks = split_text_for_telegram(message)
    for idx, chunk in enumerate(chunks, start=1):
        payload_text = f"[{idx}/{len(chunks)}]\n{chunk}" if len(chunks) > 1 else chunk
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": payload_text,
            "disable_web_page_preview": True,
        }
        response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()


def seconds_until_next_half_hour() -> int:
    now = datetime.now()
    if now.minute < 30:
        next_run = now.replace(minute=30, second=0, microsecond=0)
    else:
        next_run = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    return max(1, int((next_run - now).total_seconds()))


# =========================
# RUNNER
# =========================
def run_once() -> None:
    framework = load_framework() if ANALYSIS_MODE == "openai" else ""

    for symbol in SYMBOLS:
        print(f"[{utc_now_iso()}] Fetching data for {symbol}...")
        raw_market_data = fetch_all_symbol_data(symbol)
        ts_utc = utc_now_iso()
        current_price = derive_current_price(raw_market_data)

        if ANALYSIS_MODE == "openai":
            print(f"[{utc_now_iso()}] Sending {symbol} to OpenAI...")
            result = analyze_symbol(symbol, framework, raw_market_data)
        else:
            print(f"[{utc_now_iso()}] Running local framework engine for {symbol}...")
            result = normalize_analysis(
                framework_engine.analyze(symbol, raw_market_data, ts_utc),
                symbol,
                ts_utc,
                current_price,
            )

        output_file = save_analysis(symbol, result)
        print(f"[{utc_now_iso()}] Saved analysis: {output_file}")

        message = format_telegram_message(result)
        print(message)
        if SEND_TELEGRAM:
            send_telegram_message(message)
            print(f"[{utc_now_iso()}] Telegram sent for {symbol}.")


def main() -> None:
    print("OCEAN × Natural Chanlun Telegram runner v1.5 started.")
    print(f"Symbols: {', '.join(SYMBOLS)}")
    print(f"Analysis mode: {ANALYSIS_MODE}")
    print(f"Telegram mode: {TELEGRAM_MODE}")
    print(f"Send Telegram: {'YES' if SEND_TELEGRAM else 'NO'}")
    print("Press Ctrl+C to stop.\n")

    if not RUN_EVERY_HALF_HOUR:
        run_once()
        return

    while True:
        try:
            run_once()
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            error_message = f"⚠️ OCEAN runner error:\n{type(exc).__name__}: {exc}"
            print(error_message)
            try:
                send_telegram_message(error_message)
            except Exception:
                pass

        wait_seconds = seconds_until_next_half_hour()
        print(f"[{utc_now_iso()}] Sleeping for {wait_seconds} seconds until next run...\n")
        time.sleep(wait_seconds)


if __name__ == "__main__":
    main()
