from __future__ import annotations

import unittest

import pandas as pd

from nero_core.strategies.bos_detection import attach_bos_columns, compute_bos_states

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


def _swing_high_setup(peak: float = 110.0) -> list[dict[str, object]]:
    """A clean, isolated swing high at index 5 (peak), with 5 flat-and-lower candles on
    each side, confirmed exactly at index 10."""
    return [
        _row(0, high=100, low=95, close=98),
        _row(1, high=101, low=96, close=99),
        _row(2, high=102, low=97, close=100),
        _row(3, high=101, low=96, close=99),
        _row(4, high=100, low=95, close=98),
        _row(5, high=peak, low=100, close=105),
        _row(6, high=105, low=100, close=102),
        _row(7, high=104, low=99, close=101),
        _row(8, high=103, low=98, close=100),
        _row(9, high=102, low=97, close=99),
        _row(10, high=101, low=96, close=98),
    ]


class PivotConfirmationTimingTest(unittest.TestCase):
    def test_pivot_is_not_usable_before_confirmation_even_if_close_would_break_it(self) -> None:
        rows = _swing_high_setup(peak=110.0)
        # Candle 9's close exceeds the (not-yet-confirmed) peak of 110.
        rows[9]["close"] = 115.0
        states = compute_bos_states(_frame(rows))

        self.assertIsNone(states[9].bos_up_signal)

    def test_pivot_can_be_broken_on_the_very_candle_it_confirms(self) -> None:
        rows = _swing_high_setup(peak=110.0)
        rows[10]["close"] = 111.0  # confirmed AND broken at the same candle (index 10)
        states = compute_bos_states(_frame(rows))

        signal = states[10].bos_up_signal
        self.assertIsNotNone(signal)
        self.assertEqual(signal.broken_pivot_value, 110.0)
        self.assertEqual(signal.broken_pivot_formed_index, 5)

    def test_no_signal_when_close_never_exceeds_the_confirmed_pivot(self) -> None:
        rows = _swing_high_setup(peak=110.0)
        states = compute_bos_states(_frame(rows))

        for state in states:
            self.assertIsNone(state.bos_up_signal)


class OneShotBreakTest(unittest.TestCase):
    def test_pivot_does_not_refire_after_its_first_break(self) -> None:
        rows = _swing_high_setup(peak=110.0)
        rows[10]["close"] = 111.0  # first break
        rows.append(_row(11, high=112, low=108, close=113))  # closes even higher, same pivot

        states = compute_bos_states(_frame(rows))

        self.assertIsNotNone(states[10].bos_up_signal)
        self.assertIsNone(states[11].bos_up_signal)


class SupersessionTest(unittest.TestCase):
    def test_a_newly_confirmed_pivot_replaces_the_active_one(self) -> None:
        rows = _swing_high_setup(peak=110.0)
        # No break yet. Add a second, higher swing high later, isolated the same way.
        rows += [
            _row(11, high=106, low=101, close=103),
            _row(12, high=107, low=102, close=104),
            _row(13, high=108, low=103, close=105),
            _row(14, high=109, low=104, close=106),
            _row(15, high=120, low=110, close=112),  # new peak candidate
            _row(16, high=115, low=110, close=111),
            _row(17, high=114, low=109, close=110),
            _row(18, high=113, low=108, close=109),
            _row(19, high=112, low=107, close=108),
            _row(20, high=111, low=106, close=107),  # confirms pivot@15 (value 120)
        ]
        states = compute_bos_states(_frame(rows))

        # A close that would have broken the FIRST pivot (110) but not the new one
        # (120) must NOT fire, since the active pivot is now the newer, higher one.
        rows[-1]["close"] = 115.0  # > 110 (old pivot) but < 120 (new active pivot)
        states = compute_bos_states(_frame(rows))
        self.assertIsNone(states[20].bos_up_signal)


class PrecedingExtremeTest(unittest.TestCase):
    def test_bos_up_reports_the_preceding_confirmed_swing_low(self) -> None:
        # A swing low candidate needs 5 candles before it too, so it can't sit any
        # earlier than index 5. Swing low confirmed BEFORE the swing high, then the
        # swing high breaks.
        rows = [
            _row(0, high=100, low=90, close=95),
            _row(1, high=101, low=91, close=96),
            _row(2, high=102, low=92, close=97),
            _row(3, high=101, low=91, close=96),
            _row(4, high=100, low=92, close=97),
            _row(5, high=99, low=80, close=90),  # swing low candidate (value 80)
            _row(6, high=98, low=94, close=98),
            _row(7, high=97, low=95, close=99),
            _row(8, high=96, low=94, close=98),
            _row(9, high=95, low=93, close=97),
            _row(10, high=94, low=92, close=96),  # confirms swing low @ index5 (value 80)
        ]
        # Now build an isolated swing high starting a bit later.
        rows += [
            _row(11, high=100, low=95, close=99),
            _row(12, high=101, low=96, close=100),
            _row(13, high=102, low=97, close=100),
            _row(14, high=101, low=96, close=99),
            _row(15, high=100, low=95, close=98),
            _row(16, high=110, low=100, close=105),  # swing high candidate
            _row(17, high=105, low=100, close=102),
            _row(18, high=104, low=99, close=101),
            _row(19, high=103, low=98, close=100),
            _row(20, high=102, low=97, close=99),
            _row(21, high=101, low=96, close=112),  # confirms + breaks pivot@16 (value 110)
        ]
        states = compute_bos_states(_frame(rows))

        signal = states[21].bos_up_signal
        self.assertIsNotNone(signal)
        self.assertEqual(signal.broken_pivot_formed_index, 16)
        self.assertEqual(signal.preceding_extreme_value, 80.0)
        self.assertEqual(signal.preceding_extreme_formed_index, 5)

    def test_no_preceding_extreme_returns_none(self) -> None:
        rows = _swing_high_setup(peak=110.0)
        rows[10]["close"] = 111.0
        states = compute_bos_states(_frame(rows))

        signal = states[10].bos_up_signal
        self.assertIsNotNone(signal)
        self.assertIsNone(signal.preceding_extreme_value)
        self.assertIsNone(signal.preceding_extreme_formed_index)


class AttachBosColumnsTest(unittest.TestCase):
    def test_produces_expected_columns_and_recent_index_tracking(self) -> None:
        rows = _swing_high_setup(peak=110.0)
        rows[10]["close"] = 111.0
        rows.append(_row(11, high=101, low=96, close=100))
        enriched = attach_bos_columns(_frame(rows))

        for column in (
            "bos_up_signal_pivot_value",
            "bos_up_signal_pivot_index",
            "bos_up_signal_preceding_low",
            "bos_down_signal_pivot_value",
            "bos_down_signal_pivot_index",
            "bos_down_signal_preceding_high",
            "bos_up_recent_index",
            "bos_down_recent_index",
        ):
            self.assertIn(column, enriched.columns)

        self.assertTrue(pd.isna(enriched["bos_up_recent_index"].iloc[9]))
        self.assertEqual(enriched["bos_up_recent_index"].iloc[10], 10)
        self.assertEqual(enriched["bos_up_recent_index"].iloc[11], 10)  # carried forward


if __name__ == "__main__":
    unittest.main()
