"""Enumerations for deterministic Ocean x Natural Chanlun decision flow."""

from __future__ import annotations

from enum import Enum


class Direction(str, Enum):
    """Primary directional assessment for price movement."""

    UP = "UP"
    DOWN = "DOWN"
    NONE = "NONE"
    UNCLEAR = "UNCLEAR"


class MarketState(str, Enum):
    """High-level market regime classification."""

    TREND = "TREND"
    RANGE = "RANGE"
    TRANSITION = "TRANSITION"
    UNCLEAR = "UNCLEAR"


class DivergenceDirection(str, Enum):
    """Directionality of divergence signal."""

    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NONE = "NONE"


class DivergenceGrade(str, Enum):
    """Confidence grading for divergence quality."""

    ELITE = "ELITE"
    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"
    INVALID = "INVALID"


class SetupType(str, Enum):
    """Canonical setup classes for active trade candidates."""

    TYPE_1 = "TYPE_1"
    TYPE_2 = "TYPE_2"
    TYPE_3 = "TYPE_3"
    NONE = "NONE"


class TradeFunction(str, Enum):
    """Narrative function assigned to a trade candidate."""

    HIGHER_LEVEL_DIVERGENCE_TRADE = "HIGHER_LEVEL_DIVERGENCE_TRADE"
    DECOMPOSITION_TRADE = "DECOMPOSITION_TRADE"
    RANGE_REJECTION_TRADE = "RANGE_REJECTION_TRADE"
    BREAKOUT_TRADE = "BREAKOUT_TRADE"
    SUPPLY_DEMAND_REACTION_TRADE = "SUPPLY_DEMAND_REACTION_TRADE"
    PULLBACK_CONTINUATION_TRADE = "PULLBACK_CONTINUATION_TRADE"
    UPGRADE_TRADE = "UPGRADE_TRADE"
    NONE = "NONE"

    # Backward-compatible aliases retained for legacy callers.
    HIGHER_TF_DIVERGENCE = HIGHER_LEVEL_DIVERGENCE_TRADE
    DECOMPOSITION = DECOMPOSITION_TRADE
    RANGE_REJECTION = RANGE_REJECTION_TRADE
    BREAKOUT = BREAKOUT_TRADE
    SUPPLY_DEMAND_REACTION = SUPPLY_DEMAND_REACTION_TRADE
    PULLBACK_CONTINUATION = PULLBACK_CONTINUATION_TRADE
    UPGRADE = UPGRADE_TRADE


class CarryState(str, Enum):
    """Lifecycle stage of a carry narrative."""

    FRESH = "FRESH"
    ACTIVE = "ACTIVE"
    MATURE = "MATURE"
    EXHAUSTING = "EXHAUSTING"
    UNCLEAR = "UNCLEAR"


class FinalAction(str, Enum):
    """Terminal action output for runner delivery."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD_LONG = "HOLD_LONG"
    HOLD_SHORT = "HOLD_SHORT"
    CLOSE_LONG = "CLOSE_LONG"
    CLOSE_SHORT = "CLOSE_SHORT"
    CLOSE_AND_FLIP = "CLOSE_AND_FLIP"
    WAIT = "WAIT"


class ZoneType(str, Enum):
    """Structural zone polarity."""

    SUPPLY = "SUPPLY"
    DEMAND = "DEMAND"


class ZoneStrength(str, Enum):
    """Relative conviction of a zone."""

    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"


class ZoneAlignment(str, Enum):
    """Zone alignment versus dominant market context."""

    ALIGNED = "ALIGNED"
    COUNTER = "COUNTER"
    NEUTRAL = "NEUTRAL"
