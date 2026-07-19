from __future__ import annotations

import unittest

from tools.range_mean_reversion_grid_shift import (
    GRID_SHIFT_QUALIFYING_CONFIGS,
    NEAR_MISS_CONFIGS,
    is_grid_shift_applicable,
    verify_no_grid_shift_needed,
)


class QualifyingListTest(unittest.TestCase):
    def test_qualifying_list_is_empty_per_task_2_results(self) -> None:
        self.assertEqual(GRID_SHIFT_QUALIFYING_CONFIGS, [])


class ResampleApplicabilityTest(unittest.TestCase):
    def test_forex_is_never_resampled(self) -> None:
        for tf in ("1h", "4h", "1day"):
            self.assertFalse(is_grid_shift_applicable("forex", tf))

    def test_gold_is_never_resampled(self) -> None:
        for tf in ("4h", "1day", "1week"):
            self.assertFalse(is_grid_shift_applicable("GOLD", tf))

    def test_silver_4h_is_the_one_resampled_timeframe(self) -> None:
        self.assertTrue(is_grid_shift_applicable("SILVER", "4h"))
        self.assertFalse(is_grid_shift_applicable("SILVER", "1day"))
        self.assertFalse(is_grid_shift_applicable("SILVER", "1week"))

    def test_crypto_is_never_resampled(self) -> None:
        for tf in ("4h", "12h", "1day"):
            self.assertFalse(is_grid_shift_applicable("crypto", tf))

    def test_unaudited_combination_raises(self) -> None:
        with self.assertRaises(KeyError):
            is_grid_shift_applicable("forex", "1week")


class VerifyNoGridShiftNeededTest(unittest.TestCase):
    def test_report_explains_both_near_misses(self) -> None:
        report = verify_no_grid_shift_needed()
        self.assertIn("GOLD / 1week", report)
        self.assertIn("SILVER / 1week", report)
        self.assertIn("LOW SAMPLE", report)
        self.assertIn("no config in RANGE_MEAN_REVERSION Task 2 reaches SURVIVED", report)

    def test_near_miss_configs_match_the_documented_sample_sizes(self) -> None:
        gold = next(c for c in NEAR_MISS_CONFIGS if c["label"] == "GOLD / 1week")
        self.assertEqual(gold["test_trades"], 11)
        silver = next(c for c in NEAR_MISS_CONFIGS if c["label"] == "SILVER / 1week")
        self.assertEqual(silver["test_trades"], 15)


if __name__ == "__main__":
    unittest.main()
