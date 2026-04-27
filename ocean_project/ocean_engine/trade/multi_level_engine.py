"""Multi-level same-story synthesis without timeframe drift."""

from __future__ import annotations

from ocean_multilevel_validator import validate_multi_level_same_story
from ocean_engine.models.enums import Direction, DivergenceDirection, SetupType
from ocean_engine.models.market import ActiveTradeAudit, ActiveTradeCandidate, DivergenceAudit, MultiLevelStory

TIMEFRAME_ORDER = ("4h", "1h", "15m", "5m", "3m")
TIMEFRAME_FIELD_MAP = {
    "4h": "tf_4h",
    "1h": "tf_1h",
    "15m": "tf_15m",
    "5m": "tf_5m",
    "3m": "tf_3m",
}
def timeframe_rank(tf: str) -> int:
    """Return descending priority rank for timeframe labels."""

    return {"4h": 5, "1h": 4, "15m": 3, "5m": 2, "3m": 1}.get(tf, 0)


def normalize_tf_label(tf: str) -> str:
    """Normalize timeframe label for human-readable output."""

    if tf == "4h":
        return "4H"
    if tf == "1h":
        return "1H"
    return tf


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


def get_official_timeframes_by_direction(
    divergence_audit: DivergenceAudit,
    active_trade_audit: ActiveTradeAudit,
) -> dict[str, list[dict[str, str | ActiveTradeCandidate]]]:
    """Collect official setup rows by direction.

    Official row sources:
    1) Official divergence row (Type 1 context)
    2) Existing Type 3 trade candidate row
    """

    grouped: dict[str, list[dict[str, str | ActiveTradeCandidate]]] = {
        "BULLISH": [],
        "BEARISH": [],
    }

    for tf in TIMEFRAME_ORDER:
        divergence_row = getattr(divergence_audit, TIMEFRAME_FIELD_MAP[tf])
        if (
            divergence_row.exists
            and divergence_row.abc_valid
            and divergence_row.impulse_confirmed
            and divergence_row.direction in (DivergenceDirection.BULLISH, DivergenceDirection.BEARISH)
        ):
            key = "BULLISH" if divergence_row.direction == DivergenceDirection.BULLISH else "BEARISH"
            grouped[key].append(
                {
                    "timeframe": tf,
                    "source": "DIVERGENCE",
                    "label": f"{normalize_tf_label(tf)} {divergence_row.direction.value.title()} Divergence",
                    "candidate": None,
                }
            )

        trade_row = getattr(active_trade_audit, TIMEFRAME_FIELD_MAP[tf])
        normalized_direction = _candidate_direction(trade_row)
        if (
            trade_row.exists
            and trade_row.setup_type == SetupType.TYPE_3
            and trade_row.origin_timeframe == tf
            and normalized_direction in (Direction.UP, Direction.DOWN)
        ):
            direction_key = "BULLISH" if normalized_direction == Direction.UP else "BEARISH"
            grouped[direction_key].append(
                {
                    "timeframe": tf,
                    "source": "TRADE",
                    "label": trade_row.type_label or f"{normalize_tf_label(tf)} {direction_key.title()} Type 3",
                    "candidate": trade_row,
                }
            )

    # Deduplicate per direction/timeframe by preferring trade rows over divergence rows.
    for key in ("BULLISH", "BEARISH"):
        by_tf: dict[str, dict[str, str | ActiveTradeCandidate]] = {}
        for row in grouped[key]:
            tf = str(row["timeframe"])
            existing = by_tf.get(tf)
            if existing is None:
                by_tf[tf] = row
                continue
            if existing["source"] == "DIVERGENCE" and row["source"] == "TRADE":
                by_tf[tf] = row
        grouped[key] = list(by_tf.values())
    return grouped


def build_multi_level_story(
    divergence_audit: DivergenceAudit,
    active_trade_audit: ActiveTradeAudit,
    trace=None,
) -> MultiLevelStory:
    """Build multi-level same-story context with strict anti-drift validation."""

    divergence_rows: dict[str, dict[str, object]] = {}
    type_rows: dict[str, dict[str, object]] = {}
    carry_rows: dict[str, dict[str, object]] = {}
    for tf in TIMEFRAME_ORDER:
        divergence = getattr(divergence_audit, TIMEFRAME_FIELD_MAP[tf])
        candidate = getattr(active_trade_audit, TIMEFRAME_FIELD_MAP[tf])
        candidate_direction = _candidate_direction(candidate)
        direction_label = "BULLISH" if candidate_direction == Direction.UP else "BEARISH" if candidate_direction == Direction.DOWN else "NONE"

        divergence_rows[tf] = {
            "timeframe": tf,
            "exists": divergence.exists,
            "abc_valid": divergence.abc_valid,
            "direction": divergence.direction,
            "impulse_confirmed": divergence.impulse_confirmed,
            "valid_energy_weakening": bool(divergence.weakening_count >= 2),
            "weakening_count": divergence.weakening_count,
            "velocity_weaker": divergence.velocity_weaker,
            "acceleration_weaker": divergence.acceleration_weaker,
            "acceleration_area_weaker": divergence.acceleration_area_weaker,
        }

        type_rows[tf] = {
            "timeframe": tf,
            "origin_timeframe": candidate.origin_timeframe,
            "type_label": candidate.setup_type.value if candidate.setup_type is not None else "NONE",
            "full_label": candidate.type_label,
            "direction": direction_label,
            "valid": bool(candidate.exists and candidate.setup_type in {SetupType.TYPE_1, SetupType.TYPE_2, SetupType.TYPE_3}),
            "fresh_entry_valid": candidate.fresh_entry_valid,
            "existing_hold_valid": candidate.existing_hold_valid,
            "impulse_confirmed": bool(candidate.confirmation_price is not None),
            "breakout_acceptance_valid": bool(candidate.setup_type == SetupType.TYPE_3),
        }

        carry_rows[tf] = {
            "timeframe": candidate.carry_timeframe,
            "direction": candidate.carry_direction,
            "state": candidate.carry_state,
            "finished": candidate.current_status.upper() == "FINISHED",
        }

    validated = validate_multi_level_same_story(
        divergence_results_by_tf=divergence_rows,
        type_results_by_tf=type_rows,
        carry_results_by_tf=carry_rows,
        trace=trace,
    )

    confirmed_timeframes = list(validated.confirmed_timeframes)
    story_direction = (
        Direction.UP
        if validated.direction == "BULLISH"
        else Direction.DOWN
        if validated.direction == "BEARISH"
        else Direction.UNCLEAR
    )
    controlling_tf = confirmed_timeframes[0] if confirmed_timeframes else ""
    higher_tf_status = validated.higher_tf_official_or_context
    active = bool(validated.active and validated.valid)
    if not validated.valid and confirmed_timeframes:
        higher_tf_status = "WEAKENING_CONTEXT_ONLY"
    summary = (
        f"{validated.direction.title() if validated.direction else 'None'} story | "
        f"control={validated.controlling_origin or 'None'} | "
        f"execution={validated.active_execution_trade or 'None'} | "
        f"carry={validated.carrying_timeframe or 'None'} | valid={validated.valid}"
    )
    return MultiLevelStory(
        symbol="",
        primary_timeframe=controlling_tf,
        bias=story_direction,
        supporting_timeframes=[tf for tf in confirmed_timeframes if tf != controlling_tf],
        active=active,
        direction=story_direction,
        confirmed_timeframes=confirmed_timeframes,
        controlling_origin=validated.controlling_origin or "",
        active_execution_trade=validated.active_execution_trade or "",
        carrying_timeframe=validated.carrying_timeframe or "",
        higher_tf_status=higher_tf_status,
        explanation=validated.explanation,
        summary=summary,
    )


def multi_level_summary(story: MultiLevelStory) -> str:
    """Render compact summary for multi-level story state."""

    if not story.confirmed_timeframes:
        return "No official multi-level rows."
    confirmed = ",".join(normalize_tf_label(tf) for tf in story.confirmed_timeframes)
    return (
        f"confirmed_timeframes={confirmed} | controlling_origin={story.controlling_origin or 'None'} | "
        f"active_execution_trade={story.active_execution_trade or 'None'} | carry={story.carrying_timeframe or 'None'} | "
        f"status={story.higher_tf_status}"
    )


def _resolve_selected_trade(audit: ActiveTradeAudit) -> ActiveTradeCandidate | None:
    tf = audit.selected_active_trade_tf
    if tf is None:
        return None
    field = TIMEFRAME_FIELD_MAP.get(tf)
    if field is None:
        return None
    candidate = getattr(audit, field)
    return candidate if candidate.exists else None


def _choose_execution_row(
    rows: list[dict[str, str | ActiveTradeCandidate]],
    selected_trade: ActiveTradeCandidate | None,
    selected_direction: str,
    confirmed_timeframes: list[str],
) -> dict[str, str | ActiveTradeCandidate] | None:
    if not rows:
        return None

    if selected_trade is not None:
        selected_trade_direction = (
            "BULLISH"
            if _candidate_direction(selected_trade) == Direction.UP
            else "BEARISH"
            if _candidate_direction(selected_trade) == Direction.DOWN
            else ""
        )
        if (
            selected_trade_direction == selected_direction
            and selected_trade.origin_timeframe in confirmed_timeframes
        ):
            for row in rows:
                if row["source"] == "TRADE" and str(row["timeframe"]) == selected_trade.origin_timeframe:
                    return row

    lowest_tf = min(confirmed_timeframes, key=timeframe_rank)
    trade_rows = [
        row for row in rows if row["source"] == "TRADE" and str(row["timeframe"]) == lowest_tf
    ]
    if trade_rows:
        return trade_rows[0]
    if selected_trade is not None:
        selected_trade_direction = (
            "BULLISH"
            if _candidate_direction(selected_trade) == Direction.UP
            else "BEARISH"
            if _candidate_direction(selected_trade) == Direction.DOWN
            else ""
        )
        if (
            selected_trade_direction == selected_direction
            and selected_trade.origin_timeframe in confirmed_timeframes
        ):
            return {
                "timeframe": selected_trade.origin_timeframe,
                "source": "TRADE",
                "label": selected_trade.type_label or f"{normalize_tf_label(selected_trade.origin_timeframe)} Selected Trade",
                "candidate": selected_trade,
            }
    for row in rows:
        if str(row["timeframe"]) == lowest_tf:
            return row
    return None
