from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from nero_core.data_sources import macro_data


def _business_day_series(start: str, n: int, values: list[float]) -> pd.Series:
    dates = pd.bdate_range(start=start, periods=n)
    return pd.Series(values[:n], index=dates)


class ComputeLaggedChangeTest(unittest.TestCase):
    def test_diff_then_shift_hand_computed(self) -> None:
        # 25 business days, value = index (0..24). 20-day diff at index i (i>=20) = 20.
        series = _business_day_series("2024-01-01", 25, list(range(25)))

        change = macro_data.compute_lagged_change(series, change_window_days=20, lag_business_days=2)

        # Raw diff(20) at business-day index 20 (0-based) = 20 - 0 = 20; after shift(2)
        # that value now appears at index 22.
        self.assertTrue(pd.isna(change.iloc[20]))
        self.assertTrue(pd.isna(change.iloc[21]))
        self.assertAlmostEqual(change.iloc[22], 20.0)

    def test_zero_lag_is_pure_diff(self) -> None:
        series = _business_day_series("2024-01-01", 25, list(range(25)))

        change = macro_data.compute_lagged_change(series, change_window_days=20, lag_business_days=0)

        self.assertAlmostEqual(change.iloc[20], 20.0)


def _daily_candles(dates: list[str]) -> pd.DataFrame:
    rows = []
    for i, d in enumerate(dates):
        ts = pd.Timestamp(d, tz="UTC")
        close_time = int(ts.timestamp() * 1000)
        rows.append(
            {
                "date": ts, "open_time": close_time - 86_400_000, "close_time": close_time,
                "open": 100.0 + i, "high": 101.0 + i, "low": 99.0 + i, "close": 100.0 + i, "volume": 10.0,
            }
        )
    return pd.DataFrame(rows)


class AlignMacroToDailyCandlesTest(unittest.TestCase):
    def test_saturday_candle_sees_fridays_value_not_mondays(self) -> None:
        # Fri 2024-01-05, Sat 2024-01-06, Sun 2024-01-07, Mon 2024-01-08.
        candles = _daily_candles(["2024-01-05", "2024-01-06", "2024-01-07", "2024-01-08"])
        macro = pd.Series(
            [111.0, 222.0],
            index=[pd.Timestamp("2024-01-05"), pd.Timestamp("2024-01-08")],
        )

        merged = macro_data.align_macro_to_daily_candles(candles, macro, "macro_value")

        friday_value = merged.loc[merged["date"].dt.normalize() == pd.Timestamp("2024-01-05", tz="UTC"), "macro_value"].iloc[0]
        saturday_value = merged.loc[merged["date"].dt.normalize() == pd.Timestamp("2024-01-06", tz="UTC"), "macro_value"].iloc[0]
        sunday_value = merged.loc[merged["date"].dt.normalize() == pd.Timestamp("2024-01-07", tz="UTC"), "macro_value"].iloc[0]
        monday_value = merged.loc[merged["date"].dt.normalize() == pd.Timestamp("2024-01-08", tz="UTC"), "macro_value"].iloc[0]

        self.assertEqual(friday_value, 111.0)
        self.assertEqual(saturday_value, 111.0)  # forward-filled from Friday
        self.assertEqual(sunday_value, 111.0)  # forward-filled from Friday
        self.assertNotEqual(saturday_value, monday_value)
        self.assertEqual(monday_value, 222.0)

    def test_candle_before_any_macro_data_is_nan_not_backfilled(self) -> None:
        candles = _daily_candles(["2024-01-01", "2024-01-08"])
        macro = pd.Series([222.0], index=[pd.Timestamp("2024-01-08")])

        merged = macro_data.align_macro_to_daily_candles(candles, macro, "macro_value")

        first_row_value = merged.iloc[0]["macro_value"]
        self.assertTrue(pd.isna(first_row_value))  # nothing published yet as of 2024-01-01


class BuildRegimeFrameTest(unittest.TestCase):
    def test_risk_on_true_only_when_both_legs_negative(self) -> None:
        candles = _daily_candles(["2024-02-01", "2024-02-02"])
        dollar = _business_day_series("2024-01-01", 30, [100.0 - i for i in range(30)])  # falling -> weakening
        dfii10 = _business_day_series("2024-01-01", 30, [2.0 - 0.01 * i for i in range(30)])  # falling real yield

        frame = macro_data.build_regime_frame(candles, dollar, dfii10)

        self.assertIn("risk_on", frame.columns)
        self.assertIn("dollar_change_20d", frame.columns)
        self.assertIn("dfii10_change_20d", frame.columns)
        # Both legs are monotonically falling in this fixture, so once warmed up both
        # changes are negative and risk_on must be True.
        warmed_up = frame.dropna(subset=["dollar_change_20d", "dfii10_change_20d"])
        self.assertFalse(warmed_up.empty)
        self.assertTrue(bool(warmed_up.iloc[-1]["risk_on"]))

    def test_risk_on_false_when_one_leg_disagrees(self) -> None:
        candles = _daily_candles(["2024-02-01", "2024-02-02"])
        dollar = _business_day_series("2024-01-01", 30, [100.0 + i for i in range(30)])  # rising -> strengthening
        dfii10 = _business_day_series("2024-01-01", 30, [2.0 - 0.01 * i for i in range(30)])  # falling

        frame = macro_data.build_regime_frame(candles, dollar, dfii10)

        warmed_up = frame.dropna(subset=["dollar_change_20d", "dfii10_change_20d"])
        self.assertFalse(warmed_up.empty)
        self.assertFalse(bool(warmed_up.iloc[-1]["risk_on"]))


class FetchDollarProxyDailyTest(unittest.TestCase):
    def test_missing_api_key_raises_without_network_call(self) -> None:
        with patch.object(macro_data, "_read_cache", return_value=None):
            with patch.dict("os.environ", {"TWELVE_DATA_API_KEY": ""}, clear=False):
                with self.assertRaises(macro_data.MacroDataUnavailableError):
                    macro_data.fetch_dollar_proxy_daily(api_key="", use_cache=False)

    def test_cached_value_returned_without_requiring_api_key(self) -> None:
        cached_series = pd.Series([1.0, 2.0], index=[pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-02")])
        with patch.object(macro_data, "_read_cache", return_value=cached_series):
            series, source = macro_data.fetch_dollar_proxy_daily(api_key="", use_cache=True)
        self.assertEqual(len(series), 2)
        self.assertIn("CACHED", source)

    def test_cascades_uup_dxy_eurusd_and_inverts_eurusd(self) -> None:
        def fake_get(url, params=None, timeout=None):
            symbol = params["symbol"]
            response = MagicMock()
            response.raise_for_status = MagicMock()
            if symbol in ("UUP", "DXY"):
                response.json.return_value = {"status": "error", "message": "not found"}
            else:  # EUR/USD succeeds
                response.json.return_value = {
                    "values": [
                        {"datetime": "2024-01-02", "close": "1.10"},
                        {"datetime": "2024-01-01", "close": "1.00"},
                    ]
                }
            return response

        with patch.object(macro_data, "_read_cache", return_value=None), patch.object(macro_data, "_write_cache") as write_mock:
            with patch("nero_core.data_sources.macro_data.requests.get", side_effect=fake_get):
                series, source = macro_data.fetch_dollar_proxy_daily(api_key="fake-key", use_cache=False)

        self.assertIn("EUR/USD", source)
        self.assertIn("INVERTED", source)
        # Inverted: 1/1.00 = 1.0, 1/1.10 ~= 0.909
        self.assertAlmostEqual(series.loc[pd.Timestamp("2024-01-01")], 1.0)
        self.assertAlmostEqual(series.loc[pd.Timestamp("2024-01-02")], 1.0 / 1.10)
        write_mock.assert_called_once()


class FetchDfii10DailyTest(unittest.TestCase):
    def test_missing_api_key_raises_without_network_call(self) -> None:
        with patch.object(macro_data, "_read_cache", return_value=None):
            with patch.dict("os.environ", {"FRED_API_KEY": ""}, clear=False):
                with self.assertRaises(macro_data.MacroDataUnavailableError):
                    macro_data.fetch_dfii10_daily(api_key="", use_cache=False)

    def test_parses_fred_response_and_drops_missing_observations(self) -> None:
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json.return_value = {
            "observations": [
                {"date": "2024-01-01", "value": "1.85"},
                {"date": "2024-01-02", "value": "."},  # FRED's missing-observation marker
                {"date": "2024-01-03", "value": "1.90"},
            ]
        }
        with patch.object(macro_data, "_read_cache", return_value=None), patch.object(macro_data, "_write_cache"):
            with patch("nero_core.data_sources.macro_data.requests.get", return_value=response):
                series, source = macro_data.fetch_dfii10_daily(api_key="fake-key", use_cache=False)

        self.assertEqual(len(series), 2)
        self.assertIn("FRED DFII10", source)
        self.assertAlmostEqual(series.loc[pd.Timestamp("2024-01-01")], 1.85)


if __name__ == "__main__":
    unittest.main()
