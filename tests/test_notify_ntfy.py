from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from nero_core.execution import notify_ntfy
from nero_core.execution.notify_ntfy import (
    ZERO_SIGNAL_MESSAGE,
    build_notification_message,
    format_execution_log_line,
    format_news_sentiment_line,
    send_ntfy_notification,
)
from nero_core.truth_ledger.execution_log import (
    ExecutionLogRow,
    NewsSentimentLogRow,
    insert_execution_log_row,
    insert_execution_metadata,
    insert_news_sentiment_log,
)


def _now() -> datetime:
    return datetime(2026, 7, 18, 0, 5, tzinfo=timezone.utc)


def _exec_row(**overrides) -> ExecutionLogRow:
    base = dict(
        id=1, run_id="run-1", timestamp=_now(), strategy="BREAKOUT_MOMENTUM", strategy_version="v1.2.0",
        asset="GOLD", signal_type="NO_TRADE", entry_price=None, exit_price=None, reasoning="x",
        candle_timestamp=1000, created_at=_now(),
    )
    base.update(overrides)
    return ExecutionLogRow(**base)


def _news_row(**overrides) -> NewsSentimentLogRow:
    base = dict(
        id=1, run_id="run-1", asset="GOLD", news_timestamp=None, fetch_timestamp=_now(),
        sentiment_score=0, signal_type="NEUTRAL", confidence=0.0, reasoning="x", source="local", created_at=_now(),
    )
    base.update(overrides)
    return NewsSentimentLogRow(**base)


class FormatExecutionLogLineTest(unittest.TestCase):
    def test_entry_shows_opened_price(self) -> None:
        row = _exec_row(strategy="TREND_PULLBACK", asset="BNB", signal_type="ENTRY", entry_price=10.5)

        line = format_execution_log_line(row)

        self.assertEqual(line, "Vatican | BNB TrendPullback | BNB/12h | ENTRY | OPENED @ 10.50")

    def test_exit_with_positive_r_multiple(self) -> None:
        row = _exec_row(
            strategy="BREAKOUT_MOMENTUM", asset="GOLD", signal_type="EXIT",
            exit_price=2500.0, reasoning="TARGET exit, r_multiple=0.890, net_pnl=45.00",
        )

        line = format_execution_log_line(row)

        self.assertEqual(line, "Vatican | GOLD Momentum | GOLD/1week | EXIT | +0.89R ✓")

    def test_exit_with_negative_r_multiple(self) -> None:
        row = _exec_row(
            strategy="BREAKOUT_MOMENTUM", asset="GOLD", signal_type="EXIT",
            exit_price=2350.0, reasoning="SL exit, r_multiple=-1.020, net_pnl=-90.00",
        )

        line = format_execution_log_line(row)

        self.assertEqual(line, "Vatican | GOLD Momentum | GOLD/1week | EXIT | -1.02R ✗")

    def test_exit_with_unparseable_reasoning_falls_back_to_r_na(self) -> None:
        row = _exec_row(strategy="BREAKOUT_MOMENTUM", asset="GOLD", signal_type="EXIT", reasoning="no r-multiple here")

        line = format_execution_log_line(row)

        self.assertTrue(line.endswith("R n/a"))

    def test_no_trade_shows_no_signal(self) -> None:
        row = _exec_row(strategy="COINTEGRATION_PAIRS", asset="BTC-ETH", signal_type="NO_TRADE", reasoning="|z|=0.1 below threshold")

        line = format_execution_log_line(row)

        self.assertEqual(line, "Vatican | BTC-ETH Pairs | BTC-ETH/12h | NO_TRADE | no signal")

    def test_unrecognized_strategy_asset_falls_back_to_raw_values(self) -> None:
        row = _exec_row(strategy="SOME_NEW_STRATEGY", asset="XYZ", signal_type="NO_TRADE")

        line = format_execution_log_line(row)

        self.assertEqual(line, "Vatican | SOME_NEW_STRATEGY | XYZ | NO_TRADE | no signal")


class FormatNewsSentimentLineTest(unittest.TestCase):
    def test_neutral_shows_no_signal(self) -> None:
        row = _news_row(asset="BTC", signal_type="NEUTRAL")

        line = format_news_sentiment_line(row)

        self.assertEqual(line, "Vatican | News Sentiment | BTC | NEUTRAL | no signal")

    def test_buy_bias_shows_confidence(self) -> None:
        row = _news_row(asset="GOLD", signal_type="BUY_BIAS", confidence=0.6)

        line = format_news_sentiment_line(row)

        self.assertEqual(line, "Vatican | News Sentiment | GOLD | BUY_BIAS | confidence 0.60")


class BuildNotificationMessageTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test_truth_ledger.db"
        self.addCleanup(self._tmp.cleanup)

    def test_empty_run_sends_zero_signal_fallback(self) -> None:
        insert_execution_metadata(
            run_id="run-empty", start_time=_now(), end_time=_now(),
            assets_evaluated=[], assets_skipped=[], errors_encountered=[], db_path=self.db_path,
        )

        message = build_notification_message("run-empty", db_path=self.db_path)

        self.assertEqual(message, ZERO_SIGNAL_MESSAGE)

    def test_run_with_signals_produces_one_line_per_row(self) -> None:
        insert_execution_log_row(
            run_id="run-1", strategy="TREND_PULLBACK", strategy_version="trend-pullback-v1.0.0",
            asset="BNB", signal_type="ENTRY", reasoning="entry conditions satisfied", candle_timestamp=1000,
            entry_price=10.5, db_path=self.db_path,
        )
        insert_news_sentiment_log(
            run_id="run-1", asset="GOLD", fetch_timestamp=_now(), signal_type="NEUTRAL",
            confidence=0.0, reasoning="no eligible headlines", source="local", db_path=self.db_path,
        )

        message = build_notification_message("run-1", db_path=self.db_path)
        lines = message.splitlines()

        self.assertEqual(len(lines), 2)
        self.assertIn("BNB TrendPullback", lines[0])
        self.assertIn("News Sentiment", lines[1])

    def test_only_rows_from_the_requested_run_are_included(self) -> None:
        insert_execution_log_row(
            run_id="run-old", strategy="TREND_PULLBACK", strategy_version="v1", asset="BNB",
            signal_type="NO_TRADE", reasoning="x", candle_timestamp=1000, db_path=self.db_path,
        )
        insert_execution_log_row(
            run_id="run-new", strategy="TREND_PULLBACK", strategy_version="v1", asset="BNB",
            signal_type="NO_TRADE", reasoning="y", candle_timestamp=2000, db_path=self.db_path,
        )

        message = build_notification_message("run-new", db_path=self.db_path)

        self.assertEqual(len(message.splitlines()), 1)


class SendNtfyNotificationTest(unittest.TestCase):
    def test_successful_post_returns_true_with_correct_payload(self) -> None:
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        with patch.object(notify_ntfy.requests, "post", return_value=mock_response) as mock_post:
            result = send_ntfy_notification("Vatican | test | line", url="https://ntfy.sh/Terminal3039")

        self.assertTrue(result)
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "https://ntfy.sh/Terminal3039")
        self.assertEqual(kwargs["data"], b"Vatican | test | line")

    def test_network_failure_returns_false_and_does_not_raise(self) -> None:
        with patch.object(notify_ntfy.requests, "post", side_effect=requests.exceptions.ConnectionError("unreachable")):
            result = send_ntfy_notification("Vatican | test | line")

        self.assertFalse(result)

    def test_non_2xx_response_returns_false_and_does_not_raise(self) -> None:
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("500 server error")

        with patch.object(notify_ntfy.requests, "post", return_value=mock_response):
            result = send_ntfy_notification("Vatican | test | line")

        self.assertFalse(result)

    def test_timeout_returns_false_and_does_not_raise(self) -> None:
        with patch.object(notify_ntfy.requests, "post", side_effect=requests.exceptions.Timeout("timed out")):
            result = send_ntfy_notification("Vatican | test | line")

        self.assertFalse(result)


class MainNeverRaisesEvenWhenNtfyIsUnreachableTest(unittest.TestCase):
    def test_main_completes_when_ntfy_is_unreachable(self) -> None:
        fake_run = MagicMock(run_id="run-1")
        with patch.object(notify_ntfy, "latest_execution_metadata", return_value=fake_run), \
             patch.object(notify_ntfy, "build_notification_message", return_value="Vatican | test | line"), \
             patch.object(notify_ntfy.requests, "post", side_effect=requests.exceptions.ConnectionError("down")):
            try:
                notify_ntfy.main()
            except Exception as exc:  # noqa: BLE001
                self.fail(f"main() must never raise, even when ntfy is unreachable; raised {exc!r}")

    def test_main_handles_no_prior_run_gracefully(self) -> None:
        with patch.object(notify_ntfy, "latest_execution_metadata", return_value=None), \
             patch.object(notify_ntfy.requests, "post", return_value=MagicMock(raise_for_status=MagicMock())) as mock_post:
            notify_ntfy.main()

        args, kwargs = mock_post.call_args
        self.assertEqual(kwargs["data"], ZERO_SIGNAL_MESSAGE.encode("utf-8"))


if __name__ == "__main__":
    unittest.main()
