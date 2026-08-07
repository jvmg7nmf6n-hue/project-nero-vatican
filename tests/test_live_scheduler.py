from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import json

from nero_core.data_sources.forex_data import ForexDataResult, ForexDataUnavailableError
from nero_core.data_sources.market_data import MarketDataClient, MarketDataResult, MarketDataUnavailableError
from nero_core.data_sources.news_feed import NewsFeedResult, NewsItem
from nero_core.data_sources.orderbook_data import OrderbookSnapshot
from nero_core.execution import live_scheduler
from nero_core.strategies.news_sentiment import STRATEGY_VERSION as NEWS_SENTIMENT_V1_VERSION
from nero_core.strategies.news_sentiment_llm import STRATEGY_VERSION as NEWS_SENTIMENT_V2_VERSION
from nero_core.strategies.trend_pullback import STRATEGY_ID as TREND_PULLBACK_ID
from nero_core.strategies.trend_pullback import STRATEGY_VERSION as TREND_PULLBACK_VERSION
from nero_core.truth_ledger.execution_log import (
    has_news_sentiment_logged_today,
    insert_execution_log_row,
    latest_news_sentiment_fetch_timestamp,
    list_execution_log,
    list_execution_metadata,
    list_news_sentiment_log_for_run,
)
from tests.test_cointegration_pairs import _cointegrated_pair_frames
from tests.test_council_engine import _make_candle_row


def _mock_claude_response(impact_on_gold: str = "NEUTRAL", impact_on_btc: str = "NEUTRAL", confidence: float = 0.2, surprise_score: float = 0.1):
    """Mocked Claude Messages API response, matching the real shape (a "type":
    "text" content block) -- used so NewsSentimentSchedulingTest never makes a real
    Anthropic API call, regardless of whether ANTHROPIC_API_KEY happens to be set in
    the environment running the test suite."""
    from unittest.mock import MagicMock

    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    payload = {
        "impact_on_gold": impact_on_gold, "impact_on_btc": impact_on_btc,
        "confidence": confidence, "surprise_score": surprise_score, "reasoning": "test",
    }
    resp.json.return_value = {"content": [{"type": "text", "text": json.dumps(payload)}]}
    return resp

# CC-1 DIRECTIVE FIX (2026-08-07): was a Friday (2026-07-17) -- renamed and
# redated to a Monday (2026-07-13) after candle_schedule.py's own
# WEEKLY_CLOSE_WEEKDAY was corrected from Friday to Monday (confirmed via
# real execution_log data across all 4 "1week"-gated configs that Twelve
# Data's real weekly candle closes/labels on Monday, not Friday -- see
# docs/investigations/factory_loop_implementation_report.md). Every test
# using this constant wants a moment where BOTH "24h" and "1week" are due
# simultaneously; "24h" doesn't care which weekday, so only the date needed
# to change, not the shape of any test.
WEEKLY_BOUNDARY_MIDNIGHT_UTC = datetime(2026, 7, 13, 0, 5, tzinfo=timezone.utc)  # 2026-07-13 is a Monday
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


def _forex_weekly_history(n: int = 260) -> pd.DataFrame:
    """Weekly forex history, mildly oscillating (matches _flat_history's non-zero-ATR
    convention) -- none of the 3 Donchian forex configs are the subject of these
    general scheduler tests (see tests/test_live_wiring_donchian_deep_dive.py for
    that), so this just needs to evaluate cleanly (NO_TRADE is fine)."""
    rows = []
    close_time = 0
    for i in range(n):
        rows.append(_make_candle_row(close_time, 100.0 + (i % 5) * 0.1))
        close_time += 7 * 86_400_000
    return pd.DataFrame(rows)


def _daily_history(n: int, base: float) -> pd.DataFrame:
    """n daily candles (close_time starting at 0, same clock as _silver_daily_history)
    mildly oscillating around `base` -- used where two series must share calendar
    dates (e.g. align_gold_silver_candles), unlike _weekly_breakout_history's 7-day
    step."""
    rows = []
    close_time = 0
    for i in range(n):
        rows.append(_make_candle_row(close_time, base + (i % 7) * (base * 0.001)))
        close_time += 86_400_000
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
        self.forex_history = _forex_weekly_history()

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
        # fetched via load_intraday instead). GOLD_SILVER_RATIO_MR's own GOLD/24h
        # leg also fetches via load_daily (GOLD's other config, BREAKOUT_MOMENTUM/
        # 1week, uses load_intraday instead) -- needs its own fixture entry here too.
        source_map = {"SILVER": self.silver_history, "BTC": self.btc_history, "GOLD": self.gold_history}
        if asset not in source_map:
            raise MarketDataUnavailableError(f"no fixture configured for {asset}")
        return MarketDataResult(prices=source_map[asset], source="test-fixture", asset=asset, interval="1d")

    @staticmethod
    def _fake_fetch_earnings_surprises(ticker, limit=100):
        # PEAD isn't the subject of these general scheduler tests -- cleanly
        # SKIPPED (FETCH_INCOMPLETE, same TRANSIENT classification every other
        # missing-fixture asset in this file gets -- see classify_market_data_
        # error). Callers using this fixture with PEAD in scope MUST pass
        # sleep_fn=lambda s: None (see _patched_client's own docstring below)
        # -- otherwise each of PEAD's 14 configs retries 3x with REAL
        # time.sleep (1+3+10=14s), the exact real-sleep-contamination bug this
        # project has hit twice before with other missing test fixtures.
        # Dedicated PEAD behavior (mocked earnings response, NO_SIGNAL,
        # pairs-leg accounting) is covered in tests/test_live_wiring_post_batch.py.
        from nero_core.data_sources.earnings_data import EarningsDataUnavailableError
        raise EarningsDataUnavailableError(f"no fixture configured for {ticker}")

    @staticmethod
    def _fake_fetch_stock_ohlcv(symbol, timeframe, start=None, end=None, sleep_fn=None):
        from nero_core.data_sources.stock_data import StockDataUnavailableError
        raise StockDataUnavailableError(f"no fixture configured for {symbol}")

    def _fake_fetch_forex_ohlcv(self, pair, timeframe, *args, **kwargs):
        source_map = {"EUR/USD": self.forex_history, "GBP/USD": self.forex_history, "USD/JPY": self.forex_history}
        if pair not in source_map:
            raise ForexDataUnavailableError(f"no fixture configured for {pair}")
        return ForexDataResult(prices=source_map[pair], source="test-fixture", pair=pair, timeframe=timeframe)

    @staticmethod
    def _fake_fetch_and_cache_snapshot(binance_symbol, now=None, db_path=None):
        # imbalance_ratio=None -> ORDERFLOW_IMBALANCE never enters in these tests
        # (IMBALANCE_RATIO_UNDEFINED), keeping this a no-op for every other test's own
        # row-count/error assertions unless a test explicitly overrides it.
        return OrderbookSnapshot(
            timestamp=now or datetime(2026, 7, 17, 0, 5, tzinfo=timezone.utc), symbol=binance_symbol,
            best_bid=100.0, best_ask=100.1, bid_vol_20=1.0, ask_vol_20=1.0, imbalance_ratio=None, source="test-fixture",
        )

    def _patch_pead_fetchers(self) -> None:
        """Shared by _patched_client() and every PartialFailureResilienceTest
        method's own local patch set -- PEAD's fetchers are never mocked to
        real data in these general scheduler tests (see
        _fake_fetch_earnings_surprises), so PEAD's 14 configs are always
        cleanly SKIPPED here, never hitting real yfinance calls."""
        earnings_patcher = patch(
            "nero_core.execution.live_scheduler.fetch_earnings_surprises", side_effect=self._fake_fetch_earnings_surprises
        )
        earnings_patcher.start()
        self.addCleanup(earnings_patcher.stop)
        stock_patcher = patch(
            "nero_core.execution.live_scheduler.fetch_stock_ohlcv", side_effect=self._fake_fetch_stock_ohlcv
        )
        stock_patcher.start()
        self.addCleanup(stock_patcher.stop)

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
        forex_patcher = patch(
            "nero_core.execution.live_scheduler.fetch_forex_ohlcv", side_effect=self._fake_fetch_forex_ohlcv
        )
        forex_patcher.start()
        self.addCleanup(forex_patcher.stop)
        self._patch_pead_fetchers()
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
        # BTC/24h confirmation), 1x DONCHIAN_TREND/GOLD/1week, pairs, GOLD-SILVER
        # (GOLD_SILVER_RATIO_MR), 14x PEAD (7 tickers x 2 configs), 3x DONCHIAN_TREND
        # forex (EUR/USD, GBP/USD, USD/JPY), NEWS_SENTIMENT (ORDERFLOW_IMBALANCE isn't
        # candle-gated, so it never appears among these NOT_DUE skips).
        self.assertEqual(len(result.assets_skipped), 32)
        orderflow_errors = [e for e in result.errors_encountered if e["strategy"] == "ORDERFLOW_IMBALANCE"]
        self.assertEqual(len(orderflow_errors), 2)  # BTC and ETH each fail their own fetch
        self.assertTrue(all(e["classification"] == "DATA_UNAVAILABLE" for e in orderflow_errors))


class FullRunTest(LiveSchedulerTestCase):
    def test_due_configs_are_evaluated_and_logged(self) -> None:
        client = self._patched_client()

        # sleep_fn=lambda s: None -- PEAD's 14 configs all hit the shared "no
        # fixture configured" TRANSIENT classification (real earnings/stock
        # data isn't mocked in this general scheduler test), which would
        # otherwise retry 3x with REAL time.sleep (1+3+10=14s) EACH.
        result = live_scheduler.run_once(client=client, now=WEEKLY_BOUNDARY_MIDNIGHT_UTC, db_path=self.db_path, sleep_fn=lambda s: None)

        self.assertIn("GOLD", result.assets_evaluated)
        self.assertIn("BNB", result.assets_evaluated)
        self.assertIn("BTC-ETH", result.assets_evaluated)
        self.assertIn("EUR/USD", result.assets_evaluated)
        self.assertIn("GBP/USD", result.assets_evaluated)
        self.assertIn("USD/JPY", result.assets_evaluated)
        # 5 pre-existing SILVER configs + RANGE_MEAN_REVERSION's own SILVER/1week
        # (Replay Machinery Generalization).
        self.assertEqual(result.assets_evaluated.count("SILVER"), 6)
        # RANGE_MEAN_REVERSION's own BTC/24h long-only and confirmation configs.
        self.assertEqual(result.assets_evaluated.count("BTC"), 2)
        self.assertEqual(result.errors_encountered, [])

        gold_rows = list_execution_log(db_path=self.db_path, asset="GOLD")
        self.assertGreaterEqual(len(gold_rows), 1)
        gold_strategy_versions = {(r.strategy, r.strategy_version) for r in gold_rows}
        self.assertEqual(len(gold_strategy_versions), 3)  # BREAKOUT_MOMENTUM + RANGE_MEAN_REVERSION + DONCHIAN_TREND, none colliding
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

        live_scheduler.run_once(client=client, now=WEEKLY_BOUNDARY_MIDNIGHT_UTC, db_path=self.db_path, sleep_fn=lambda s: None)
        first_count = len(list_execution_log(db_path=self.db_path))

        second_result = live_scheduler.run_once(client=client, now=WEEKLY_BOUNDARY_MIDNIGHT_UTC, db_path=self.db_path, sleep_fn=lambda s: None)
        second_count = len(list_execution_log(db_path=self.db_path))

        self.assertEqual(first_count, second_count)
        # Fetches still succeed and evaluate the same (already-logged) candle again.
        self.assertIn("GOLD", second_result.assets_evaluated)
        self.assertEqual(len(list_execution_metadata(db_path=self.db_path)), 2)

    def test_a_redundant_delayed_run_within_the_same_window_does_not_duplicate(self) -> None:
        """The exact scenario the REDUNDANT TRIGGER safety net (2026-07-29
        infrastructure-resilience task) depends on: a first run lands early in the
        1week/24h boundary window, GitHub Actions drops/delays the next few ticks
        (see .github/workflows/live_scheduler.yml's own REDUNDANT TRIGGER SAFETY NET
        comment), and a LATER run -- different `now`, still inside
        SINGLE_SHOT_TOLERANCE_MINUTES -- picks up the same period. Both `now` values
        must resolve to candle_boundary_due(...)=True for this to actually exercise
        the scenario, not just re-run the exact same instant."""
        client = self._patched_client()
        first_now = WEEKLY_BOUNDARY_MIDNIGHT_UTC  # 00:05 UTC Monday
        second_now = datetime(2026, 7, 13, 3, 30, tzinfo=timezone.utc)  # same window, 3h25m later
        self.assertTrue(live_scheduler.candle_boundary_due("1week", second_now))
        self.assertTrue(live_scheduler.candle_boundary_due("24h", second_now))

        live_scheduler.run_once(client=client, now=first_now, db_path=self.db_path, sleep_fn=lambda s: None)
        first_count = len(list_execution_log(db_path=self.db_path))

        second_result = live_scheduler.run_once(client=client, now=second_now, db_path=self.db_path, sleep_fn=lambda s: None)
        second_count = len(list_execution_log(db_path=self.db_path))

        self.assertEqual(first_count, second_count)
        self.assertIn("GOLD", second_result.assets_evaluated)
        self.assertEqual(second_result.errors_encountered, [])
        # Both runs are still recorded (the redundant run isn't skipped at the
        # metadata level -- only the already-logged candle's own signal is a no-op).
        self.assertEqual(len(list_execution_metadata(db_path=self.db_path)), 2)


class PartialFailureResilienceTest(LiveSchedulerTestCase):
    def test_one_configs_permanent_failure_does_not_block_the_others(self) -> None:
        def _fake_load_intraday(asset, interval="1h", candles=240, twelve_data_api_key=None):
            if asset == "GOLD":
                raise MarketDataUnavailableError("Twelve Data: missing API key")
            source_map = {"BNB": self.bnb_history, "BTC": self.btc_history, "ETH": self.eth_history, "SILVER": self.silver_history}
            return MarketDataResult(prices=source_map[asset], source="test-fixture", asset=asset, interval=interval)

        self._patch_pead_fetchers()
        with patch.object(MarketDataClient, "load_intraday", side_effect=_fake_load_intraday), patch.object(
            MarketDataClient, "load_daily", side_effect=self._fake_load_daily
        ), patch(
            "nero_core.execution.live_scheduler.fetch_and_cache_snapshot", side_effect=self._fake_fetch_and_cache_snapshot
        ), patch(
            "nero_core.execution.live_scheduler.fetch_forex_ohlcv", side_effect=self._fake_fetch_forex_ohlcv
        ):
            client = MarketDataClient()
            result = live_scheduler.run_once(client=client, now=WEEKLY_BOUNDARY_MIDNIGHT_UTC, db_path=self.db_path, sleep_fn=lambda _s: None)

        self.assertNotIn("GOLD", result.assets_evaluated)
        self.assertIn("BNB", result.assets_evaluated)
        self.assertIn("BTC-ETH", result.assets_evaluated)

        # THREE configs now fetch GOLD/1week (BREAKOUT_MOMENTUM, RANGE_MEAN_REVERSION,
        # and the Donchian Cross-Asset Deep-Dive's DONCHIAN_TREND) -- all three fail
        # from the same fixture's missing-API-key GOLD error.
        gold_errors = [e for e in result.errors_encountered if e["asset"] == "GOLD"]
        self.assertEqual(len(gold_errors), 3)
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

        # This test tracks RAW sleep calls to isolate GOLD's own retry sequence --
        # the shared _patch_pead_fetchers' "no fixture configured" TRANSIENT
        # mock would otherwise append its own 3-attempt backoff (1, 3, 10) per
        # one of PEAD's 14 configs onto this SAME sleeps list. A PERMANENT-
        # classified message (matching classify_market_data_error's own
        # "missing api key" marker) skips PEAD immediately, contributing zero
        # sleep calls, without needing to fabricate a successful PEAD fetch.
        def _fake_earnings_permanent(ticker, limit=100):
            from nero_core.data_sources.earnings_data import EarningsDataUnavailableError
            raise EarningsDataUnavailableError(f"missing api key style skip for {ticker}")

        def _fake_stock_permanent(symbol, timeframe, start=None, end=None, sleep_fn=None):
            from nero_core.data_sources.stock_data import StockDataUnavailableError
            raise StockDataUnavailableError(f"missing api key style skip for {symbol}")

        with patch.object(MarketDataClient, "load_intraday", side_effect=_fake_load_intraday), patch.object(
            MarketDataClient, "load_daily", side_effect=self._fake_load_daily
        ), patch(
            "nero_core.execution.live_scheduler.fetch_and_cache_snapshot", side_effect=self._fake_fetch_and_cache_snapshot
        ), patch(
            "nero_core.execution.live_scheduler.fetch_earnings_surprises", side_effect=_fake_earnings_permanent
        ), patch(
            "nero_core.execution.live_scheduler.fetch_stock_ohlcv", side_effect=_fake_stock_permanent
        ), patch(
            "nero_core.execution.live_scheduler.fetch_forex_ohlcv", side_effect=self._fake_fetch_forex_ohlcv
        ):
            client = MarketDataClient()
            result = live_scheduler.run_once(client=client, now=WEEKLY_BOUNDARY_MIDNIGHT_UTC, db_path=self.db_path, sleep_fn=sleeps.append)

        self.assertIn("GOLD", result.assets_evaluated)
        # BREAKOUT_MOMENTUM's GOLD/1week fetch fails twice then succeeds on the 3rd
        # call (clearing call_count["GOLD"] to 3); RANGE_MEAN_REVERSION's own and
        # DONCHIAN_TREND's own GOLD/1week fetches both run afterward and succeed
        # immediately on their first calls (the counter has already cleared the < 3
        # failure threshold) -- 5 calls total, only the first config's 2 failures
        # produce backoff sleeps. Forex fetches succeed cleanly (test fixture), adding
        # no further sleep calls.
        self.assertEqual(call_count["GOLD"], 5)
        self.assertEqual(sleeps, [1, 3])

    def test_transient_failure_exhausting_all_retries_is_skipped_not_fatal(self) -> None:
        def _fake_load_intraday(asset, interval="1h", candles=240, twelve_data_api_key=None):
            if asset == "GOLD":
                raise MarketDataUnavailableError("Binance: ConnectionError: timed out")
            source_map = {"BNB": self.bnb_history, "BTC": self.btc_history, "ETH": self.eth_history, "SILVER": self.silver_history}
            return MarketDataResult(prices=source_map[asset], source="test-fixture", asset=asset, interval=interval)

        self._patch_pead_fetchers()
        with patch.object(MarketDataClient, "load_intraday", side_effect=_fake_load_intraday), patch.object(
            MarketDataClient, "load_daily", side_effect=self._fake_load_daily
        ), patch(
            "nero_core.execution.live_scheduler.fetch_and_cache_snapshot", side_effect=self._fake_fetch_and_cache_snapshot
        ), patch(
            "nero_core.execution.live_scheduler.fetch_forex_ohlcv", side_effect=self._fake_fetch_forex_ohlcv
        ):
            client = MarketDataClient()
            result = live_scheduler.run_once(client=client, now=WEEKLY_BOUNDARY_MIDNIGHT_UTC, db_path=self.db_path, sleep_fn=lambda _s: None)

        self.assertNotIn("GOLD", result.assets_evaluated)
        # All three GOLD/1week configs (BREAKOUT_MOMENTUM, RANGE_MEAN_REVERSION, and
        # DONCHIAN_TREND) exhaust their retries and get skipped.
        gold_skips = [r for r in result.assets_skipped if r["asset"] == "GOLD"]
        self.assertEqual(len(gold_skips), 3)
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

        with patch("nero_core.execution.live_scheduler.NewsFeedClient.load", return_value=fake_result), \
             patch("nero_core.strategies.news_sentiment_llm.requests.post", return_value=_mock_claude_response()):
            client = self._patched_client()
            first = live_scheduler.run_once(client=client, now=NEWS_HOUR_UTC, db_path=self.db_path)

            self.assertTrue(has_news_sentiment_logged_today("GOLD", NEWS_SENTIMENT_V1_VERSION, NEWS_HOUR_UTC, db_path=self.db_path))
            self.assertTrue(has_news_sentiment_logged_today("BTC", NEWS_SENTIMENT_V1_VERSION, NEWS_HOUR_UTC, db_path=self.db_path))
            self.assertIn("NEWS_SENTIMENT:GOLD", first.assets_evaluated)

            later_same_day = NEWS_HOUR_UTC.replace(minute=35)
            second = live_scheduler.run_once(client=client, now=later_same_day, db_path=self.db_path)

        # Already logged today -> the daily gate skips re-fetching/re-scoring entirely.
        self.assertNotIn("NEWS_SENTIMENT:GOLD", second.assets_evaluated)

    def test_news_sentiment_not_due_outside_its_daily_hour(self) -> None:
        client = self._patched_client()

        result = live_scheduler.run_once(client=client, now=WEEKLY_BOUNDARY_MIDNIGHT_UTC, db_path=self.db_path, sleep_fn=lambda s: None)

        news_skips = [r for r in result.assets_skipped if r["asset"] == "NEWS_SENTIMENT"]
        self.assertEqual(len(news_skips), 1)
        self.assertEqual(news_skips[0]["classification"], "NOT_DUE")

    def test_both_v1_and_v2_log_independently_on_the_shared_schedule(self) -> None:
        """v1 (keyword) and v2 (LLM) must BOTH evaluate and log on the same
        daily_time_due run, each under its own strategy_version, without either
        suppressing the other -- the actual point of the schema migration and the
        version-aware has_news_sentiment_logged_today gate."""
        headlines = [
            NewsItem(
                title="gold price surge rally record high",
                source="Test", link="", published="Fri, 17 Jul 2026 12:00:00 GMT", tags=[],
            )
        ]
        fake_result = NewsFeedResult(headlines=headlines, status="live (1 matched)")

        with patch("nero_core.execution.live_scheduler.NewsFeedClient.load", return_value=fake_result), \
             patch("nero_core.strategies.news_sentiment_llm.requests.post", return_value=_mock_claude_response()):
            client = self._patched_client()
            result = live_scheduler.run_once(client=client, now=NEWS_HOUR_UTC, db_path=self.db_path)

        self.assertTrue(has_news_sentiment_logged_today("GOLD", NEWS_SENTIMENT_V1_VERSION, NEWS_HOUR_UTC, db_path=self.db_path))
        self.assertTrue(has_news_sentiment_logged_today("GOLD", NEWS_SENTIMENT_V2_VERSION, NEWS_HOUR_UTC, db_path=self.db_path))
        self.assertTrue(has_news_sentiment_logged_today("BTC", NEWS_SENTIMENT_V1_VERSION, NEWS_HOUR_UTC, db_path=self.db_path))
        self.assertTrue(has_news_sentiment_logged_today("BTC", NEWS_SENTIMENT_V2_VERSION, NEWS_HOUR_UTC, db_path=self.db_path))

        rows = list_news_sentiment_log_for_run(result.run_id, db_path=self.db_path)
        versions_by_asset = {(r.asset, r.strategy_version) for r in rows}
        self.assertEqual(
            versions_by_asset,
            {
                ("GOLD", NEWS_SENTIMENT_V1_VERSION), ("GOLD", NEWS_SENTIMENT_V2_VERSION),
                ("BTC", NEWS_SENTIMENT_V1_VERSION), ("BTC", NEWS_SENTIMENT_V2_VERSION),
            },
        )
        self.assertIn("NEWS_SENTIMENT:GOLD", result.assets_evaluated)
        self.assertIn("NEWS_SENTIMENT:BTC", result.assets_evaluated)

    def test_v1_behavior_unchanged_when_v2_has_no_api_key(self) -> None:
        """v1 must keep logging exactly as before even when ANTHROPIC_API_KEY isn't
        set (v2 then no-ops via its own "no api key" path, never falling back to
        keyword matching -- see news_sentiment_llm's own module docstring) --
        confirms v1 was not accidentally coupled to v2's availability."""
        headlines = [
            NewsItem(
                title="gold price surge rally record high",
                source="Test", link="", published="Fri, 17 Jul 2026 12:00:00 GMT", tags=[],
            )
        ]
        fake_result = NewsFeedResult(headlines=headlines, status="live (1 matched)")

        with patch("nero_core.execution.live_scheduler.NewsFeedClient.load", return_value=fake_result), \
             patch("nero_core.execution.live_scheduler.os.getenv", side_effect=lambda key, default="": default):
            client = self._patched_client()
            result = live_scheduler.run_once(client=client, now=NEWS_HOUR_UTC, db_path=self.db_path)

        self.assertTrue(has_news_sentiment_logged_today("GOLD", NEWS_SENTIMENT_V1_VERSION, NEWS_HOUR_UTC, db_path=self.db_path))
        rows = list_news_sentiment_log_for_run(result.run_id, db_path=self.db_path)
        v1_gold = next(r for r in rows if r.asset == "GOLD" and r.strategy_version == NEWS_SENTIMENT_V1_VERSION)
        self.assertEqual(v1_gold.signal_type, "BUY_BIAS")
        self.assertEqual(v1_gold.source, "keyword (no gemini key configured)")
        v2_gold = next(r for r in rows if r.asset == "GOLD" and r.strategy_version == NEWS_SENTIMENT_V2_VERSION)
        self.assertEqual(v2_gold.source, "no api key")


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

    def test_data_source_combines_candle_and_orderbook_sources(self) -> None:
        """process_orderflow_imbalance's data_source must reflect BOTH independent
        fetches (1h candles + order-book snapshot), not just one of them -- the fix
        for the confirmed cross-exchange-entry-vs-exit contamination risk (entry and
        exit are separate scheduler runs, each independently cascading Binance ->
        Coinbase -> Kraken for candles). Uses deliberately DIFFERENT source strings
        for the two fetches so a test that silently duplicated one into the other's
        slot would fail."""
        def _fake_load_intraday_distinct_source(asset, interval="1h", candles=240, twelve_data_api_key=None):
            source_map = {
                "GOLD": self.gold_history, "BNB": self.bnb_history,
                "BTC": self.btc_uptrend_history, "ETH": self.btc_uptrend_history,
            }
            if asset not in source_map:
                raise MarketDataUnavailableError(f"no fixture configured for {asset}")
            return MarketDataResult(prices=source_map[asset], source="Binance BTCUSDT 1h candles", asset=asset, interval=interval)

        patcher = patch.object(MarketDataClient, "load_intraday", side_effect=_fake_load_intraday_distinct_source)
        patcher.start()
        self.addCleanup(patcher.stop)
        daily_patcher = patch.object(MarketDataClient, "load_daily", side_effect=self._fake_load_daily)
        daily_patcher.start()
        self.addCleanup(daily_patcher.stop)
        client = MarketDataClient()

        def _high_ratio_snapshot_distinct_source(binance_symbol, now=None, db_path=None):
            return OrderbookSnapshot(
                timestamp=now, symbol=binance_symbol, best_bid=100.0, best_ask=100.1,
                bid_vol_20=10.0, ask_vol_20=1.0, imbalance_ratio=10.0, source="data-api.binance.vision",
            )

        with patch("nero_core.execution.live_scheduler.fetch_and_cache_snapshot", side_effect=_high_ratio_snapshot_distinct_source):
            result = live_scheduler.run_once(client=client, now=NOT_DUE_UTC, db_path=self.db_path)

        self.assertIn("ORDERFLOW_IMBALANCE:BTC", result.assets_evaluated)
        entry_rows = [r for r in list_execution_log(db_path=self.db_path, asset="BTC", strategy="ORDERFLOW_IMBALANCE") if r.signal_type == "ENTRY"]
        self.assertEqual(len(entry_rows), 1)
        self.assertEqual(entry_rows[0].data_source, "Binance BTCUSDT 1h candles | orderbook: data-api.binance.vision")


class DataSourcePersistenceTest(LiveSchedulerTestCase):
    """Regression coverage for the SILVER-via-YFinance-with-zero-record incident: the
    provenance string tools.timeframe_data.fetch_timeframe_candles already computes
    (see process_single_asset) must now actually reach execution_log.data_source
    instead of being discarded."""

    def test_single_asset_config_persists_the_fetch_source(self) -> None:
        client = self._patched_client()
        result = live_scheduler.run_once(client=client, now=WEEKLY_BOUNDARY_MIDNIGHT_UTC, db_path=self.db_path, sleep_fn=lambda _s: None)

        self.assertIn("GOLD", result.assets_evaluated)
        rows = list_execution_log(db_path=self.db_path, asset="GOLD", strategy="BREAKOUT_MOMENTUM")
        self.assertTrue(rows, "expected at least one BREAKOUT_MOMENTUM/GOLD row")
        for row in rows:
            self.assertEqual(row.data_source, "NATIVE: test-fixture")

    def test_data_source_is_none_when_not_supplied(self) -> None:
        """insert_execution_log_row's default (no data_source passed) must stay None,
        not an empty string or fabricated value -- a caller that genuinely has no
        provenance string to give it must read back as honestly "not recorded", never
        silently blank. As of this test every live_scheduler call site IS wired
        (process_single_asset in 38405e7; process_orderflow_imbalance in c877025;
        process_pairs/process_gold_silver_ratio in c29a825; process_pead_config/
        process_donchian_forex_config in the pead-donchian-provenance follow-up -- see
        PairsAndGoldSilverRatioDataSourceTest and PeadAndDonchianForexDataSourceTest
        below) -- this test exercises insert_execution_log_row's own default directly,
        not a scheduler call site that discards a source it has."""
        from nero_core.truth_ledger.execution_log import insert_execution_log_row

        row = insert_execution_log_row(
            run_id="test-run", strategy="TEST_STRATEGY", strategy_version="v1", asset="TEST",
            signal_type="NO_TRADE", reasoning="no data_source passed", candle_timestamp=1000,
            db_path=self.db_path,
        )
        self.assertIsNone(row.data_source)
        reloaded = list_execution_log(db_path=self.db_path, asset="TEST", strategy="TEST_STRATEGY")
        self.assertEqual(len(reloaded), 1)
        self.assertIsNone(reloaded[0].data_source)


class PairsAndGoldSilverRatioDataSourceTest(LiveSchedulerTestCase):
    """orderflow-verification Task 3: process_pairs and process_gold_silver_ratio
    discarded their two legs' fetch_timeframe_candles provenance the same way
    process_single_asset did before 38405e7 -- both now combine both legs' sources
    into one execution_log.data_source string. Each test uses DELIBERATELY DIFFERENT
    source strings per leg so a fix that silently duplicated one leg's source into the
    other's slot would fail."""

    def test_pairs_combines_both_legs_sources(self) -> None:
        client = self._patched_client()

        def _distinct_pairs_source(asset, interval="1h", candles=240, twelve_data_api_key=None):
            source_map = {
                "GOLD": self.gold_history, "BNB": self.bnb_history,
                "BTC": self.btc_history, "ETH": self.eth_history, "SILVER": self.silver_history,
            }
            if asset not in source_map:
                raise MarketDataUnavailableError(f"no fixture configured for {asset}")
            leg_source = {"BTC": "Binance BTCUSDT 12h candles", "ETH": "Coinbase ETH-USD 12h candles"}.get(asset, "test-fixture")
            return MarketDataResult(prices=source_map[asset], source=leg_source, asset=asset, interval=interval)

        patcher = patch.object(MarketDataClient, "load_intraday", side_effect=_distinct_pairs_source)
        patcher.start()
        self.addCleanup(patcher.stop)

        result = live_scheduler.run_once(client=client, now=WEEKLY_BOUNDARY_MIDNIGHT_UTC, db_path=self.db_path, sleep_fn=lambda s: None)

        self.assertIn("BTC-ETH", result.assets_evaluated)
        rows = list_execution_log(db_path=self.db_path, asset="BTC-ETH", strategy="COINTEGRATION_PAIRS")
        self.assertTrue(rows, "expected at least one COINTEGRATION_PAIRS/BTC-ETH row")
        for row in rows:
            self.assertEqual(row.data_source, "BTC: NATIVE: Binance BTCUSDT 12h candles | ETH: NATIVE: Coinbase ETH-USD 12h candles")

    def test_gold_silver_ratio_combines_both_legs_sources(self) -> None:
        # GOLD_SILVER_RATIO_MR needs a 252-session rolling window (see
        # nero_core/strategies/gold_silver_ratio_mr.py's rolling_window default) with
        # BOTH legs sharing calendar dates (align_gold_silver_candles joins on date) --
        # the shared LiveSchedulerTestCase fixtures don't fit this (gold_history is
        # weekly-stepped, built for BREAKOUT_MOMENTUM/1week; silver_history is daily
        # but on its own clock), so this test builds its own same-clock daily pair
        # long enough to clear warmup, calling process_gold_silver_ratio directly
        # rather than through run_once's candle_boundary_due gate (irrelevant here).
        gold_daily = _daily_history(300, base=2000.0)
        silver_daily = _daily_history(300, base=25.0)

        def _distinct_gsr_source(asset, days=365, twelve_data_api_key=None):
            source_map = {"GOLD": gold_daily, "SILVER": silver_daily}
            if asset not in source_map:
                raise MarketDataUnavailableError(f"no fixture configured for {asset}")
            leg_source = {"GOLD": "Twelve Data XAU/USD daily candles", "SILVER": "YFinance SI=F daily candles"}[asset]
            return MarketDataResult(prices=source_map[asset], source=leg_source, asset=asset, interval="1d")

        client = MarketDataClient()
        patcher = patch.object(MarketDataClient, "load_daily", side_effect=_distinct_gsr_source)
        patcher.start()
        self.addCleanup(patcher.stop)

        status, record = live_scheduler.process_gold_silver_ratio(client, run_id="test-run", now=WEEKLY_BOUNDARY_MIDNIGHT_UTC, db_path=self.db_path)

        self.assertEqual(status, "EVALUATED", f"expected EVALUATED, got SKIPPED: {record}")
        rows = list_execution_log(db_path=self.db_path, asset="GOLD-SILVER", strategy="GOLD_SILVER_RATIO_MR")
        self.assertTrue(rows, "expected at least one GOLD_SILVER_RATIO_MR/GOLD-SILVER row")
        for row in rows:
            self.assertEqual(row.data_source, "GOLD: NATIVE: Twelve Data XAU/USD daily candles | SILVER: NATIVE: YFinance SI=F daily candles")


class PeadAndDonchianForexDataSourceTest(LiveSchedulerTestCase):
    """pead-donchian-provenance follow-up: process_pead_config and process_donchian_
    forex_config discarded their fetch's provenance the same way process_single_asset
    did before 38405e7 -- both now persist a real data_source string. Unlike
    process_pairs/process_gold_silver_ratio (above), neither combines two legs: PEAD's
    data_source is the stock-candle source ONLY, since fetch_earnings_surprises is a
    single hardcoded yfinance call with no provenance field at all (nothing to combine
    it with); Donchian forex is a plain single-value fetch, identical in shape to
    process_single_asset. Each test uses a source string distinct from any other
    fixture's default ("test-fixture" etc.) so a fix that silently dropped the real
    value in favor of a hardcoded placeholder would fail."""

    def test_pead_persists_the_stock_candle_source(self) -> None:
        from nero_core.data_sources.stock_data import StockDataResult
        from nero_core.strategies.pead import PeadParameters
        from tests.test_live_wiring_post_batch import _pead_candles, _pead_events

        candles = _pead_candles(n=40)
        # process_pead_config always starts a fresh account (nothing logged yet for
        # this db_path) at replay_pead_events's PEAD-specific fresh-start index --
        # newest row minus holding_window_sessions, NOT candle 0 -- so the
        # announcement must fall within that window (idx 34, matching
        # PeadLiveReplayTest.test_fresh_deployment_still_catches_a_recent_qualifying_
        # event's own convention) or it's correctly ignored as pre-inception history.
        ann_time = candles.iloc[34]["date"]
        events_df = _pead_events([(ann_time, 1.0, 1.10, 10.0)])  # qualifying 10% positive surprise
        params = PeadParameters(surprise_threshold_pct=0.05, holding_window_sessions=5)
        config = live_scheduler.PeadLiveConfig(ticker="AAPL", strategy_version="pead-test-v1", params=params)
        stock_result = StockDataResult(prices=candles, source="YFinance AAPL daily candles", symbol="AAPL", timeframe="1day")

        with patch("nero_core.execution.live_scheduler.fetch_earnings_surprises", return_value=events_df), \
                patch("nero_core.execution.live_scheduler.fetch_stock_ohlcv", return_value=stock_result):
            status, record = live_scheduler.process_pead_config(config, run_id="test-run", now=WEEKLY_BOUNDARY_MIDNIGHT_UTC, db_path=self.db_path)

        self.assertEqual(status, "EVALUATED", f"expected EVALUATED, got SKIPPED: {record}")
        rows = list_execution_log(db_path=self.db_path, asset="AAPL", strategy=live_scheduler.PEAD_ID)
        self.assertTrue(rows, "expected at least one PEAD/AAPL row")
        for row in rows:
            self.assertEqual(row.data_source, "YFinance AAPL daily candles")

    def test_donchian_forex_persists_the_fetch_source(self) -> None:
        config = live_scheduler.DONCHIAN_FOREX_CONFIGS[0]  # EUR/USD, N20
        forex_result = ForexDataResult(
            prices=self.forex_history, source="Twelve Data EUR/USD weekly candles",
            pair=config.pair, timeframe=live_scheduler.DONCHIAN_FOREX_TIMEFRAME,
        )

        with patch("nero_core.execution.live_scheduler.fetch_forex_ohlcv", return_value=forex_result):
            status, record = live_scheduler.process_donchian_forex_config(config, run_id="test-run", now=WEEKLY_BOUNDARY_MIDNIGHT_UTC, db_path=self.db_path)

        self.assertEqual(status, "EVALUATED", f"expected EVALUATED, got SKIPPED: {record}")
        rows = list_execution_log(db_path=self.db_path, asset=config.pair, strategy=live_scheduler.DONCHIAN_TREND_ID)
        self.assertTrue(rows, "expected at least one DONCHIAN_TREND/EUR/USD row")
        for row in rows:
            self.assertEqual(row.data_source, "Twelve Data EUR/USD weekly candles")


class ApiKeyStartupValidationTest(LiveSchedulerTestCase):
    """Fix 2: a missing expected API key must produce a durable, queryable
    CONFIG_WARNING in execution_metadata.errors_encountered -- checked once at the
    very start of run_once, before any strategy evaluation -- and must never stop
    the run or leak a key's actual value."""

    _ALL_KEYS_PRESENT = {
        "TWELVE_DATA_API_KEY": "td-real-value-should-never-appear-anywhere",
        "GEMINI_API_KEY": "gemini-real-value-should-never-appear-anywhere",
        "ANTHROPIC_API_KEY": "anthropic-real-value-should-never-appear-anywhere",
    }

    @staticmethod
    def _getenv_from(env: dict[str, str]):
        # Same pattern as NewsSentimentSchedulingTest.test_v1_behavior_unchanged_when_
        # v2_has_no_api_key -- patches os.getenv directly rather than clearing the
        # real process environment (safer: nothing outside this dict can leak in or
        # be accidentally wiped for the duration of the call).
        return lambda key, default="": env.get(key, default)

    def test_missing_key_produces_config_warning_without_stopping_the_run(self) -> None:
        env = dict(self._ALL_KEYS_PRESENT)
        del env["ANTHROPIC_API_KEY"]
        client = self._patched_client()
        with patch("nero_core.execution.live_scheduler.os.getenv", side_effect=self._getenv_from(env)):
            result = live_scheduler.run_once(client=client, now=WEEKLY_BOUNDARY_MIDNIGHT_UTC, db_path=self.db_path, sleep_fn=lambda _s: None)

        warnings = [e for e in result.errors_encountered if e.get("classification") == "CONFIG_WARNING"]
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["key"], "ANTHROPIC_API_KEY")

        # the run must not stop -- other strategies still evaluate normally.
        self.assertIn("GOLD", result.assets_evaluated)

    def test_all_keys_present_produces_no_config_warning(self) -> None:
        client = self._patched_client()
        with patch("nero_core.execution.live_scheduler.os.getenv", side_effect=self._getenv_from(self._ALL_KEYS_PRESENT)):
            result = live_scheduler.run_once(client=client, now=WEEKLY_BOUNDARY_MIDNIGHT_UTC, db_path=self.db_path, sleep_fn=lambda _s: None)

        warnings = [e for e in result.errors_encountered if e.get("classification") == "CONFIG_WARNING"]
        self.assertEqual(warnings, [])

    def test_multiple_missing_keys_each_get_their_own_warning(self) -> None:
        client = self._patched_client()
        with patch("nero_core.execution.live_scheduler.os.getenv", side_effect=self._getenv_from({})):
            result = live_scheduler.run_once(client=client, now=WEEKLY_BOUNDARY_MIDNIGHT_UTC, db_path=self.db_path, sleep_fn=lambda _s: None)

        warned_keys = {e["key"] for e in result.errors_encountered if e.get("classification") == "CONFIG_WARNING"}
        self.assertEqual(warned_keys, {"TWELVE_DATA_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY"})

    def test_key_value_never_appears_in_the_warning(self) -> None:
        """Even when a key IS present (and therefore not warned about), its value
        must never leak into any other run_once output -- this test's fixture keys
        are deliberately distinctive strings so any accidental leak is unmissable."""
        client = self._patched_client()
        with patch("nero_core.execution.live_scheduler.os.getenv", side_effect=self._getenv_from(self._ALL_KEYS_PRESENT)):
            result = live_scheduler.run_once(client=client, now=WEEKLY_BOUNDARY_MIDNIGHT_UTC, db_path=self.db_path, sleep_fn=lambda _s: None)

        serialized = str(result.errors_encountered) + str(result.assets_skipped) + str(result.assets_evaluated)
        for value in self._ALL_KEYS_PRESENT.values():
            self.assertNotIn(value, serialized)


class CatchUpMechanismTest(LiveSchedulerTestCase):
    """CC-1 DIRECTIVE (2026-08-07, retry/catch-up), item 2c: simulates a genuine
    missed-tick gap (not just a delayed-but-still-in-window run, which
    RedundantTriggerTest-style scenarios already cover) and confirms
    candle_schedule.catch_up_due fires process_single_asset even though
    candle_boundary_due itself is False at NOT_DUE_UTC, and that every event it
    logs is marked [CATCHUP] (live_scheduler._mark_reasoning) so it never blends
    into a normal on-schedule run's own log rows."""

    def _seed_stale_bnb_row(self) -> None:
        # BNB/TREND_PULLBACK is the one SINGLE_ASSET_CONFIGS entry with a single,
        # unambiguous config for this asset (see live_scheduler.py's own
        # SINGLE_ASSET_CONFIGS list) -- no risk of colliding with a second BNB
        # config's own already_logged cursor. candle_timestamp is chosen from deep
        # inside _flat_history's own close_time range (index 100 of 260, each 12h
        # apart) so replay still finds later fixture candles to emit fresh events
        # for; timestamp=2020-01-01 is irrelevant to catch_up_due (it reads
        # candle_timestamp, not this row's own timestamp column).
        insert_execution_log_row(
            run_id="pretest-seed-stale-bnb",
            strategy=TREND_PULLBACK_ID,
            strategy_version=TREND_PULLBACK_VERSION,
            asset="BNB",
            signal_type="NO_TRADE",
            reasoning="seed row simulating a stale already-logged candle",
            candle_timestamp=100 * 12 * 3_600_000,
            timestamp=datetime(2020, 1, 1, tzinfo=timezone.utc),
            data_source="test-fixture",
            db_path=self.db_path,
        )

    def test_missed_tick_is_not_caught_up_without_the_mechanism_present(self) -> None:
        """Sanity check on the fixture itself: at NOT_DUE_UTC, BNB/12h is genuinely
        not on-schedule (candle_boundary_due alone says no) -- proves the gap this
        test creates is real, not an artifact of a badly-chosen `now`."""
        self.assertFalse(live_scheduler.candle_boundary_due("12h", NOT_DUE_UTC))

    def test_catch_up_due_fires_and_process_single_asset_backfills_the_missed_candle(self) -> None:
        self._seed_stale_bnb_row()
        client = self._patched_client()

        result = live_scheduler.run_once(client=client, now=NOT_DUE_UTC, db_path=self.db_path, sleep_fn=lambda s: None)

        # BNB is evaluated even though candle_boundary_due("12h", NOT_DUE_UTC) is
        # False -- every other config with no seeded stale row stays a genuine
        # NOT_DUE skip (this isn't candle_boundary_due itself changing behavior).
        self.assertIn("BNB", result.assets_evaluated)
        skipped_assets = {r["asset"] for r in result.assets_skipped}
        self.assertNotIn("BNB", skipped_assets)
        self.assertIn("GOLD", skipped_assets)  # unaffected control: GOLD has no seeded row, stays NOT_DUE

        bnb_rows = list_execution_log(db_path=self.db_path, asset="BNB")
        backfilled_rows = [r for r in bnb_rows if r.run_id == result.run_id]
        self.assertGreater(len(backfilled_rows), 0)
        self.assertTrue(
            all(r.reasoning.startswith(live_scheduler.CATCHUP_REASONING_MARKER) for r in backfilled_rows),
            "every row logged by the catch-up-triggered run must carry the [CATCHUP] marker",
        )
        # The manually seeded stale row itself predates the mechanism and must be
        # untouched -- the marker is applied only to NEWLY logged catch-up rows.
        seed_row = next(r for r in bnb_rows if r.run_id == "pretest-seed-stale-bnb")
        self.assertFalse(seed_row.reasoning.startswith(live_scheduler.CATCHUP_REASONING_MARKER))

    def test_a_normal_on_schedule_run_never_gets_the_catchup_marker(self) -> None:
        """Regression guard on the OTHER branch of _mark_reasoning: a config that
        IS on-schedule (no gap at all) must log completely unmarked reasoning,
        proving the marker is conditioned on is_catchup, not applied unconditionally."""
        client = self._patched_client()

        result = live_scheduler.run_once(client=client, now=WEEKLY_BOUNDARY_MIDNIGHT_UTC, db_path=self.db_path, sleep_fn=lambda s: None)

        self.assertIn("BNB", result.assets_evaluated)
        bnb_rows = [r for r in list_execution_log(db_path=self.db_path, asset="BNB") if r.run_id == result.run_id]
        self.assertGreater(len(bnb_rows), 0)
        self.assertTrue(all(not r.reasoning.startswith(live_scheduler.CATCHUP_REASONING_MARKER) for r in bnb_rows))


if __name__ == "__main__":
    unittest.main()
