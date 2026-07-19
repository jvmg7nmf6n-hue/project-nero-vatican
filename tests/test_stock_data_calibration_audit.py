from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from nero_core.data_sources.stock_data import StockDataResult, StockDataUnavailableError
from tools.stock_data_calibration_audit import (
    ADEQUATE_MIN_CANDLES,
    audit_symbol_timeframe,
    run_audit,
)


def _result(n: int) -> StockDataResult:
    dates = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    return StockDataResult(
        prices=pd.DataFrame({"date": dates, "close": [100.0] * n}), source="NATIVE: test", symbol="TEST", timeframe="1day"
    )


class AuditSymbolTimeframeTest(unittest.TestCase):
    def test_adequate_candles_marked_adequate(self) -> None:
        with patch("tools.stock_data_calibration_audit.fetch_stock_ohlcv", return_value=_result(ADEQUATE_MIN_CANDLES)):
            row = audit_symbol_timeframe("SPY", "1day", sleep_fn=lambda _s: None)
        self.assertEqual(row["status"], "ADEQUATE")
        self.assertEqual(row["candles"], ADEQUATE_MIN_CANDLES)

    def test_below_threshold_marked_insufficient(self) -> None:
        with patch("tools.stock_data_calibration_audit.fetch_stock_ohlcv", return_value=_result(ADEQUATE_MIN_CANDLES - 1)):
            row = audit_symbol_timeframe("SPY", "1h", sleep_fn=lambda _s: None)
        self.assertEqual(row["status"], "SKIPPED (INSUFFICIENT DATA)")

    def test_unresolved_ticker_marked_skipped_not_raised(self) -> None:
        with patch(
            "tools.stock_data_calibration_audit.fetch_stock_ohlcv",
            side_effect=StockDataUnavailableError("'SQ' returned no data"),
        ):
            row = audit_symbol_timeframe("SQ", "1day", sleep_fn=lambda _s: None)
        self.assertEqual(row["status"], "SKIPPED (UNRESOLVED)")
        self.assertIn("SQ", row["reason"])

    def test_empty_but_successful_fetch_marked_skipped_empty(self) -> None:
        empty = StockDataResult(prices=pd.DataFrame(columns=["date", "close"]), source="NATIVE: test", symbol="X", timeframe="1day")
        with patch("tools.stock_data_calibration_audit.fetch_stock_ohlcv", return_value=empty):
            row = audit_symbol_timeframe("X", "1day", sleep_fn=lambda _s: None)
        self.assertEqual(row["status"], "SKIPPED (EMPTY)")


class RunAuditResilienceTest(unittest.TestCase):
    def test_one_symbols_failure_does_not_block_the_rest(self) -> None:
        def _fake_fetch(symbol, timeframe, sleep_fn=None):
            if symbol == "SQ":
                raise StockDataUnavailableError("unresolved")
            return _result(ADEQUATE_MIN_CANDLES)

        with patch("tools.stock_data_calibration_audit.fetch_stock_ohlcv", side_effect=_fake_fetch):
            rows = run_audit(universe=["SPY", "SQ", "QQQ"], sleep_fn=lambda _s: None)

        statuses = {(r["symbol"], r["status"]) for r in rows if r["timeframe"] == "1day"}
        self.assertIn(("SPY", "ADEQUATE"), statuses)
        self.assertIn(("SQ", "SKIPPED (UNRESOLVED)"), statuses)
        self.assertIn(("QQQ", "ADEQUATE"), statuses)


if __name__ == "__main__":
    unittest.main()
