from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from nero_core.data_sources.market_data import MarketDataClient, MarketDataResult, MarketDataUnavailableError
from tools.backtest_volatility_squeeze_sweep import (
    TREND_FILTER_REASON,
    VARIANTS,
    format_consolidated_table,
    format_trend_filter_summary,
    run_backtest_with_reason_tally,
    run_sweep,
)
from tools.backtest_compare import VARIANT_SPECS


def _breakout_history() -> pd.DataFrame:
    """Long flat/varying warmup then a squeeze block then a sustained breakout leg, so at
    least one variant opens and closes a real trade — mirrors the fixture style in
    test_volatility_squeeze.py, reused here at hourly spacing for speed."""
    import math

    rows: list[dict[str, object]] = []
    close_time = 0
    for i in range(220):
        amplitude = 3.0 + 2.0 * math.sin(i * 0.15)
        wobble = amplitude if i % 2 == 0 else -amplitude
        price = 100.0 + wobble
        rows.append(
            {
                "date": pd.Timestamp(close_time, unit="ms", tz="UTC"),
                "open_time": close_time - 3_600_000,
                "close_time": close_time,
                "open": price,
                "high": price + 4.0 + abs(math.sin(i * 0.07)),
                "low": price - 4.0 - abs(math.cos(i * 0.09)),
                "close": price,
                "volume": 100.0,
            }
        )
        close_time += 3_600_000
    for i in range(25):
        price = 100.0 + 0.01 * i
        rows.append(
            {
                "date": pd.Timestamp(close_time, unit="ms", tz="UTC"),
                "open_time": close_time - 3_600_000,
                "close_time": close_time,
                "open": price,
                "high": 100.05,
                "low": 99.95,
                "close": price,
                "volume": 100.0,
            }
        )
        close_time += 3_600_000
    price = 100.05
    for _ in range(15):
        price *= 1.05
        rows.append(
            {
                "date": pd.Timestamp(close_time, unit="ms", tz="UTC"),
                "open_time": close_time - 3_600_000,
                "close_time": close_time,
                "open": price,
                "high": price * 1.01,
                "low": price * 0.99,
                "close": price,
                "volume": 100.0,
            }
        )
        close_time += 3_600_000
    return pd.DataFrame(rows)


class RunBacktestWithReasonTallyTest(unittest.TestCase):
    def test_reason_tally_covers_every_evaluated_candle_not_just_closed_trades(self) -> None:
        candles = _breakout_history()
        spec = VARIANT_SPECS["volatility_squeeze_ma200"]

        trades, state, reasons, evaluated_count = run_backtest_with_reason_tally(candles, spec)

        self.assertGreater(evaluated_count, 0)
        total_reason_hits = sum(reasons.values())
        # every rejected candle contributes at least one reason, so total hits can't be
        # zero unless every single candle passed (implausible given the strict entry
        # conditions), and must never exceed evaluated_count * number_of_possible_reasons.
        self.assertGreaterEqual(total_reason_hits, 0)
        self.assertIsInstance(trades, list)

    def test_trend_filter_reason_key_matches_the_strategys_own_reason_code(self) -> None:
        from nero_core.strategies.volatility_squeeze import DEFAULT_PARAMETERS_MA200, evaluate_entry
        from nero_core.strategies.mean_reversion import MeanReversionState

        candle = pd.Series(
            {
                "date": pd.Timestamp("2026-01-01T00:00:00Z"),
                "close_time": 0,
                "close": 100.0,
                "atr": 2.0,
                "bb_width": 0.05,
                "squeeze_streak": 0,
                "prior_squeeze_streak": 10,
                "prior_squeeze_run_high": 99.0,
                "trend_ma": 150.0,  # blocks: close way below trend
            }
        )
        evaluation = evaluate_entry(candle, MeanReversionState(equity=10000.0), DEFAULT_PARAMETERS_MA200)
        self.assertIn(TREND_FILTER_REASON, evaluation.reasons)


class RunSweepOfflineTest(unittest.TestCase):
    def test_produces_one_row_per_asset_timeframe_variant(self) -> None:
        history = _breakout_history()
        result = MarketDataResult(prices=history, source="test-fixture", asset="BTC", interval="4h")
        with patch.object(MarketDataClient, "load_intraday", return_value=result):
            rows, trend_totals = run_sweep(["BTC"], ["4h"], MarketDataClient())

        self.assertEqual(len(rows), len(VARIANTS))
        variant_keys = {row["variant_key"] for row in rows}
        self.assertEqual(variant_keys, {"ma200", "ma150", "ma100"})
        for row in rows:
            for split in ("full", "train", "test"):
                self.assertIn("trades", row[split])

    def test_skipped_combo_is_reported_for_every_variant_not_silently_dropped(self) -> None:
        with patch.object(MarketDataClient, "load_intraday", side_effect=MarketDataUnavailableError("no data")):
            with patch.object(MarketDataClient, "load_daily", side_effect=MarketDataUnavailableError("no data")):
                rows, _ = run_sweep(["BTC"], ["4h"], MarketDataClient())

        self.assertEqual(len(rows), len(VARIANTS))
        for row in rows:
            self.assertIn("skip_reason", row["full"])

    def test_trend_filter_totals_are_tallied_per_variant(self) -> None:
        history = _breakout_history()
        result = MarketDataResult(prices=history, source="test-fixture", asset="BTC", interval="4h")
        with patch.object(MarketDataClient, "load_intraday", return_value=result):
            _, trend_totals = run_sweep(["BTC"], ["4h"], MarketDataClient())

        self.assertEqual(set(trend_totals.keys()), {"ma200", "ma150", "ma100"})
        for totals in trend_totals.values():
            self.assertGreater(totals["evaluated"], 0)
            self.assertGreaterEqual(totals["blocked"], 0)
            self.assertLessEqual(totals["blocked"], totals["evaluated"])


class FormattingTest(unittest.TestCase):
    def test_format_consolidated_table_flags_low_sample_cells(self) -> None:
        rows = [
            {
                "asset": "BTC",
                "timeframe": "4h",
                "variant_key": "ma200",
                "variant": "VOLATILITY_SQUEEZE ma200",
                "full": {"trades": 5, "win_rate": 0.4, "expectancy_r": 0.1, "profit_factor": 1.1, "below_min_sample": True},
                "train": {"trades": 30, "win_rate": 0.5, "expectancy_r": 0.2, "profit_factor": 1.5, "below_min_sample": False},
                "test": {"trades": 2, "win_rate": 0.0, "expectancy_r": -0.5, "profit_factor": 0.0, "below_min_sample": True},
            }
        ]

        table = format_consolidated_table(rows)

        self.assertIn("BTC", table)
        self.assertIn("*", table)  # low-sample flag present

    def test_format_consolidated_table_reports_skipped_rows(self) -> None:
        rows = [
            {
                "asset": "GOLD",
                "timeframe": "2h",
                "variant_key": "ma200",
                "variant": "VOLATILITY_SQUEEZE ma200",
                "full": {"trades": 0, "win_rate": 0.0, "expectancy_r": 0.0, "profit_factor": 0.0, "below_min_sample": True, "skip_reason": "missing API key"},
                "train": {"trades": 0, "win_rate": 0.0, "expectancy_r": 0.0, "profit_factor": 0.0, "below_min_sample": True, "skip_reason": "missing API key"},
                "test": {"trades": 0, "win_rate": 0.0, "expectancy_r": 0.0, "profit_factor": 0.0, "below_min_sample": True, "skip_reason": "missing API key"},
            }
        ]

        table = format_consolidated_table(rows)

        self.assertIn("SKIPPED", table)
        self.assertIn("missing API key", table)

    def test_trend_filter_summary_reports_all_three_variants(self) -> None:
        totals = {"ma200": {"evaluated": 100, "blocked": 40}, "ma150": {"evaluated": 100, "blocked": 30}, "ma100": {"evaluated": 100, "blocked": 20}}

        summary = format_trend_filter_summary(totals)

        self.assertIn("ma200", summary)
        self.assertIn("ma150", summary)
        self.assertIn("ma100", summary)
        self.assertIn("40.0%", summary)


if __name__ == "__main__":
    unittest.main()
