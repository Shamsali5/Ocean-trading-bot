"""A-B-C structural candidate detection for same-timeframe legs."""

from __future__ import annotations

from ocean_engine.models.enums import Direction, DivergenceDirection
from ocean_engine.models.market import ABCStructure, Leg, StructureState


def find_abc_candidates(
    structure: StructureState,
    min_reset_pct: float = 0.001,
    min_reset_bars: int = 3,
    retest_tolerance_pct: float = 0.001,
) -> list[ABCStructure]:
    """Scan rolling A-B-C leg triples and return valid candidates."""

    if min_reset_pct < 0.0:
        raise ValueError("min_reset_pct must be >= 0")
    if min_reset_bars < 1:
        raise ValueError("min_reset_bars must be >= 1")
    if retest_tolerance_pct < 0.0:
        raise ValueError("retest_tolerance_pct must be >= 0")

    legs = sorted(structure.legs, key=lambda leg: leg.end_index)
    if len(legs) < 3:
        return []

    candidates: list[ABCStructure] = []

    for a_leg, b_leg, c_leg in zip(legs, legs[1:], legs[2:]):
        bearish_sequence = (
            a_leg.direction == Direction.UP
            and b_leg.direction == Direction.DOWN
            and c_leg.direction == Direction.UP
        )
        bullish_sequence = (
            a_leg.direction == Direction.DOWN
            and b_leg.direction == Direction.UP
            and c_leg.direction == Direction.DOWN
        )
        if not bearish_sequence and not bullish_sequence:
            continue

        b_reset_valid = _validate_b_reset(
            a_leg=a_leg,
            b_leg=b_leg,
            c_leg=c_leg,
            min_reset_pct=min_reset_pct,
            min_reset_bars=min_reset_bars,
        )
        if not b_reset_valid:
            continue

        if bearish_sequence:
            c_retest_valid = c_leg.high >= a_leg.high * (1.0 - retest_tolerance_pct)
            candidate_direction = DivergenceDirection.BEARISH
        else:
            c_retest_valid = c_leg.low <= a_leg.low * (1.0 + retest_tolerance_pct)
            candidate_direction = DivergenceDirection.BULLISH
        if not c_retest_valid:
            continue

        candidates.append(
            ABCStructure(
                timeframe=structure.timeframe,
                a_index=a_leg.start_index,
                b_index=b_leg.start_index,
                c_index=c_leg.start_index,
                direction=candidate_direction,
                segment_a=a_leg,
                segment_b=b_leg,
                segment_c=c_leg,
                abc_valid=True,
                b_reset_valid=b_reset_valid,
                c_retest_valid=c_retest_valid,
                summary=(
                    f"{candidate_direction.value} A-B-C on {structure.timeframe} "
                    f"with C ending at leg index {c_leg.end_index}"
                ),
            )
        )
    return candidates


def select_latest_abc_candidate(candidates: list[ABCStructure]) -> ABCStructure | None:
    """Return the candidate with the latest C segment end index."""

    if not candidates:
        return None

    def _c_end_index(candidate: ABCStructure) -> int:
        if candidate.segment_c is not None:
            return candidate.segment_c.end_index
        return candidate.c_index

    return max(candidates, key=_c_end_index)


def _validate_b_reset(
    a_leg: Leg,
    b_leg: Leg,
    c_leg: Leg,
    min_reset_pct: float,
    min_reset_bars: int,
) -> bool:
    """Validate reset quality for B segment."""

    bars = b_leg.end_index - b_leg.start_index
    enough_bars = bars >= min_reset_bars

    if b_leg.start_price is None or b_leg.start_price == 0.0 or b_leg.end_price is None:
        move_pct = 0.0
    else:
        move_pct = abs(b_leg.end_price - b_leg.start_price) / abs(b_leg.start_price)
    enough_move = move_pct >= min_reset_pct

    overlap_low = max(a_leg.low, b_leg.low, c_leg.low)
    overlap_high = min(a_leg.high, b_leg.high, c_leg.high)
    overlap_width = overlap_high - overlap_low
    if overlap_width > 0.0:
        reference = max(abs(a_leg.high), abs(a_leg.low), 1e-12)
        has_pause_overlap = (overlap_width / reference) >= min_reset_pct
    else:
        has_pause_overlap = False

    # Direction sequencing is enforced before this function; here we require
    # a substantive reset signal from size, duration, or pause overlap.
    return enough_move or enough_bars or has_pause_overlap
