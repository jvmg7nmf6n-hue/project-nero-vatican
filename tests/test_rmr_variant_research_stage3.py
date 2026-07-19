from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from nero_core.data_sources.market_data import MarketDataUnavailableError
from tests.test_council_engine import _make_candle_row
from tools.rmr_variant_research_stage3 import _qualifies, run_refinement1_btc_1d, run_refinement2_eth_4h


class QualifiesTest(unittest.TestCase):
    def test_qualifies_when_positive_and_adequate_both_halves(self) -> None:
        train = {"trades": 25, "expectancy_r": 0.1}
        test = {"trades": 20, "expectancy_r": 0.05}
        self.assertTrue(_qualifies(train, test))

    def test_does_not_qualify_below_min_sample(self) -> None:
        train = {"trades": 19, "expectancy_r": 0.1}
        test = {"trades": 20, "expectancy_r": 0.05}
        self.assertFalse(_qualifies(train, test))

    def test_does_not_qualify_negative_half(self) -> None:
        train = {"trades": 25, "expectancy_r": 0.1}
        test = {"trades": 20, "expectancy_r": -0.05}
        self.assertFalse(_qualifies(train, test))


def _history(n: int = 300, hours_per_candle: int = 4) -> pd.DataFrame:
    rows = []
    close_time = 0
    for i in range(n):
        close = 100.0 + (3.0 if i % 4 < 2 else -3.0)
        rows.append(_make_candle_row(close_time, close))
        close_time += hours_per_candle * 3_600_000
    return pd.DataFrame(rows)


def _hourly_history_with_open_time(n: int = 300) -> pd.DataFrame:
    """resample_hourly_to_grid needs an open_time column that _make_candle_row
    doesn't provide — a dedicated 1h fixture for Refinement 2's grid-shift path."""
    rows = []
    close_time = 3_600_000
    for i in range(n):
        close = 100.0 + (3.0 if i % 4 < 2 else -3.0)
        row = _make_candle_row(close_time, close)
        row["open_time"] = close_time - 3_600_000
        rows.append(row)
        close_time += 3_600_000
    return pd.DataFrame(rows)


class RunRefinement1SmokeTest(unittest.TestCase):
    def test_runs_without_error(self) -> None:
        history = _history()
        with patch("tools.rmr_variant_research_stage3.fetch_timeframe_candles", return_value=(history, "test-fixture")):
            result = run_refinement1_btc_1d()
        self.assertIn("train", result)
        self.assertIn("grid_shift", result)
        self.assertIn("NOT_APPLICABLE", result["grid_shift"])

    def test_fetch_failure_reports_error_not_crash(self) -> None:
        with patch("tools.rmr_variant_research_stage3.fetch_timeframe_candles", side_effect=MarketDataUnavailableError("no data")):
            result = run_refinement1_btc_1d()
        self.assertIn("error", result)


class RunRefinement2SmokeTest(unittest.TestCase):
    def test_runs_without_error_and_skips_grid_shift_when_not_qualifying(self) -> None:
        history = _hourly_history_with_open_time(n=300)
        fake_client = MagicMock()
        fake_client.load_intraday.return_value = MagicMock(prices=history)
        with patch("tools.rmr_variant_research_stage3.MarketDataClient", return_value=fake_client):
            result = run_refinement2_eth_4h()
        self.assertIn("train", result)
        self.assertFalse(result["qualifies_control"])
        self.assertEqual(result["grid_results"], [])

    def test_fetch_failure_reports_error_not_crash(self) -> None:
        fake_client = MagicMock()
        fake_client.load_intraday.side_effect = MarketDataUnavailableError("no data")
        with patch("tools.rmr_variant_research_stage3.MarketDataClient", return_value=fake_client):
            result = run_refinement2_eth_4h()
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
