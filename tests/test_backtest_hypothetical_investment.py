from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pandas as pd

from nero_core.data_sources.market_data import MarketDataClient, MarketDataResult
from tools.backtest_hypothetical_investment import run_hypothetical_investment
from tests.test_council_engine import _make_candle_row


def _breakout_history_for_hypothetical() -> pd.DataFrame:
    """Long flat warmup (so MA200 is valid well before the cutoff) followed by a
    sustained breakout leg entirely AFTER the simulated cutoff, so the hypothetical
    account actually opens and closes at least one real trade within its window."""
    rows: list[dict[str, float]] = []
    close_time = 0
    for i in range(220):
        close = 100.0 + 0.01 * i
        rows.append(_make_candle_row(close_time, close))
        close_time += 7 * 86_400_000  # weekly spacing
    price = rows[-1]["close"]
    for _ in range(10):
        price *= 1.05
        rows.append(_make_candle_row(close_time, price))
        close_time += 7 * 86_400_000
    return pd.DataFrame(rows)


class RunHypotheticalInvestmentOfflineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.history = _breakout_history_for_hypothetical()
        self.client = MarketDataClient()

    def _mocked_client(self):
        result = MarketDataResult(prices=self.history, source="test-fixture", asset="GOLD", interval="1week")
        patcher = patch.object(MarketDataClient, "load_intraday", return_value=result)
        patcher.start()
        self.addCleanup(patcher.stop)
        return self.client

    def test_starting_equity_is_respected_and_final_equity_reflects_trades(self) -> None:
        client = self._mocked_client()
        # "now" set to the last candle's date, lookback covers exactly the breakout leg.
        now = pd.Timestamp(self.history.iloc[-1]["close_time"], unit="ms", tz="UTC").to_pydatetime()

        report = run_hypothetical_investment(
            "GOLD", "1week", "breakout_momentum_gold_calibrated", 2000.0, lookback_days=90, client=client, now=now
        )

        self.assertEqual(report["starting_equity"], 2000.0)
        self.assertGreaterEqual(len(report["trades"]) + (1 if report["open_trade"] else 0), 1)
        # equity after each trade must be internally consistent with net_pnl accumulation
        running = 2000.0
        for trade in report["trades"]:
            running += trade.net_pnl
            self.assertAlmostEqual(running, trade.equity_after, places=6)
        self.assertAlmostEqual(report["final_equity"], running, places=6)

    def test_total_return_pct_matches_final_vs_starting_equity(self) -> None:
        client = self._mocked_client()
        now = pd.Timestamp(self.history.iloc[-1]["close_time"], unit="ms", tz="UTC").to_pydatetime()

        report = run_hypothetical_investment(
            "GOLD", "1week", "breakout_momentum_gold_calibrated", 2000.0, lookback_days=90, client=client, now=now
        )

        expected_return = (report["final_equity"] / 2000.0 - 1.0) * 100.0
        self.assertAlmostEqual(report["total_return_pct"], expected_return, places=6)

    def test_no_entries_allowed_before_the_cutoff_date(self) -> None:
        client = self._mocked_client()
        now = pd.Timestamp(self.history.iloc[-1]["close_time"], unit="ms", tz="UTC").to_pydatetime()

        report = run_hypothetical_investment(
            "GOLD", "1week", "breakout_momentum_gold_calibrated", 2000.0, lookback_days=90, client=client, now=now
        )

        cutoff = pd.Timestamp(now - timedelta(days=90))
        for trade in report["trades"]:
            self.assertGreaterEqual(trade.entry_date, cutoff)
        if report["open_trade"] is not None and report["open_trade"]["entry_date"] is not None:
            self.assertGreaterEqual(report["open_trade"]["entry_date"], cutoff)

    def test_returns_error_when_no_candles_within_lookback_window(self) -> None:
        client = self._mocked_client()
        # "now" far beyond the fixture's last candle -> no evaluable candle within lookback.
        far_future = datetime(2099, 1, 1, tzinfo=timezone.utc)

        report = run_hypothetical_investment(
            "GOLD", "1week", "breakout_momentum_gold_calibrated", 2000.0, lookback_days=30, client=client, now=far_future
        )

        self.assertIn("error", report)

    def test_open_trade_at_end_is_reported_not_fabricated(self) -> None:
        # Truncate history right after the breakout leg starts so the last opened trade
        # has no further candle to resolve against.
        truncated = self.history.iloc[:225].reset_index(drop=True)
        result = MarketDataResult(prices=truncated, source="test-fixture-truncated", asset="GOLD", interval="1week")
        with patch.object(MarketDataClient, "load_intraday", return_value=result):
            now = pd.Timestamp(truncated.iloc[-1]["close_time"], unit="ms", tz="UTC").to_pydatetime()
            report = run_hypothetical_investment(
                "GOLD", "1week", "breakout_momentum_gold_calibrated", 2000.0, lookback_days=90,
                client=self.client, now=now,
            )

        if report["open_trade"] is not None:
            self.assertIn("OPEN", report["open_trade"]["status"])
            self.assertNotIn("net_pnl", report["open_trade"])


if __name__ == "__main__":
    unittest.main()
