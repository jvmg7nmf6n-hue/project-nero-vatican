from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pandas as pd
import requests

from nero_core.data_sources.market_data import (
    CANDLE_COLUMNS,
    MarketDataClient,
    MarketDataUnavailableError,
)

NOW = datetime.now(timezone.utc)
SAFE_END_MS = int((NOW - timedelta(hours=2)).timestamp() * 1000)  # comfortably closed


def _mock_response(payload: object, status_ok: bool = True) -> Mock:
    response = Mock()
    response.json.return_value = payload
    if status_ok:
        response.raise_for_status.return_value = None
    else:
        response.raise_for_status.side_effect = requests.HTTPError("bad status")
    return response


def _binance_klines(count: int, interval_ms: int = 86_400_000, end_ms: int = SAFE_END_MS) -> list[list[object]]:
    rows = []
    for i in range(count):
        close_time = end_ms - (count - 1 - i) * interval_ms
        open_time = close_time - interval_ms
        price = 100.0 + i
        rows.append(
            [open_time, price, price + 1, price - 1, price + 0.5, 10.0, close_time, "0", 5, "0", "0", "0"]
        )
    return rows


def _coinbase_candles(count: int, granularity_seconds: int = 86400, end_ms: int = SAFE_END_MS) -> list[list[float]]:
    rows = []
    for i in range(count):
        open_time_s = (end_ms - (count - 1 - i) * granularity_seconds * 1000 - granularity_seconds * 1000) / 1000
        price = 100.0 + i
        rows.append([open_time_s, price - 1, price + 1, price, price + 0.5, 10.0])  # time, low, high, open, close, volume
    return rows


def _kraken_result(pair_key: str, count: int, interval_minutes: int = 1440, end_ms: int = SAFE_END_MS) -> dict:
    rows = []
    for i in range(count):
        open_time_s = (end_ms - (count - 1 - i) * interval_minutes * 60 * 1000 - interval_minutes * 60 * 1000) / 1000
        price = 100.0 + i
        rows.append([open_time_s, price, price + 1, price - 1, price + 0.5, "0", 10.0, 5])
    return {"error": [], "result": {pair_key: rows, "last": 0}}


def _twelve_data_values(count: int, end: datetime = NOW - timedelta(hours=2)) -> list[dict[str, str]]:
    values = []
    for i in range(count):
        dt = end - timedelta(days=(count - 1 - i))
        price = 100.0 + i
        values.append(
            {
                "datetime": dt.strftime("%Y-%m-%d"),
                "open": str(price),
                "high": str(price + 1),
                "low": str(price - 1),
                "close": str(price + 0.5),
                "volume": "10",
            }
        )
    return values


class MarketDataDailyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = MarketDataClient()

    def test_binance_success_returns_closed_candles_only(self) -> None:
        with patch("nero_core.data_sources.market_data.requests.get", return_value=_mock_response(_binance_klines(40))):
            result = self.client.load_daily("BTC", days=40)

        self.assertIn("Binance", result.source)
        self.assertEqual(list(result.prices.columns), CANDLE_COLUMNS)
        self.assertGreater(len(result.prices), 0)
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        self.assertTrue((result.prices["close_time"] < now_ms).all())

    def test_falls_back_to_coinbase_when_binance_fails(self) -> None:
        def side_effect(url, **kwargs):
            if "binance" in url:
                raise requests.ConnectionError("binance down")
            return _mock_response(_coinbase_candles(40))

        with patch("nero_core.data_sources.market_data.requests.get", side_effect=side_effect):
            result = self.client.load_daily("BTC", days=40)

        self.assertIn("Coinbase", result.source)
        self.assertGreater(len(result.prices), 0)

    def test_falls_back_to_kraken_when_binance_and_coinbase_fail(self) -> None:
        def side_effect(url, **kwargs):
            if "binance" in url or "coinbase" in url:
                raise requests.ConnectionError("down")
            return _mock_response(_kraken_result("XXBTZUSD", 40))

        with patch("nero_core.data_sources.market_data.requests.get", side_effect=side_effect):
            result = self.client.load_daily("BTC", days=40)

        self.assertIn("Kraken", result.source)
        self.assertGreater(len(result.prices), 0)

    def test_raises_market_data_unavailable_when_all_sources_fail_no_fabricated_data(self) -> None:
        with patch(
            "nero_core.data_sources.market_data.requests.get",
            side_effect=requests.ConnectionError("all down"),
        ):
            with self.assertRaises(MarketDataUnavailableError) as ctx:
                self.client.load_daily("BTC", days=40)

        message = str(ctx.exception)
        self.assertIn("Binance", message)
        self.assertIn("Coinbase", message)
        self.assertIn("Kraken", message)

    def test_malformed_binance_response_falls_back_instead_of_crashing(self) -> None:
        def side_effect(url, **kwargs):
            if "binance" in url:
                return _mock_response([])  # empty payload -> ValueError inside client
            return _mock_response(_coinbase_candles(40))

        with patch("nero_core.data_sources.market_data.requests.get", side_effect=side_effect):
            result = self.client.load_daily("BTC", days=40)

        self.assertIn("Coinbase", result.source)

    def test_gold_uses_twelve_data_with_api_key(self) -> None:
        with patch(
            "nero_core.data_sources.market_data.requests.get",
            return_value=_mock_response({"status": "ok", "values": _twelve_data_values(40)}),
        ):
            result = self.client.load_daily("GOLD", days=40, twelve_data_api_key="fake-key")

        self.assertIn("Twelve Data", result.source)
        self.assertGreater(len(result.prices), 0)

    def test_gold_with_no_volume_field_in_response_does_not_crash(self) -> None:
        # Regression test: Twelve Data's spot Gold (XAU/USD) feed omits "volume" entirely
        # at some intervals — frame.get("volume") on a missing column used to collapse to
        # a scalar NaN instead of a Series, breaking a chained .fillna() call downstream.
        values = [
            {"datetime": v["datetime"], "open": v["open"], "high": v["high"], "low": v["low"], "close": v["close"]}
            for v in _twelve_data_values(40)
        ]
        self.assertNotIn("volume", values[0])

        with patch(
            "nero_core.data_sources.market_data.requests.get",
            return_value=_mock_response({"status": "ok", "values": values}),
        ):
            result = self.client.load_daily("GOLD", days=40, twelve_data_api_key="fake-key")

        self.assertTrue((result.prices["volume"] == 0.0).all())

    def test_gold_raises_clear_error_when_api_key_missing(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TWELVE_DATA_API_KEY", None)
            with self.assertRaises(MarketDataUnavailableError) as ctx:
                self.client.load_daily("GOLD", days=40, twelve_data_api_key=None)

        self.assertIn("missing API key", str(ctx.exception))

    def test_unsupported_asset_raises_immediately_listing_supported_assets(self) -> None:
        with self.assertRaises(MarketDataUnavailableError) as ctx:
            self.client.load_daily("ZZZ", days=40)

        self.assertIn("No data source configured", str(ctx.exception))
        self.assertIn("BTC", str(ctx.exception))

    def test_bnb_has_no_fallback_beyond_binance(self) -> None:
        with patch(
            "nero_core.data_sources.market_data.requests.get",
            side_effect=requests.ConnectionError("binance down"),
        ):
            with self.assertRaises(MarketDataUnavailableError) as ctx:
                self.client.load_daily("BNB", days=40)

        message = str(ctx.exception)
        self.assertIn("Binance", message)
        self.assertNotIn("Coinbase", message)
        self.assertNotIn("Kraken", message)


class MarketDataPaginationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = MarketDataClient()

    def test_requesting_more_than_1000_candles_pages_backward_and_stitches_results(self) -> None:
        interval_ms = 3_600_000
        call_state = {"end_ms": SAFE_END_MS, "calls": 0}

        def side_effect(url, **kwargs):
            call_state["calls"] += 1
            params = kwargs["params"]
            batch_size = params["limit"]
            end_ms = params.get("endTime", call_state["end_ms"])
            return _mock_response(_binance_klines(batch_size, interval_ms=interval_ms, end_ms=end_ms))

        with patch("nero_core.data_sources.market_data.requests.get", side_effect=side_effect):
            result = self.client.load_intraday("BTC", interval="1h", candles=1500)

        self.assertEqual(call_state["calls"], 2)  # 1000 + 500
        self.assertEqual(len(result.prices), 1500)
        # Pages must stitch into one continuously ordered, de-duplicated series.
        self.assertTrue(result.prices["close_time"].is_monotonic_increasing)
        self.assertEqual(result.prices["close_time"].nunique(), len(result.prices))

    def test_pagination_stops_early_when_exchange_runs_out_of_history(self) -> None:
        # Exchange only has 1200 candles of history total, even though 5000 were requested.
        interval_ms = 3_600_000
        call_state = {"remaining": 1200}

        def side_effect(url, **kwargs):
            params = kwargs["params"]
            requested = params["limit"]
            end_ms = params.get("endTime", SAFE_END_MS)
            given = min(requested, call_state["remaining"])
            call_state["remaining"] -= given
            if given <= 0:
                return _mock_response([])
            return _mock_response(_binance_klines(given, interval_ms=interval_ms, end_ms=end_ms))

        with patch("nero_core.data_sources.market_data.requests.get", side_effect=side_effect):
            result = self.client.load_intraday("BTC", interval="1h", candles=5000)

        self.assertEqual(len(result.prices), 1200)


class MarketDataIntradayTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = MarketDataClient()

    def test_binance_intraday_success(self) -> None:
        klines = _binance_klines(50, interval_ms=3_600_000)
        with patch("nero_core.data_sources.market_data.requests.get", return_value=_mock_response(klines)):
            result = self.client.load_intraday("ETH", interval="1h", candles=50)

        self.assertIn("Binance", result.source)
        self.assertEqual(result.interval, "1h")
        self.assertGreater(len(result.prices), 0)

    def test_intraday_all_sources_fail_raises_not_fabricates(self) -> None:
        with patch(
            "nero_core.data_sources.market_data.requests.get",
            side_effect=requests.Timeout("timed out"),
        ):
            with self.assertRaises(MarketDataUnavailableError):
                self.client.load_intraday("SOL", interval="1h", candles=50)


def _twelve_data_intraday_values(count: int, end: datetime, interval_hours: int = 1) -> list[dict[str, str]]:
    """Unlike _twelve_data_values (daily, date-only strings), this uses a full
    datetime string with a time-of-day component — the shape Twelve Data actually
    returns for intraday intervals, and the input that exposed the resolution bug
    below (a date-only string happens to not exercise the same pandas datetime64
    resolution path in every pandas version)."""
    values = []
    for i in range(count):
        dt = end - timedelta(hours=interval_hours * (count - 1 - i))
        price = 100.0 + i
        values.append(
            {
                "datetime": dt.strftime("%Y-%m-%d %H:%M:%S"),
                "open": str(price),
                "high": str(price + 1),
                "low": str(price - 1),
                "close": str(price + 0.5),
                "volume": "10",
            }
        )
    return values


class TimestampMillisecondPrecisionRegressionTest(unittest.TestCase):
    """Regression test for a real bug found while auditing metals data sources: on a
    pandas version where pd.to_datetime infers a non-nanosecond resolution (e.g. the
    project's own pandas>=2.0,<3 pin drifting to an installed pandas 3.0.3), a bare
    `.astype("int64") // 1_000_000` silently produces a close_time off by 1000x (seconds
    mislabeled as milliseconds) instead of raising — which in turn breaks every
    downstream holding-hours/TIME-exit computation without ever crashing. Both
    _load_twelve_data and _load_yfinance must produce a close_time that, when converted
    back via pd.to_datetime(close_time, unit="ms"), reproduces the source date exactly —
    regardless of what resolution pandas happens to infer internally."""

    def setUp(self) -> None:
        self.client = MarketDataClient()

    def test_twelve_data_intraday_close_time_is_millisecond_precision(self) -> None:
        end = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc) - timedelta(hours=3)
        values = _twelve_data_intraday_values(30, end=end, interval_hours=1)
        expected_last_close_ms = int(end.timestamp() * 1000)

        with patch(
            "nero_core.data_sources.market_data.requests.get",
            return_value=_mock_response({"status": "ok", "values": values}),
        ):
            result = self.client.load_intraday("GOLD", interval="1h", candles=30, twelve_data_api_key="fake-key")

        last_close_ms = int(result.prices["close_time"].iloc[-1])
        self.assertEqual(last_close_ms, expected_last_close_ms)
        # A close_time 1000x too small (the bug) would round-trip to 1970, not 2026.
        reconstructed = pd.to_datetime(last_close_ms, unit="ms", utc=True)
        self.assertEqual(reconstructed.year, 2026)

    def test_yfinance_metals_close_time_is_millisecond_precision(self) -> None:
        end = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc) - timedelta(hours=3)
        index = pd.DatetimeIndex(
            [end - timedelta(hours=i) for i in range(29, -1, -1)], name="Datetime", tz="UTC"
        )
        history = pd.DataFrame(
            {
                "Open": [100.0 + i for i in range(30)],
                "High": [101.0 + i for i in range(30)],
                "Low": [99.0 + i for i in range(30)],
                "Close": [100.5 + i for i in range(30)],
                "Volume": [10.0] * 30,
            },
            index=index,
        )
        expected_last_open_ms = int(end.timestamp() * 1000)

        with patch("nero_core.data_sources.market_data.yf.Ticker") as mock_ticker_cls:
            mock_ticker_cls.return_value.history.return_value = history
            result = self.client.load_intraday("SILVER", interval="1h", candles=30)

        last_open_ms = int(result.prices["open_time"].iloc[-1])
        self.assertEqual(last_open_ms, expected_last_open_ms)
        reconstructed = pd.to_datetime(last_open_ms, unit="ms", utc=True)
        self.assertEqual(reconstructed.year, 2026)


if __name__ == "__main__":
    unittest.main()
