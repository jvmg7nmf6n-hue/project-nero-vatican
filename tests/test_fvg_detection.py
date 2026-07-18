from __future__ import annotations

import unittest

import pandas as pd

from nero_core.strategies.fvg_detection import (
    FVG_EXPIRY_CANDLES,
    FVG_MAX_OPEN_PER_DIRECTION,
    any_bullish_gap_overlaps_range,
    attach_fvg_columns,
    compute_fvg_states,
)

HOUR_MS = 3_600_000


def _row(index: int, high: float, low: float, close: float | None = None) -> dict[str, object]:
    close_time = index * HOUR_MS
    return {
        "date": pd.Timestamp(close_time, unit="ms", tz="UTC"),
        "close_time": close_time,
        "open": (high + low) / 2,
        "high": high,
        "low": low,
        "close": close if close is not None else (high + low) / 2,
        "volume": 10.0,
    }


def _frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


class BullishGapFormationTest(unittest.TestCase):
    def test_gap_forms_when_low_exceeds_high_two_candles_back(self) -> None:
        rows = [
            _row(0, high=105, low=100),
            _row(1, high=104, low=99),
            _row(2, high=112, low=107),  # low(107) > high[0](105) -> bullish gap zone [105, 107]
        ]
        states = compute_fvg_states(_frame(rows))

        self.assertEqual(states[2].open_bullish_gaps, ((105.0, 107.0),))

    def test_no_gap_when_condition_not_met(self) -> None:
        rows = [
            _row(0, high=105, low=100),
            _row(1, high=104, low=99),
            _row(2, high=106, low=103),  # low(103) < high[0](105) -> no gap
        ]
        states = compute_fvg_states(_frame(rows))

        self.assertEqual(states[2].open_bullish_gaps, ())

    def test_formation_candle_itself_cannot_be_touched(self) -> None:
        rows = [
            _row(0, high=105, low=100),
            _row(1, high=104, low=99),
            _row(2, high=112, low=107),  # gap forms here
        ]
        states = compute_fvg_states(_frame(rows))

        self.assertIsNone(states[2].bullish_signal)


class BullishGapTouchTest(unittest.TestCase):
    def _formed_gap_rows(self) -> list[dict[str, object]]:
        # high[1] is deliberately raised to 110 (well above zone_top=107) so that a
        # later touch/filler candle with low in the 104-108 range doesn't ALSO satisfy
        # the independent "low[i] > high[i-2]" condition against candle 1 and spawn an
        # unintended second, cascading gap — gap formation is checked fresh every
        # candle against whatever sits exactly 2 positions back, so any candle whose
        # low exceeds an older high 2-back forms its OWN gap regardless of any other
        # gap already open. This fixture is only trying to exercise ONE gap's
        # lifecycle at a time.
        return [
            _row(0, high=105, low=100),
            _row(1, high=110, low=99),
            _row(2, high=112, low=107),  # bullish gap zone [105, 107]
        ]

    def test_first_candle_with_low_inside_zone_fires_a_touch_signal(self) -> None:
        rows = self._formed_gap_rows() + [_row(3, high=110, low=106)]  # low(106) in (105, 107]
        states = compute_fvg_states(_frame(rows))

        signal = states[3].bullish_signal
        self.assertIsNotNone(signal)
        self.assertEqual(signal.direction, "bullish")
        self.assertEqual(signal.zone_bottom, 105.0)

    def test_low_above_zone_top_does_not_touch(self) -> None:
        rows = self._formed_gap_rows() + [_row(3, high=115, low=108)]  # low(108) > zone_top(107)
        states = compute_fvg_states(_frame(rows))

        self.assertIsNone(states[3].bullish_signal)
        self.assertEqual(states[3].open_bullish_gaps, ((105.0, 107.0),))  # untouched, unchanged

    def test_partial_fill_shrinks_remaining_top(self) -> None:
        rows = self._formed_gap_rows() + [_row(3, high=110, low=106)]  # dips to 106, doesn't fully fill
        states = compute_fvg_states(_frame(rows))

        self.assertEqual(states[3].open_bullish_gaps, ((105.0, 106.0),))  # remaining_top shrunk to 106

    def test_full_fill_kills_the_gap(self) -> None:
        rows = self._formed_gap_rows() + [_row(3, high=110, low=104)]  # low(104) <= zone_bottom(105)
        states = compute_fvg_states(_frame(rows))

        self.assertIsNone(states[3].bullish_signal)
        self.assertEqual(states[3].open_bullish_gaps, ())

    def test_touch_and_partial_fill_happen_on_the_same_candle(self) -> None:
        rows = self._formed_gap_rows() + [_row(3, high=110, low=106)]
        states = compute_fvg_states(_frame(rows))

        self.assertIsNotNone(states[3].bullish_signal)
        self.assertEqual(states[3].open_bullish_gaps, ((105.0, 106.0),))

    def test_one_shot_no_second_signal_from_the_same_gap(self) -> None:
        rows = self._formed_gap_rows() + [
            _row(3, high=110, low=106),  # first touch -> signal, shrinks to (105, 106)
            _row(4, high=108, low=105.5),  # re-touches the (still open) shrunk zone
        ]
        states = compute_fvg_states(_frame(rows))

        self.assertIsNotNone(states[3].bullish_signal)
        self.assertIsNone(states[4].bullish_signal)


class BearishGapMirrorTest(unittest.TestCase):
    def test_gap_forms_when_high_below_low_two_candles_back(self) -> None:
        rows = [
            _row(0, high=100, low=95),
            _row(1, high=99, low=94),
            _row(2, high=93, low=88),  # high(93) < low[0](95) -> bearish gap zone [93, 95]
        ]
        states = compute_fvg_states(_frame(rows))

        self.assertEqual(states[2].open_bearish_gaps, ((93.0, 95.0),))

    def test_touch_when_high_inside_zone(self) -> None:
        rows = [
            _row(0, high=100, low=95),
            _row(1, high=99, low=94),
            _row(2, high=93, low=88),
            _row(3, high=94, low=90),  # high(94) in [93, 95)
        ]
        states = compute_fvg_states(_frame(rows))

        signal = states[3].bearish_signal
        self.assertIsNotNone(signal)
        self.assertEqual(signal.direction, "bearish")
        self.assertEqual(signal.zone_top, 95.0)

    def test_full_fill_kills_the_bearish_gap(self) -> None:
        rows = [
            _row(0, high=100, low=95),
            _row(1, high=99, low=94),
            _row(2, high=93, low=88),
            _row(3, high=96, low=90),  # high(96) >= zone_top(95) -> fully filled
        ]
        states = compute_fvg_states(_frame(rows))

        self.assertIsNone(states[3].bearish_signal)
        self.assertEqual(states[3].open_bearish_gaps, ())


class ExpiryTest(unittest.TestCase):
    def test_gap_expires_after_100_candles_untouched(self) -> None:
        rows = [
            _row(0, high=105, low=100),
            _row(1, high=110, low=99),  # raised, same cascade-avoidance reason as above
            _row(2, high=112, low=107),  # gap forms at index 2, zone [105, 107]
        ]
        # Flat, self-identical filler candles at a level safely above zone_top (107) —
        # never touches or fills the zone, and (being identical to each other) never
        # independently satisfies the 2-back gap-formation condition once the window
        # has fully slid past the original candles.
        for i in range(3, 3 + FVG_EXPIRY_CANDLES + 5):
            rows.append(_row(i, high=112, low=108))
        states = compute_fvg_states(_frame(rows))

        just_before_expiry = 2 + FVG_EXPIRY_CANDLES - 1
        just_after_expiry = 2 + FVG_EXPIRY_CANDLES
        self.assertEqual(states[just_before_expiry].open_bullish_gaps, ((105.0, 107.0),))
        self.assertEqual(states[just_after_expiry].open_bullish_gaps, ())


class MaxOpenGapsTest(unittest.TestCase):
    def test_open_gaps_never_exceed_the_cap(self) -> None:
        # A steep monotonic staircase legitimately forms a NEW gap at almost every
        # index (gap formation is re-checked fresh each candle against whatever sits
        # exactly 2 positions back — this cascading is correct per the spec, not a
        # fixture artifact, see BullishGapTouchTest._formed_gap_rows). This test only
        # asserts the cap itself, regardless of exactly how many gaps cascade into
        # existence along the way.
        rows = [_row(k, high=100 * (k + 1) + 10, low=100 * (k + 1)) for k in range(15)]
        states = compute_fvg_states(_frame(rows))

        for state in states:
            self.assertLessEqual(len(state.open_bullish_gaps), FVG_MAX_OPEN_PER_DIRECTION)

    def test_earliest_gap_is_evicted_once_the_cap_is_exceeded(self) -> None:
        rows = [_row(k, high=100 * (k + 1) + 10, low=100 * (k + 1)) for k in range(15)]
        states = compute_fvg_states(_frame(rows))

        first_possible_gap_bottom = 110.0  # high[0] = 100*(0+1)+10
        final_bottoms = [bottom for bottom, _ in states[-1].open_bullish_gaps]
        self.assertNotIn(first_possible_gap_bottom, final_bottoms)


class AttachFvgColumnsTest(unittest.TestCase):
    def test_produces_expected_columns(self) -> None:
        rows = [
            _row(0, high=105, low=100),
            _row(1, high=104, low=99),
            _row(2, high=112, low=107),
            _row(3, high=110, low=106),
        ]
        enriched = attach_fvg_columns(_frame(rows))

        for column in (
            "fvg_bullish_signal_zone_bottom",
            "fvg_bullish_signal_remaining_top",
            "fvg_bearish_signal_zone_top",
            "fvg_bearish_signal_remaining_bottom",
            "fvg_open_bullish_gaps",
            "fvg_open_bearish_gaps",
        ):
            self.assertIn(column, enriched.columns)
        self.assertEqual(enriched["fvg_bullish_signal_zone_bottom"].iloc[3], 105.0)
        self.assertTrue(pd.isna(enriched["fvg_bullish_signal_zone_bottom"].iloc[0]))


class AnyBullishGapOverlapsRangeTest(unittest.TestCase):
    def test_overlapping_range_returns_true(self) -> None:
        gaps = ((100.0, 110.0),)
        self.assertTrue(any_bullish_gap_overlaps_range(gaps, range_low=105.0, range_high=120.0))

    def test_non_overlapping_range_returns_false(self) -> None:
        gaps = ((100.0, 110.0),)
        self.assertFalse(any_bullish_gap_overlaps_range(gaps, range_low=120.0, range_high=130.0))

    def test_empty_gaps_returns_false(self) -> None:
        self.assertFalse(any_bullish_gap_overlaps_range((), range_low=0.0, range_high=1000.0))


if __name__ == "__main__":
    unittest.main()
