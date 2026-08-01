from __future__ import annotations

import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from nero_core.research_agent import auto_tester
from nero_core.research_agent.auto_tester import (
    REVIEW_DEAD,
    REVIEW_PENDING,
    REVIEW_REJECTED_TOO_SLOW,
    REVIEW_REJECTED_UNMEASURABLE,
    REVIEW_UNTESTABLE,
    VERDICT_DIED,
    VERDICT_PROMISING_WATCHLIST,
    VERDICT_SKIPPED,
    VERDICT_SURVIVED,
    VERDICT_UNTESTABLE,
    load_existing_test_results,
    persist_test_results,
    run_grid_shift_check,
    test_hypothesis,
)
from nero_core.research_agent.frequency_gate import FAST, TOO_SLOW, UNMEASURABLE
from tools.backtest_statistics import BootstrapCI, RandomBaselineResult
from tools.backtest_statistics import bootstrap_mean_r_ci as harness_bootstrap_mean_r_ci
from tools.backtest_statistics import classify_verdict as harness_classify_verdict
from tools.backtest_statistics import random_entry_baseline_single_asset as harness_random_baseline
from tools.backtest_train_test_split import split_chronological as harness_split_chronological

HOUR_MS = 3_600_000
START_MS = 1_700_000_000_000


def _flat_noise_candles(n: int, spike_indices: dict[int, float] | None = None) -> pd.DataFrame:
    """Hourly candles oscillating gently around 100 (keeps ATR positive and
    finite everywhere) with optional one-candle price spikes at specific
    indices -- used to build deterministic, well-separated entry triggers."""
    spike_indices = spike_indices or {}
    rows = []
    for i in range(n):
        close = spike_indices.get(i, 100.0 + 0.1 * ((i % 7) - 3))
        rows.append({"close_time": START_MS + i * HOUR_MS, "close": close, "high": close + 0.3, "low": close - 0.3, "volume": 1.0})
    return pd.DataFrame(rows)


SPARSE_SPIKE_RULE = {"conditions": [{"field": "close", "op": "gt", "value": 200.0}]}
SHORT_EXIT_PLAN = {"stop_atr_multiple": 1.5, "target_r_multiple": 1.0, "max_holding_hours": 2.0}


def _hypothesis(**overrides) -> dict:
    base = {
        "hypothesis_name": "TEST_HYPOTHESIS",
        "asset": "BTC",
        "timeframe": "1h",
        "generated_at": None,  # filled per-test
        "structured_entry_rule": SPARSE_SPIKE_RULE,
        "structured_exit_plan": SHORT_EXIT_PLAN,
    }
    base.update(overrides)
    return base


class GateRejectionSkipsHarnessTest(unittest.TestCase):
    """HARD TEST (per the branch's own task spec): a TOO_SLOW hypothesis must
    never reach the harness (split_chronological / bootstrap / random
    baseline), no matter how strong its mechanism looks."""

    def test_too_slow_hypothesis_is_skipped_and_never_calls_split_chronological(self) -> None:
        # a single spike in 1000 candles -- far too rare to ever be FAST/VIABLE
        candles = _flat_noise_candles(1000, spike_indices={500: 500.0})
        generated_at = datetime.fromtimestamp((START_MS + 1000 * HOUR_MS) / 1000, tz=timezone.utc)
        hypothesis = _hypothesis(generated_at=generated_at.isoformat())

        with patch("nero_core.research_agent.auto_tester.split_chronological") as mock_split:
            result = test_hypothesis(hypothesis, candles)

        mock_split.assert_not_called()
        self.assertEqual(result.verdict, VERDICT_SKIPPED)
        self.assertEqual(result.frequency_classification, TOO_SLOW)
        self.assertEqual(result.review_status, REVIEW_REJECTED_TOO_SLOW)
        self.assertIsNone(result.train)
        self.assertIsNone(result.test)

    def test_unmeasurable_hypothesis_is_also_skipped_before_harness(self) -> None:
        candles = _flat_noise_candles(1000)
        generated_at = datetime.fromtimestamp((START_MS + 1000 * HOUR_MS) / 1000, tz=timezone.utc)
        hypothesis = _hypothesis(
            generated_at=generated_at.isoformat(),
            structured_entry_rule={"conditions": [{"field": "macd", "op": "lt", "value": 30.0}]},  # unsupported field
        )

        with patch("nero_core.research_agent.auto_tester.split_chronological") as mock_split:
            result = test_hypothesis(hypothesis, candles)

        mock_split.assert_not_called()
        self.assertEqual(result.verdict, VERDICT_SKIPPED)
        self.assertEqual(result.frequency_classification, UNMEASURABLE)
        self.assertEqual(result.review_status, REVIEW_REJECTED_UNMEASURABLE)


class UntestableDetectionTest(unittest.TestCase):
    def test_missing_structured_exit_plan_is_untestable_not_guessed(self) -> None:
        # frequent trigger -> gate passes (FAST), but no machine-checkable exit/stop
        spikes = {i: 500.0 for i in range(50, 900, 20)}  # frequent enough to be FAST
        candles = _flat_noise_candles(1000, spike_indices=spikes)
        generated_at = datetime.fromtimestamp((START_MS + 1000 * HOUR_MS) / 1000, tz=timezone.utc)
        hypothesis = _hypothesis(generated_at=generated_at.isoformat(), structured_exit_plan=None)

        result = test_hypothesis(hypothesis, candles)

        self.assertIn(result.frequency_classification, (FAST,))
        self.assertEqual(result.verdict, VERDICT_UNTESTABLE)
        self.assertEqual(result.review_status, REVIEW_UNTESTABLE)

    def test_malformed_structured_exit_plan_is_untestable(self) -> None:
        spikes = {i: 500.0 for i in range(50, 900, 20)}
        candles = _flat_noise_candles(1000, spike_indices=spikes)
        generated_at = datetime.fromtimestamp((START_MS + 1000 * HOUR_MS) / 1000, tz=timezone.utc)
        hypothesis = _hypothesis(
            generated_at=generated_at.isoformat(), structured_exit_plan={"stop_atr_multiple": -1.0, "target_r_multiple": 2.0, "max_holding_hours": 24.0}
        )

        result = test_hypothesis(hypothesis, candles)
        self.assertEqual(result.verdict, VERDICT_UNTESTABLE)

    def test_malformed_generated_at_is_untestable_never_defaulted_to_now(self) -> None:
        # HARD TEST: a malformed generated_at must never silently fall back to
        # now() -- that would be the most PERMISSIVE possible lookahead cutoff,
        # defeating the frequency gate's own no-lookahead guarantee. Frequent
        # trigger so a bug that DID fall back to now() would otherwise pass the
        # gate (FAST) and reach the harness -- proving this is a real reject,
        # not an accidental TOO_SLOW/UNMEASURABLE from an unrelated cause.
        spikes = {i: 500.0 for i in range(50, 900, 20)}
        candles = _flat_noise_candles(1000, spike_indices=spikes)
        hypothesis = _hypothesis(generated_at="not-a-real-timestamp")

        with patch("nero_core.research_agent.auto_tester.measure_entry_frequency") as mock_gate:
            result = test_hypothesis(hypothesis, candles)

        mock_gate.assert_not_called()  # never even reaches the frequency gate
        self.assertEqual(result.verdict, VERDICT_UNTESTABLE)
        self.assertEqual(result.review_status, REVIEW_UNTESTABLE)
        self.assertIn("generated_at", result.reason)
        self.assertIsNone(result.train)
        self.assertIsNone(result.test)

    def test_missing_generated_at_is_untestable_never_defaulted_to_now(self) -> None:
        spikes = {i: 500.0 for i in range(50, 900, 20)}
        candles = _flat_noise_candles(1000, spike_indices=spikes)
        hypothesis = _hypothesis(generated_at=None)

        with patch("nero_core.research_agent.auto_tester.measure_entry_frequency") as mock_gate:
            result = test_hypothesis(hypothesis, candles)

        mock_gate.assert_not_called()
        self.assertEqual(result.verdict, VERDICT_UNTESTABLE)
        self.assertEqual(result.review_status, REVIEW_UNTESTABLE)


class RealBacktestVerdictTest(unittest.TestCase):
    def test_strong_deterministic_uptrend_survives_or_watchlists_not_dies(self) -> None:
        # Steady, noise-free uptrend with a frequent entry trigger and a small
        # ATR-relative target -- in a strict uptrend the target should clear
        # before the stop on almost every trade, giving a real, consistently
        # positive expectancy on both halves.
        n = 1000
        rows = []
        price = 100.0
        for i in range(n):
            price *= 1.003
            rows.append({"close_time": START_MS + i * HOUR_MS, "close": price, "high": price * 1.004, "low": price * 0.999, "volume": 1.0})
        candles = pd.DataFrame(rows)
        generated_at = datetime.fromtimestamp((START_MS + n * HOUR_MS) / 1000, tz=timezone.utc)

        hypothesis = _hypothesis(
            generated_at=generated_at.isoformat(),
            structured_entry_rule={"conditions": [{"field": "ret_1", "op": "gt", "value": -1.0}]},  # fires whenever not already in a trade
            structured_exit_plan={"stop_atr_multiple": 2.0, "target_r_multiple": 1.5, "max_holding_hours": 20.0},
        )

        result = test_hypothesis(hypothesis, candles)

        self.assertIn(result.verdict, (VERDICT_SURVIVED, VERDICT_PROMISING_WATCHLIST))
        self.assertEqual(result.review_status, REVIEW_PENDING)
        self.assertGreater(result.train.trades, 0)
        self.assertGreater(result.test.trades, 0)
        self.assertGreater(result.train.expectancy_r, 0.0)
        self.assertGreater(result.test.expectancy_r, 0.0)


class HarnessReuseTest(unittest.TestCase):
    """Proves genuine reuse (not reimplementation) of the existing harness --
    identity checks against the exact objects tools.backtest_statistics /
    tools.backtest_train_test_split already define."""

    def test_bootstrap_ci_type_is_the_harness_dataclass(self) -> None:
        n = 200
        rows = []
        price = 100.0
        for i in range(n):
            price *= 1.004
            rows.append({"close_time": START_MS + i * HOUR_MS, "close": price, "high": price * 1.005, "low": price * 0.999, "volume": 1.0})
        candles = pd.DataFrame(rows)
        generated_at = datetime.fromtimestamp((START_MS + n * HOUR_MS) / 1000, tz=timezone.utc)
        hypothesis = _hypothesis(
            generated_at=generated_at.isoformat(),
            structured_entry_rule={"conditions": [{"field": "ret_1", "op": "gt", "value": -1.0}]},
            structured_exit_plan={"stop_atr_multiple": 2.0, "target_r_multiple": 1.5, "max_holding_hours": 20.0},
        )
        result = test_hypothesis(hypothesis, candles)
        if result.train.ci is not None:
            self.assertIsInstance(result.train.ci, BootstrapCI)
        if result.train.random_baseline is not None:
            self.assertIsInstance(result.train.random_baseline, RandomBaselineResult)

    def test_auto_tester_imports_are_literally_the_harness_functions(self) -> None:
        # identity (is), not just equal behavior -- proves no shadow/rewrite exists
        self.assertIs(auto_tester.bootstrap_mean_r_ci, harness_bootstrap_mean_r_ci)
        self.assertIs(auto_tester.classify_verdict, harness_classify_verdict)
        self.assertIs(auto_tester.random_entry_baseline_single_asset, harness_random_baseline)
        self.assertIs(auto_tester.split_chronological, harness_split_chronological)


class GridShiftCheckTest(unittest.TestCase):
    def test_reruns_test_hypothesis_once_per_named_grid(self) -> None:
        candles_a = _flat_noise_candles(200)
        candles_b = _flat_noise_candles(200, spike_indices={50: 500.0})
        generated_at = datetime.fromtimestamp((START_MS + 200 * HOUR_MS) / 1000, tz=timezone.utc)
        hypothesis = _hypothesis(generated_at=generated_at.isoformat())

        results = run_grid_shift_check(hypothesis, {"native": candles_a, "offset+3h": candles_b})

        self.assertEqual(set(results.keys()), {"native", "offset+3h"})
        self.assertEqual(results["native"].hypothesis_name, "TEST_HYPOTHESIS")

    def test_backtest_params_forwarded_unchanged_to_every_grids_test_hypothesis_call(self) -> None:
        # feature/external-candidates-formal-test: closes a latent gap --
        # test_hypothesis already supported a custom backtest_params (e.g. a
        # forex-specific fee_bps), but its own grid-shift companion silently
        # never forwarded one, which would have made a hypothesis's cost
        # assumptions inconsistent between its main run and its grid-shift
        # verification. Proven here by mocking test_hypothesis directly and
        # checking every call received the SAME object, not by inference from
        # a P&L difference.
        from nero_core.strategies.mean_reversion import MeanReversionParameters

        custom_params = MeanReversionParameters(fee_bps=2.0, slippage_bps=2.0)
        hypothesis = _hypothesis(generated_at=datetime.now(timezone.utc).isoformat())
        grids = {"native": _flat_noise_candles(50), "offset+1h": _flat_noise_candles(50)}

        with patch("nero_core.research_agent.auto_tester.test_hypothesis") as mock_test_hypothesis:
            run_grid_shift_check(hypothesis, grids, backtest_params=custom_params)

        self.assertEqual(mock_test_hypothesis.call_count, 2)
        for call in mock_test_hypothesis.call_args_list:
            self.assertIs(call.kwargs["backtest_params"], custom_params)

    def test_omitting_backtest_params_is_byte_identical_to_before_this_parameter_existed(self) -> None:
        candles_a = _flat_noise_candles(200)
        generated_at = datetime.fromtimestamp((START_MS + 200 * HOUR_MS) / 1000, tz=timezone.utc)
        hypothesis = _hypothesis(generated_at=generated_at.isoformat())
        fixed_now = datetime.now(timezone.utc)  # held fixed across both calls -- tested_at would otherwise differ trivially

        with_explicit_none = run_grid_shift_check(hypothesis, {"native": candles_a}, now=fixed_now, backtest_params=None)
        without_the_kwarg_at_all = run_grid_shift_check(hypothesis, {"native": candles_a}, now=fixed_now)

        self.assertEqual(with_explicit_none["native"].to_dict(), without_the_kwarg_at_all["native"].to_dict())


class PersistTestResultsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "agent_test_results.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_persist_is_append_only_and_round_trips(self) -> None:
        candles = _flat_noise_candles(1000, spike_indices={500: 500.0})
        generated_at = datetime.fromtimestamp((START_MS + 1000 * HOUR_MS) / 1000, tz=timezone.utc)
        result_a = test_hypothesis(_hypothesis(hypothesis_name="A", generated_at=generated_at.isoformat()), candles)
        result_b = test_hypothesis(_hypothesis(hypothesis_name="B", generated_at=generated_at.isoformat()), candles)

        persist_test_results([result_a], self.path)
        persist_test_results([result_b], self.path)

        stored = load_existing_test_results(self.path)
        self.assertEqual([r["hypothesis_name"] for r in stored], ["A", "B"])
        self.assertIn("measured_trades_per_year", stored[0])
        self.assertIn("expected_time_to_30_trades_months", stored[0])


if __name__ == "__main__":
    unittest.main()
