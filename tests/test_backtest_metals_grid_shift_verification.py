from __future__ import annotations

import unittest

from tools.backtest_metals_grid_shift_verification import NOT_APPLICABLE_CANDIDATES, _qualifies


class QualifiesTest(unittest.TestCase):
    def test_qualifies_when_positive_and_adequate_both_halves(self) -> None:
        train = {"trades": 25, "expectancy_r": 0.1}
        test = {"trades": 20, "expectancy_r": 0.05}
        self.assertTrue(_qualifies(train, test))

    def test_does_not_qualify_below_min_sample(self) -> None:
        train = {"trades": 19, "expectancy_r": 0.1}
        test = {"trades": 20, "expectancy_r": 0.05}
        self.assertFalse(_qualifies(train, test))

    def test_does_not_qualify_negative_half(self) -> None:
        train = {"trades": 25, "expectancy_r": 0.1}
        test = {"trades": 20, "expectancy_r": -0.05}
        self.assertFalse(_qualifies(train, test))


class NotApplicableCandidatesTest(unittest.TestCase):
    def test_lists_exactly_the_eight_24h_task2_candidates(self) -> None:
        self.assertEqual(len(NOT_APPLICABLE_CANDIDATES), 8)
        self.assertTrue(all("24h" in label for label in NOT_APPLICABLE_CANDIDATES))


if __name__ == "__main__":
    unittest.main()
