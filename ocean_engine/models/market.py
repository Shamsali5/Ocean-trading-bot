"""Typed dataclasses for deterministic Ocean x Natural Chanlun state exchange."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from .enums import (
    CarryState,
    Direction,
    DivergenceDirection,
    DivergenceGrade,
    FinalAction,
    MarketState,
    SetupType,
    TradeFunction,
    ZoneAlignment,
    ZoneStrength,
    ZoneType,
)


@dataclass(slots=True)
class Candle:
    """Single OHLCV candle entry."""

    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int


@dataclass(slots=True)
class TimeframeData:
    """Market data and coarse state for one timeframe."""

    timeframe: str
    candles: list[Candle] = field(default_factory=list)
    direction: Direction = Direction.UNCLEAR
    market_state: MarketState = MarketState.UNCLEAR


@dataclass(slots=True)
class Swing:
    """Detected swing point metadata."""

    index: int
    price: float
    direction: Direction
    timestamp: int


@dataclass(slots=True)
class Leg:
    """Directional leg bounded by two swing points."""

    start_index: int
    end_index: int
    direction: Direction
    high: float
    low: float
    start_price: float | None = None
    end_price: float | None = None
    start_time: int | None = None
    end_time: int | None = None
    is_active: bool = False


@dataclass(slots=True)
class StructureState:
    """Structure-engine output snapshot for one timeframe."""

    timeframe: str
    candles: list[Candle] = field(default_factory=list)
    swings: list[Swing] = field(default_factory=list)
    legs: list[Leg] = field(default_factory=list)
    active_leg: Leg | None = None
    range_state: RangeState | None = None
    current_price: float | None = None
    direction: Direction = Direction.UNCLEAR
    market_state: MarketState = MarketState.UNCLEAR
    summary: str = ""


@dataclass(slots=True)
class RangeState:
    """Range context and mid-line references."""

    timeframe: str
    is_range: bool = False
    high: float | None = None
    low: float | None = None
    mid: float | None = None
    active: bool = False
    upper_edge: float | None = None
    lower_edge: float | None = None
    midpoint: float | None = None
    pivot_low: float | None = None
    pivot_high: float | None = None
    price_location: str = "UNCLEAR"
    leg_count: int = 0
    start_index: int | None = None
    end_index: int | None = None
    summary: str = ""


@dataclass(slots=True)
class VAccPoint:
    """Single velocity/acceleration derived sample."""

    timestamp: int
    velocity: float
    acceleration: float


@dataclass(slots=True)
class VAccSeries:
    """Ordered velocity/acceleration series for a timeframe."""

    timeframe: str
    points: list[VAccPoint] = field(default_factory=list)


@dataclass(slots=True)
class ABCStructure:
    """Candidate A-B-C decomposition descriptor."""

    timeframe: str
    a_index: int
    b_index: int
    c_index: int
    direction: DivergenceDirection = DivergenceDirection.NONE
    segment_a: Leg | None = None
    segment_b: Leg | None = None
    segment_c: Leg | None = None
    abc_valid: bool = False
    b_reset_valid: bool = False
    c_retest_valid: bool = False
    summary: str = ""


@dataclass(slots=True)
class DivergenceState:
    """Divergence synthesis outcome for one timeframe."""

    timeframe: str
    exists: bool = False
    abc_valid: bool = False
    direction: DivergenceDirection = DivergenceDirection.NONE
    grade: DivergenceGrade = DivergenceGrade.INVALID
    weakening_count: int = 0
    impulse_confirmed: bool = False
    velocity_weaker: bool = False
    acceleration_area_weaker: bool = False
    zero_axis_reset: bool = False
    price_zone: str = ""
    locked: bool = False
    notes: str = ""


@dataclass(slots=True)
class DivergenceAudit:
    """Per-timeframe divergence audit summary and selection record."""

    tf_4h: DivergenceState = field(default_factory=lambda: DivergenceState(timeframe="4h"))
    tf_1h: DivergenceState = field(default_factory=lambda: DivergenceState(timeframe="1h"))
    tf_15m: DivergenceState = field(default_factory=lambda: DivergenceState(timeframe="15m"))
    tf_5m: DivergenceState = field(default_factory=lambda: DivergenceState(timeframe="5m"))
    tf_3m: DivergenceState = field(default_factory=lambda: DivergenceState(timeframe="3m"))
    selected_last_meaningful_tf: str | None = None
    selection_reason: str = ""


@dataclass(slots=True)
class SupplyDemandZone:
    """Supply or demand reaction zone."""

    timeframe: str
    zone_type: ZoneType
    lower: float
    upper: float
    strength: ZoneStrength = ZoneStrength.MODERATE
    alignment: ZoneAlignment = ZoneAlignment.NEUTRAL
    price_band: str = ""
    role: str = ""
    status: str = "UNTESTED"
    summary: str = ""


@dataclass(slots=True)
class CarryStatus:
    """Carry engine state summary."""

    timeframe: str
    direction: Direction = Direction.UNCLEAR
    state: CarryState = CarryState.UNCLEAR
    cycle_complete: str = "UNCLEAR"
    opposite_divergence: bool = False
    opposite_impulse: bool = False
    finished: bool = False
    summary: str = ""
    invalidated: bool = False
    notes: str = ""


@dataclass(slots=True)
class ActiveTradeCandidate:
    """Candidate trade object before final decision."""

    timeframe: str
    exists: bool = False
    origin_timeframe: str = ""
    direction: DivergenceDirection = DivergenceDirection.NONE
    setup_type: SetupType = SetupType.NONE
    trade_function: TradeFunction = TradeFunction.NONE
    type_label: str = ""
    origin_price_zone: str = ""
    confirmation_price: float | None = None
    confirmation_time_utc: str = ""
    earliest_legal_trigger_price: float | None = None
    carry_timeframe: str = ""
    carry_direction: Direction = Direction.UNCLEAR
    carry_state: CarryState = CarryState.UNCLEAR
    fresh_entry_valid: bool = False
    existing_hold_valid: bool = False
    too_late_to_chase: bool = False
    invalidation: str = ""
    current_status: str = "INACTIVE"
    selection_reason: str = ""
    summary: str = ""


@dataclass(slots=True)
class ActiveTradeAudit:
    """Audit event for active-trade lock ownership."""

    tf_4h: ActiveTradeCandidate = field(default_factory=lambda: ActiveTradeCandidate(timeframe="4h", origin_timeframe="4h"))
    tf_1h: ActiveTradeCandidate = field(default_factory=lambda: ActiveTradeCandidate(timeframe="1h", origin_timeframe="1h"))
    tf_15m: ActiveTradeCandidate = field(default_factory=lambda: ActiveTradeCandidate(timeframe="15m", origin_timeframe="15m"))
    tf_5m: ActiveTradeCandidate = field(default_factory=lambda: ActiveTradeCandidate(timeframe="5m", origin_timeframe="5m"))
    tf_3m: ActiveTradeCandidate = field(default_factory=lambda: ActiveTradeCandidate(timeframe="3m", origin_timeframe="3m"))
    selected_active_trade_tf: str | None = None
    selection_reason: str = ""


@dataclass(slots=True)
class MultiLevelStory:
    """Cross-timeframe narrative produced by story synthesis."""

    symbol: str = ""
    primary_timeframe: str = ""
    bias: Direction = Direction.UNCLEAR
    supporting_timeframes: list[str] = field(default_factory=list)
    active: bool = False
    direction: str = "UNCLEAR"
    confirmed_timeframes: list[str] = field(default_factory=list)
    controlling_origin: str = ""
    active_execution_trade: str = ""
    carrying_timeframe: str = ""
    higher_tf_status: str = "NONE"
    explanation: str = ""
    summary: str = ""


@dataclass(slots=True)
class DecisionState:
    """Final deterministic decision payload before output formatting."""

    symbol: str
    action: FinalAction = FinalAction.WAIT
    confidence: float = 0.0
    rationale: str = ""
    candidate: ActiveTradeCandidate | None = None


@dataclass(slots=True)
class MarketReport:
    """Top-level report assembled by deterministic runner pipeline."""

    symbol: str
    generated_at: str
    timeframe_data: dict[str, TimeframeData] = field(default_factory=dict)
    structure: dict[str, StructureState] = field(default_factory=dict)
    ranges: dict[str, RangeState] = field(default_factory=dict)
    vacc: dict[str, VAccSeries] = field(default_factory=dict)
    divergences: dict[str, DivergenceState] = field(default_factory=dict)
    divergence_audits: list[DivergenceAudit] = field(default_factory=list)
    zones: dict[str, list[SupplyDemandZone]] = field(default_factory=dict)
    carry: dict[str, CarryStatus] = field(default_factory=dict)
    active_trade_audits: list[ActiveTradeAudit] = field(default_factory=list)
    story: MultiLevelStory | None = None
    decision: DecisionState | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)
