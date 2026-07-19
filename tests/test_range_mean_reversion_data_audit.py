from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from nero_core.data_sources.forex_data import ForexDataResult, ForexDataUnavailableError
from nero_core.data_sources.market_data import MarketDataUnavailableError
from tools.range_mean_reversion_data_audit import (
    ADEQUATE_MIN_CANDLES,
    audit_crypto_or_metal,
    audit_forex,
)


def _forex_result(n: int) -> ForexDataResult:
    dates = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    return ForexDataResult(prices=pd.DataFrame({"date": dates, "close": [1.1] * n}), source="test", pair="EUR/USD", timeframe="1h")


class AuditForexTest(unittest.TestCase):
    def test_adequate_marked_adequate(self) -> None:
        with patch("tools.range_mean_reversion_data_audit.fetch_forex_ohlcv", return_value=_forex_result(ADEQUATE_MIN_CANDLES)):
            row = audit_forex("EUR/USD", "1h")
        self.assertEqual(row["status"], "ADEQUATE")
        self.assertEqual(row["tier"], "TIER 1 (forex)")

    def test_insufficient_marked_skipped(self) -> None:
        with patch("tools.range_mean_reversion_data_audit.fetch_forex_ohlcv", return_value=_forex_result(ADEQUATE_MIN_CANDLES - 1)):
            row = audit_forex("EUR/USD", "1h")
        self.assertEqual(row["status"], "SKIPPED (INSUFFICIENT DATA)")

    def test_unresolved_marked_skipped_not_raised(self) -> None:
        with patch("tools.range_mean_reversion_data_audit.fetch_forex_ohlcv", side_effect=ForexDataUnavailableError("no data")):
            row = audit_forex("EUR/USD", "1h")
        self.assertEqual(row["status"], "SKIPPED (UNRESOLVED)")


class AuditCryptoOrMetalTest(unittest.TestCase):
    def test_adequate_marked_adequate(self) -> None:
        dates = pd.date_range("2024-01-01", periods=ADEQUATE_MIN_CANDLES, freq="h", tz="UTC")
        candles = pd.DataFrame({"date": dates, "close": [100.0] * ADEQUATE_MIN_CANDLES})
        with patch("tools.range_mean_reversion_data_audit.fetch_timeframe_candles", return_value=(candles, "NATIVE: test")):
            row = audit_crypto_or_metal(None, "TIER 3 (stress-test)", "NEAR", "4h", "4h")
        self.assertEqual(row["status"], "ADEQUATE")
        self.assertEqual(row["tier"], "TIER 3 (stress-test)")

    def test_unresolved_marked_skipped_not_raised(self) -> None:
        with patch("tools.range_mean_reversion_data_audit.fetch_timeframe_candles", side_effect=MarketDataUnavailableError("no data")):
            row = audit_crypto_or_metal(None, "TIER 2 (crypto)", "BTC", "1day", "24h")
        self.assertEqual(row["status"], "SKIPPED (UNRESOLVED)")

    def test_insufficient_marked_skipped(self) -> None:
        dates = pd.date_range("2024-01-01", periods=ADEQUATE_MIN_CANDLES - 1, freq="h", tz="UTC")
        candles = pd.DataFrame({"date": dates, "close": [100.0] * (ADEQUATE_MIN_CANDLES - 1)})
        with patch("tools.range_mean_reversion_data_audit.fetch_timeframe_candles", return_value=(candles, "NATIVE: test")):
            row = audit_crypto_or_metal(None, "TIER 1 (metals)", "GOLD", "4h", "4h")
        self.assertEqual(row["status"], "SKIPPED (INSUFFICIENT DATA)")


if __name__ == "__main__":
    unittest.main()
