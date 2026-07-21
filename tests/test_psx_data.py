from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from nero_core.data_sources import psx_data
from nero_core.data_sources.stock_data import CANDLE_COLUMNS, StockDataResult


def _daily_candles(closes: list[float], start: str = "2024-01-01") -> pd.DataFrame:
    rows = []
    ts = pd.Timestamp(start, tz="UTC")
    for i, close in enumerate(closes):
        day = ts + pd.Timedelta(days=i)
        close_time = int(day.timestamp() * 1000)
        rows.append(
            {
                "date": day, "open_time": close_time - 86_400_000, "close_time": close_time,
                "open": close, "high": close + 1.0, "low": close - 1.0, "close": close, "volume": 1000.0,
            }
        )
    return pd.DataFrame(rows, columns=CANDLE_COLUMNS)


class DetectCorporateActionBreaksTest(unittest.TestCase):
    def test_clean_data_produces_no_flags(self) -> None:
        # Small, realistic day-to-day noise -- nothing near the 40% threshold.
        closes = [100.0, 101.5, 99.8, 102.0, 103.4, 101.0, 104.2]
        flags = psx_data.detect_corporate_action_breaks(_daily_candles(closes))
        self.assertEqual(flags, [])

    def test_synthetic_over_40_percent_move_fires(self) -> None:
        # MARI-shaped synthetic case: smooth rise then an ~8:1 cliff (~-88%).
        closes = [3400.0, 3444.0, 3641.0, 398.0, 403.0, 405.0]
        flags = psx_data.detect_corporate_action_breaks(_daily_candles(closes))
        self.assertEqual(len(flags), 1)
        self.assertAlmostEqual(flags[0].prior_close, 3641.0)
        self.assertAlmostEqual(flags[0].close, 398.0)
        self.assertLess(flags[0].pct_change, -40.0)

    def test_move_exactly_at_threshold_does_not_fire(self) -> None:
        closes = [100.0, 140.0]  # exactly +40.0%
        flags = psx_data.detect_corporate_action_breaks(closes and _daily_candles(closes), threshold_pct=40.0)
        self.assertEqual(flags, [])

    def test_empty_and_single_row_frames_produce_no_flags(self) -> None:
        self.assertEqual(psx_data.detect_corporate_action_breaks(pd.DataFrame(columns=CANDLE_COLUMNS)), [])
        self.assertEqual(psx_data.detect_corporate_action_breaks(_daily_candles([100.0])), [])


class FetchPsxStockOhlcvTest(unittest.TestCase):
    def test_unknown_symbol_raises_value_error_never_guesses_a_suffix(self) -> None:
        with self.assertRaises(ValueError):
            psx_data.fetch_psx_stock_ohlcv("NOTPSX")

    def test_clean_series_passes_through_unflagged(self) -> None:
        candles = _daily_candles([100.0, 101.0, 99.5, 102.0])
        fake_result = StockDataResult(prices=candles, source="NATIVE: yfinance OGDC.KA 1d", symbol="OGDC.KA", timeframe="1day")
        with patch.object(psx_data, "fetch_stock_ohlcv", return_value=fake_result) as mocked:
            result = psx_data.fetch_psx_stock_ohlcv("OGDC", sleep_fn=lambda _s: None)
        mocked.assert_called_once()
        self.assertEqual(mocked.call_args.args[0], "OGDC.KA")
        self.assertEqual(len(result.prices), 4)

    def test_corporate_action_break_halts_and_raises_not_silently_returned(self) -> None:
        candles = _daily_candles([3400.0, 3444.0, 3641.0, 398.0, 403.0])
        fake_result = StockDataResult(prices=candles, source="NATIVE: yfinance MARI.KA 1d", symbol="MARI.KA", timeframe="1day")
        with patch.object(psx_data, "fetch_stock_ohlcv", return_value=fake_result):
            with self.assertRaises(psx_data.PsxCorporateActionSuspectedError):
                psx_data.fetch_psx_stock_ohlcv("MARI", sleep_fn=lambda _s: None)


class FetchKse100DailyTest(unittest.TestCase):
    def test_parses_dps_html_table_into_candle_columns(self) -> None:
        html = (
            "<table><thead><tr><th>DATE </th><th>OPEN</th><th>HIGH</th><th>LOW</th>"
            "<th>CLOSE</th><th>VOLUME</th></tr></thead><tbody>"
            "<tr><td>Jun 28, 2024</td><td>78,698.47</td><td>78,784.23</td><td>78,312.36</td>"
            "<td>78,444.96</td><td>206,490,563</td></tr>"
            "<tr><td>Jun 27, 2024</td><td>78,470.34</td><td>78,978.60</td><td>78,294.23</td>"
            "<td>78,528.25</td><td>137,886,062</td></tr>"
            "</tbody></table>"
        )
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.text = html
        with patch.object(psx_data.requests.Session, "post", return_value=response):
            result = psx_data.fetch_kse100_daily(2024, 2024, sleep_fn=lambda _s: None)

        self.assertEqual(list(result.prices.columns), CANDLE_COLUMNS)
        self.assertEqual(len(result.prices), 2)
        self.assertEqual(result.symbol, "KSE100")
        self.assertIn("dps.psx.com.pk", result.source)

    def test_zero_rows_across_entire_range_raises(self) -> None:
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.text = "<table><thead><tr><th>DATE </th></tr></thead><tbody></tbody></table>"
        with patch.object(psx_data.requests.Session, "post", return_value=response):
            with self.assertRaises(psx_data.StockDataUnavailableError):
                psx_data.fetch_kse100_daily(2024, 2024, sleep_fn=lambda _s: None)


class MacroProxyFetchTest(unittest.TestCase):
    def test_usd_pkr_cached_value_returned_without_network_call(self) -> None:
        cached = pd.Series([280.0, 281.5], index=[pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-02")])
        with patch.object(psx_data, "_read_cache", return_value=cached):
            series, source = psx_data.fetch_usd_pkr_daily(use_cache=True)
        self.assertEqual(len(series), 2)
        self.assertIn("CACHED", source)

    def test_oil_native_fetch_writes_cache(self) -> None:
        history = pd.DataFrame(
            {"Close": [70.0, 71.5]},
            index=pd.DatetimeIndex([pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-02")], name="Date"),
        )
        with patch.object(psx_data, "_read_cache", return_value=None), patch.object(psx_data, "_write_cache") as write_mock:
            with patch("nero_core.data_sources.psx_data.yf.Ticker") as mock_ticker:
                mock_ticker.return_value.history.return_value = history
                series, source = psx_data.fetch_oil_price_daily(use_cache=True, sleep_fn=lambda _s: None)
        self.assertEqual(len(series), 2)
        self.assertIn("NATIVE", source)
        write_mock.assert_called_once()

    def test_sbp_policy_rate_always_raises_with_documented_reason(self) -> None:
        with self.assertRaises(psx_data.PsxMacroDataUnavailableError) as ctx:
            psx_data.fetch_sbp_policy_rate()
        self.assertIn("FRED", str(ctx.exception))
        self.assertIn("USD/PKR", str(ctx.exception))

    def test_graceful_fallback_pattern_catches_sbp_unavailable_and_uses_usd_pkr(self) -> None:
        # Mirrors how a caller (the sweep tool) is expected to use this: try SBP first,
        # fall back to USD/PKR alone on failure, never crash the whole run.
        cached = pd.Series([280.0], index=[pd.Timestamp("2024-01-01")])
        try:
            psx_data.fetch_sbp_policy_rate()
            self.fail("expected PsxMacroDataUnavailableError")
        except psx_data.PsxMacroDataUnavailableError:
            with patch.object(psx_data, "_read_cache", return_value=cached):
                series, source = psx_data.fetch_usd_pkr_daily(use_cache=True)
        self.assertEqual(len(series), 1)
        self.assertIn("CACHED", source)


class RegimeFrameTest(unittest.TestCase):
    def test_ogdc_regime_requires_both_legs_positive(self) -> None:
        candles = _daily_candles([100.0] * 25, start="2024-02-01")
        rising_usdpkr = pd.Series([280.0 + i for i in range(30)], index=pd.bdate_range("2024-01-01", periods=30))
        rising_oil = pd.Series([70.0 + i for i in range(30)], index=pd.bdate_range("2024-01-01", periods=30))

        frame = psx_data.build_psx_regime_frame_oil_and_currency(candles, rising_usdpkr, rising_oil)

        warmed_up = frame.dropna(subset=["dollar_change_20d", "dfii10_change_20d"])
        self.assertFalse(warmed_up.empty)
        self.assertTrue(bool(warmed_up.iloc[-1]["risk_on"]))

    def test_ogdc_regime_false_when_oil_falling(self) -> None:
        candles = _daily_candles([100.0] * 25, start="2024-02-01")
        rising_usdpkr = pd.Series([280.0 + i for i in range(30)], index=pd.bdate_range("2024-01-01", periods=30))
        falling_oil = pd.Series([70.0 - i for i in range(30)], index=pd.bdate_range("2024-01-01", periods=30))

        frame = psx_data.build_psx_regime_frame_oil_and_currency(candles, rising_usdpkr, falling_oil)

        warmed_up = frame.dropna(subset=["dollar_change_20d", "dfii10_change_20d"])
        self.assertFalse(bool(warmed_up.iloc[-1]["risk_on"]))

    def test_currency_only_regime_tracks_usdpkr_alone(self) -> None:
        candles = _daily_candles([100.0] * 25, start="2024-02-01")
        rising_usdpkr = pd.Series([280.0 + i for i in range(30)], index=pd.bdate_range("2024-01-01", periods=30))

        frame = psx_data.build_psx_regime_frame_currency_only(candles, rising_usdpkr)

        warmed_up = frame.dropna(subset=["dollar_change_20d"])
        self.assertFalse(warmed_up.empty)
        self.assertTrue(bool(warmed_up.iloc[-1]["risk_on"]))
        self.assertTrue((frame["dfii10_change_20d"] == 0.0).all())


if __name__ == "__main__":
    unittest.main()
