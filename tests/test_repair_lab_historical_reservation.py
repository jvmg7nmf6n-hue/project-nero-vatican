"""Repair Lab v1, Task 4a: historical-segment reservation (non-overlap proof)
and frozen-snapshot grid-shift reproducibility. Uses this project's own real,
committed BTC_4h.json frozen fixture (feature/short-side-support's own
backward-compat proof fixture) for the reservation tests -- real candle
data, not synthetic."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

import pandas as pd

from nero_core.research_agent.repair_historical_reservation import (
    GRID_OFFSETS_4H,
    build_frozen_grids,
    candle_content_hash,
    reserve_historical_segment,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "frozen_candles"


def _load_btc_4h() -> pd.DataFrame:
    data = json.loads((FIXTURES_DIR / "BTC_4h.json").read_text())
    return pd.DataFrame(data["candles"])


def _synthetic_hourly(n: int = 400, start_ms: int = 1_700_000_000_000) -> pd.DataFrame:
    rows = []
    price = 100.0
    for i in range(n):
        price *= 1.001
        open_time = start_ms + i * 3_600_000
        rows.append({
            "date": pd.Timestamp(open_time, unit="ms", tz="UTC").isoformat(),
            "open_time": open_time, "close_time": open_time + 3_600_000 - 1,
            "open": price, "high": price * 1.002, "low": price * 0.998, "close": price * 1.0005,
            "volume": 10.0,
        })
    return pd.DataFrame(rows)


class ReserveHistoricalSegmentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.candles = _load_btc_4h()
        self.all_close_times = self.candles["close_time"].tolist()

    def test_no_consumed_windows_reserves_the_full_span(self) -> None:
        segment = reserve_historical_segment(self.candles, [])
        self.assertIsNotNone(segment)
        self.assertEqual(segment.candle_count, len(self.candles))
        self.assertEqual(segment.start_close_time_ms, min(self.all_close_times))
        self.assertEqual(segment.end_close_time_ms, max(self.all_close_times))

    def test_reserved_segment_never_overlaps_a_consumed_window(self) -> None:
        midpoint = self.all_close_times[len(self.all_close_times) // 2]
        original_window = [(min(self.all_close_times), midpoint)]
        segment = reserve_historical_segment(self.candles, original_window)
        self.assertIsNotNone(segment)
        self.assertGreater(segment.start_close_time_ms, midpoint)
        # Provable non-overlap: every close_time in the reserved segment is
        # strictly outside the consumed window.
        for ct in segment.candles["close_time"]:
            self.assertFalse(original_window[0][0] <= ct <= original_window[0][1])

    def test_reserving_twice_produces_disjoint_segments(self) -> None:
        # Simulates attempt 1 reserving, then attempt 2 reserving from what's left.
        segment_1 = reserve_historical_segment(self.candles, [])
        self.assertIsNotNone(segment_1)
        consumed = [(segment_1.start_close_time_ms, segment_1.end_close_time_ms)]
        segment_2 = reserve_historical_segment(self.candles, consumed)
        # The entire fixture was consumed by segment_1 -- nothing disjoint remains.
        self.assertIsNone(segment_2)

    def test_a_middle_window_consumed_leaves_two_candidate_spans_and_picks_the_larger(self) -> None:
        n = len(self.all_close_times)
        # Consume a window in the middle, leaving a small span before and a larger span after.
        consumed_start = self.all_close_times[int(n * 0.2)]
        consumed_end = self.all_close_times[int(n * 0.9)]
        segment = reserve_historical_segment(self.candles, [(consumed_start, consumed_end)])
        self.assertIsNotNone(segment)
        # The larger remaining span is AFTER the consumed window (0.9 -> 1.0 is
        # smaller than the segment before 0.2, so this asserts the after-span
        # is correctly rejected in favor of the (larger) pre-consumption span).
        self.assertLessEqual(segment.end_close_time_ms, consumed_start)

    def test_insufficient_remaining_candles_returns_none_not_a_shrunk_segment(self) -> None:
        # Consume everything except the last 5 candles -- below MIN_CANDLES_FOR_MEASUREMENT.
        n = len(self.all_close_times)
        consumed = [(self.all_close_times[0], self.all_close_times[n - 6])]
        segment = reserve_historical_segment(self.candles, consumed, min_candle_count=60)
        self.assertIsNone(segment)

    def test_content_hash_is_deterministic_for_the_same_segment(self) -> None:
        segment = reserve_historical_segment(self.candles, [])
        hash_again = candle_content_hash(segment.candles)
        self.assertEqual(segment.content_hash, hash_again)

    def test_content_hash_differs_for_different_segments(self) -> None:
        full = reserve_historical_segment(self.candles, [])
        midpoint = self.all_close_times[len(self.all_close_times) // 2]
        partial = reserve_historical_segment(self.candles, [(self.all_close_times[0], midpoint)])
        self.assertNotEqual(full.content_hash, partial.content_hash)


class FrozenGridShiftReproducibilityTest(unittest.TestCase):
    def test_two_calls_with_the_same_hourly_frame_produce_byte_identical_grids(self) -> None:
        # THE proof required by the task: two runs of the same attempt's
        # grid-shift, using the frozen-snapshot technique, must be identical
        # -- unlike tools.philosophy_hypotheses_live_test.build_4h_grids,
        # which fetches live data on every call and is NOT guaranteed this.
        hourly = _synthetic_hourly()
        grids_1 = build_frozen_grids(hourly)
        grids_2 = build_frozen_grids(hourly)

        self.assertEqual(set(grids_1.keys()), set(grids_2.keys()))
        for label in grids_1:
            pd.testing.assert_frame_equal(grids_1[label], grids_2[label])

    def test_every_configured_offset_produces_a_labeled_grid(self) -> None:
        hourly = _synthetic_hourly()
        grids = build_frozen_grids(hourly)
        self.assertEqual(len(grids), len(GRID_OFFSETS_4H))
        self.assertIn("native (offset+0h)", grids)
        self.assertIn("offset+3h", grids)

    def test_a_mutated_hourly_frame_produces_a_different_grid_proving_the_function_is_not_a_no_op(self) -> None:
        hourly = _synthetic_hourly()
        grids_original = build_frozen_grids(hourly)

        mutated = hourly.copy()
        mutated["close"] = mutated["close"] * 1.5
        grids_mutated = build_frozen_grids(mutated)

        native_label = "native (offset+0h)"
        self.assertFalse(grids_original[native_label]["close"].equals(grids_mutated[native_label]["close"]))


if __name__ == "__main__":
    unittest.main()
