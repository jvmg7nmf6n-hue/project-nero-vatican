from __future__ import annotations

import unittest

import pandas as pd

from tools.backtest_timeframe_sweep import aggregate_n_consecutive_candles


def _daily_candle(day_index: int, open_: float, high: float, low: float, close: float, volume: float = 10.0) -> dict[str, object]:
    close_time = (day_index + 1) * 86_400_000
    open_time = day_index * 86_400_000
    return {
        "date": pd.Timestamp(close_time, unit="ms", tz="UTC"),
        "open_time": open_time,
        "close_time": close_time,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


class AggregateConsecutiveCandlesTest(unittest.TestCase):
    def test_groups_n_consecutive_candles_with_correct_ohlcv(self) -> None:
        # Two daily candles -> one 48h candle.
        candles = pd.DataFrame(
            [
                _daily_candle(0, open_=100.0, high=105.0, low=98.0, close=102.0, volume=10.0),
                _daily_candle(1, open_=102.0, high=110.0, low=101.0, close=108.0, volume=20.0),
            ]
        )

        resampled = aggregate_n_consecutive_candles(candles, 2)

        self.assertEqual(len(resampled), 1)
        row = resampled.iloc[0]
        self.assertEqual(row["open"], 100.0)  # first candle's open
        self.assertEqual(row["high"], 110.0)  # max of both highs
        self.assertEqual(row["low"], 98.0)  # min of both lows
        self.assertEqual(row["close"], 108.0)  # last candle's close
        self.assertEqual(row["volume"], 30.0)  # sum of both volumes
        self.assertEqual(row["open_time"], candles.iloc[0]["open_time"])
        self.assertEqual(row["close_time"], candles.iloc[1]["close_time"])

    def test_drops_trailing_partial_group_no_lookahead(self) -> None:
        # 5 daily candles grouped by 2 -> 2 complete groups, 1 leftover candle dropped.
        candles = pd.DataFrame([_daily_candle(i, 100.0 + i, 101.0 + i, 99.0 + i, 100.5 + i) for i in range(5)])

        resampled = aggregate_n_consecutive_candles(candles, 2)

        self.assertEqual(len(resampled), 2)
        # the 5th (index 4) candle must not appear in any resampled bar's close_time
        last_source_close_time = candles.iloc[4]["close_time"]
        self.assertNotIn(last_source_close_time, resampled["close_time"].tolist())

    def test_grouping_by_15_matches_expected_bar_count(self) -> None:
        candles = pd.DataFrame([_daily_candle(i, 100.0, 101.0, 99.0, 100.5) for i in range(47)])  # 47 // 15 = 3

        resampled = aggregate_n_consecutive_candles(candles, 15)

        self.assertEqual(len(resampled), 3)

    def test_fewer_than_n_candles_returns_empty(self) -> None:
        candles = pd.DataFrame([_daily_candle(0, 100.0, 101.0, 99.0, 100.5)])

        resampled = aggregate_n_consecutive_candles(candles, 2)

        self.assertTrue(resampled.empty)

    def test_empty_input_returns_empty(self) -> None:
        resampled = aggregate_n_consecutive_candles(pd.DataFrame(), 2)

        self.assertTrue(resampled.empty)

    def test_output_columns_match_candle_contract(self) -> None:
        candles = pd.DataFrame([_daily_candle(i, 100.0, 101.0, 99.0, 100.5) for i in range(4)])

        resampled = aggregate_n_consecutive_candles(candles, 2)

        self.assertEqual(list(resampled.columns), ["date", "open_time", "close_time", "open", "high", "low", "close", "volume"])


if __name__ == "__main__":
    unittest.main()
