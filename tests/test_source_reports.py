from __future__ import annotations

import os
import unittest

from nero_core.execution.source_reports import (
    DEFAULT_SOURCE_REPORT,
    SOURCE_REPORTS,
    source_report_for,
)


class SourceReportForTest(unittest.TestCase):
    def test_known_gold_breakout_momentum_report(self) -> None:
        self.assertEqual(
            source_report_for("BREAKOUT_MOMENTUM", "breakout-momentum-v1.2.0-gold-calibrated-1week", "GOLD"),
            "docs/statistical_harness_upgrade.md",
        )

    def test_known_pead_report(self) -> None:
        self.assertEqual(
            source_report_for("PEAD", "pead-v1.0.0-surprise3pct-hold10", "AAPL"),
            "docs/pead_results.md",
        )

    def test_unmapped_config_falls_back_to_default(self) -> None:
        self.assertEqual(source_report_for("SOME_NEW_STRATEGY", "some-version", "XYZ"), DEFAULT_SOURCE_REPORT)

    def test_unmapped_version_of_a_known_strategy_falls_back_to_default(self) -> None:
        self.assertEqual(
            source_report_for("RANGE_MEAN_REVERSION", "range-mean-reversion-v9.9.9-made-up", "BTC"),
            DEFAULT_SOURCE_REPORT,
        )

    def test_long_only_and_confirmation_do_not_collide_on_the_same_btc_report(self) -> None:
        long_only = source_report_for("RANGE_MEAN_REVERSION", "range-mean-reversion-v1.1.0-long-only", "BTC")
        confirmation = source_report_for("RANGE_MEAN_REVERSION", "range-mean-reversion-v1.3.0-confirmation", "BTC")
        self.assertEqual(long_only, "docs/rmr_variant_research_stage1.md")
        self.assertEqual(confirmation, "docs/rmr_variant_research_stage1.md")

    def test_configs_with_no_historical_backtest_map_to_none_not_a_fabricated_path(self) -> None:
        self.assertIsNone(source_report_for("NEWS_SENTIMENT", "news-sentiment-v1.0.0", "GOLD"))
        self.assertIsNone(source_report_for("ORDERFLOW_IMBALANCE", "orderflow-imbalance-v1.0.0", "BTC"))

    def test_every_mapped_source_report_path_exists_on_disk(self) -> None:
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        for key, path in SOURCE_REPORTS.items():
            if path is None:
                continue
            full_path = os.path.join(repo_root, path)
            self.assertTrue(os.path.exists(full_path), f"{key} -> {path} does not exist")


if __name__ == "__main__":
    unittest.main()
