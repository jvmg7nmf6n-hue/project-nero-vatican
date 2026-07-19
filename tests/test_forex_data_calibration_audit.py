from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from nero_core.data_sources.forex_data import ForexDataResult, ForexDataUnavailableError
from tools.forex_data_calibration_audit import (
    ADEQUATE_MIN_CANDLES,
    audit_pair_timeframe,
    run_audit,
)


def _result(n: int) -> ForexDataResult:
    dates = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    return ForexDataResult(
        prices=pd.DataFrame({"date": dates, "close": [1.1] * n}), source="NATIVE: test", pair="EUR/USD", timeframe="1h"
    )


class AuditPairTimeframeTest(unittest.TestCase):
    def test_adequate_candles_marked_adequate(self) -> None:
        with patch("tools.forex_data_calibration_audit.fetch_forex_ohlcv", return_value=_result(ADEQUATE_MIN_CANDLES)):
            row = audit_pair_timeframe("EUR/USD", "1h", sleep_fn=lambda _s: None)
        self.assertEqual(row["status"], "ADEQUATE")

    def test_below_threshold_marked_insufficient(self) -> None:
        with patch("tools.forex_data_calibration_audit.fetch_forex_ohlcv", return_value=_result(ADEQUATE_MIN_CANDLES - 1)):
            row = audit_pair_timeframe("EUR/USD", "1h", sleep_fn=lambda _s: None)
        self.assertEqual(row["status"], "SKIPPED (INSUFFICIENT DATA)")

    def test_unresolved_pair_marked_skipped_not_raised(self) -> None:
        with patch(
            "tools.forex_data_calibration_audit.fetch_forex_ohlcv",
            side_effect=ForexDataUnavailableError("'XXX/YYY' not found"),
        ):
            row = audit_pair_timeframe("XXX/YYY", "1h", sleep_fn=lambda _s: None)
        self.assertEqual(row["status"], "SKIPPED (UNRESOLVED)")


class RunAuditResilienceTest(unittest.TestCase):
    def test_one_pairs_failure_does_not_block_the_rest(self) -> None:
        def _fake_fetch(pair, timeframe, sleep_fn=None):
            if pair == "XXX/YYY":
                raise ForexDataUnavailableError("unresolved")
            return _result(ADEQUATE_MIN_CANDLES)

        with patch("tools.forex_data_calibration_audit.fetch_forex_ohlcv", side_effect=_fake_fetch):
            rows = run_audit(pairs=["EUR/USD", "XXX/YYY", "GBP/USD"], sleep_fn=lambda _s: None)

        statuses = {(r["pair"], r["status"]) for r in rows if r["timeframe"] == "1h"}
        self.assertIn(("EUR/USD", "ADEQUATE"), statuses)
        self.assertIn(("XXX/YYY", "SKIPPED (UNRESOLVED)"), statuses)
        self.assertIn(("GBP/USD", "ADEQUATE"), statuses)


if __name__ == "__main__":
    unittest.main()
