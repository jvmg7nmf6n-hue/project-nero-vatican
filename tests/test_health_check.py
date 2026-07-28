from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from nero_core.execution import health_check
from nero_core.execution.live_scheduler import (
    BREAKOUT_MOMENTUM_ID,
    GOLD_BM_VERSION,
    GOLD_SILVER_RATIO_ID,
    GOLD_SILVER_RATIO_LABEL,
    GOLD_SILVER_RATIO_VERSION,
    NEWS_SENTIMENT_ID,
    NEWS_SENTIMENT_V1_VERSION,
    NEWS_SENTIMENT_V2_VERSION,
    ORDERFLOW_ID,
    ORDERFLOW_VERSION,
    PEAD_CONFIGS,
    PEAD_ID,
    SILVER_BM_VERSION,
    TREND_PULLBACK_ID,
    TREND_PULLBACK_VERSION,
)
from nero_core.truth_ledger.execution_log import insert_execution_log_row, insert_execution_metadata, insert_news_sentiment_log

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
# Inside candle_boundary_due("24h", ...)'s post-midnight-UTC window (see
# nero_core/execution/candle_schedule.py) AND well within NOW's 48h staleness
# threshold -- a genuine "the gate fired this morning" run.
GATE_SATISFIED_RECENTLY = datetime(2026, 7, 28, 0, 10, tzinfo=timezone.utc)


def _hours_ago(hours: float, base: datetime = NOW) -> datetime:
    return base - timedelta(hours=hours)


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


class HealthCheckTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test_truth_ledger.db"
        self.addCleanup(self._tmp.cleanup)

    def _find(self, results: list[health_check.StrategyHealth], strategy: str, strategy_version: str, asset: str):
        for r in results:
            if r.strategy == strategy and r.strategy_version == strategy_version and r.asset == asset:
                return r
        self.fail(f"no result for {strategy}:{strategy_version}:{asset}")


class ContinuousSignalStalenessTest(HealthCheckTestCase):
    """Staleness for a continuously-evaluated strategy (logs NO_TRADE/WATCH on
    essentially every gate-satisfied run) is judged directly against its own last
    logged signal -- see health_check.py's own module docstring."""

    def test_1week_strategy_flagged_when_last_signal_older_than_8_days(self) -> None:
        insert_execution_log_row(
            run_id="r1", strategy=BREAKOUT_MOMENTUM_ID, strategy_version=GOLD_BM_VERSION, asset="GOLD",
            signal_type="NO_TRADE", reasoning="no signal", candle_timestamp=1,
            timestamp=_hours_ago(10 * 24), db_path=self.db_path,
        )
        results = health_check.run_health_check(db_path=self.db_path, now=NOW)
        result = self._find(results, BREAKOUT_MOMENTUM_ID, GOLD_BM_VERSION, "GOLD")
        self.assertTrue(result.stale)
        self.assertIn("last signal", result.flag_reason)

    def test_1week_strategy_not_flagged_when_recent(self) -> None:
        insert_execution_log_row(
            run_id="r1", strategy=BREAKOUT_MOMENTUM_ID, strategy_version=GOLD_BM_VERSION, asset="GOLD",
            signal_type="NO_TRADE", reasoning="no signal", candle_timestamp=_ms(_hours_ago(2 * 24)),
            timestamp=_hours_ago(2 * 24), db_path=self.db_path,
        )
        results = health_check.run_health_check(db_path=self.db_path, now=NOW)
        result = self._find(results, BREAKOUT_MOMENTUM_ID, GOLD_BM_VERSION, "GOLD")
        self.assertFalse(result.stale)

    def test_24h_strategy_flagged_when_last_signal_older_than_2_days(self) -> None:
        insert_execution_log_row(
            run_id="r1", strategy=BREAKOUT_MOMENTUM_ID, strategy_version=SILVER_BM_VERSION, asset="SILVER",
            signal_type="NO_TRADE", reasoning="no signal", candle_timestamp=1,
            timestamp=_hours_ago(72), db_path=self.db_path,
        )
        results = health_check.run_health_check(db_path=self.db_path, now=NOW)
        result = self._find(results, BREAKOUT_MOMENTUM_ID, SILVER_BM_VERSION, "SILVER")
        self.assertTrue(result.stale)

    def test_24h_strategy_not_flagged_within_2_days(self) -> None:
        insert_execution_log_row(
            run_id="r1", strategy=BREAKOUT_MOMENTUM_ID, strategy_version=SILVER_BM_VERSION, asset="SILVER",
            signal_type="NO_TRADE", reasoning="no signal", candle_timestamp=_ms(_hours_ago(30)),
            timestamp=_hours_ago(30), db_path=self.db_path,
        )
        results = health_check.run_health_check(db_path=self.db_path, now=NOW)
        result = self._find(results, BREAKOUT_MOMENTUM_ID, SILVER_BM_VERSION, "SILVER")
        self.assertFalse(result.stale)

    def test_12h_strategy_flagged_when_last_signal_older_than_1_day(self) -> None:
        insert_execution_log_row(
            run_id="r1", strategy=TREND_PULLBACK_ID, strategy_version=TREND_PULLBACK_VERSION, asset="BNB",
            signal_type="NO_TRADE", reasoning="no signal", candle_timestamp=1,
            timestamp=_hours_ago(30), db_path=self.db_path,
        )
        results = health_check.run_health_check(db_path=self.db_path, now=NOW)
        result = self._find(results, TREND_PULLBACK_ID, TREND_PULLBACK_VERSION, "BNB")
        self.assertTrue(result.stale)

    def test_12h_strategy_not_flagged_within_1_day(self) -> None:
        insert_execution_log_row(
            run_id="r1", strategy=TREND_PULLBACK_ID, strategy_version=TREND_PULLBACK_VERSION, asset="BNB",
            signal_type="NO_TRADE", reasoning="no signal", candle_timestamp=_ms(_hours_ago(10)),
            timestamp=_hours_ago(10), db_path=self.db_path,
        )
        results = health_check.run_health_check(db_path=self.db_path, now=NOW)
        result = self._find(results, TREND_PULLBACK_ID, TREND_PULLBACK_VERSION, "BNB")
        self.assertFalse(result.stale)

    def test_never_logged_is_flagged_stale(self) -> None:
        # A key present in the roster with NO execution_log rows at all (fresh
        # deployment, or a genuinely stuck gate) must be flagged, not silently
        # treated as fine -- indistinguishable from starvation by timestamp alone.
        results = health_check.run_health_check(db_path=self.db_path, now=NOW)
        result = self._find(results, TREND_PULLBACK_ID, TREND_PULLBACK_VERSION, "BNB")
        self.assertTrue(result.stale)
        self.assertIn("no last signal ever recorded", result.flag_reason)


class NewsSentimentVersionIsolatedStalenessTest(HealthCheckTestCase):
    """v1.0.0 and v2.0.0-llm-claude each get their own roster entry and must be
    staleness-checked independently -- a version-blind lookup would report v2's
    entry as "fresh" off v1's timestamp alone even if v2 were silently broken, which
    is exactly the failure mode the strategy_version-scoped news_sentiment_log
    schema (and latest_news_sentiment_fetch_timestamp's new required parameter)
    exists to prevent."""

    def test_v2_stale_is_not_masked_by_v1_being_fresh(self) -> None:
        insert_news_sentiment_log(
            run_id="r1", asset="GOLD", strategy_version=NEWS_SENTIMENT_V1_VERSION, fetch_timestamp=_hours_ago(1),
            signal_type="NEUTRAL", confidence=0.0, reasoning="v1 fresh", source="local", db_path=self.db_path,
        )
        # v2 has never logged anything for GOLD -- must be flagged stale in its OWN
        # roster entry despite v1's row existing for the same asset.
        results = health_check.run_health_check(db_path=self.db_path, now=NOW)
        v1_result = self._find(results, NEWS_SENTIMENT_ID, NEWS_SENTIMENT_V1_VERSION, "GOLD")
        v2_result = self._find(results, NEWS_SENTIMENT_ID, NEWS_SENTIMENT_V2_VERSION, "GOLD")
        self.assertFalse(v1_result.stale)
        self.assertTrue(v2_result.stale)
        self.assertIn("no last signal ever recorded", v2_result.flag_reason)

    def test_v1_stale_is_not_masked_by_v2_being_fresh(self) -> None:
        insert_news_sentiment_log(
            run_id="r1", asset="BTC", strategy_version=NEWS_SENTIMENT_V2_VERSION, fetch_timestamp=_hours_ago(1),
            signal_type="NEUTRAL", confidence=0.0, reasoning="v2 fresh", source="claude", db_path=self.db_path,
        )
        results = health_check.run_health_check(db_path=self.db_path, now=NOW)
        v1_result = self._find(results, NEWS_SENTIMENT_ID, NEWS_SENTIMENT_V1_VERSION, "BTC")
        v2_result = self._find(results, NEWS_SENTIMENT_ID, NEWS_SENTIMENT_V2_VERSION, "BTC")
        self.assertTrue(v1_result.stale)
        self.assertFalse(v2_result.stale)

    def test_both_fresh_when_both_have_logged_recently(self) -> None:
        for version, source in ((NEWS_SENTIMENT_V1_VERSION, "local"), (NEWS_SENTIMENT_V2_VERSION, "claude")):
            insert_news_sentiment_log(
                run_id="r1", asset="GOLD", strategy_version=version, fetch_timestamp=_hours_ago(1),
                signal_type="NEUTRAL", confidence=0.0, reasoning="fresh", source=source, db_path=self.db_path,
            )
        results = health_check.run_health_check(db_path=self.db_path, now=NOW)
        self.assertFalse(self._find(results, NEWS_SENTIMENT_ID, NEWS_SENTIMENT_V1_VERSION, "GOLD").stale)
        self.assertFalse(self._find(results, NEWS_SENTIMENT_ID, NEWS_SENTIMENT_V2_VERSION, "GOLD").stale)


class EventDrivenStalenessTest(HealthCheckTestCase):
    """PEAD / GOLD_SILVER_RATIO_MR correctly log nothing on the overwhelming
    majority of runs (no qualifying event that day) -- staleness must be judged
    against whether the shared 24h gate was satisfied by a real recent scheduler
    run, NOT against last-logged-signal, or these would be flagged permanently."""

    def test_pead_not_flagged_when_gate_recently_satisfied_even_with_zero_signals(self) -> None:
        # No execution_log rows at all for GOOGL -- legitimately quiet market,
        # exactly PEAD's normal, healthy state.
        insert_execution_metadata(
            run_id="r1", start_time=GATE_SATISFIED_RECENTLY, end_time=GATE_SATISFIED_RECENTLY,
            assets_evaluated=[], assets_skipped=[], errors_encountered=[], db_path=self.db_path,
        )
        pead_googl = next(c for c in PEAD_CONFIGS if c.ticker == "GOOGL")
        results = health_check.run_health_check(db_path=self.db_path, now=NOW)
        result = self._find(results, PEAD_ID, pead_googl.strategy_version, "GOOGL")
        self.assertFalse(result.stale)
        self.assertIsNone(result.last_signal_at)  # confirms this genuinely tests the zero-signal path

    def test_pead_flagged_when_gate_has_not_been_satisfied_recently(self) -> None:
        # This is the ACTUAL 2026-07-28 bug scenario: real scheduler runs exist,
        # but none of them ever land inside the 24h gate's window.
        insert_execution_metadata(
            run_id="r1", start_time=_hours_ago(1), end_time=_hours_ago(1),
            assets_evaluated=[], assets_skipped=[], errors_encountered=[], db_path=self.db_path,
        )  # a run exists, but NOT_DUE (not near a midnight-UTC boundary)
        pead_googl = next(c for c in PEAD_CONFIGS if c.ticker == "GOOGL")
        results = health_check.run_health_check(db_path=self.db_path, now=NOW)
        result = self._find(results, PEAD_ID, pead_googl.strategy_version, "GOOGL")
        self.assertTrue(result.stale)
        self.assertIn("gate last satisfied", result.flag_reason)

    def test_gold_silver_ratio_shares_the_same_pead_gate_signal(self) -> None:
        insert_execution_metadata(
            run_id="r1", start_time=GATE_SATISFIED_RECENTLY, end_time=GATE_SATISFIED_RECENTLY,
            assets_evaluated=[], assets_skipped=[], errors_encountered=[], db_path=self.db_path,
        )
        results = health_check.run_health_check(db_path=self.db_path, now=NOW)
        result = self._find(results, GOLD_SILVER_RATIO_ID, GOLD_SILVER_RATIO_VERSION, GOLD_SILVER_RATIO_LABEL)
        self.assertFalse(result.stale)


class OrderflowNeverStaleTest(HealthCheckTestCase):
    def test_orderflow_never_flagged_regardless_of_data_age(self) -> None:
        # No gate exists for ORDERFLOW_IMBALANCE at all (evaluated every run) --
        # this class of starvation bug structurally cannot happen to it.
        results = health_check.run_health_check(db_path=self.db_path, now=NOW)
        result = self._find(results, ORDERFLOW_ID, ORDERFLOW_VERSION, "BTC")
        self.assertFalse(result.stale)
        self.assertIsNone(result.gate)


class FailIndependentTest(HealthCheckTestCase):
    def test_one_entrys_failure_does_not_blank_the_others(self) -> None:
        real_last_signal_at = health_check._last_signal_at

        def _boom(rows, strategy, strategy_version, asset):
            if asset == "GOLD" and strategy == BREAKOUT_MOMENTUM_ID:
                raise RuntimeError("simulated failure for one entry only")
            return real_last_signal_at(rows, strategy, strategy_version, asset)

        insert_execution_log_row(
            run_id="r1", strategy=TREND_PULLBACK_ID, strategy_version=TREND_PULLBACK_VERSION, asset="BNB",
            signal_type="NO_TRADE", reasoning="no signal", candle_timestamp=_ms(_hours_ago(1)),
            timestamp=_hours_ago(1), db_path=self.db_path,
        )
        with patch.object(health_check, "_last_signal_at", side_effect=_boom):
            results = health_check.run_health_check(db_path=self.db_path, now=NOW)

        failed = self._find(results, BREAKOUT_MOMENTUM_ID, GOLD_BM_VERSION, "GOLD")
        self.assertTrue(failed.stale)
        self.assertIn("health check itself failed", failed.flag_reason)

        healthy = self._find(results, TREND_PULLBACK_ID, TREND_PULLBACK_VERSION, "BNB")
        self.assertFalse(healthy.stale)

        # The whole roster is still present -- one failure didn't shrink the report.
        self.assertEqual(len(results), len(health_check._live_roster()))


class FreshnessGapTest(HealthCheckTestCase):
    """evaluation_gap_hours/freshness_flagged catch a strategy that IS still being
    evaluated every period, just later each time -- degrading timeliness that the
    binary staleness check (last_signal_at vs. MAX_GAP_HOURS_BY_GATE, a much more
    lenient threshold) wouldn't trip on until it's already a full miss. See
    health_check.py's own FRESHNESS GAP docstring note."""

    def test_12h_strategy_freshness_flagged_when_evaluation_lagged_its_candle_close(self) -> None:
        # MULTI_SHOT_TOLERANCE_MINUTES=150 (2.5h) -- a 4h gap between candle close
        # and the run that logged it is well past that, even though 4h is nowhere
        # near the 24h staleness threshold this strategy's gate uses.
        candle_closed_at = _hours_ago(4)
        insert_execution_log_row(
            run_id="r1", strategy=TREND_PULLBACK_ID, strategy_version=TREND_PULLBACK_VERSION, asset="BNB",
            signal_type="NO_TRADE", reasoning="no signal", candle_timestamp=_ms(candle_closed_at),
            timestamp=NOW, db_path=self.db_path,
        )
        results = health_check.run_health_check(db_path=self.db_path, now=NOW)
        result = self._find(results, TREND_PULLBACK_ID, TREND_PULLBACK_VERSION, "BNB")
        self.assertTrue(result.freshness_flagged)
        self.assertTrue(result.stale)
        self.assertAlmostEqual(result.evaluation_gap_hours, 4.0, places=2)
        self.assertIn("lagged its own candle close", result.flag_reason)

    def test_12h_strategy_not_freshness_flagged_when_evaluated_promptly(self) -> None:
        candle_closed_at = _hours_ago(1)
        insert_execution_log_row(
            run_id="r1", strategy=TREND_PULLBACK_ID, strategy_version=TREND_PULLBACK_VERSION, asset="BNB",
            signal_type="NO_TRADE", reasoning="no signal", candle_timestamp=_ms(candle_closed_at),
            timestamp=NOW, db_path=self.db_path,
        )
        results = health_check.run_health_check(db_path=self.db_path, now=NOW)
        result = self._find(results, TREND_PULLBACK_ID, TREND_PULLBACK_VERSION, "BNB")
        self.assertFalse(result.freshness_flagged)
        self.assertFalse(result.stale)
        self.assertAlmostEqual(result.evaluation_gap_hours, 1.0, places=2)

    def test_24h_strategy_freshness_flagged_past_single_shot_tolerance(self) -> None:
        # SINGLE_SHOT_TOLERANCE_MINUTES=240 (4h). A 5h gap is past it, but nowhere
        # near the 48h staleness threshold "24h" strategies use.
        candle_closed_at = _hours_ago(5)
        insert_execution_log_row(
            run_id="r1", strategy=BREAKOUT_MOMENTUM_ID, strategy_version=SILVER_BM_VERSION, asset="SILVER",
            signal_type="NO_TRADE", reasoning="no signal", candle_timestamp=_ms(candle_closed_at),
            timestamp=NOW, db_path=self.db_path,
        )
        results = health_check.run_health_check(db_path=self.db_path, now=NOW)
        result = self._find(results, BREAKOUT_MOMENTUM_ID, SILVER_BM_VERSION, "SILVER")
        self.assertTrue(result.freshness_flagged)
        self.assertTrue(result.stale)

    def test_event_driven_strategy_never_freshness_flagged(self) -> None:
        # PEAD/GOLD_SILVER_RATIO_MR are event-driven -- a logged row's
        # candle_timestamp doesn't represent "this period's gate was evaluated"
        # for them (see health_check.py's own docstring), so no freshness gap
        # applies even with an old candle_timestamp on a real logged row.
        insert_execution_metadata(
            run_id="r1", start_time=GATE_SATISFIED_RECENTLY, end_time=GATE_SATISFIED_RECENTLY,
            assets_evaluated=[], assets_skipped=[], errors_encountered=[], db_path=self.db_path,
        )
        pead_googl = next(c for c in PEAD_CONFIGS if c.ticker == "GOOGL")
        insert_execution_log_row(
            run_id="r1", strategy=PEAD_ID, strategy_version=pead_googl.strategy_version, asset="GOOGL",
            signal_type="ENTRY", reasoning="earnings surprise", candle_timestamp=_ms(_hours_ago(24 * 30)),
            entry_price=100.0, timestamp=NOW, db_path=self.db_path,
        )
        results = health_check.run_health_check(db_path=self.db_path, now=NOW)
        result = self._find(results, PEAD_ID, pead_googl.strategy_version, "GOOGL")
        self.assertIsNone(result.evaluation_gap_hours)
        self.assertFalse(result.freshness_flagged)

    def test_never_logged_has_no_freshness_gap(self) -> None:
        # No execution_log rows at all -- the existing staleness check already
        # flags this; evaluation_gap_hours has nothing to compute against.
        results = health_check.run_health_check(db_path=self.db_path, now=NOW)
        result = self._find(results, TREND_PULLBACK_ID, TREND_PULLBACK_VERSION, "BNB")
        self.assertIsNone(result.evaluation_gap_hours)
        self.assertFalse(result.freshness_flagged)

    def test_tied_timestamp_batch_uses_the_newest_candle_not_the_oldest(self) -> None:
        # Regression test (2026-07-29 bug, found via real production data): a
        # backlog catch-up run logs several rows in the SAME instant (one per
        # missed candle, all sharing the identical wall-clock `timestamp`) --
        # e.g. SILVER/BREAKOUT_MOMENTUM's real 2026-07-28 03:48:34 run logged 4
        # rows (candles 07-22 through 07-25) at that one timestamp.
        # max(matching, key=lambda r: r.timestamp) doesn't break that tie by
        # candle recency, so it silently picked whichever tied row sorted
        # first (the OLDEST candle, since rows are ordered by candle_timestamp
        # ASC) -- reporting a much larger gap than the real one. Inserted here
        # in a deliberately non-chronological order so a naive "first
        # matching row wins" implementation can't accidentally pass by luck.
        batch_logged_at = NOW
        oldest_candle = _hours_ago(96)  # 4 days before the newest candle
        newest_candle = _hours_ago(24)  # 1 day before NOW -- the real gap
        insert_execution_log_row(
            run_id="r1", strategy=BREAKOUT_MOMENTUM_ID, strategy_version=SILVER_BM_VERSION, asset="SILVER",
            signal_type="NO_TRADE", reasoning="no signal (oldest of the batch)",
            candle_timestamp=_ms(oldest_candle), timestamp=batch_logged_at, db_path=self.db_path,
        )
        insert_execution_log_row(
            run_id="r1", strategy=BREAKOUT_MOMENTUM_ID, strategy_version=SILVER_BM_VERSION, asset="SILVER",
            signal_type="NO_TRADE", reasoning="no signal (newest of the batch)",
            candle_timestamp=_ms(newest_candle), timestamp=batch_logged_at, db_path=self.db_path,
        )
        insert_execution_log_row(
            run_id="r1", strategy=BREAKOUT_MOMENTUM_ID, strategy_version=SILVER_BM_VERSION, asset="SILVER",
            signal_type="NO_TRADE", reasoning="no signal (middle of the batch)",
            candle_timestamp=_ms(_hours_ago(60)), timestamp=batch_logged_at, db_path=self.db_path,
        )
        results = health_check.run_health_check(db_path=self.db_path, now=NOW)
        result = self._find(results, BREAKOUT_MOMENTUM_ID, SILVER_BM_VERSION, "SILVER")
        self.assertAlmostEqual(result.evaluation_gap_hours, 24.0, places=2)


class AlertMessageTest(unittest.TestCase):
    def test_no_alert_when_nothing_flagged(self) -> None:
        export = {"flagged_strategies": [], "flagged_count": 0}
        self.assertIsNone(health_check.build_alert_message(export))

    def test_alert_lists_flagged_strategy_names_when_something_is_stale(self) -> None:
        export = {"flagged_strategies": ["PEAD:pead-v1.0.0-surprise3pct-hold10:GOOGL"], "flagged_count": 1}
        message = health_check.build_alert_message(export)
        self.assertIsNotNone(message)
        self.assertIn("GOOGL", message)
        self.assertIn("1", message)


class JsonExportSchemaTest(HealthCheckTestCase):
    def test_write_health_check_produces_the_documented_schema(self) -> None:
        output_path = Path(self._tmp.name) / "health_check.json"
        insert_execution_log_row(
            run_id="r1", strategy=TREND_PULLBACK_ID, strategy_version=TREND_PULLBACK_VERSION, asset="BNB",
            signal_type="NO_TRADE", reasoning="no signal", candle_timestamp=_ms(_hours_ago(1)),
            timestamp=_hours_ago(1), db_path=self.db_path,
        )
        export = health_check.write_health_check(db_path=self.db_path, output_path=output_path, now=NOW)

        self.assertTrue(output_path.exists())
        on_disk = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual(on_disk, export)

        self.assertEqual(export["schema_version"], 1)
        self.assertEqual(export["last_updated"], NOW.isoformat())
        self.assertIsInstance(export["strategies"], list)
        self.assertEqual(len(export["strategies"]), len(health_check._live_roster()))
        self.assertIsInstance(export["flagged_count"], int)
        self.assertIsInstance(export["flagged_strategies"], list)
        self.assertEqual(export["flagged_count"], len(export["flagged_strategies"]))

        for row in export["strategies"]:
            self.assertIn("strategy", row)
            self.assertIn("strategy_version", row)
            self.assertIn("asset", row)
            self.assertIn("gate", row)
            self.assertIn("last_signal_at", row)
            self.assertIn("resolved_trades", row)
            self.assertIn("win_rate", row)
            self.assertIn("open_position", row)
            self.assertIn("stale", row)
            self.assertIn("flag_reason", row)
            self.assertIn("evaluation_gap_hours", row)
            self.assertIn("freshness_flagged", row)

        bnb_row = next(r for r in export["strategies"] if r["asset"] == "BNB" and r["strategy"] == TREND_PULLBACK_ID)
        self.assertFalse(bnb_row["stale"])
        self.assertIsNotNone(bnb_row["last_signal_at"])


if __name__ == "__main__":
    unittest.main()
