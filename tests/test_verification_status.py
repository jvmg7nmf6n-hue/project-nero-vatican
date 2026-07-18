from __future__ import annotations

import unittest

from nero_core.execution.verification_status import (
    DEFAULT_VERIFICATION_STATUS,
    verification_status_for,
)


class VerificationStatusForTest(unittest.TestCase):
    def test_known_gold_breakout_momentum_status(self) -> None:
        self.assertEqual(verification_status_for("BREAKOUT_MOMENTUM", "GOLD"), "triple-verified")

    def test_known_bnb_trend_pullback_status(self) -> None:
        self.assertEqual(verification_status_for("TREND_PULLBACK", "BNB"), "verified — sample-limited")

    def test_known_pairs_status(self) -> None:
        self.assertEqual(verification_status_for("COINTEGRATION_PAIRS", "BTC-ETH"), "verified — weakest, live-proving")

    def test_unmapped_config_falls_back_to_default(self) -> None:
        self.assertEqual(verification_status_for("SOME_NEW_STRATEGY", "XYZ"), DEFAULT_VERIFICATION_STATUS)


if __name__ == "__main__":
    unittest.main()
