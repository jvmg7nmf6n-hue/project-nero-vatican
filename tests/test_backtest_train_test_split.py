from __future__ import annotations

import unittest

import pandas as pd

from tools.backtest_train_test_split import split_chronological


def _make_candles(n: int) -> pd.DataFrame:
    rows = []
    for i in range(n):
        close_time = i * 3_600_000
        rows.append(
            {
                "date": pd.Timestamp(close_time, unit="ms", tz="UTC"),
                "open_time": close_time - 3_600_000,
                "close_time": close_time,
                "open": 100.0 + i,
                "high": 101.0 + i,
                "low": 99.0 + i,
                "close": 100.5 + i,
                "volume": 10.0,
            }
        )
    return pd.DataFrame(rows)


class SplitChronologicalTest(unittest.TestCase):
    def test_splits_by_count_at_70_30(self) -> None:
        candles = _make_candles(100)

        train, test = split_chronological(candles)

        self.assertEqual(len(train), 70)
        self.assertEqual(len(test), 30)

    def test_train_is_strictly_earlier_than_test(self) -> None:
        candles = _make_candles(100)

        train, test = split_chronological(candles)

        self.assertLess(train["close_time"].max(), test["close_time"].min())

    def test_no_candle_appears_in_both_halves(self) -> None:
        candles = _make_candles(50)

        train, test = split_chronological(candles)

        train_times = set(train["close_time"])
        test_times = set(test["close_time"])
        self.assertEqual(train_times & test_times, set())
        self.assertEqual(len(train_times) + len(test_times), 50)

    def test_split_is_not_randomized_input_order_does_not_matter(self) -> None:
        ordered = _make_candles(20)
        shuffled = ordered.sample(frac=1, random_state=42).reset_index(drop=True)

        train_ordered, test_ordered = split_chronological(ordered)
        train_shuffled, test_shuffled = split_chronological(shuffled)

        self.assertEqual(sorted(train_ordered["close_time"].tolist()), sorted(train_shuffled["close_time"].tolist()))
        self.assertEqual(sorted(test_ordered["close_time"].tolist()), sorted(test_shuffled["close_time"].tolist()))

    def test_custom_train_fraction(self) -> None:
        candles = _make_candles(100)

        train, test = split_chronological(candles, train_fraction=0.5)

        self.assertEqual(len(train), 50)
        self.assertEqual(len(test), 50)

    def test_empty_input_returns_two_empty_frames(self) -> None:
        train, test = split_chronological(pd.DataFrame())

        self.assertTrue(train.empty)
        self.assertTrue(test.empty)


if __name__ == "__main__":
    unittest.main()
