"""Single source-of-truth contract for Ocean x Natural Chanlun v1.2."""

from __future__ import annotations

MARKET_STATES = [
    "UP",
    "DOWN",
    "RANGE",
    "TRANSITION",
    "UNCLEAR",
]

FINAL_ACTIONS = [
    "BUY",
    "SELL",
    "HOLD LONG",
    "HOLD SHORT",
    "CLOSE LONG",
    "CLOSE SHORT",
    "CLOSE AND FLIP",
    "WAIT",
]

MOVE_ORIGINS = [
    "DIVERGENCE_ORIGIN",
    "BREAKOUT_ORIGIN",
    "RANGE_REJECTION_ORIGIN",
    "PULLBACK_RESTART_ORIGIN",
    "SUPPLY_DEMAND_REACTION_ORIGIN",
    "UNCLEAR",
]

DIVERGENCE_GRADES = [
    "ELITE",
    "STRONG",
    "MODERATE",
    "WEAK",
    "INVALID",
]

IMPULSE_GRADES = [
    "STRONG",
    "MODERATE",
    "WEAK",
    "INVALID",
    "NONE",
]

CARRY_STATES = [
    "FRESH",
    "ACTIVE",
    "MATURE",
    "EXHAUSTING",
    "UNCLEAR",
]

MANAGEMENT_STATES = [
    "HOLD",
    "HOLD_WITH_CAUTION",
    "CLOSE_WATCH",
    "FULL_CLOSE",
    "CLOSE_AND_FLIP",
    "NONE",
]

TYPE_LABELS = [
    "TYPE_1",
    "TYPE_2",
    "TYPE_3",
    "NONE",
]

TRADE_FUNCTIONS = [
    "HIGHER_LEVEL_DIVERGENCE_TRADE",
    "DECOMPOSITION_TRADE",
    "RANGE_REJECTION_TRADE",
    "BREAKOUT_TRADE",
    "PULLBACK_CONTINUATION_TRADE",
    "SUPPLY_DEMAND_REACTION_TRADE",
    "UPGRADE_TRADE",
    "NONE",
]

ZONE_TYPES = [
    "SUPPLY",
    "DEMAND",
    "NONE",
]

ZONE_STRENGTHS = [
    "STRONG",
    "MODERATE",
    "WEAK",
    "INVALID",
    "NONE",
]

ZONE_ALIGNMENTS = [
    "ALIGNED",
    "COUNTER",
    "NEUTRAL",
    "NONE",
]

ZONE_STATUSES = [
    "UNTESTED",
    "TESTED",
    "REACTING",
    "FAILED",
    "ACCEPTED_THROUGH",
    "NONE",
]

CARRY_MAP = {
    "4h": "1h",
    "1h": "15m",
    "15m": "5m",
    "5m": "3m",
    "4H": "1h",
    "1H": "15m",
    "15M": "5m",
    "5M": "3m",
    "3M": None,
    "3m": None,
}

REQUIRED_OUTPUT_SECTIONS = [
    "META",
    "HIGHER_TIMEFRAME_CONTEXT",
    "CURRENT_MOVE",
    "STRUCTURE_STATE",
    "DIVERGENCE_STATE",
    "LAST_MEANINGFUL_DIVERGENCE",
    "IMPULSE_ACCEPTANCE",
    "SUPPLY_DEMAND_ZONE_MAP",
    "CARRY_STATUS",
    "MULTI_LEVEL_STORY",
    "TRADE_CLASSIFICATION",
    "MANAGEMENT_STATE",
    "CURRENT_ACTIVE_MEANINGFUL_TRADE",
    "POSITION_MANAGEMENT_FOR_ACTIVE_TRADE",
    "MARKET_HIERARCHY",
    "WHAT_TO_WATCH_NEXT",
    "CURRENT_MOVE_SUMMARY",
    "FINAL_EXECUTION_BLOCK",
]

HARD_RULES = [
    "Do not predict.",
    "Use only supplied OHLCV.",
    "Start from highest timeframe.",
    "Structure before VAcc.",
    "Supply/demand after structure.",
    "No A-B-C = no divergence.",
    "No impulse = no trade confirmation.",
    "No clear carry = WAIT.",
    "Range midpoint = WAIT unless extremely clear.",
    "Divergence cannot be copied across timeframes.",
    "Multi-level divergence requires independent A-B-C on each level.",
    "Supply/demand cannot create trades alone.",
    "No fresh entry if carry is exhausting.",
    "Existing hold is different from fresh entry.",
    "Close only when carry shows opposite divergence + opposite impulse.",
    "Flip only when close conditions are met and opposite side has authority.",
    "Every Type label must include timeframe and direction.",
    "Final output must be one clear action only.",
    "Active trade timeframe must equal true setup origin timeframe.",
    "Carry timeframe must not be used as trade-origin timeframe.",
    "Higher timeframe controlling origin requires official same-timeframe A-B-C + impulse.",
    "If higher timeframe only contains lower-timeframe structure, label it as weakening context.",
]


def normalize_tf(tf: str) -> str:
    """Return lowercase normalized timeframe string."""

    text = str(tf or "").strip().lower()
    mapping = {
        "1d": "1d",
        "12h": "12h",
        "4h": "4h",
        "1h": "1h",
        "15m": "15m",
        "5m": "5m",
        "3m": "3m",
    }
    return mapping.get(text, text)


def expected_carry_tf(origin_tf: str) -> str | None:
    """Return expected carry timeframe from contract mapping."""

    if origin_tf in CARRY_MAP:
        return CARRY_MAP[origin_tf]
    normalized = normalize_tf(origin_tf)
    return CARRY_MAP.get(normalized)
