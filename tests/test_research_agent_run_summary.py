from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.research_agent_run_summary import append_run_summary, build_summary, compute_summary_data


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

    def test_by_channel_breakdown_splits_scanner_from_web_search(self) -> None:
        run_entry = {
            "hypotheses_generated": 2, "duplicates_skipped": 0, "llm_calls_made": 5,
            "total_llm_cost_usd": 0.08, "cost_limit_hit": True,
            "too_slow_rejected": 0, "unmeasurable_rejected": 0,
            "survived": 0, "promising_watchlist": 0, "died": 0, "untestable": 0,
            "no_candles_available": 0,
            "web_hypotheses_generated": 0, "web_llm_calls_made": 3,
            "web_total_llm_cost_usd": 0.05, "web_cost_limit_hit": True,
        }
        out = build_summary([], [], run_entry)
        self.assertIn(
            "by channel: scanner hypotheses=2 calls=2 cost=$0.030000 | "
            "web_search hypotheses=0 calls=3 cost=$0.050000 cost_limit_hit=True",
            out,
        )
        self.assertIn("NOTE: web_search made 3 call(s) this run but produced zero hypotheses", out)

    def test_by_channel_breakdown_defaults_to_zero_web_activity_on_pre_web_channel_run_entries(self) -> None:
        # Run entries recorded before the web-search channel existed have no
        # web_* keys at all -- .get(..., 0) must read that as zero web
        # activity (the honest historical fact), not crash or fabricate.
        run_entry = {
            "hypotheses_generated": 5, "duplicates_skipped": 0, "llm_calls_made": 5,
            "total_llm_cost_usd": 0.10, "cost_limit_hit": False,
            "too_slow_rejected": 0, "unmeasurable_rejected": 0,
            "survived": 0, "promising_watchlist": 0, "died": 0, "untestable": 0,
            "no_candles_available": 0,
        }
        out = build_summary([], [], run_entry)
        self.assertIn(
            "by channel: scanner hypotheses=5 calls=5 cost=$0.100000 | "
            "web_search hypotheses=0 calls=0 cost=$0.000000 cost_limit_hit=False",
            out,
        )
        self.assertNotIn("NOTE: web_search made", out)

    def test_per_hypothesis_line_shows_discovery_channel(self) -> None:
        hypotheses = [{"hypothesis_name": "H1", "asset": "BTC", "timeframe": "1h",
                       "expected_frequency_claim": 40.0, "discovery_channel": "web_search"}]
        test_results = [{
            "hypothesis_name": "H1", "asset": "BTC", "timeframe": "1h",
            "verdict": "DIED", "frequency_classification": "VIABLE",
            "measured_trades_per_year": 25.0, "expected_time_to_30_trades_months": 14.4,
        }]
        out = build_summary(hypotheses, test_results, None)
        self.assertIn("[H1] asset=BTC timeframe=1h channel=web_search", out)

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


class ComputeSummaryDataTest(unittest.TestCase):
    """compute_summary_data is the single source of truth build_summary
    formats and append_run_summary persists -- direct coverage of the
    structured facts, independent of build_summary's own text formatting."""

    def test_calibration_ratio_and_direction_match_the_overestimate_flag_case(self) -> None:
        hypotheses = [
            {"hypothesis_name": "A", "asset": "BTC", "timeframe": "1h", "expected_frequency_claim": 60.0},
            {"hypothesis_name": "B", "asset": "ETH", "timeframe": "1h", "expected_frequency_claim": 90.0},
        ]
        test_results = [
            {"hypothesis_name": "A", "asset": "BTC", "timeframe": "1h", "verdict": "DIED", "frequency_classification": "VIABLE", "measured_trades_per_year": 20.0, "expected_time_to_30_trades_months": 18.0},
            {"hypothesis_name": "B", "asset": "ETH", "timeframe": "1h", "verdict": "DIED", "frequency_classification": "VIABLE", "measured_trades_per_year": 30.0, "expected_time_to_30_trades_months": 12.0},
        ]
        data = compute_summary_data(hypotheses, test_results, None)
        self.assertEqual(data["calibration"]["n"], 2)
        self.assertEqual(data["calibration"]["direction"], "overestimate")
        self.assertAlmostEqual(data["calibration"]["average_ratio"], (3.0 + 3.0) / 2)
        self.assertEqual(data["calibration"]["ratio_by_hypothesis_name"]["A"], 3.0)
        self.assertEqual(data["calibration"]["ratio_by_hypothesis_name"]["B"], 3.0)

    def test_zero_measured_frequency_recorded_as_infinite_overestimate_not_a_crash(self) -> None:
        hypotheses = [{"hypothesis_name": "D", "asset": "BTC", "timeframe": "1h", "expected_frequency_claim": 15.0}]
        test_results = [{"hypothesis_name": "D", "asset": "BTC", "timeframe": "1h", "verdict": "SKIPPED", "frequency_classification": "TOO_SLOW", "measured_trades_per_year": 0.0, "expected_time_to_30_trades_months": None}]
        data = compute_summary_data(hypotheses, test_results, None)
        self.assertEqual(data["calibration"], None)
        self.assertEqual(data["too_slow"][0]["measured_trades_per_year"], 0.0)

    def test_no_calibration_data_when_nothing_has_both_claim_and_measurement(self) -> None:
        data = compute_summary_data([], [], None)
        self.assertIsNone(data["calibration"])

    def test_run_aggregate_none_when_no_run_entry(self) -> None:
        data = compute_summary_data([], [], None)
        self.assertIsNone(data["run_aggregate"])

    def test_run_aggregate_present_and_by_channel_split_computed(self) -> None:
        run_entry = {
            "hypotheses_generated": 2, "duplicates_skipped": 0, "llm_calls_made": 5,
            "total_llm_cost_usd": 0.08, "cost_limit_hit": True,
            "too_slow_rejected": 0, "unmeasurable_rejected": 0,
            "survived": 0, "promising_watchlist": 0, "died": 0, "untestable": 0, "no_candles_available": 0,
            "web_hypotheses_generated": 0, "web_llm_calls_made": 3, "web_total_llm_cost_usd": 0.05, "web_cost_limit_hit": True,
        }
        data = compute_summary_data([], [], run_entry)
        self.assertEqual(data["run_aggregate"]["by_channel"]["scanner"]["calls"], 2)
        self.assertEqual(data["run_aggregate"]["by_channel"]["web_search"]["calls"], 3)
        self.assertTrue(data["run_aggregate"]["web_search_zero_hypotheses_note"])

    def test_output_is_json_serializable(self) -> None:
        # append_run_summary writes this straight to JSON -- must never
        # contain a non-serializable value (e.g. a NaN float from a bad
        # division, or a set instead of a list).
        hypotheses = [{"hypothesis_name": "A", "asset": "BTC", "timeframe": "1h", "expected_frequency_claim": 40.0}]
        test_results = [{"hypothesis_name": "A", "asset": "BTC", "timeframe": "1h", "verdict": "DIED", "frequency_classification": "VIABLE", "measured_trades_per_year": 25.0, "expected_time_to_30_trades_months": 14.4}]
        data = compute_summary_data(hypotheses, test_results, None)
        json.dumps(data)  # must not raise


class AppendRunSummaryTest(unittest.TestCase):
    """CC-1 review, item 2b: persist every real run's summary to an
    append-only committed file, so this never depends on a transcript
    again."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.path = Path(self._tmpdir.name) / "agent_run_summaries.json"

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_creates_the_file_with_one_entry(self) -> None:
        data = compute_summary_data([], [], None)
        append_run_summary(data, run_at="2026-08-03T12:00:00+00:00", source="research_agent_run_summary.py", path=self.path)
        on_disk = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(len(on_disk), 1)
        self.assertEqual(on_disk[0]["run_at"], "2026-08-03T12:00:00+00:00")
        self.assertEqual(on_disk[0]["source"], "research_agent_run_summary.py")

    def test_append_only_preserves_prior_entries(self) -> None:
        data = compute_summary_data([], [], None)
        append_run_summary(data, run_at="2026-08-01T00:00:00+00:00", source="research_agent_run_summary.py", path=self.path)
        append_run_summary(data, run_at="2026-08-02T00:00:00+00:00", source="research_agent_run_summary.py", path=self.path)
        on_disk = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(len(on_disk), 2)
        self.assertEqual([e["run_at"] for e in on_disk], ["2026-08-01T00:00:00+00:00", "2026-08-02T00:00:00+00:00"])

    def test_backfilled_source_tag_is_distinct_from_a_real_run(self) -> None:
        # CC-1 review, item 2c: a reconstructed/backfilled entry must never
        # be indistinguishable from a real script-produced one.
        data = compute_summary_data([], [], None)
        append_run_summary(data, run_at="2026-08-03T00:00:00+00:00", source="backfilled-from-chat-transcript-not-independently-verified", path=self.path)
        on_disk = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertNotEqual(on_disk[0]["source"], "research_agent_run_summary.py")

    def test_creates_parent_directory_if_missing(self) -> None:
        nested_path = Path(self._tmpdir.name) / "nested" / "dir" / "agent_run_summaries.json"
        data = compute_summary_data([], [], None)
        append_run_summary(data, run_at="2026-08-03T00:00:00+00:00", source="research_agent_run_summary.py", path=nested_path)
        self.assertTrue(nested_path.exists())

    def test_no_leftover_tmp_file_after_write(self) -> None:
        data = compute_summary_data([], [], None)
        append_run_summary(data, run_at="2026-08-03T00:00:00+00:00", source="research_agent_run_summary.py", path=self.path)
        self.assertFalse((self.path.parent / (self.path.name + ".tmp")).exists())


if __name__ == "__main__":
    unittest.main()
