from __future__ import annotations

import unittest

from nero_core.eve import scoring


class NormalApproxPValueTest(unittest.TestCase):
    def test_none_ci_gives_none_p_value(self) -> None:
        self.assertIsNone(scoring.normal_approx_p_value(None))

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
