from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from nero_core.data_sources.market_data import MarketDataClient, MarketDataResult, MarketDataUnavailableError
from nero_core.data_sources.news_feed import NewsFeedResult, NewsItem
from nero_core.data_sources.orderbook_data import OrderbookSnapshot
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
        # RMR GOLD/1week and SILVER/1week (Replay Machinery Generalization) both fetch
        # via load_intraday(interval="1week") -- SILVER now needs a fixture entry here
        # too (its other 5 configs are all 24h, fetched via load_daily instead).
        source_map = {
            "GOLD": self.gold_history,
            "BNB": self.bnb_history,
            "BTC": self.btc_history,
            "ETH": self.eth_history,
            "SILVER": self.silver_history,
        }
        if asset not in source_map:
            raise MarketDataUnavailableError(f"no fixture configured for {asset}")
        return MarketDataResult(prices=source_map[asset], source="test-fixture", asset=asset, interval=interval)

    def _fake_load_daily(self, asset, days=365, twelve_data_api_key=None):
        # RMR BTC/24h (long-only, confirmation) fetch via load_daily -- BTC needs a
        # fixture entry here too (its other config, COINTEGRATION_PAIRS, is 12h,
        # fetched via load_intraday instead).
        source_map = {"SILVER": self.silver_history, "BTC": self.btc_history}
        if asset not in source_map:
            raise MarketDataUnavailableError(f"no fixture configured for {asset}")
        return MarketDataResult(prices=source_map[asset], source="test-fixture", asset=asset, interval="1d")

    @staticmethod
    def _fake_fetch_and_cache_snapshot(binance_symbol, now=None, db_path=None):
        # imbalance_ratio=None -> ORDERFLOW_IMBALANCE never enters in these tests
        # (IMBALANCE_RATIO_UNDEFINED), keeping this a no-op for every other test's own
        # row-count/error assertions unless a test explicitly overrides it.
        return OrderbookSnapshot(
            timestamp=now or datetime(2026, 7, 17, 0, 5, tzinfo=timezone.utc), symbol=binance_symbol,
            best_bid=100.0, best_ask=100.1, bid_vol_20=1.0, ask_vol_20=1.0, imbalance_ratio=None, source="test-fixture",
        )

    def _patched_client(self):
        intraday_patcher = patch.object(MarketDataClient, "load_intraday", side_effect=self._fake_load_intraday)
        intraday_patcher.start()
        self.addCleanup(intraday_patcher.stop)
        daily_patcher = patch.object(MarketDataClient, "load_daily", side_effect=self._fake_load_daily)
        daily_patcher.start()
        self.addCleanup(daily_patcher.stop)
        orderbook_patcher = patch(
            "nero_core.execution.live_scheduler.fetch_and_cache_snapshot", side_effect=self._fake_fetch_and_cache_snapshot
        )
        orderbook_patcher.start()
        self.addCleanup(orderbook_patcher.stop)
        return MarketDataClient()


class NotDueSkipsWithoutFetchingTest(LiveSchedulerTestCase):
    def test_no_candle_gated_network_call_attempted_when_nothing_is_due(self) -> None:
        # ORDERFLOW_IMBALANCE has no candle_boundary_due gate (see live_scheduler.py's
        # module docstring) — it legitimately fetches every run, even when every other
        # config is NOT_DUE. This fixture lets ONLY that fetch through (and fails it
        # gracefully via MarketDataUnavailableError) while still proving every
        # candle-gated config makes zero network calls.
        def _explode(asset, *_args, **_kwargs):
            if asset in ("BTC", "ETH"):
                raise MarketDataUnavailableError("no network in this test")
            raise AssertionError(f"load_intraday/load_daily must not be called for {asset} when nothing is due")

        with patch.object(MarketDataClient, "load_intraday", side_effect=_explode), patch.object(
            MarketDataClient, "load_daily", side_effect=_explode
        ):
            client = MarketDataClient()
            result = live_scheduler.run_once(client=client, now=NOT_DUE_UTC, db_path=self.db_path)

        self.assertEqual(result.assets_evaluated, [])
        skipped_reasons = {r["classification"] for r in result.assets_skipped}
        self.assertEqual(skipped_reasons, {"NOT_DUE"})
        # GOLD, BNB, 5x SILVER, 4x RMR (GOLD/1week, SILVER/1week, BTC/24h long-only,
        # BTC/24h confirmation), pairs, NEWS_SENTIMENT (ORDERFLOW_IMBALANCE isn't
        # candle-gated, so it never appears among these NOT_DUE skips).
        self.assertEqual(len(result.assets_skipped), 13)
        orderflow_errors = [e for e in result.errors_encountered if e["strategy"] == "ORDERFLOW_IMBALANCE"]
        self.assertEqual(len(orderflow_errors), 2)  # BTC and ETH each fail their own fetch
        self.assertTrue(all(e["classification"] == "DATA_UNAVAILABLE" for e in orderflow_errors))


class FullRunTest(LiveSchedulerTestCase):
    def test_due_configs_are_evaluated_and_logged(self) -> None:
        client = self._patched_client()

        result = live_scheduler.run_once(client=client, now=FRIDAY_MIDNIGHT_UTC, db_path=self.db_path)

        self.assertIn("GOLD", result.assets_evaluated)
        self.assertIn("BNB", result.assets_evaluated)
        self.assertIn("BTC-ETH", result.assets_evaluated)
        # 5 pre-existing SILVER configs + RANGE_MEAN_REVERSION's own SILVER/1week
        # (Replay Machinery Generalization).
        self.assertEqual(result.assets_evaluated.count("SILVER"), 6)
        # RANGE_MEAN_REVERSION's own BTC/24h long-only and confirmation configs.
        self.assertEqual(result.assets_evaluated.count("BTC"), 2)
        self.assertEqual(result.errors_encountered, [])

        gold_rows = list_execution_log(db_path=self.db_path, asset="GOLD")
        self.assertGreaterEqual(len(gold_rows), 1)
        gold_strategy_versions = {(r.strategy, r.strategy_version) for r in gold_rows}
        self.assertEqual(len(gold_strategy_versions), 2)  # BREAKOUT_MOMENTUM + RANGE_MEAN_REVERSION, none colliding
        silver_rows = list_execution_log(db_path=self.db_path, asset="SILVER")
        self.assertGreaterEqual(len(silver_rows), 1)
        silver_strategy_versions = {(r.strategy, r.strategy_version) for r in silver_rows}
        self.assertEqual(len(silver_strategy_versions), 6)  # 6 distinct SILVER configs, none colliding
        btc_rows = list_execution_log(db_path=self.db_path, asset="BTC")
        btc_strategy_versions = {(r.strategy, r.strategy_version) for r in btc_rows}
        self.assertEqual(len(btc_strategy_versions), 2)  # long-only + confirmation, none colliding

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
            source_map = {"BNB": self.bnb_history, "BTC": self.btc_history, "ETH": self.eth_history, "SILVER": self.silver_history}
            return MarketDataResult(prices=source_map[asset], source="test-fixture", asset=asset, interval=interval)

        with patch.object(MarketDataClient, "load_intraday", side_effect=_fake_load_intraday), patch.object(
            MarketDataClient, "load_daily", side_effect=self._fake_load_daily
        ), patch(
            "nero_core.execution.live_scheduler.fetch_and_cache_snapshot", side_effect=self._fake_fetch_and_cache_snapshot
        ):
            client = MarketDataClient()
            result = live_scheduler.run_once(client=client, now=FRIDAY_MIDNIGHT_UTC, db_path=self.db_path, sleep_fn=lambda _s: None)

        self.assertNotIn("GOLD", result.assets_evaluated)
        self.assertIn("BNB", result.assets_evaluated)
        self.assertIn("BTC-ETH", result.assets_evaluated)

        # TWO configs now fetch GOLD/1week (BREAKOUT_MOMENTUM and, since the Replay
        # Machinery Generalization, RANGE_MEAN_REVERSION) -- both fail from the same
        # fixture's missing-API-key GOLD error.
        gold_errors = [e for e in result.errors_encountered if e["asset"] == "GOLD"]
        self.assertEqual(len(gold_errors), 2)
        self.assertTrue(all(e["classification"] == "FATAL" for e in gold_errors))

    def test_transient_failure_retries_then_succeeds(self) -> None:
        call_count = {"GOLD": 0}

        def _fake_load_intraday(asset, interval="1h", candles=240, twelve_data_api_key=None):
            if asset == "GOLD":
                call_count["GOLD"] += 1
                if call_count["GOLD"] < 3:
                    raise MarketDataUnavailableError("Binance: ConnectionError: timed out")
                return MarketDataResult(prices=self.gold_history, source="test-fixture", asset="GOLD", interval=interval)
            source_map = {"BNB": self.bnb_history, "BTC": self.btc_history, "ETH": self.eth_history, "SILVER": self.silver_history}
            return MarketDataResult(prices=source_map[asset], source="test-fixture", asset=asset, interval=interval)

        sleeps: list[float] = []
        with patch.object(MarketDataClient, "load_intraday", side_effect=_fake_load_intraday), patch.object(
            MarketDataClient, "load_daily", side_effect=self._fake_load_daily
        ), patch(
            "nero_core.execution.live_scheduler.fetch_and_cache_snapshot", side_effect=self._fake_fetch_and_cache_snapshot
        ):
            client = MarketDataClient()
            result = live_scheduler.run_once(client=client, now=FRIDAY_MIDNIGHT_UTC, db_path=self.db_path, sleep_fn=sleeps.append)

        self.assertIn("GOLD", result.assets_evaluated)
        # BREAKOUT_MOMENTUM's GOLD/1week fetch fails twice then succeeds on the 3rd
        # call (clearing call_count["GOLD"] to 3); RANGE_MEAN_REVERSION's own GOLD/
        # 1week fetch runs afterward and succeeds immediately on its first call (the
        # counter has already cleared the < 3 failure threshold) -- 4 calls total,
        # only the first config's 2 failures produce backoff sleeps.
        self.assertEqual(call_count["GOLD"], 4)
        self.assertEqual(sleeps, [1, 3])

    def test_transient_failure_exhausting_all_retries_is_skipped_not_fatal(self) -> None:
        def _fake_load_intraday(asset, interval="1h", candles=240, twelve_data_api_key=None):
            if asset == "GOLD":
                raise MarketDataUnavailableError("Binance: ConnectionError: timed out")
            source_map = {"BNB": self.bnb_history, "BTC": self.btc_history, "ETH": self.eth_history, "SILVER": self.silver_history}
            return MarketDataResult(prices=source_map[asset], source="test-fixture", asset=asset, interval=interval)

        with patch.object(MarketDataClient, "load_intraday", side_effect=_fake_load_intraday), patch.object(
            MarketDataClient, "load_daily", side_effect=self._fake_load_daily
        ), patch(
            "nero_core.execution.live_scheduler.fetch_and_cache_snapshot", side_effect=self._fake_fetch_and_cache_snapshot
        ):
            client = MarketDataClient()
            result = live_scheduler.run_once(client=client, now=FRIDAY_MIDNIGHT_UTC, db_path=self.db_path, sleep_fn=lambda _s: None)

        self.assertNotIn("GOLD", result.assets_evaluated)
        # Both GOLD/1week configs (BREAKOUT_MOMENTUM and RANGE_MEAN_REVERSION) exhaust
        # their retries and get skipped.
        gold_skips = [r for r in result.assets_skipped if r["asset"] == "GOLD"]
        self.assertEqual(len(gold_skips), 2)
        self.assertTrue(all(s["classification"] == "FETCH_INCOMPLETE" for s in gold_skips))
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


def _uptrend_1h_history(n: int = 40) -> pd.DataFrame:
    """Steady uptrend so close ends up above MA20 — the entry precondition
    ORDERFLOW_IMBALANCE's LONG side needs alongside a high imbalance_ratio."""
    rows = []
    close_time = 0
    for i in range(n):
        rows.append(_make_candle_row(close_time, 100.0 + i * 0.5))
        close_time += 3_600_000
    return pd.DataFrame(rows)


class OrderflowImbalanceSchedulingTest(LiveSchedulerTestCase):
    """Task C1: proves the full scheduler-integration loop — snapshot fetch -> entry ->
    Truth Ledger logging -> state reconstruction on the next run -> ratio-reversal
    exit — not just the pure strategy-function unit tests in
    tests/test_orderflow_imbalance.py."""

    def setUp(self) -> None:
        super().setUp()
        self.btc_uptrend_history = _uptrend_1h_history()

    def _patched_client_with_uptrend_btc(self):
        def _fake_load_intraday(asset, interval="1h", candles=240, twelve_data_api_key=None):
            source_map = {
                "GOLD": self.gold_history, "BNB": self.bnb_history,
                "BTC": self.btc_uptrend_history, "ETH": self.btc_uptrend_history,
            }
            if asset not in source_map:
                raise MarketDataUnavailableError(f"no fixture configured for {asset}")
            return MarketDataResult(prices=source_map[asset], source="test-fixture", asset=asset, interval=interval)

        patcher = patch.object(MarketDataClient, "load_intraday", side_effect=_fake_load_intraday)
        patcher.start()
        self.addCleanup(patcher.stop)
        daily_patcher = patch.object(MarketDataClient, "load_daily", side_effect=self._fake_load_daily)
        daily_patcher.start()
        self.addCleanup(daily_patcher.stop)
        return MarketDataClient()

    def test_entry_logged_then_reversal_exit_on_a_later_run(self) -> None:
        def _high_ratio_snapshot(binance_symbol, now=None, db_path=None):
            return OrderbookSnapshot(
                timestamp=now, symbol=binance_symbol, best_bid=100.0, best_ask=100.1,
                bid_vol_20=10.0, ask_vol_20=1.0, imbalance_ratio=10.0, source="test-fixture",
            )

        client = self._patched_client_with_uptrend_btc()
        with patch("nero_core.execution.live_scheduler.fetch_and_cache_snapshot", side_effect=_high_ratio_snapshot):
            first = live_scheduler.run_once(client=client, now=NOT_DUE_UTC, db_path=self.db_path)

        self.assertIn("ORDERFLOW_IMBALANCE:BTC", first.assets_evaluated)
        entry_rows = [r for r in list_execution_log(db_path=self.db_path, asset="BTC", strategy="ORDERFLOW_IMBALANCE") if r.signal_type == "ENTRY"]
        self.assertEqual(len(entry_rows), 1)
        self.assertIn("direction=LONG", entry_rows[0].reasoning)
        self.assertIsNotNone(entry_rows[0].entry_price)

        def _reversal_ratio_snapshot(binance_symbol, now=None, db_path=None):
            return OrderbookSnapshot(
                timestamp=now, symbol=binance_symbol, best_bid=100.0, best_ask=100.1,
                bid_vol_20=1.0, ask_vol_20=1.0, imbalance_ratio=1.0, source="test-fixture",
            )

        with patch("nero_core.execution.live_scheduler.fetch_and_cache_snapshot", side_effect=_reversal_ratio_snapshot):
            second = live_scheduler.run_once(client=client, now=NOT_DUE_UTC, db_path=self.db_path)

        self.assertIn("ORDERFLOW_IMBALANCE:BTC", second.assets_evaluated)
        exit_rows = [r for r in list_execution_log(db_path=self.db_path, asset="BTC", strategy="ORDERFLOW_IMBALANCE") if r.signal_type == "EXIT"]
        self.assertEqual(len(exit_rows), 1)
        self.assertIn("RATIO_REVERSAL", exit_rows[0].reasoning)

    def test_no_open_position_undefined_ratio_never_enters(self) -> None:
        def _undefined_ratio_snapshot(binance_symbol, now=None, db_path=None):
            return OrderbookSnapshot(
                timestamp=now, symbol=binance_symbol, best_bid=100.0, best_ask=100.1,
                bid_vol_20=5.0, ask_vol_20=0.0, imbalance_ratio=None, source="test-fixture",
            )

        client = self._patched_client_with_uptrend_btc()
        with patch("nero_core.execution.live_scheduler.fetch_and_cache_snapshot", side_effect=_undefined_ratio_snapshot):
            result = live_scheduler.run_once(client=client, now=NOT_DUE_UTC, db_path=self.db_path)

        self.assertIn("ORDERFLOW_IMBALANCE:BTC", result.assets_evaluated)
        rows = list_execution_log(db_path=self.db_path, asset="BTC", strategy="ORDERFLOW_IMBALANCE")
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
