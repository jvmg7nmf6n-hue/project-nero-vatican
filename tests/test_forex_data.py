from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from nero_core.data_sources.forex_data import (
    CANDLE_COLUMNS,
    ForexDataUnavailableError,
    fetch_forex_ohlcv,
)


def _payload(n: int = 3, start_date: str = "2026-07-15") -> dict:
    dates = pd.date_range(start_date, periods=n, freq="D")
    values = [
        {"datetime": d.strftime("%Y-%m-%d"), "open": "1.1", "high": "1.2", "low": "1.0", "close": "1.15", "volume": "0"}
        for d in reversed(dates)
    ]
    return {"values": values}


class MissingApiKeyTest(unittest.TestCase):
    def test_raises_when_no_api_key_configured(self) -> None:
        with patch.dict("os.environ", {"TWELVE_DATA_API_KEY": ""}, clear=False):
            with self.assertRaises(ForexDataUnavailableError):
                fetch_forex_ohlcv("EUR/USD", "1day", api_key="", sleep_fn=lambda _s: None)


class NativeFetchTest(unittest.TestCase):
    def test_native_1day_fetch_produces_millisecond_precision_and_correct_columns(self) -> None:
        with patch("nero_core.data_sources.forex_data.requests.get") as mock_get:
            mock_get.return_value.raise_for_status.return_value = None
            mock_get.return_value.json.return_value = {"status": "ok", **_payload()}
            result = fetch_forex_ohlcv("EUR/USD", "1day", api_key="fake-key", sleep_fn=lambda _s: None)

        self.assertEqual(list(result.prices.columns), CANDLE_COLUMNS)
        self.assertEqual(len(result.prices), 3)
        self.assertEqual(len(str(int(result.prices["close_time"].iloc[-1]))), 13)
        self.assertEqual(result.pair, "EUR/USD")
        self.assertIn("NATIVE", result.source)

    def test_unsupported_timeframe_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            fetch_forex_ohlcv("EUR/USD", "12h", api_key="fake-key")


class UnresolvedPairTest(unittest.TestCase):
    def test_twelve_data_error_status_raises_immediately_not_retried_as_rate_limit(self) -> None:
        with patch("nero_core.data_sources.forex_data.requests.get") as mock_get:
            mock_get.return_value.raise_for_status.return_value = None
            mock_get.return_value.json.return_value = {"status": "error", "message": "symbol not found"}
            with self.assertRaises(ForexDataUnavailableError):
                fetch_forex_ohlcv("XXX/YYY", "1day", api_key="fake-key", sleep_fn=lambda _s: None)


class RateLimitRetryTest(unittest.TestCase):
    def test_rate_limit_error_retries_then_succeeds(self) -> None:
        call_count = {"n": 0}

        def _fake_get(*args, **kwargs):
            call_count["n"] += 1
            response = unittest_mock_response()
            if call_count["n"] < 3:
                response.json.return_value = {"status": "error", "message": "You have run out of API credits (429)"}
            else:
                response.json.return_value = {"status": "ok", **_payload()}
            return response

        def unittest_mock_response():
            from unittest.mock import MagicMock

            m = MagicMock()
            m.raise_for_status.return_value = None
            return m

        sleeps: list[float] = []
        with patch("nero_core.data_sources.forex_data.requests.get", side_effect=_fake_get):
            result = fetch_forex_ohlcv("EUR/USD", "1day", api_key="fake-key", sleep_fn=sleeps.append)

        self.assertEqual(call_count["n"], 3)
        self.assertEqual(sleeps, [10.0, 20.0])
        self.assertEqual(len(result.prices), 3)

    def test_all_retries_exhausted_raises(self) -> None:
        with patch("nero_core.data_sources.forex_data.requests.get") as mock_get:
            mock_get.return_value.raise_for_status.return_value = None
            mock_get.return_value.json.return_value = {"status": "error", "message": "429 rate limited"}
            with self.assertRaises(ForexDataUnavailableError):
                fetch_forex_ohlcv("EUR/USD", "1day", api_key="fake-key", sleep_fn=lambda _s: None)
            self.assertEqual(mock_get.call_count, 4)  # 1 initial + 3 retries


if __name__ == "__main__":
    unittest.main()
