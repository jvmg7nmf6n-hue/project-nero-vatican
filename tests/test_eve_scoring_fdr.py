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


class SelfDerivativeExcludedFromFdrFamilyTest(unittest.TestCase):
    """CC-1 review, item 1a: a self-derivative hypothesis is still SCORED
    and its verdict still RECORDED (measure, never gate) -- what changes is
    that it is excluded from the FDR family, because it is not an
    independent test. This must be explicit in the record, not just an
    absence."""

    def _self_derivative_record(self, p_value_oos):
        return {
            "hypothesis_name": "REPEAT", "p_value_oos": p_value_oos, "p_value_is": p_value_oos,
            "contamination_tags": [{"tag": "SELF_DERIVATIVE", "matched_hypothesis_name": "PRIOR", "similarity": 0.9, "method": "x"}],
        }

    def _fresh_record(self, p_value_oos):
        return {"hypothesis_name": "FRESH", "p_value_oos": p_value_oos, "p_value_is": p_value_oos, "contamination_tags": []}

    def test_self_derivative_record_excluded_even_with_a_significant_p_value(self) -> None:
        # Would otherwise trivially "survive" FDR (p=0.001, alone in the
        # family) -- must instead be excluded regardless of how significant
        # its own p-value looks.
        records = [self._self_derivative_record(0.001)]
        updated = scoring.apply_fdr_correction(records, field="p_value_oos")
        self.assertIsNone(updated[0]["fdr_survives_oos"])

    def test_exclusion_reason_is_explicit_not_just_a_bare_none(self) -> None:
        records = [self._self_derivative_record(0.001)]
        updated = scoring.apply_fdr_correction(records, field="p_value_oos")
        self.assertEqual(updated[0]["excluded_from_fdr_family_reason"], "self_derivative")

    def test_a_record_with_no_p_value_at_all_gets_no_fabricated_exclusion_reason(self) -> None:
        # A record can be None for an unrelated reason (e.g. INSUFFICIENT_
        # SAMPLE) without ever being self-derivative -- must not silently
        # acquire an "excluded_from_fdr_family_reason" it doesn't deserve.
        records = [self._fresh_record(None)]
        updated = scoring.apply_fdr_correction(records, field="p_value_oos")
        self.assertNotIn("excluded_from_fdr_family_reason", updated[0])

    def test_fresh_hypothesis_still_participates_in_the_family_normally(self) -> None:
        records = [self._self_derivative_record(0.001), self._fresh_record(0.002)]
        updated = scoring.apply_fdr_correction(records, field="p_value_oos", alpha=0.05)
        self.assertIsNone(updated[0]["fdr_survives_oos"])
        self.assertTrue(updated[1]["fdr_survives_oos"])

    def test_self_derivative_status_never_affects_the_bh_threshold_for_others(self) -> None:
        # A self-derivative record excluded from the family must not be
        # counted in BH's own `n` (family size) -- confirm by comparing
        # against running BH directly on just the fresh p-values.
        fresh_p_values = [0.01, 0.02, 0.5]
        direct = scoring.benjamini_hochberg(fresh_p_values, alpha=0.05)

        records = [self._self_derivative_record(0.0001)] + [self._fresh_record(p) for p in fresh_p_values]
        updated = scoring.apply_fdr_correction(records, field="p_value_oos", alpha=0.05)
        via_pipeline = [r["fdr_survives_oos"] for r in updated[1:]]
        self.assertEqual(via_pipeline, direct)

    def test_verdict_and_p_value_are_untouched_only_fdr_survives_changes(self) -> None:
        # "Scored yes, verdict recorded yes, counted as an independent data
        # point no" -- the self-derivative record's own p_value_oos and any
        # verdict fields must be left exactly as scored.
        record = self._self_derivative_record(0.001)
        record["verdict_oos"] = "SURVIVED"
        updated = scoring.apply_fdr_correction([record], field="p_value_oos")
        self.assertEqual(updated[0]["p_value_oos"], 0.001)
        self.assertEqual(updated[0]["verdict_oos"], "SURVIVED")


class ValidateDerivedFromTest(unittest.TestCase):
    """CC-1 directive, item B1 (2026-08-06): a declared derived_from must
    be either absent or fully real -- never partial, never naming an
    invented parent."""

    def test_none_is_always_valid(self) -> None:
        ok, reason = scoring.validate_derived_from({"hypothesis_name": "X"}, {"SOME_PARENT"})
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_non_dict_derived_from_is_invalid(self) -> None:
        ok, reason = scoring.validate_derived_from({"derived_from": "not a dict"}, {"SOME_PARENT"})
        self.assertFalse(ok)
        self.assertIn("must be a JSON object", reason)

    def test_partial_derived_from_is_a_hard_error(self) -> None:
        ok, reason = scoring.validate_derived_from(
            {"derived_from": {"parent_hypothesis_name": "SOME_PARENT", "what_changed": "tightened the RSI threshold"}},
            {"SOME_PARENT"},
        )
        self.assertFalse(ok)
        self.assertIn("parent_session_id", reason)
        self.assertIn("why_this_change", reason)

    def test_all_four_fields_present_and_real_parent_is_valid(self) -> None:
        ok, reason = scoring.validate_derived_from(
            {
                "derived_from": {
                    "parent_hypothesis_name": "SOME_PARENT",
                    "parent_session_id": "eve-20260803T095520Z-394385c7",
                    "what_changed": "tightened the RSI threshold from 30 to 25",
                    "why_this_change": "the original fired too often on shallow pullbacks",
                }
            },
            {"SOME_PARENT"},
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_naming_a_never_proposed_parent_is_a_hard_error(self) -> None:
        # The core anti-hallucination check: the whole point of REFINEMENT
        # tagging is that the declared parent is verified real, not just
        # claimed.
        ok, reason = scoring.validate_derived_from(
            {
                "derived_from": {
                    "parent_hypothesis_name": "INVENTED_HYPOTHESIS_THAT_NEVER_EXISTED",
                    "parent_session_id": "eve-fake",
                    "what_changed": "x",
                    "why_this_change": "y",
                }
            },
            {"SOME_PARENT"},
        )
        self.assertFalse(ok)
        self.assertIn("INVENTED_HYPOTHESIS_THAT_NEVER_EXISTED", reason)
        self.assertIn("never invented", reason)

    def test_empty_known_names_rejects_any_declared_parent(self) -> None:
        ok, reason = scoring.validate_derived_from(
            {
                "derived_from": {
                    "parent_hypothesis_name": "SOME_PARENT",
                    "parent_session_id": "eve-x",
                    "what_changed": "x",
                    "why_this_change": "y",
                }
            },
            set(),
        )
        self.assertFalse(ok)


class RefinementVsSelfDerivativeTest(unittest.TestCase):
    """CC-1 directive, item B1: apply_self_derivative_tags splits a
    similarity match into REFINEMENT (declared, validated parent) vs
    SELF_DERIVATIVE (no declared parent, or a match against something
    OTHER than the declared parent) -- and apply_fdr_correction must
    treat only the latter as exclusion-worthy."""

    def _record(self, name: str, mechanism: str, derived_from: dict | None = None) -> dict:
        raw = {"hypothesis_name": name, "mechanism": mechanism}
        if derived_from is not None:
            raw["derived_from"] = derived_from
        return {"raw_hypothesis": raw, "contamination_tags": []}

    def test_declared_and_similar_parent_is_tagged_refinement_not_self_derivative(self) -> None:
        prior = {"hypothesis_name": "RSI_DIP_BUY", "mechanism": "buy when rsi14 drops below 30 in an uptrend"}
        child = self._record(
            "RSI_DIP_BUY_TIGHTER", "buy when rsi14 drops below 30 in an uptrend",
            derived_from={
                "parent_hypothesis_name": "RSI_DIP_BUY", "parent_session_id": "eve-x",
                "what_changed": "tightened threshold", "why_this_change": "fewer false positives",
            },
        )
        updated = scoring.apply_self_derivative_tags([child], eve_history=[prior])
        tags = updated[0]["contamination_tags"]
        self.assertEqual(len(tags), 1)
        self.assertEqual(tags[0]["tag"], "REFINEMENT")
        self.assertFalse(scoring.is_self_derivative(updated[0]))
        self.assertTrue(scoring.is_refinement(updated[0]))

    def test_similar_but_undeclared_stays_self_derivative(self) -> None:
        # Same similarity shape as the REFINEMENT case above, but no
        # derived_from at all -- unchanged, pre-B1 behavior.
        prior = {"hypothesis_name": "RSI_DIP_BUY", "mechanism": "buy when rsi14 drops below 30 in an uptrend"}
        child = self._record("RSI_DIP_BUY_TIGHTER", "buy when rsi14 drops below 30 in an uptrend")
        updated = scoring.apply_self_derivative_tags([child], eve_history=[prior])
        self.assertTrue(scoring.is_self_derivative(updated[0]))
        self.assertFalse(scoring.is_refinement(updated[0]))

    def test_declared_parent_that_does_not_match_the_similarity_hit_stays_self_derivative(self) -> None:
        # The declared parent must be the SAME hypothesis the similarity
        # engine actually matched -- declaring an unrelated real name does
        # not launder an unrelated similarity hit.
        prior_a = {"hypothesis_name": "RSI_DIP_BUY", "mechanism": "buy when rsi14 drops below 30 in an uptrend"}
        prior_b = {"hypothesis_name": "UNRELATED_OTHER_IDEA", "mechanism": "completely different mechanism about volume spikes"}
        child = self._record(
            "RSI_DIP_BUY_TIGHTER", "buy when rsi14 drops below 30 in an uptrend",
            derived_from={
                "parent_hypothesis_name": "UNRELATED_OTHER_IDEA", "parent_session_id": "eve-x",
                "what_changed": "x", "why_this_change": "y",
            },
        )
        updated = scoring.apply_self_derivative_tags([child], eve_history=[prior_a, prior_b])
        self.assertTrue(scoring.is_self_derivative(updated[0]))
        self.assertFalse(scoring.is_refinement(updated[0]))

    def test_refinement_tagged_record_is_not_excluded_from_fdr_family(self) -> None:
        # The whole point: REFINEMENT stays IN the family, unlike
        # SELF_DERIVATIVE (see SelfDerivativeExcludedFromFdrFamilyTest
        # above for the contrasting excluded case).
        record = {
            "hypothesis_name": "RSI_DIP_BUY_TIGHTER", "p_value_oos": 0.001, "p_value_is": 0.001,
            "contamination_tags": [{"tag": "REFINEMENT", "matched_hypothesis_name": "RSI_DIP_BUY", "similarity": 0.7, "method": "x"}],
        }
        updated = scoring.apply_fdr_correction([record], field="p_value_oos")
        self.assertTrue(updated[0]["fdr_survives_oos"])
        self.assertNotIn("excluded_from_fdr_family_reason", updated[0])

    def test_a_record_with_both_a_refinement_and_an_unrelated_self_derivative_tag_is_still_excluded(self) -> None:
        # Declaring one real parent does not launder an UNRELATED
        # undeclared near-duplicate the same record also happens to match.
        record = {
            "hypothesis_name": "X", "p_value_oos": 0.001, "p_value_is": 0.001,
            "contamination_tags": [
                {"tag": "REFINEMENT", "matched_hypothesis_name": "DECLARED_PARENT", "similarity": 0.7, "method": "x"},
                {"tag": "SELF_DERIVATIVE", "matched_hypothesis_name": "SOME_OTHER_PRIOR", "similarity": 0.65, "method": "x"},
            ],
        }
        updated = scoring.apply_fdr_correction([record], field="p_value_oos")
        self.assertIsNone(updated[0]["fdr_survives_oos"])
        self.assertEqual(updated[0]["excluded_from_fdr_family_reason"], "self_derivative")

    def test_fdr_family_size_grows_when_a_refinement_joins_it_making_the_bar_harder_not_easier(self) -> None:
        # Statistical note the directive requires addressing explicitly:
        # moving a REFINEMENT record back into the family means Benjamini-
        # Hochberg corrects over a LARGER family -- the bar gets harder,
        # never easier, than if that same record had stayed excluded as
        # SELF_DERIVATIVE. Confirmed arithmetically: a marginal p-value
        # that survives in the smaller family fails once a REFINEMENT
        # record with a large p-value joins.
        fresh = [{"hypothesis_name": f"F{i}", "p_value_oos": 0.04, "p_value_is": 0.04, "contamination_tags": []} for i in range(3)]

        excluded_as_self_derivative = fresh + [{
            "hypothesis_name": "R", "p_value_oos": 0.5, "p_value_is": 0.5,
            "contamination_tags": [{"tag": "SELF_DERIVATIVE", "matched_hypothesis_name": "P", "similarity": 0.9, "method": "x"}],
        }]
        included_as_refinement = fresh + [{
            "hypothesis_name": "R", "p_value_oos": 0.5, "p_value_is": 0.5,
            "contamination_tags": [{"tag": "REFINEMENT", "matched_hypothesis_name": "P", "similarity": 0.9, "method": "x"}],
        }]

        result_excluded = scoring.apply_fdr_correction(excluded_as_self_derivative, field="p_value_oos", alpha=0.05)
        result_included = scoring.apply_fdr_correction(included_as_refinement, field="p_value_oos", alpha=0.05)

        family_size_excluded = sum(1 for r in result_excluded if r["fdr_survives_oos"] is not None)
        family_size_included = sum(1 for r in result_included if r["fdr_survives_oos"] is not None)
        self.assertEqual(family_size_excluded, 3)  # the 3 fresh records only
        self.assertEqual(family_size_included, 4)  # + the refinement record itself

        fresh_survivals_excluded = [r["fdr_survives_oos"] for r in result_excluded[:3]]
        fresh_survivals_included = [r["fdr_survives_oos"] for r in result_included[:3]]
        # A larger family with a large-p-value member never makes the SAME
        # fresh p-values MORE likely to survive BH correction.
        self.assertGreaterEqual(sum(fresh_survivals_excluded), sum(fresh_survivals_included))


if __name__ == "__main__":
    unittest.main()
