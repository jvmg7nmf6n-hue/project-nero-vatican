from __future__ import annotations

import unittest

from tools.research_agent_run_summary import build_summary


class BuildSummaryTest(unittest.TestCase):
    def test_reports_aggregate_counts_from_run_entry(self) -> None:
        run_entry = {
            "hypotheses_generated": 2, "duplicates_skipped": 1, "llm_calls_made": 2,
            "total_llm_cost_usd": 0.0123, "cost_limit_hit": False,
            "too_slow_rejected": 1, "unmeasurable_rejected": 0,
            "survived": 0, "promising_watchlist": 1, "died": 0, "untestable": 0,
            "no_candles_available": 0,
        }
        out = build_summary([], [], run_entry)
        self.assertIn("hypotheses_generated=2 duplicates_skipped=1", out)
        self.assertIn("total_llm_cost_usd=$0.012300", out)
        self.assertIn("too_slow_rejected=1 unmeasurable_rejected=0", out)

    def test_missing_run_entry_reports_unavailable_instead_of_crashing(self) -> None:
        out = build_summary([], [], None)
        self.assertIn("aggregate counts unavailable", out)

    def test_per_hypothesis_line_joins_claim_from_hypotheses_with_measured_from_test_results(self) -> None:
        hypotheses = [{"hypothesis_name": "H1", "asset": "BTC", "timeframe": "1h", "expected_frequency_claim": 40.0}]
        test_results = [{
            "hypothesis_name": "H1", "asset": "BTC", "timeframe": "1h",
            "verdict": "PROMISING-WATCHLIST", "frequency_classification": "VIABLE",
            "measured_trades_per_year": 25.0, "expected_time_to_30_trades_months": 14.4,
        }]
        out = build_summary(hypotheses, test_results, None)
        self.assertIn("[H1] asset=BTC timeframe=1h", out)
        self.assertIn("LLM claim=40.0 trades/yr", out)
        self.assertIn("measured=25.0 trades/yr", out)
        self.assertIn("classification=VIABLE", out)
        self.assertIn("verdict=PROMISING-WATCHLIST", out)

    def test_too_slow_section_lists_measured_value_and_llm_claim(self) -> None:
        hypotheses = [{"hypothesis_name": "H2", "asset": "ETH", "timeframe": "4h", "expected_frequency_claim": 50.0}]
        test_results = [{
            "hypothesis_name": "H2", "asset": "ETH", "timeframe": "4h",
            "verdict": "SKIPPED", "frequency_classification": "TOO_SLOW",
            "measured_trades_per_year": 3.0, "expected_time_to_30_trades_months": 120.0,
        }]
        out = build_summary(hypotheses, test_results, None)
        self.assertIn("--- TOO_SLOW rejections (1)", out)
        self.assertIn("[H2] measured=3.0 trades/yr (LLM claimed 50.0 trades/yr)", out)

    def test_unmeasurable_section_lists_reason(self) -> None:
        hypotheses = [{"hypothesis_name": "H3", "asset": "GOLD", "timeframe": "1d", "expected_frequency_claim": None}]
        test_results = [{
            "hypothesis_name": "H3", "asset": "GOLD", "timeframe": "1d",
            "verdict": "SKIPPED", "frequency_classification": "UNMEASURABLE",
            "measured_trades_per_year": None, "expected_time_to_30_trades_months": None,
            "reason": "fewer than 2 closed-candle years of history",
        }]
        out = build_summary(hypotheses, test_results, None)
        self.assertIn("--- UNMEASURABLE (1) ---", out)
        self.assertIn("[H3] reason=fewer than 2 closed-candle years of history", out)

    def test_generated_but_untested_hypothesis_listed_separately_from_no_candles(self) -> None:
        hypotheses = [{"hypothesis_name": "H4", "asset": "BTC", "timeframe": "1w", "expected_frequency_claim": 10.0}]
        out = build_summary(hypotheses, [], None)
        self.assertIn("--- Generated but never reached the tester (no_candles_available) ---", out)
        self.assertIn("[H4] asset=BTC timeframe=1w", out)

    def test_overestimate_flag_fires_when_llm_claims_exceed_measured_by_1_5x_or_more(self) -> None:
        hypotheses = [
            {"hypothesis_name": "A", "asset": "BTC", "timeframe": "1h", "expected_frequency_claim": 60.0},
            {"hypothesis_name": "B", "asset": "ETH", "timeframe": "1h", "expected_frequency_claim": 90.0},
        ]
        test_results = [
            {"hypothesis_name": "A", "asset": "BTC", "timeframe": "1h", "verdict": "DIED",
             "frequency_classification": "VIABLE", "measured_trades_per_year": 20.0,
             "expected_time_to_30_trades_months": 18.0},
            {"hypothesis_name": "B", "asset": "ETH", "timeframe": "1h", "verdict": "DIED",
             "frequency_classification": "VIABLE", "measured_trades_per_year": 30.0,
             "expected_time_to_30_trades_months": 12.0},
        ]
        out = build_summary(hypotheses, test_results, None)
        self.assertIn("FLAG: the LLM systematically OVERESTIMATES", out)

    def test_no_flag_when_roughly_calibrated(self) -> None:
        hypotheses = [{"hypothesis_name": "C", "asset": "BTC", "timeframe": "1h", "expected_frequency_claim": 22.0}]
        test_results = [{
            "hypothesis_name": "C", "asset": "BTC", "timeframe": "1h", "verdict": "DIED",
            "frequency_classification": "VIABLE", "measured_trades_per_year": 20.0,
            "expected_time_to_30_trades_months": 18.0,
        }]
        out = build_summary(hypotheses, test_results, None)
        self.assertIn("Roughly calibrated on this run", out)
        self.assertNotIn("FLAG", out)

    def test_zero_measured_frequency_excluded_from_average_but_reported(self) -> None:
        hypotheses = [{"hypothesis_name": "D", "asset": "BTC", "timeframe": "1h", "expected_frequency_claim": 15.0}]
        test_results = [{
            "hypothesis_name": "D", "asset": "BTC", "timeframe": "1h", "verdict": "SKIPPED",
            "frequency_classification": "TOO_SLOW", "measured_trades_per_year": 0.0,
            "expected_time_to_30_trades_months": None,
        }]
        out = build_summary(hypotheses, test_results, None)
        self.assertIn("measured=0 trades/yr, LLM claimed 15.0 -- infinite overestimate", out)
        self.assertIn("(no hypothesis had both a measurable frequency and an LLM claim to compare)", out)


if __name__ == "__main__":
    unittest.main()
