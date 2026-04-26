"""Multi-level same-story synthesis without timeframe drift."""

from __future__ import annotations

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
) -> MultiLevelStory:
    """Build multi-level same-story context from official rows."""

    grouped = get_official_timeframes_by_direction(divergence_audit, active_trade_audit)
    bullish_rows = grouped["BULLISH"]
    bearish_rows = grouped["BEARISH"]

    if not bullish_rows and not bearish_rows:
        return MultiLevelStory(
            symbol="",
            primary_timeframe="",
            active=False,
            direction=Direction.UNCLEAR,
            confirmed_timeframes=[],
            controlling_origin="",
            active_execution_trade="",
            carrying_timeframe="",
            higher_tf_status="NONE",
            explanation="No official timeframe rows.",
            summary="No multi-level story.",
        )

    if len(bullish_rows) > len(bearish_rows):
        selected_direction = "BULLISH"
        rows = bullish_rows
    elif len(bearish_rows) > len(bullish_rows):
        selected_direction = "BEARISH"
        rows = bearish_rows
    else:
        # Tie-break by highest timeframe presence.
        bullish_best = max((timeframe_rank(str(row["timeframe"])) for row in bullish_rows), default=0)
        bearish_best = max((timeframe_rank(str(row["timeframe"])) for row in bearish_rows), default=0)
        if bullish_best >= bearish_best:
            selected_direction = "BULLISH"
            rows = bullish_rows
        else:
            selected_direction = "BEARISH"
            rows = bearish_rows

    confirmed_timeframes = sorted({str(row["timeframe"]) for row in rows}, key=timeframe_rank, reverse=True)
    active = len(confirmed_timeframes) >= 2
    higher_tf_status = "OFFICIAL_MULTI_LEVEL" if active else "WEAKENING_CONTEXT_ONLY"

    controlling_tf = max(confirmed_timeframes, key=timeframe_rank)
    controlling_row = next(row for row in rows if str(row["timeframe"]) == controlling_tf)
    controlling_origin = str(controlling_row["label"])

    selected_trade = _resolve_selected_trade(active_trade_audit)
    execution_row = _choose_execution_row(rows, selected_trade, selected_direction, confirmed_timeframes)
    active_execution_trade = str(execution_row["label"]) if execution_row is not None else ""

    carrying_timeframe = ""
    if execution_row is not None and execution_row.get("candidate") is not None:
        candidate = execution_row["candidate"]
        if isinstance(candidate, ActiveTradeCandidate):
            carrying_timeframe = candidate.carry_timeframe

    story_direction = Direction.UP if selected_direction == "BULLISH" else Direction.DOWN
    explanation = (
        f"{selected_direction.title()} confirmation on {', '.join(normalize_tf_label(tf) for tf in confirmed_timeframes)}."
    )
    summary = (
        f"{selected_direction.title()} story | control={controlling_origin} | "
        f"execution={active_execution_trade or 'None'} | carry={carrying_timeframe or 'None'}"
    )

    return MultiLevelStory(
        symbol="",
        primary_timeframe=controlling_tf,
        bias=story_direction,
        supporting_timeframes=[tf for tf in confirmed_timeframes if tf != controlling_tf],
        active=active,
        direction=story_direction,
        confirmed_timeframes=confirmed_timeframes,
        controlling_origin=controlling_origin,
        active_execution_trade=active_execution_trade,
        carrying_timeframe=carrying_timeframe,
        higher_tf_status=higher_tf_status,
        explanation=explanation,
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
