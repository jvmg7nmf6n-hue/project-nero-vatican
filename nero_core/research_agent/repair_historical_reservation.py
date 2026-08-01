"""Repair Lab v1, Task 4a: historical-segment reservation + frozen-snapshot
grid-shift -- the "historical reservation" half of the two accepted
fresh-data mechanisms (docs/repair_lab_investigation_report.md Task 2). See
nero_core.research_agent.repair_forward_tracker for the other half.

NON-OVERLAP GUARANTEE (the critical anti-p-hacking constraint, made
concrete): reserve_historical_segment NEVER returns a segment that overlaps
ANY window already consumed by the original run or any prior attempt in the
same chain -- it returns None (never a fabricated or partially-overlapping
segment) when no disjoint span of at least `min_candle_count` candles
remains. This is what makes historical reservation a genuinely fresh-data
method rather than "re-testing on the same data with extra steps."

GRID-SHIFT NON-DETERMINISM FIX: `tools.philosophy_hypotheses_live_test.
build_4h_grids` performs its OWN independent, live, unfrozen hourly refetch
on every call -- traced directly, during feature/short-side-support's own
backward-compat proof this project already completed, to a real (small but
real) divergence between two runs of "the same" grid-shift minutes apart.
build_frozen_grids below is the fix: it takes an already-fetched
`hourly_frame` as a parameter and resamples every offset from that SAME
frame, never fetching anything itself -- two calls with the same
hourly_frame are guaranteed byte-identical (proven directly in
test_repair_lab_historical_reservation.py), because there is no live call
left to introduce drift."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

import pandas as pd

from nero_core.data_sources.candle_resampling import resample_hourly_to_grid
from nero_core.research_agent.frequency_gate import MIN_CANDLES_FOR_MEASUREMENT

# Mirrors tools.philosophy_hypotheses_live_test.GRID_OFFSETS_4H exactly (the
# same 4 offsets that module's own build_4h_grids tests) -- not re-derived,
# just restated here since this module deliberately never imports that
# live-fetching function itself.
GRID_OFFSETS_4H = (0, 1, 2, 3)


@dataclass(frozen=True)
class ReservedSegment:
    candles: pd.DataFrame
    start_close_time_ms: int
    end_close_time_ms: int
    candle_count: int
    content_hash: str


def candle_content_hash(candles: pd.DataFrame) -> str:
    """A stable content hash of the exact candle data a repair attempt runs
    against -- recorded as the chain record's "fresh-data snapshot
    reference" (Task 6). Directly addresses the grid-shift non-determinism
    finding: a later question of "did this attempt really use fresh,
    unmodified data" has a concrete artifact to check against, not just a
    claim. Hashes only the columns that determine backtest outcome (close_
    time/close/high/low) so re-serializing the SAME candles through a
    different pandas dtype/index state still hashes identically."""
    payload = candles[["close_time", "close", "high", "low"]].to_json(orient="records")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _windows_overlap(point: int, windows: list[tuple[int, int]]) -> bool:
    return any(start <= point <= end for start, end in windows)


def reserve_historical_segment(
    full_candles: pd.DataFrame,
    already_consumed_windows: list[tuple[int, int]],
    min_candle_count: int = MIN_CANDLES_FOR_MEASUREMENT,
) -> ReservedSegment | None:
    """Finds the LARGEST contiguous, chronologically-ordered span of
    `full_candles` whose close_time never falls inside any window in
    `already_consumed_windows` (each a (start_close_time_ms, end_close_time_
    ms) inclusive range -- the original run's own [min, max] close_time,
    plus every prior attempt's own reserved segment in the same chain).
    Returns None if no disjoint span of at least `min_candle_count` candles
    remains (frequency_gate.MIN_CANDLES_FOR_MEASUREMENT by default -- the
    same floor this project already treats as the line below which a rate
    can't be trusted at all) -- NEVER a segment smaller than that floor, and
    NEVER a segment that borrows even one candle from a consumed window.

    Where this applies cleanly vs. where it's genuinely limited: see
    docs/repair_lab_investigation_report.md Task 2 -- BTC/ETH-class deep
    history has ample unconsumed span for a full 4-attempt chain; EUR/USD-
    class intraday forex (Twelve Data's ~2.3-year single-call cap) may
    exhaust its available span before 4 attempts, in which case this
    function's own None return is exactly what routes that attempt to
    forward testing instead (nero_core.research_agent.repair_forward_
    tracker) -- never a shrunk-below-the-floor segment used anyway."""
    sorted_candles = full_candles.sort_values("close_time").reset_index(drop=True)
    close_times = sorted_candles["close_time"].tolist()
    n = len(close_times)

    best_start_idx: int | None = None
    best_end_idx: int | None = None
    i = 0
    while i < n:
        if _windows_overlap(close_times[i], already_consumed_windows):
            i += 1
            continue
        j = i
        while j + 1 < n and not _windows_overlap(close_times[j + 1], already_consumed_windows):
            j += 1
        if best_start_idx is None or (j - i) > (best_end_idx - best_start_idx):
            best_start_idx, best_end_idx = i, j
        i = j + 1

    if best_start_idx is None:
        return None
    count = best_end_idx - best_start_idx + 1
    if count < min_candle_count:
        return None

    segment = sorted_candles.iloc[best_start_idx : best_end_idx + 1].reset_index(drop=True)
    return ReservedSegment(
        candles=segment,
        start_close_time_ms=int(segment["close_time"].iloc[0]),
        end_close_time_ms=int(segment["close_time"].iloc[-1]),
        candle_count=len(segment),
        content_hash=candle_content_hash(segment),
    )


def build_frozen_grids(hourly_frame: pd.DataFrame, offsets: tuple[int, ...] = GRID_OFFSETS_4H) -> dict[str, pd.DataFrame]:
    """Builds every grid-shift offset by resampling the SAME, already-in-
    memory `hourly_frame` -- never fetching live data itself, unlike
    tools.philosophy_hypotheses_live_test.build_4h_grids. The caller fetches
    `hourly_frame` ONCE at attempt-launch time; every offset is resampled
    from that one frozen frame. Deterministic and pure: calling this twice
    with the same hourly_frame produces byte-identical grids by
    construction (there is no live call left inside this function to
    introduce drift)."""
    grids: dict[str, pd.DataFrame] = {}
    for offset in offsets:
        label = "native (offset+0h)" if offset == 0 else f"offset+{offset}h"
        grids[label] = resample_hourly_to_grid(hourly_frame, 4, offset)
    return grids
