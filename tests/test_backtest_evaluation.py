from __future__ import annotations

import unittest

from nero_core.execution.backtest_evaluation import (
    DEFAULT_BACKTEST_EVALUATION,
    backtest_evaluation_for,
)


class BacktestEvaluationForTest(unittest.TestCase):
    def test_unmapped_config_falls_back_to_default(self) -> None:
        self.assertEqual(
            backtest_evaluation_for("SOME_NEW_STRATEGY", "some-version", "XYZ"),
            DEFAULT_BACKTEST_EVALUATION,
        )

    def test_default_has_no_fabricated_verdict(self) -> None:
        # The whole point of this module: an unevaluated config must show an
        # honest "not yet evaluated" note, never a guessed verdict.
        self.assertIsNone(DEFAULT_BACKTEST_EVALUATION["verdict_is"])
        self.assertIsNone(DEFAULT_BACKTEST_EVALUATION["verdict_oos"])
        self.assertIsNotNone(DEFAULT_BACKTEST_EVALUATION["note"])

    def test_range_mean_reversion_long_only_btc_died_in_sample(self) -> None:
        result = backtest_evaluation_for("RANGE_MEAN_REVERSION", "range-mean-reversion-v1.1.0-long-only", "BTC")
        self.assertEqual(result["verdict_is"], "DIED")
        self.assertEqual(result["verdict_oos"], "INSUFFICIENT_SAMPLE")
        self.assertEqual(result["is_trades"], 10)
        self.assertEqual(result["oos_trades"], 5)
        self.assertIsNone(result["untestable_reason"])

    def test_range_mean_reversion_confirmation_btc_died_in_sample(self) -> None:
        result = backtest_evaluation_for("RANGE_MEAN_REVERSION", "range-mean-reversion-v1.3.0-confirmation", "BTC")
        self.assertEqual(result["verdict_is"], "DIED")
        self.assertEqual(result["verdict_oos"], "INSUFFICIENT_SAMPLE")
        self.assertEqual(result["is_trades"], 9)
        self.assertEqual(result["oos_trades"], 7)

    def test_long_only_and_confirmation_do_not_collide(self) -> None:
        long_only = backtest_evaluation_for("RANGE_MEAN_REVERSION", "range-mean-reversion-v1.1.0-long-only", "BTC")
        confirmation = backtest_evaluation_for("RANGE_MEAN_REVERSION", "range-mean-reversion-v1.3.0-confirmation", "BTC")
        self.assertNotEqual(long_only, confirmation)

    def test_cointegration_pairs_is_untestable_but_not_evidence_free(self) -> None:
        # "Untestable" here means "not compatible with the standard harness,"
        # NOT "no evidence exists" -- this is the exact distinction the
        # module's own docstring insists on. A test that only checked
        # untestable_reason is set (without also checking real trade/
        # expectancy numbers are present) would miss the whole point.
        result = backtest_evaluation_for("COINTEGRATION_PAIRS", "cointegration-pairs-v1.0.0", "BTC-ETH")
        self.assertIsNotNone(result["untestable_reason"])
        self.assertIn("rule_dsl", result["untestable_reason"])
        self.assertEqual(result["is_trades"], 61)
        self.assertEqual(result["oos_trades"], 22)
        self.assertGreater(result["is_expectancy_r"], 0)
        self.assertGreater(result["oos_expectancy_r"], 0)
        # verdict_is/verdict_oos deliberately null here -- classify_verdict's
        # own vocabulary (SURVIVED/DIED/PROMISING-WATCHLIST) was never applied
        # via a bootstrap CI for this entry; this is not the same as "no data."
        self.assertIsNone(result["verdict_is"])
        self.assertIsNone(result["verdict_oos"])

    def test_repair_breakout_quality_has_no_entry_here(self) -> None:
        # FIX_BREAKOUT_QUALITY (display name for REPAIR_BREAKOUT_QUALITY) is
        # dead (graveyard.json), never wired to live paper trading -- it has
        # no strategies.json roster entry at all, so it never reaches this
        # lookup in practice. Documented here so a future reader doesn't
        # wonder why it's absent from BACKTEST_EVALUATIONS.
        self.assertEqual(
            backtest_evaluation_for("REPAIR_BREAKOUT_QUALITY", "repair-breakout-quality-v1.0.0", "BTC"),
            DEFAULT_BACKTEST_EVALUATION,
        )


if __name__ == "__main__":
    unittest.main()
