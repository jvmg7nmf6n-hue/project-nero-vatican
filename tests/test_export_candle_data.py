from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from nero_core.data_sources.forex_data import ForexDataResult
from nero_core.data_sources.stock_data import StockDataResult
from nero_core.execution import export_candle_data
from nero_core.execution.export_candle_data import (
    IN_SCOPE_PAIRS,
    _already_fresh,
    candle_filename,
    export_candle_data as run_export,
    sanitize_asset_for_filename,
)

# Real weekday alignment: 2026-07-24 is a Friday (matches candle_boundary_due's
# WEEKLY_CLOSE_WEEKDAY=4 constant), 2026-07-27 is the following Monday.
NOW_24H_DUE = datetime(2026, 7, 27, 0, 10, tzinfo=timezone.utc)
NOW_1WEEK_DUE = datetime(2026, 7, 24, 0, 10, tzinfo=timezone.utc)
NOW_12H_DUE = datetime(2026, 7, 27, 12, 5, tzinfo=timezone.utc)
NOW_NOTHING_DUE = datetime(2026, 7, 27, 6, 0, tzinfo=timezone.utc)


def _make_candles(n: int = 5, start_ms: int = 0, step_ms: int = 86_400_000, volume: float = 1000.0) -> pd.DataFrame:
    rows = []
    t = start_ms
    price = 100.0
    for _ in range(n):
        rows.append(
            {
                "date": pd.Timestamp(t, unit="ms", tz="UTC"),
                "open_time": t,
                "close_time": t + step_ms,
                "open": price,
                "high": price + 1.0,
                "low": price - 1.0,
                "close": price + 0.5,
                "volume": volume,
            }
        )
        t += step_ms
        price += 1.0
    return pd.DataFrame(rows)


class SanitizationTest(unittest.TestCase):
    def test_forex_slash_is_stripped(self) -> None:
        self.assertEqual(sanitize_asset_for_filename("EUR/USD"), "EURUSD")
        self.assertEqual(sanitize_asset_for_filename("GBP/USD"), "GBPUSD")
        self.assertEqual(sanitize_asset_for_filename("USD/JPY"), "USDJPY")

    def test_non_forex_asset_is_unchanged(self) -> None:
        self.assertEqual(sanitize_asset_for_filename("BTC"), "BTC")
        self.assertEqual(sanitize_asset_for_filename("GOLD"), "GOLD")

    def test_candle_filename_combines_sanitized_asset_and_timeframe(self) -> None:
        self.assertEqual(candle_filename("EUR/USD", "1week"), "EURUSD_1week.json")
        self.assertEqual(candle_filename("BTC", "24h"), "BTC_24h.json")


class InScopePairsTest(unittest.TestCase):
    def test_pair_strategy_assets_are_excluded(self) -> None:
        assets = [p.asset for p in IN_SCOPE_PAIRS]
        self.assertNotIn("BTC-ETH", assets)
        self.assertNotIn("GOLD-SILVER", assets)

    def test_eth_is_not_included_since_it_has_no_standalone_roster_entry(self) -> None:
        assets = [p.asset for p in IN_SCOPE_PAIRS]
        self.assertNotIn("ETH", assets)

    def test_expected_pair_count(self) -> None:
        self.assertEqual(len(IN_SCOPE_PAIRS), 18)

    def test_eurusd_4h_is_included_as_a_deliberate_pre_roster_exception(self) -> None:
        # See the IN_SCOPE_PAIRS docstring's RMR_LONG_ONLY_EURUSD_4H EXCEPTION
        # note: added ahead of a live roster entry, using forex_data.py's
        # already-confirmed native 4h Twelve Data interval -- no resampling.
        pair = next(p for p in IN_SCOPE_PAIRS if p.asset == "EUR/USD" and p.timeframe == "4h")
        self.assertEqual(pair.cadence_timeframe, "4h")
        self.assertEqual(pair.fetch_family, "forex")

    def test_no_duplicate_asset_timeframe_pairs(self) -> None:
        keys = [(p.asset, p.timeframe) for p in IN_SCOPE_PAIRS]
        self.assertEqual(len(keys), len(set(keys)))

    def test_btc_12h_is_included_as_a_deliberate_pre_roster_exception(self) -> None:
        # See the IN_SCOPE_PAIRS docstring's Day 7 EXCEPTION note: added ahead of
        # a live roster entry, using the same Binance 12h fetch path as BNB/12h.
        pair = next(p for p in IN_SCOPE_PAIRS if p.asset == "BTC" and p.timeframe == "12h")
        self.assertEqual(pair.cadence_timeframe, "12h")
        self.assertEqual(pair.fetch_family, "crypto_metals")


class AlreadyFreshTest(unittest.TestCase):
    """Direct unit coverage of the "4h" branch added alongside EUR/USD/4h --
    previously unhandled (fell through to the unconditional `return False`),
    which would have meant EUR/USD/4h was refetched on every scheduler tick
    inside the same ~40-minute due window instead of once per real 4h close."""

    def test_same_4h_bucket_is_fresh(self) -> None:
        existing = datetime(2026, 7, 24, 0, 10, tzinfo=timezone.utc)
        now = existing.replace(minute=30)  # same day, same hour -- same 4h bucket
        self.assertTrue(_already_fresh(existing, "4h", now))

    def test_different_4h_bucket_is_not_fresh(self) -> None:
        existing = datetime(2026, 7, 24, 0, 10, tzinfo=timezone.utc)
        now = datetime(2026, 7, 24, 4, 5, tzinfo=timezone.utc)  # next 4h bucket
        self.assertFalse(_already_fresh(existing, "4h", now))

    def test_no_existing_file_is_never_fresh(self) -> None:
        self.assertFalse(_already_fresh(None, "4h", datetime(2026, 7, 24, 0, 10, tzinfo=timezone.utc)))


class ExportCandleDataTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.output_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _patch_all_fetchers(self, crypto_metals_frame=None, forex_frame=None, stock_frame=None):
        crypto_metals_frame = crypto_metals_frame if crypto_metals_frame is not None else _make_candles()
        forex_frame = forex_frame if forex_frame is not None else _make_candles()
        stock_frame = stock_frame if stock_frame is not None else _make_candles()

        return (
            patch.object(export_candle_data, "fetch_timeframe_candles", return_value=(crypto_metals_frame, "NATIVE: test")),
            patch.object(
                export_candle_data,
                "fetch_forex_ohlcv",
                return_value=ForexDataResult(forex_frame, "test", "EUR/USD", "1week"),
            ),
            patch.object(
                export_candle_data,
                "fetch_stock_ohlcv",
                return_value=StockDataResult(stock_frame, "test", "AAPL", "1day"),
            ),
        )

    def test_crypto_metals_pair_is_exported_with_correct_schema(self) -> None:
        p_ctc, p_forex, p_stock = self._patch_all_fetchers(crypto_metals_frame=_make_candles(n=3))
        with p_ctc, p_forex, p_stock:
            run_export(now=NOW_24H_DUE, output_dir=self.output_dir)

        path = self.output_dir / "BTC_24h.json"
        self.assertTrue(path.exists())
        payload = json.loads(path.read_text())
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["asset"], "BTC")
        self.assertEqual(payload["timeframe"], "24h")
        self.assertEqual(payload["last_updated"], NOW_24H_DUE.isoformat())
        self.assertEqual(len(payload["candles"]), 3)
        candle = payload["candles"][0]
        self.assertEqual(set(candle.keys()), {"time", "open", "high", "low", "close", "volume"})
        self.assertEqual(candle["volume"], 1000.0)  # crypto -- genuine volume, passed through

    def test_eurusd_4h_pair_is_exported_with_correct_schema_and_null_volume(self) -> None:
        p_ctc, p_forex, p_stock = self._patch_all_fetchers(forex_frame=_make_candles(n=3))
        with p_ctc, p_forex, p_stock:
            result = run_export(now=NOW_NOTHING_DUE.replace(minute=10), output_dir=self.output_dir, force=True)

        self.assertIn("EURUSD_4h.json", result.exported)
        payload = json.loads((self.output_dir / "EURUSD_4h.json").read_text())
        self.assertEqual(payload["asset"], "EUR/USD")
        self.assertEqual(payload["timeframe"], "4h")
        self.assertEqual(len(payload["candles"]), 3)
        for candle in payload["candles"]:
            self.assertIsNone(candle["volume"])  # same forex volume-honesty rule as EUR/USD/1week

    def test_forex_pair_is_exported_with_null_volume(self) -> None:
        p_ctc, p_forex, p_stock = self._patch_all_fetchers()
        with p_ctc, p_forex, p_stock:
            run_export(now=NOW_1WEEK_DUE, output_dir=self.output_dir)

        payload = json.loads((self.output_dir / "EURUSD_1week.json").read_text())
        self.assertEqual(payload["asset"], "EUR/USD")
        for candle in payload["candles"]:
            self.assertIsNone(candle["volume"])

    def test_gold_is_exported_with_null_volume_but_silver_is_not(self) -> None:
        p_ctc, p_forex, p_stock = self._patch_all_fetchers()
        with p_ctc, p_forex, p_stock:
            run_export(now=NOW_24H_DUE, output_dir=self.output_dir)

        gold_payload = json.loads((self.output_dir / "GOLD_24h.json").read_text())
        for candle in gold_payload["candles"]:
            self.assertIsNone(candle["volume"])

        silver_payload = json.loads((self.output_dir / "SILVER_24h.json").read_text())
        for candle in silver_payload["candles"]:
            self.assertIsNotNone(candle["volume"])

    def test_stock_pair_is_exported(self) -> None:
        p_ctc, p_forex, p_stock = self._patch_all_fetchers()
        with p_ctc, p_forex, p_stock:
            result = run_export(now=NOW_24H_DUE, output_dir=self.output_dir)

        self.assertIn("AAPL_1day.json", result.exported)
        payload = json.loads((self.output_dir / "AAPL_1day.json").read_text())
        self.assertEqual(payload["timeframe"], "1day")

    def test_candles_are_ordered_oldest_first(self) -> None:
        # Deliberately shuffled input -- output must still be sorted ascending.
        shuffled = _make_candles(n=4).sample(frac=1, random_state=1).reset_index(drop=True)
        p_ctc, p_forex, p_stock = self._patch_all_fetchers(crypto_metals_frame=shuffled)
        with p_ctc, p_forex, p_stock:
            run_export(now=NOW_24H_DUE, output_dir=self.output_dir)

        payload = json.loads((self.output_dir / "BTC_24h.json").read_text())
        times = [c["time"] for c in payload["candles"]]
        self.assertEqual(times, sorted(times))

    def test_only_the_most_recent_200_candles_are_kept(self) -> None:
        big_frame = _make_candles(n=250)
        p_ctc, p_forex, p_stock = self._patch_all_fetchers(crypto_metals_frame=big_frame)
        with p_ctc, p_forex, p_stock:
            run_export(now=NOW_24H_DUE, output_dir=self.output_dir)

        payload = json.loads((self.output_dir / "BTC_24h.json").read_text())
        self.assertEqual(len(payload["candles"]), 200)
        # Kept the NEWEST 200, not the oldest.
        self.assertEqual(payload["candles"][-1]["time"], int(big_frame["open_time"].max()) // 1000)

    def test_nothing_is_due_outside_any_cadence_window(self) -> None:
        p_ctc, p_forex, p_stock = self._patch_all_fetchers()
        with p_ctc as mock_ctc, p_forex as mock_forex, p_stock as mock_stock:
            result = run_export(now=NOW_NOTHING_DUE, output_dir=self.output_dir)
            mock_ctc.assert_not_called()
            mock_forex.assert_not_called()
            mock_stock.assert_not_called()

        self.assertEqual(result.exported, [])
        self.assertEqual(len(result.skipped_not_due), len(IN_SCOPE_PAIRS))
        self.assertEqual(list(self.output_dir.iterdir()), [])

    def test_force_bypasses_both_the_cadence_gate_and_the_freshness_check(self) -> None:
        p_ctc, p_forex, p_stock = self._patch_all_fetchers()
        with p_ctc as mock_ctc, p_forex as mock_forex, p_stock as mock_stock:
            result = run_export(now=NOW_NOTHING_DUE, output_dir=self.output_dir, force=True)
            self.assertTrue(mock_ctc.called)
            self.assertTrue(mock_forex.called)
            self.assertTrue(mock_stock.called)

        self.assertEqual(len(result.exported), len(IN_SCOPE_PAIRS))
        self.assertEqual(result.skipped_not_due, [])

    def test_a_1week_series_is_not_refetched_on_a_second_run_the_same_week(self) -> None:
        p_ctc, p_forex, p_stock = self._patch_all_fetchers()
        with p_ctc, p_forex, p_stock:
            run_export(now=NOW_1WEEK_DUE, output_dir=self.output_dir)

        p_ctc2, p_forex2, p_stock2 = self._patch_all_fetchers()
        later_same_week = NOW_1WEEK_DUE.replace(minute=30)  # still within the same due window, same week
        with p_ctc2 as mock_ctc2, p_forex2 as mock_forex2, p_stock2 as mock_stock2:
            result = run_export(now=later_same_week, output_dir=self.output_dir)

        # Weekly pairs already fresh from the first run must not be re-fetched.
        weekly_filenames = {candle_filename(p.asset, p.timeframe) for p in IN_SCOPE_PAIRS if p.cadence_timeframe == "1week"}
        self.assertTrue(weekly_filenames.issubset(set(result.skipped_fresh)))
        mock_forex2.assert_not_called()

    def test_one_asset_failing_does_not_block_the_others(self) -> None:
        p_ctc, p_forex, p_stock = self._patch_all_fetchers()
        with p_ctc, p_forex as mock_forex, p_stock:
            mock_forex.side_effect = Exception("boom")
            result = run_export(now=NOW_1WEEK_DUE, output_dir=self.output_dir)

        # All 3 forex pairs failed...
        error_assets = {err["asset"] for err in result.errors}
        self.assertEqual(error_assets, {"EUR/USD", "GBP/USD", "USD/JPY"})
        # ...but GOLD and SILVER's own 1week series (crypto_metals family) still succeeded.
        self.assertIn("GOLD_1week.json", result.exported)
        self.assertIn("SILVER_1week.json", result.exported)

    def test_no_candles_returned_is_reported_as_an_error_not_a_crash(self) -> None:
        p_ctc, p_forex, p_stock = self._patch_all_fetchers(crypto_metals_frame=pd.DataFrame(columns=list(_make_candles().columns)))
        with p_ctc, p_forex, p_stock:
            result = run_export(now=NOW_24H_DUE, output_dir=self.output_dir)

        self.assertFalse((self.output_dir / "BTC_24h.json").exists())
        self.assertTrue(any(e["asset"] == "BTC" for e in result.errors))


if __name__ == "__main__":
    unittest.main()
