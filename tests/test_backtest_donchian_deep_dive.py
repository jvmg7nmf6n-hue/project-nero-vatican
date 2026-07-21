from __future__ import annotations

import unittest

import pandas as pd

from nero_core.strategies import donchian_breakout_bracket as dbb
from tools.backtest_donchian_deep_dive import (
    _apply_grid_shift_cap,
    _half_stats,
    donchian_bracket_eligible_mask,
)


class ApplyGridShiftCapTest(unittest.TestCase):
    def test_raw_survived_capped_to_promising_watchlist_1week(self) -> None:
        verdict, note = _apply_grid_shift_cap("SURVIVED", "1week")
        self.assertEqual(verdict, "PROMISING-WATCHLIST")
        self.assertIn("settlement gap", note)

    def test_raw_survived_capped_to_promising_watchlist_1day(self) -> None:
        verdict, note = _apply_grid_shift_cap("SURVIVED", "1day")
        self.assertEqual(verdict, "PROMISING-WATCHLIST")
        self.assertIn("recent window", note)

    def test_non_survived_verdicts_pass_through_unchanged(self) -> None:
        for v in ("PROMISING-WATCHLIST", "DIED"):
            verdict, note = _apply_grid_shift_cap(v, "1week")
            self.assertEqual(verdict, v)
            self.assertIsNone(note)


class DonchianBracketEligibleMaskTest(unittest.TestCase):
    def test_true_everywhere(self) -> None:
        evaluable = pd.DataFrame({"close": [1.0, 2.0, 3.0]})
        mask = donchian_bracket_eligible_mask(evaluable)
        self.assertTrue(mask.all())
        self.assertEqual(len(mask), 3)


def _candles(rows: list[tuple[float, float, float, float]], start: str = "2024-01-01") -> pd.DataFrame:
    out = []
    ts = pd.Timestamp(start, tz="UTC")
    for i, (o, h, l, c) in enumerate(rows):
        day = ts + pd.Timedelta(days=i)
        close_time = int(day.timestamp() * 1000)
        out.append({
            "date": day, "open_time": close_time - 86_400_000, "close_time": close_time,
            "open": o, "high": h, "low": l, "close": c, "volume": 1000.0,
        })
    return pd.DataFrame(out)


class HalfStatsTest(unittest.TestCase):
    def test_produces_expected_shape_and_fields(self) -> None:
        flat = [(10, 10, 9, 10)] * 5
        breakout = [(10, 30, 10, 30)]
        follow_through = [(30, 60, 30, 60)] * 3
        rows = flat + breakout + follow_through
        params = dbb.DonchianBracketParameters(channel_period=3, atr_period=3)
        stats = _half_stats(_candles(rows), params)
        self.assertIn("trades", stats)
        self.assertIn("expectancy_r", stats)
        self.assertIn("below_min_sample", stats)
        self.assertIn("ci", stats)
        self.assertIn("baseline", stats)
        self.assertGreaterEqual(stats["trades"], 1)
        self.assertTrue(stats["below_min_sample"])  # far fewer than MIN_SAMPLE_SIZE=20 trades

    def test_zero_trades_produces_zero_expectancy_and_no_ci(self) -> None:
        flat = [(10, 10, 9, 10)] * 10  # never breaks out
        params = dbb.DonchianBracketParameters(channel_period=3, atr_period=3)
        stats = _half_stats(_candles(flat), params)
        self.assertEqual(stats["trades"], 0)
        self.assertEqual(stats["expectancy_r"], 0.0)
        self.assertIsNone(stats["ci"])


if __name__ == "__main__":
    unittest.main()
