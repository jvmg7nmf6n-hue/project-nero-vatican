from __future__ import annotations

import unittest

from nero_core.execution.verification_status import (
    DEFAULT_VERIFICATION_STATUS,
    verification_status_for,
)


class VerificationStatusForTest(unittest.TestCase):
    def test_known_gold_breakout_momentum_status(self) -> None:
        self.assertEqual(
            verification_status_for("BREAKOUT_MOMENTUM", "breakout-momentum-v1.2.0-gold-calibrated-1week", "GOLD"),
            "triple-verified",
        )

    def test_known_bnb_trend_pullback_status(self) -> None:
        self.assertEqual(
            verification_status_for("TREND_PULLBACK", "trend-pullback-v1.0.0", "BNB"),
            "verified — sample-limited",
        )

    def test_known_pairs_status(self) -> None:
        self.assertEqual(
            verification_status_for("COINTEGRATION_PAIRS", "cointegration-pairs-v1.0.0", "BTC-ETH"),
            "verified — weakest, live-proving",
        )

    def test_unmapped_config_falls_back_to_default(self) -> None:
        self.assertEqual(verification_status_for("SOME_NEW_STRATEGY", "some-version", "XYZ"), DEFAULT_VERIFICATION_STATUS)

    def test_unmapped_version_of_a_known_strategy_falls_back_to_default(self) -> None:
        # Same (strategy_id, asset) as a known row, but a DIFFERENT version -- proves
        # the key genuinely includes strategy_version, not just (strategy_id, asset).
        self.assertEqual(
            verification_status_for("TREND_PULLBACK", "trend-pullback-v9.9.9-made-up", "BNB"),
            DEFAULT_VERIFICATION_STATUS,
        )

    def test_range_mean_reversion_gold_1week_status(self) -> None:
        self.assertEqual(
            verification_status_for("RANGE_MEAN_REVERSION", "range-mean-reversion-v1.0.0", "GOLD"),
            "watchlist — forward-testing, not verified (band-timing beat random both halves; N below 20-trade bar)",
        )

    def test_range_mean_reversion_silver_1week_status(self) -> None:
        self.assertEqual(
            verification_status_for("RANGE_MEAN_REVERSION", "range-mean-reversion-v1.0.0", "SILVER"),
            "watchlist — forward-testing, not verified (band-timing beat random both halves; N below 20-trade bar)",
        )

    def test_range_mean_reversion_long_only_btc_status(self) -> None:
        self.assertEqual(
            verification_status_for("RANGE_MEAN_REVERSION", "range-mean-reversion-v1.1.0-long-only", "BTC"),
            "watchlist — forward-testing, not verified (mechanism-backed, LOW SAMPLE, CI crosses zero, 1d grid-shift structurally unavailable)",
        )

    def test_range_mean_reversion_confirmation_btc_status(self) -> None:
        self.assertEqual(
            verification_status_for("RANGE_MEAN_REVERSION", "range-mean-reversion-v1.3.0-confirmation", "BTC"),
            "watchlist — forward-testing, not verified (68% reversion-target exit rate vs 32% baseline; LOW SAMPLE, CI crosses zero, 1d grid-shift structurally unavailable)",
        )

    def test_long_only_and_confirmation_do_not_collide_on_the_same_btc_status(self) -> None:
        # The whole reason strategy_version was added to the key: two RANGE_MEAN_
        # REVERSION versions share the same (strategy_id, asset) = (..., "BTC").
        long_only = verification_status_for("RANGE_MEAN_REVERSION", "range-mean-reversion-v1.1.0-long-only", "BTC")
        confirmation = verification_status_for("RANGE_MEAN_REVERSION", "range-mean-reversion-v1.3.0-confirmation", "BTC")
        self.assertNotEqual(long_only, confirmation)


if __name__ == "__main__":
    unittest.main()
