from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from nero_core.data_sources.market_data import MarketDataClient, MarketDataResult, MarketDataUnavailableError
from nero_core.data_sources.news_feed import NewsFeedResult, NewsItem
from nero_core.execution import live_scheduler
from nero_core.truth_ledger.execution_log import list_execution_log, list_execution_metadata, has_news_sentiment_logged_today
from tests.test_cointegration_pairs import _cointegrated_pair_frames
from tests.test_council_engine import _make_candle_row

FRIDAY_MIDNIGHT_UTC = datetime(2026, 7, 17, 0, 5, tzinfo=timezone.utc)  # 2026-07-17 is a Friday
NEWS_HOUR_UTC = datetime(2026, 7, 17, 19, 5, tzinfo=timezone.utc)
NOT_DUE_UTC = datetime(2026, 7, 17, 6, 0, tzinfo=timezone.utc)  # off every boundary this module checks


def _weekly_breakout_history(n_flat: int = 220, n_breakout: int = 15) -> pd.DataFrame:
    rows: list[dict[str, float]] = []
    close_time = 0
    for i in range(n_flat):
        close = 100.0 + 0.01 * i
        rows.append(_make_candle_row(close_time, close))
        close_time += 7 * 86_400_000
    price = rows[-1]["close"]
    for _ in range(n_breakout):
        price *= 1.05
        rows.append(_make_candle_row(close_time, price))
        close_time += 7 * 86_400_000
    return pd.DataFrame(rows)


def _flat_history(n: int = 260) -> pd.DataFrame:
    rows = []
    close_time = 0
    for i in range(n):
        rows.append(_make_candle_row(close_time, 100.0 + (i % 5) * 0.1))
        close_time += 12 * 3_600_000
    return pd.DataFrame(rows)


def _silver_daily_history(n: int = 300) -> pd.DataFrame:
    """300 daily candles, enough warmup past every SILVER config's MA200 requirement
    (BREAKOUT_MOMENTUM/TREND_PULLBACK/VOLATILITY_SQUEEZE ma200) — mild oscillation
    (not perfectly flat) so ATR is non-zero, matching _flat_history's convention."""
    rows = []
    close_time = 0
    for i in range(n):
        rows.append(_make_candle_row(close_time, 100.0 + (i % 5) * 0.1))
        close_time += 86_400_000
    return pd.DataFrame(rows)


class LiveSchedulerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test_truth_ledger.db"
        self.addCleanup(self._tmp.cleanup)

        self.gold_history = _weekly_breakout_history()
        btc_df, eth_df = _cointegrated_pair_frames(500)
        self.btc_history = btc_df
        self.eth_history = eth_df
        self.bnb_history = _flat_history()
        self.silver_history = _silver_daily_history()

    def _fake_load_intraday(self, asset, interval="1h", candles=240, twelve_data_api_key=None):
        source_map = {
            "GOLD": self.gold_history,
            "BNB": self.bnb_history,
            "BTC": self.btc_history,
            "ETH": self.eth_history,
        }
        if asset not in source_map:
            raise MarketDataUnavailableError(f"no fixture configured for {asset}")
        return MarketDataResult(prices=source_map[asset], source="test-fixture", asset=asset, interval=interval)

    def _fake_load_daily(self, asset, days=365, twelve_data_api_key=None):
        source_map = {"SILVER": self.silver_history}
        if asset not in source_map:
            raise MarketDataUnavailableError(f"no fixture configured for {asset}")
        return MarketDataResult(prices=source_map[asset], source="test-fixture", asset=asset, interval="1d")

    def _patched_client(self):
        intraday_patcher = patch.object(MarketDataClient, "load_intraday", side_effect=self._fake_load_intraday)
        intraday_patcher.start()
        self.addCleanup(intraday_patcher.stop)
        daily_patcher = patch.object(MarketDataClient, "load_daily", side_effect=self._fake_load_daily)
        daily_patcher.start()
        self.addCleanup(daily_patcher.stop)
        return MarketDataClient()


class NotDueSkipsWithoutFetchingTest(LiveSchedulerTestCase):
    def test_no_network_call_attempted_when_nothing_is_due(self) -> None:
        def _explode(*_args, **_kwargs):
            raise AssertionError("load_intraday/load_daily must not be called when nothing is due")

        with patch.object(MarketDataClient, "load_intraday", side_effect=_explode), patch.object(
            MarketDataClient, "load_daily", side_effect=_explode
        ):
            client = MarketDataClient()
            result = live_scheduler.run_once(client=client, now=NOT_DUE_UTC, db_path=self.db_path)

        self.assertEqual(result.assets_evaluated, [])
        skipped_reasons = {r["classification"] for r in result.assets_skipped}
        self.assertEqual(skipped_reasons, {"NOT_DUE"})
        # GOLD, BNB, 5x SILVER, pairs, NEWS_SENTIMENT
        self.assertEqual(len(result.assets_skipped), 9)


class FullRunTest(LiveSchedulerTestCase):
    def test_due_configs_are_evaluated_and_logged(self) -> None:
        client = self._patched_client()

        result = live_scheduler.run_once(client=client, now=FRIDAY_MIDNIGHT_UTC, db_path=self.db_path)

        self.assertIn("GOLD", result.assets_evaluated)
        self.assertIn("BNB", result.assets_evaluated)
        self.assertIn("BTC-ETH", result.assets_evaluated)
        self.assertEqual(result.assets_evaluated.count("SILVER"), 5)
        self.assertEqual(result.errors_encountered, [])

        gold_rows = list_execution_log(db_path=self.db_path, asset="GOLD")
        self.assertGreaterEqual(len(gold_rows), 1)
        silver_rows = list_execution_log(db_path=self.db_path, asset="SILVER")
        self.assertGreaterEqual(len(silver_rows), 1)
        silver_strategy_versions = {(r.strategy, r.strategy_version) for r in silver_rows}
        self.assertEqual(len(silver_strategy_versions), 5)  # 5 distinct SILVER configs, none colliding

        metadata_rows = list_execution_metadata(db_path=self.db_path)
        self.assertEqual(len(metadata_rows), 1)
        self.assertEqual(metadata_rows[0].run_id, result.run_id)

    def test_running_twice_with_identical_data_produces_no_duplicate_rows(self) -> None:
        client = self._patched_client()

        live_scheduler.run_once(client=client, now=FRIDAY_MIDNIGHT_UTC, db_path=self.db_path)
        first_count = len(list_execution_log(db_path=self.db_path))

        second_result = live_scheduler.run_once(client=client, now=FRIDAY_MIDNIGHT_UTC, db_path=self.db_path)
        second_count = len(list_execution_log(db_path=self.db_path))

        self.assertEqual(first_count, second_count)
        # Fetches still succeed and evaluate the same (already-logged) candle again.
        self.assertIn("GOLD", second_result.assets_evaluated)
        self.assertEqual(len(list_execution_metadata(db_path=self.db_path)), 2)


class PartialFailureResilienceTest(LiveSchedulerTestCase):
    def test_one_configs_permanent_failure_does_not_block_the_others(self) -> None:
        def _fake_load_intraday(asset, interval="1h", candles=240, twelve_data_api_key=None):
            if asset == "GOLD":
                raise MarketDataUnavailableError("Twelve Data: missing API key")
            source_map = {"BNB": self.bnb_history, "BTC": self.btc_history, "ETH": self.eth_history}
            return MarketDataResult(prices=source_map[asset], source="test-fixture", asset=asset, interval=interval)

        with patch.object(MarketDataClient, "load_intraday", side_effect=_fake_load_intraday), patch.object(
            MarketDataClient, "load_daily", side_effect=self._fake_load_daily
        ):
            client = MarketDataClient()
            result = live_scheduler.run_once(client=client, now=FRIDAY_MIDNIGHT_UTC, db_path=self.db_path, sleep_fn=lambda _s: None)

        self.assertNotIn("GOLD", result.assets_evaluated)
        self.assertIn("BNB", result.assets_evaluated)
        self.assertIn("BTC-ETH", result.assets_evaluated)

        gold_errors = [e for e in result.errors_encountered if e["asset"] == "GOLD"]
        self.assertEqual(len(gold_errors), 1)
        self.assertEqual(gold_errors[0]["classification"], "FATAL")

    def test_transient_failure_retries_then_succeeds(self) -> None:
        call_count = {"GOLD": 0}

        def _fake_load_intraday(asset, interval="1h", candles=240, twelve_data_api_key=None):
            if asset == "GOLD":
                call_count["GOLD"] += 1
                if call_count["GOLD"] < 3:
                    raise MarketDataUnavailableError("Binance: ConnectionError: timed out")
                return MarketDataResult(prices=self.gold_history, source="test-fixture", asset="GOLD", interval=interval)
            source_map = {"BNB": self.bnb_history, "BTC": self.btc_history, "ETH": self.eth_history}
            return MarketDataResult(prices=source_map[asset], source="test-fixture", asset=asset, interval=interval)

        sleeps: list[float] = []
        with patch.object(MarketDataClient, "load_intraday", side_effect=_fake_load_intraday), patch.object(
            MarketDataClient, "load_daily", side_effect=self._fake_load_daily
        ):
            client = MarketDataClient()
            result = live_scheduler.run_once(client=client, now=FRIDAY_MIDNIGHT_UTC, db_path=self.db_path, sleep_fn=sleeps.append)

        self.assertIn("GOLD", result.assets_evaluated)
        self.assertEqual(call_count["GOLD"], 3)
        self.assertEqual(sleeps, [1, 3])

    def test_transient_failure_exhausting_all_retries_is_skipped_not_fatal(self) -> None:
        def _fake_load_intraday(asset, interval="1h", candles=240, twelve_data_api_key=None):
            if asset == "GOLD":
                raise MarketDataUnavailableError("Binance: ConnectionError: timed out")
            source_map = {"BNB": self.bnb_history, "BTC": self.btc_history, "ETH": self.eth_history}
            return MarketDataResult(prices=source_map[asset], source="test-fixture", asset=asset, interval=interval)

        with patch.object(MarketDataClient, "load_intraday", side_effect=_fake_load_intraday), patch.object(
            MarketDataClient, "load_daily", side_effect=self._fake_load_daily
        ):
            client = MarketDataClient()
            result = live_scheduler.run_once(client=client, now=FRIDAY_MIDNIGHT_UTC, db_path=self.db_path, sleep_fn=lambda _s: None)

        self.assertNotIn("GOLD", result.assets_evaluated)
        gold_skips = [r for r in result.assets_skipped if r["asset"] == "GOLD"]
        self.assertEqual(len(gold_skips), 1)
        self.assertEqual(gold_skips[0]["classification"], "FETCH_INCOMPLETE")
        self.assertEqual(result.errors_encountered, [])


class NewsSentimentSchedulingTest(LiveSchedulerTestCase):
    def test_news_sentiment_runs_at_its_daily_hour_and_dedupes_same_day(self) -> None:
        headlines = [
            NewsItem(
                title="gold price surge rally record high",
                source="Test", link="", published="Fri, 17 Jul 2026 12:00:00 GMT", tags=[],
            )
        ]
        fake_result = NewsFeedResult(headlines=headlines, status="live (1 matched)")

        with patch("nero_core.execution.live_scheduler.NewsFeedClient.load", return_value=fake_result):
            client = self._patched_client()
            first = live_scheduler.run_once(client=client, now=NEWS_HOUR_UTC, db_path=self.db_path)

            self.assertTrue(has_news_sentiment_logged_today("GOLD", NEWS_HOUR_UTC, db_path=self.db_path))
            self.assertTrue(has_news_sentiment_logged_today("BTC", NEWS_HOUR_UTC, db_path=self.db_path))
            self.assertIn("NEWS_SENTIMENT:GOLD", first.assets_evaluated)

            later_same_day = NEWS_HOUR_UTC.replace(minute=35)
            second = live_scheduler.run_once(client=client, now=later_same_day, db_path=self.db_path)

        # Already logged today -> the daily gate skips re-fetching/re-scoring entirely.
        self.assertNotIn("NEWS_SENTIMENT:GOLD", second.assets_evaluated)

    def test_news_sentiment_not_due_outside_its_daily_hour(self) -> None:
        client = self._patched_client()

        result = live_scheduler.run_once(client=client, now=FRIDAY_MIDNIGHT_UTC, db_path=self.db_path)

        news_skips = [r for r in result.assets_skipped if r["asset"] == "NEWS_SENTIMENT"]
        self.assertEqual(len(news_skips), 1)
        self.assertEqual(news_skips[0]["classification"], "NOT_DUE")


if __name__ == "__main__":
    unittest.main()
