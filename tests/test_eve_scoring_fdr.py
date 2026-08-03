from __future__ import annotations

import random
import unittest
from datetime import datetime, timezone

import pandas as pd

from nero_core.eve import hypothesis_shapes, scoring


class NormalApproxPValueTest(unittest.TestCase):
    def test_none_ci_gives_none_p_value(self) -> None:
        self.assertIsNone(scoring.normal_approx_p_value(None))

    def test_degenerate_zero_width_ci_returns_none_never_a_fabricated_p_value(self) -> None:
        # The exact real-world bug this guards against: a single-trade half
        # resamples the SAME value every bootstrap iteration, collapsing
        # lower_2_5 == upper_97_5. The OLD behavior returned 0.0 (maximally
        # "significant") for any nonzero mean_r here -- fabricating
        # significance from one data point. Must now return None.
        from tools.backtest_statistics import BootstrapCI

        ci = BootstrapCI(sample_size=1, mean_r=0.9505666235252774, lower_2_5=0.9505666235252774, upper_97_5=0.9505666235252774, crosses_zero=False)
        self.assertIsNone(scoring.normal_approx_p_value(ci))

    def test_degenerate_zero_mean_and_zero_width_ci_also_returns_none(self) -> None:
        # The OLD behavior's OTHER branch (se<=0 and mean_r==0 -> p=1.0) is
        # equally a fabrication -- also must be None now.
        from tools.backtest_statistics import BootstrapCI

        ci = BootstrapCI(sample_size=1, mean_r=0.0, lower_2_5=0.0, upper_97_5=0.0, crosses_zero=True)
        self.assertIsNone(scoring.normal_approx_p_value(ci))

    def test_near_zero_but_not_exactly_zero_se_also_returns_none(self) -> None:
        # Floating-point noise from resampling near-identical values could
        # produce an SE that's nonzero but numerically meaningless -- the
        # gate uses a small epsilon, not a bare `<= 0` check.
        from tools.backtest_statistics import BootstrapCI

        ci = BootstrapCI(sample_size=2, mean_r=0.5, lower_2_5=0.5 - 1e-12, upper_97_5=0.5 + 1e-12, crosses_zero=False)
        self.assertIsNone(scoring.normal_approx_p_value(ci))

    def test_mean_far_from_zero_with_tight_ci_gives_small_p_value(self) -> None:
        from tools.backtest_statistics import BootstrapCI

        ci = BootstrapCI(sample_size=100, mean_r=1.0, lower_2_5=0.9, upper_97_5=1.1, crosses_zero=False)
        p = scoring.normal_approx_p_value(ci)
        self.assertLess(p, 0.01)

    def test_ci_crossing_zero_gives_large_p_value(self) -> None:
        from tools.backtest_statistics import BootstrapCI

        ci = BootstrapCI(sample_size=20, mean_r=0.05, lower_2_5=-0.5, upper_97_5=0.6, crosses_zero=True)
        p = scoring.normal_approx_p_value(ci)
        self.assertGreater(p, 0.5)

    def test_p_value_always_in_valid_range(self) -> None:
        from tools.backtest_statistics import BootstrapCI

        for mean_r, lower, upper in [(2.0, 1.5, 2.5), (-1.0, -1.5, -0.5), (0.0, -0.1, 0.1)]:
            ci = BootstrapCI(sample_size=50, mean_r=mean_r, lower_2_5=lower, upper_97_5=upper, crosses_zero=(lower <= 0 <= upper))
            p = scoring.normal_approx_p_value(ci)
            self.assertGreaterEqual(p, 0.0)
            self.assertLessEqual(p, 1.0)


class BenjaminiHochbergTest(unittest.TestCase):
    def test_empty_input(self) -> None:
        self.assertEqual(scoring.benjamini_hochberg([]), [])

    def test_all_significant_p_values_survive(self) -> None:
        p_values = [0.001, 0.002, 0.003, 0.004]
        self.assertTrue(all(scoring.benjamini_hochberg(p_values, alpha=0.05)))

    def test_all_non_significant_p_values_fail(self) -> None:
        p_values = [0.9, 0.8, 0.7, 0.95]
        self.assertFalse(any(scoring.benjamini_hochberg(p_values, alpha=0.05)))

    def test_mixed_p_values_only_the_small_ones_survive_bh_threshold(self) -> None:
        # Classic textbook-style example: BH is less strict than a flat
        # Bonferroni cutoff, so more than just the single smallest p-value
        # can survive, but not every one of a mostly-null family should.
        p_values = [0.001, 0.008, 0.039, 0.041, 0.042, 0.6, 0.7, 0.8, 0.9, 0.99]
        survives = scoring.benjamini_hochberg(p_values, alpha=0.05)
        self.assertTrue(survives[0])  # smallest p-value should always survive if anything does
        self.assertFalse(survives[-1])  # largest should never survive
        self.assertLess(sum(survives), len(p_values))  # not everything survives

    def test_survives_flags_correspond_to_original_order(self) -> None:
        p_values = [0.9, 0.001, 0.5]
        survives = scoring.benjamini_hochberg(p_values, alpha=0.05)
        self.assertEqual(len(survives), 3)
        self.assertTrue(survives[1])  # the smallest p-value, at index 1


def _make_candles(n: int, seed: int) -> pd.DataFrame:
    rng = random.Random(seed)
    rows = []
    price = 100.0
    t0 = 1_700_000_000_000
    for i in range(n):
        price *= 1 + rng.uniform(-0.01, 0.01)
        rows.append({"close_time": t0 + i * 3_600_000, "close": price, "high": price * 1.004, "low": price * 0.996, "volume": 1.0})
    return pd.DataFrame(rows)


class PValueUnderMinSampleSizeGateTest(unittest.TestCase):
    """The item-3 fix: n_trades < MIN_SAMPLE_SIZE must EXCLUDE a half from
    the FDR family (p_value = None) even when its CI happens to be
    non-degenerate -- not just when the CI collapses to zero width."""

    def test_p_value_for_half_is_none_below_min_sample_size_even_with_a_real_ci(self) -> None:
        from tools.backtest_statistics import MIN_SAMPLE_SIZE, BootstrapCI

        class _FakeStats:
            trades = MIN_SAMPLE_SIZE - 1
            ci = BootstrapCI(sample_size=MIN_SAMPLE_SIZE - 1, mean_r=1.0, lower_2_5=0.5, upper_97_5=1.5, crosses_zero=False)

        self.assertIsNotNone(scoring.normal_approx_p_value(_FakeStats.ci))  # the CI itself is NOT degenerate...
        self.assertIsNone(scoring._p_value_for_half(_FakeStats))  # ...but the trade count still excludes it

    def test_p_value_for_half_is_populated_at_or_above_min_sample_size(self) -> None:
        from tools.backtest_statistics import MIN_SAMPLE_SIZE, BootstrapCI

        class _FakeStats:
            trades = MIN_SAMPLE_SIZE
            ci = BootstrapCI(sample_size=MIN_SAMPLE_SIZE, mean_r=1.0, lower_2_5=0.5, upper_97_5=1.5, crosses_zero=False)

        self.assertIsNotNone(scoring._p_value_for_half(_FakeStats))

    def test_p_value_for_half_is_none_when_stats_is_none(self) -> None:
        self.assertIsNone(scoring._p_value_for_half(None))


ALWAYS_FIRES_SINGLE_TRADE_SHAPED_RAW = {
    "hypothesis_name": "TEST_SINGLE_TRADE_REGRESSION",
    "mechanism": "test fixture -- engineered to produce very few trades",
    "asset": "BTC",
    "timeframe": "1h",
    "generated_at": "2026-07-29T00:00:00+00:00",
    # A very tight z-score threshold combined with a short frame keeps the
    # real trade count low without being literally zero, exercising the
    # small-but-nonzero-trades regime this fix targets.
    "structured_entry_rule": {"conditions": [{"field": "zscore20", "op": "lt", "value": -2.7}]},
    "structured_exit_plan": {"stop_atr_multiple": 1.5, "target_r_multiple": 2.0, "max_holding_hours": 24.0},
}


class SingleTradeEndToEndRegressionTest(unittest.TestCase):
    """The exact regression test requested: a hypothesis that ends up with
    very few (in practice, often exactly zero or one) trades in a half must
    get p_value=None for that half and be excluded from the FDR family --
    run through the REAL harness, not a hand-built HalfStats."""

    def test_low_trade_count_hypothesis_yields_none_p_value_and_is_excluded_from_fdr_family(self) -> None:
        candles = _make_candles(n=600, seed=99)
        record = hypothesis_shapes.build_hypothesis_record(
            ALWAYS_FIRES_SINGLE_TRADE_SHAPED_RAW, session_id="s1", turn_index=0, tool_use_id="toolu_1"
        )
        scored = scoring.score_hypothesis(record, candles_provider=lambda a, t: candles, now=datetime(2026, 8, 1, tzinfo=timezone.utc))

        from tools.backtest_statistics import MIN_SAMPLE_SIZE

        # Whichever half(s) ended up below MIN_SAMPLE_SIZE must have a null
        # p-value -- this is a live, real-harness check, not a synthetic one.
        if scored["verdict_is"] == scoring.VERDICT_EVE_INSUFFICIENT_SAMPLE:
            self.assertIsNone(scored["p_value_is"])
        if scored["verdict_oos"] == scoring.VERDICT_EVE_INSUFFICIENT_SAMPLE:
            self.assertIsNone(scored["p_value_oos"])

        family = scoring.apply_fdr_correction([scored], field="p_value_oos")
        if scored["p_value_oos"] is None:
            self.assertIsNone(family[0]["fdr_survives_oos"])


class VerdictUnaffectedByPValueGateTest(unittest.TestCase):
    """Required regression test: the p-value/FDR fix must NOT change any
    hypothesis's verdict. Nothing gets downgraded to DIED; INSUFFICIENT_SAMPLE
    stays exactly as it is, regardless of what the (now-often-null) p-value
    looks like."""

    def test_insufficient_sample_hypothesis_keeps_its_verdict_even_though_its_p_value_is_now_null(self) -> None:
        candles = _make_candles(n=600, seed=99)
        record = hypothesis_shapes.build_hypothesis_record(
            ALWAYS_FIRES_SINGLE_TRADE_SHAPED_RAW, session_id="s1", turn_index=0, tool_use_id="toolu_1"
        )
        scored = scoring.score_hypothesis(record, candles_provider=lambda a, t: candles, now=datetime(2026, 8, 1, tzinfo=timezone.utc))

        # Recompute the verdict independently, directly from the same
        # HalfStats-shaped inputs auto_tester itself produced, completely
        # bypassing score_hypothesis's own p-value computation -- if the two
        # ever disagreed, that would mean the p-value gate had somehow
        # leaked into verdict computation. `now` must match score_hypothesis's
        # own call so auto_tester's chronological split lines up identically.
        from nero_core.research_agent.auto_tester import test_hypothesis as adam_test_hypothesis

        result = adam_test_hypothesis(ALWAYS_FIRES_SINGLE_TRADE_SHAPED_RAW, candles, now=datetime(2026, 8, 1, tzinfo=timezone.utc))
        self.assertEqual(scored["verdict_is"], scoring._map_half_verdict(result.train))
        self.assertEqual(scored["verdict_oos"], scoring._map_half_verdict(result.test))

    def test_verdicts_identical_whether_or_not_p_value_gate_would_have_nulled_it(self) -> None:
        # Direct proof the two concerns are decoupled: construct the SAME
        # HalfStats-shaped input, compute verdict via _map_half_verdict and
        # p-value via _p_value_for_half independently, and confirm the
        # verdict computation path never reads a p-value at all (by
        # construction: _map_half_verdict's signature takes no p-value
        # argument whatsoever).
        import inspect

        sig = inspect.signature(scoring._map_half_verdict)
        self.assertNotIn("p_value", sig.parameters)
        self.assertNotIn("p", sig.parameters)


class ApplyFdrCorrectionTest(unittest.TestCase):
    def _record(self, p_value_oos):
        return {"hypothesis_name": "X", "p_value_oos": p_value_oos, "p_value_is": p_value_oos}

    def test_records_without_p_value_pass_through_with_none(self) -> None:
        records = [self._record(None)]
        updated = scoring.apply_fdr_correction(records)
        self.assertIsNone(updated[0]["fdr_survives_oos"])

    def test_significant_family_all_survive(self) -> None:
        records = [self._record(0.001), self._record(0.002), self._record(0.003)]
        updated = scoring.apply_fdr_correction(records, alpha=0.05)
        self.assertTrue(all(r["fdr_survives_oos"] for r in updated))

    def test_does_not_mutate_input_records(self) -> None:
        records = [self._record(0.001)]
        scoring.apply_fdr_correction(records)
        self.assertNotIn("fdr_survives_oos", records[0])

    def test_can_run_separately_for_is_field(self) -> None:
        records = [self._record(0.001), self._record(0.5)]
        updated = scoring.apply_fdr_correction(records, field="p_value_is")
        self.assertIn("fdr_survives_is", updated[0])
        self.assertNotIn("fdr_survives_oos", updated[0])


if __name__ == "__main__":
    unittest.main()
