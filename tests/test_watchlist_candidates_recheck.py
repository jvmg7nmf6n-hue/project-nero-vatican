"""feature/watchlist-candidates-recheck: proves (1) the out-of-sample
date-range selection never overlaps the original in-sample window, and (2)
this module's classification path is the SAME function objects the original
Stage 1/Stage 3 RMR research used -- not a forked/parallel reimplementation
that could silently behave differently."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

import pandas as pd

from tools import rmr_variant_research_stage1
from tools import backtest_statistics
from tools import backtest_train_test_split
from tools.watchlist_candidates_recheck import (
    CANDIDATES,
    OUT_OF_SAMPLE_CUTOFF,
    VERDICT_UNTESTABLE,
    recheck_candidate,
    select_out_of_sample_candles,
)

DAY_MS = 86_400_000


def _candles(start_ms: int, n: int) -> pd.DataFrame:
    rows = []
    close = 100.0
    for i in range(n):
        close += 0.5 * ((i % 5) - 2)
        t = start_ms + i * DAY_MS
        rows.append({"close_time": t, "open_time": t - DAY_MS, "open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1.0})
    return pd.DataFrame(rows)


class SelectOutOfSampleCandlesTest(unittest.TestCase):
    def test_never_includes_a_candle_before_the_cutoff(self) -> None:
        cutoff = datetime(2026, 7, 19, tzinfo=timezone.utc)
        cutoff_ms = int(cutoff.timestamp() * 1000)
        # Spans well before AND after the cutoff.
        candles = _candles(cutoff_ms - 30 * DAY_MS, 60)

        result = select_out_of_sample_candles(candles, cutoff)

        self.assertFalse(result.empty)
        self.assertTrue((result["close_time"] >= cutoff_ms).all(), "found a candle before the cutoff -- overlap with the original in-sample window")

    def test_includes_every_candle_at_or_after_the_cutoff_none_dropped(self) -> None:
        cutoff = datetime(2026, 7, 19, tzinfo=timezone.utc)
        cutoff_ms = int(cutoff.timestamp() * 1000)
        candles = _candles(cutoff_ms - 10 * DAY_MS, 25)
        expected_fresh_count = (candles["close_time"] >= cutoff_ms).sum()

        result = select_out_of_sample_candles(candles, cutoff)

        self.assertEqual(len(result), expected_fresh_count)

    def test_naive_cutoff_datetime_is_treated_as_utc_not_silently_dropped(self) -> None:
        # A caller passing a naive datetime must get the SAME boundary as an
        # explicit UTC one -- never a silent, unannounced timezone assumption
        # that shifts the boundary without anyone noticing.
        naive_cutoff = datetime(2026, 7, 19)
        aware_cutoff = datetime(2026, 7, 19, tzinfo=timezone.utc)
        candles = _candles(int(aware_cutoff.timestamp() * 1000) - 5 * DAY_MS, 15)

        result_naive = select_out_of_sample_candles(candles, naive_cutoff)
        result_aware = select_out_of_sample_candles(candles, aware_cutoff)

        self.assertEqual(len(result_naive), len(result_aware))

    def test_zero_candles_at_or_after_cutoff_returns_empty_not_an_error(self) -> None:
        cutoff = datetime(2026, 7, 19, tzinfo=timezone.utc)
        cutoff_ms = int(cutoff.timestamp() * 1000)
        # Entirely BEFORE cutoff.
        candles = _candles(cutoff_ms - 60 * DAY_MS, 30)

        result = select_out_of_sample_candles(candles, cutoff)

        self.assertTrue(result.empty)

    def test_the_real_out_of_sample_cutoff_matches_the_documented_derivation(self) -> None:
        # 2026-07-19 00:00:00 UTC -- both original commits (dd24839 2026-07-20
        # 04:26:29 +0500, 373a8fb 2026-07-20 04:39:16 +0500) ran before
        # 2026-07-19 23:59:59 UTC, so July 18 was the last CLOSED daily candle
        # either could have seen. See the module's own docstring.
        self.assertEqual(OUT_OF_SAMPLE_CUTOFF, datetime(2026, 7, 19, 0, 0, 0, tzinfo=timezone.utc))


class ClassificationPathIdentityTest(unittest.TestCase):
    """Proves this module reuses the ORIGINAL harness's function objects
    directly -- not lookalikes that happen to share a name."""

    def test_half_stats_is_the_literal_same_function_object_as_the_original_stage1_script(self) -> None:
        import tools.watchlist_candidates_recheck as wcr

        self.assertIs(wcr._half_stats, rmr_variant_research_stage1._half_stats)

    def test_classify_verdict_is_the_literal_same_function_object_used_by_backtest_statistics(self) -> None:
        import tools.watchlist_candidates_recheck as wcr

        self.assertIs(wcr.classify_verdict, backtest_statistics.classify_verdict)

    def test_split_chronological_is_the_literal_same_function_object(self) -> None:
        import tools.watchlist_candidates_recheck as wcr

        self.assertIs(wcr.split_chronological, backtest_train_test_split.split_chronological)

    def test_min_sample_size_is_the_same_constant_not_a_redefined_copy(self) -> None:
        import tools.watchlist_candidates_recheck as wcr

        self.assertEqual(wcr.MIN_SAMPLE_SIZE, backtest_statistics.MIN_SAMPLE_SIZE)
        self.assertIs(wcr.MIN_SAMPLE_SIZE, backtest_statistics.MIN_SAMPLE_SIZE)


class RecheckCandidateUntestableGateTest(unittest.TestCase):
    """recheck_candidate must report UNTESTABLE (never let a 0-trade half
    silently read as classify_verdict's DIED) -- but only when there is
    genuinely nothing to classify; anything with >=1 trade in either half
    goes through classify_verdict UNMODIFIED (no manual override)."""

    def _params_and_backtest(self):
        name, params, run_backtest_fn = CANDIDATES[0]
        return params, run_backtest_fn

    def test_zero_out_of_sample_candles_is_untestable(self) -> None:
        params, run_backtest_fn = self._params_and_backtest()
        cutoff = datetime(2026, 7, 19, tzinfo=timezone.utc)
        cutoff_ms = int(cutoff.timestamp() * 1000)
        # Entirely before cutoff -- zero out-of-sample candles.
        candles = _candles(cutoff_ms - 100 * DAY_MS, 50)

        result = recheck_candidate("TEST_CANDIDATE", params, run_backtest_fn, candles, cutoff=cutoff)

        self.assertEqual(result["verdict"], VERDICT_UNTESTABLE)
        self.assertEqual(result["oos_candle_count"], 0)

    def test_a_thin_out_of_sample_window_too_short_for_indicator_warmup_is_untestable(self) -> None:
        params, run_backtest_fn = self._params_and_backtest()
        cutoff = datetime(2026, 7, 19, tzinfo=timezone.utc)
        cutoff_ms = int(cutoff.timestamp() * 1000)
        # Plenty of pre-cutoff history (irrelevant -- must not be used for
        # warmup) but only 13 candles after cutoff, matching the real BTC/1d
        # recheck's own finding.
        candles = pd.concat(
            [_candles(cutoff_ms - 3000 * DAY_MS, 3000), _candles(cutoff_ms, 13)], ignore_index=True
        )

        result = recheck_candidate("TEST_CANDIDATE", params, run_backtest_fn, candles, cutoff=cutoff)

        self.assertEqual(result["verdict"], VERDICT_UNTESTABLE)
        self.assertEqual(result["oos_candle_count"], 13)
        self.assertIn("0 trades", result["reason"])


if __name__ == "__main__":
    unittest.main()
