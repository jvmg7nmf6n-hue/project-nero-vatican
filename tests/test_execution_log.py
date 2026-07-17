from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from nero_core.truth_ledger.execution_log import (
    earliest_logged_candle_timestamp,
    has_news_sentiment_logged_today,
    insert_execution_log_row,
    insert_execution_metadata,
    insert_news_sentiment_log,
    latest_logged_candle_timestamp,
    list_execution_log,
    list_execution_metadata,
)


class ExecutionLogTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test_truth_ledger.db"
        self.addCleanup(self._tmp.cleanup)


class InsertExecutionLogRowTest(ExecutionLogTestCase):
    def test_insert_and_read_back(self) -> None:
        row = insert_execution_log_row(
            run_id="run-1", strategy="BREAKOUT_MOMENTUM", strategy_version="breakout-momentum-v1.2.0-gold-calibrated-1week",
            asset="GOLD", signal_type="ENTRY", reasoning="entry conditions satisfied", candle_timestamp=1_000_000,
            entry_price=2400.0, db_path=self.db_path,
        )
        self.assertIsNotNone(row)
        self.assertEqual(row.asset, "GOLD")
        self.assertEqual(row.signal_type, "ENTRY")

        rows = list_execution_log(db_path=self.db_path, asset="GOLD")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].candle_timestamp, 1_000_000)

    def test_duplicate_signal_for_same_candle_is_a_no_op_not_an_error(self) -> None:
        first = insert_execution_log_row(
            run_id="run-1", strategy="TREND_PULLBACK", strategy_version="trend-pullback-v1.0.0",
            asset="BNB", signal_type="NO_TRADE", reasoning="no entry", candle_timestamp=5_000, db_path=self.db_path,
        )
        second = insert_execution_log_row(
            run_id="run-2", strategy="TREND_PULLBACK", strategy_version="trend-pullback-v1.0.0",
            asset="BNB", signal_type="NO_TRADE", reasoning="no entry (re-run)", candle_timestamp=5_000, db_path=self.db_path,
        )
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(len(list_execution_log(db_path=self.db_path, asset="BNB")), 1)

    def test_entry_and_exit_at_same_candle_both_persist(self) -> None:
        # A trade can close AND a fresh entry be evaluated on the very same candle.
        insert_execution_log_row(
            run_id="run-1", strategy="TREND_PULLBACK", strategy_version="trend-pullback-v1.0.0",
            asset="BNB", signal_type="EXIT", reasoning="SL exit", candle_timestamp=9_000, exit_price=10.0, db_path=self.db_path,
        )
        insert_execution_log_row(
            run_id="run-1", strategy="TREND_PULLBACK", strategy_version="trend-pullback-v1.0.0",
            asset="BNB", signal_type="ENTRY", reasoning="re-entry same candle", candle_timestamp=9_000, entry_price=10.1, db_path=self.db_path,
        )
        rows = list_execution_log(db_path=self.db_path, asset="BNB")
        self.assertEqual({r.signal_type for r in rows}, {"EXIT", "ENTRY"})

    def test_no_update_or_delete_functions_exist(self) -> None:
        import nero_core.truth_ledger.execution_log as module

        names = dir(module)
        self.assertFalse(any("update" in n.lower() for n in names))
        self.assertFalse(any("delete" in n.lower() for n in names))


class CandleTimestampCursorTest(ExecutionLogTestCase):
    def test_none_when_nothing_logged(self) -> None:
        self.assertIsNone(latest_logged_candle_timestamp("BREAKOUT_MOMENTUM", "v1", "GOLD", db_path=self.db_path))
        self.assertIsNone(earliest_logged_candle_timestamp("BREAKOUT_MOMENTUM", "v1", "GOLD", db_path=self.db_path))

    def test_earliest_and_latest_track_min_and_max(self) -> None:
        for candle_timestamp, signal in ((1000, "NO_TRADE"), (2000, "ENTRY"), (3000, "EXIT")):
            insert_execution_log_row(
                run_id="run-1", strategy="BREAKOUT_MOMENTUM", strategy_version="v1", asset="GOLD",
                signal_type=signal, reasoning="x", candle_timestamp=candle_timestamp, db_path=self.db_path,
            )
        self.assertEqual(earliest_logged_candle_timestamp("BREAKOUT_MOMENTUM", "v1", "GOLD", db_path=self.db_path), 1000)
        self.assertEqual(latest_logged_candle_timestamp("BREAKOUT_MOMENTUM", "v1", "GOLD", db_path=self.db_path), 3000)

    def test_scoped_per_asset_and_strategy_version(self) -> None:
        insert_execution_log_row(
            run_id="run-1", strategy="BREAKOUT_MOMENTUM", strategy_version="v1", asset="GOLD",
            signal_type="ENTRY", reasoning="x", candle_timestamp=5000, db_path=self.db_path,
        )
        self.assertIsNone(latest_logged_candle_timestamp("BREAKOUT_MOMENTUM", "v2", "GOLD", db_path=self.db_path))
        self.assertIsNone(latest_logged_candle_timestamp("BREAKOUT_MOMENTUM", "v1", "BTC", db_path=self.db_path))


class ExecutionMetadataTest(ExecutionLogTestCase):
    def test_insert_and_list(self) -> None:
        start = datetime(2026, 7, 17, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 7, 17, 0, 1, tzinfo=timezone.utc)
        insert_execution_metadata(
            run_id="run-1", start_time=start, end_time=end,
            assets_evaluated=["GOLD"], assets_skipped=[{"asset": "BNB", "classification": "NOT_DUE"}],
            errors_encountered=[], db_path=self.db_path,
        )
        rows = list_execution_metadata(db_path=self.db_path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].run_id, "run-1")
        self.assertEqual(rows[0].assets_evaluated, ["GOLD"])
        self.assertEqual(rows[0].assets_skipped, [{"asset": "BNB", "classification": "NOT_DUE"}])


class NewsSentimentLogTest(ExecutionLogTestCase):
    def test_insert_then_dedupe_within_same_day(self) -> None:
        now = datetime(2026, 7, 17, 19, 0, tzinfo=timezone.utc)
        self.assertFalse(has_news_sentiment_logged_today("GOLD", now, db_path=self.db_path))

        ok = insert_news_sentiment_log(
            run_id="run-1", asset="GOLD", fetch_timestamp=now, signal_type="NEUTRAL",
            confidence=0.0, reasoning="no eligible headlines", source="local", db_path=self.db_path,
        )
        self.assertTrue(ok)
        self.assertTrue(has_news_sentiment_logged_today("GOLD", now, db_path=self.db_path))

        later_same_day = datetime(2026, 7, 17, 19, 30, tzinfo=timezone.utc)
        duplicate = insert_news_sentiment_log(
            run_id="run-2", asset="GOLD", fetch_timestamp=later_same_day, signal_type="NEUTRAL",
            confidence=0.0, reasoning="dup attempt", source="local", db_path=self.db_path,
        )
        # The row itself can insert (different fetch_timestamp) but the daily gate is what
        # the scheduler actually relies on to avoid calling this twice in the first place.
        self.assertTrue(duplicate)

    def test_next_day_is_not_considered_logged(self) -> None:
        day_one = datetime(2026, 7, 17, 19, 0, tzinfo=timezone.utc)
        insert_news_sentiment_log(
            run_id="run-1", asset="BTC", fetch_timestamp=day_one, signal_type="NEUTRAL",
            confidence=0.0, reasoning="x", source="local", db_path=self.db_path,
        )
        day_two = datetime(2026, 7, 18, 19, 0, tzinfo=timezone.utc)
        self.assertFalse(has_news_sentiment_logged_today("BTC", day_two, db_path=self.db_path))


if __name__ == "__main__":
    unittest.main()
