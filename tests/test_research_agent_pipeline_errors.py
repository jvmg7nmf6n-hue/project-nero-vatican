from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from nero_core.research_agent.hypothesis_gen import GenerationRunResult
from nero_core.research_agent.pipeline import (
    STATUS_CLEAN,
    STATUS_ERROR,
    default_candles_provider,
    main,
    run_pipeline,
)
from nero_core.research_agent.scanner import ScanResult

EMPTY_SCAN = ScanResult([], [], [], [], [])


class ScanErrorsSurfaceTest(unittest.TestCase):
    """TIER 2: ScanResult.scan_errors already populates correctly at the
    scanner layer -- this proves run_pipeline actually reads it now, instead
    of silently discarding it as before."""

    def test_scan_error_surfaces_in_pipeline_result_and_sets_status_error(self) -> None:
        scan_with_error = ScanResult(
            [], [], [], [], [{"source": "docs/site_data/quant_metrics.json", "message": "missing or unparseable"}]
        )
        with patch("nero_core.research_agent.pipeline.is_enabled", return_value=True), \
             patch("nero_core.research_agent.pipeline.scanner.run_scan", return_value=scan_with_error), \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.load_existing_hypotheses", return_value=[]), \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.generate_web_hypotheses", return_value=GenerationRunResult()), \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.persist_hypotheses"), \
             patch("nero_core.research_agent.pipeline.auto_tester.persist_test_results"), \
             patch("nero_core.research_agent.pipeline.performance.record_run"):
            result = run_pipeline(api_key="fake-key")

        self.assertEqual(result.status, STATUS_ERROR)
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(result.errors[0]["phase"], "scan")
        self.assertEqual(result.errors[0]["context"], "docs/site_data/quant_metrics.json")
        self.assertEqual(result.errors[0]["message"], "missing or unparseable")

    def test_no_scan_errors_and_no_generation_errors_yields_status_clean(self) -> None:
        with patch("nero_core.research_agent.pipeline.is_enabled", return_value=True), \
             patch("nero_core.research_agent.pipeline.scanner.run_scan", return_value=EMPTY_SCAN), \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.load_existing_hypotheses", return_value=[]), \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.generate_web_hypotheses", return_value=GenerationRunResult()), \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.persist_hypotheses"), \
             patch("nero_core.research_agent.pipeline.auto_tester.persist_test_results"), \
             patch("nero_core.research_agent.pipeline.performance.record_run"):
            result = run_pipeline(api_key="fake-key")

        self.assertEqual(result.status, STATUS_CLEAN)
        self.assertEqual(result.errors, [])


class HypothesisGenErrorsSurfaceTest(unittest.TestCase):
    """GenerationRunResult.errors (API failures, preflight 401s, parse
    failures) already populates correctly at the hypothesis_gen layer --
    proves run_pipeline reads it now instead of discarding it."""

    def test_api_failure_surfaces_in_pipeline_result_and_sets_status_error(self) -> None:
        generation_with_error = GenerationRunResult(
            hypotheses=[], duplicates_skipped=[], llm_calls_made=1, total_cost_usd=0.0, cost_limit_hit=False,
            errors=[{"scan_finding": "(preflight key validation)", "message": "ApiKeyRejectedError: 401 Unauthorized"}],
        )
        with patch("nero_core.research_agent.pipeline.is_enabled", return_value=True), \
             patch("nero_core.research_agent.pipeline.scanner.run_scan", return_value=EMPTY_SCAN), \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.load_existing_hypotheses", return_value=[]), \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.generate_hypotheses", return_value=generation_with_error), \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.generate_web_hypotheses", return_value=GenerationRunResult()), \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.persist_hypotheses"), \
             patch("nero_core.research_agent.pipeline.auto_tester.persist_test_results"), \
             patch("nero_core.research_agent.pipeline.performance.record_run"):
            result = run_pipeline(api_key="fake-key")

        self.assertEqual(result.status, STATUS_ERROR)
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(result.errors[0]["phase"], "hypothesis_gen")
        self.assertEqual(result.errors[0]["context"], "(preflight key validation)")
        self.assertIn("401", result.errors[0]["message"])
        # llm_calls_made=1, total_cost=0.0, hypotheses=0 -- the exact real-run
        # symptom this whole diagnostics effort started from -- but now paired
        # with a visible, non-empty errors list instead of printing identically
        # to a genuinely uneventful run.
        self.assertEqual(result.llm_calls_made, 1)
        self.assertEqual(result.hypotheses_generated, 0)

    def test_parse_failure_surfaces_in_pipeline_result_and_sets_status_error(self) -> None:
        generation_with_error = GenerationRunResult(
            hypotheses=[], duplicates_skipped=[], llm_calls_made=1, total_cost_usd=0.0, cost_limit_hit=False,
            errors=[{"scan_finding": "BTC/1h extreme z-score", "message": "JSONDecodeError: Expecting value: line 1 column 1"}],
        )
        with patch("nero_core.research_agent.pipeline.is_enabled", return_value=True), \
             patch("nero_core.research_agent.pipeline.scanner.run_scan", return_value=EMPTY_SCAN), \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.load_existing_hypotheses", return_value=[]), \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.generate_hypotheses", return_value=generation_with_error), \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.generate_web_hypotheses", return_value=GenerationRunResult()), \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.persist_hypotheses"), \
             patch("nero_core.research_agent.pipeline.auto_tester.persist_test_results"), \
             patch("nero_core.research_agent.pipeline.performance.record_run"):
            result = run_pipeline(api_key="fake-key")

        self.assertEqual(result.status, STATUS_ERROR)
        self.assertEqual(result.errors[0]["phase"], "hypothesis_gen")
        self.assertIn("JSONDecodeError", result.errors[0]["message"])


class MainPrintsErrorsProminentlyTest(unittest.TestCase):
    """Errors must print as prominently as the existing summary lines, and
    the key value must never appear -- confirmed here, not just at the
    secret_handling AST-check layer, since this exercises the ACTUAL printed
    text for a real error scenario."""

    def test_main_prints_an_errors_section_when_status_is_error(self) -> None:
        generation_with_error = GenerationRunResult(
            hypotheses=[], duplicates_skipped=[], llm_calls_made=1, total_cost_usd=0.0, cost_limit_hit=False,
            errors=[{"scan_finding": "(preflight key validation)", "message": "ApiKeyRejectedError: 401 Unauthorized"}],
        )
        secret_key = "sk-ant-TESTSECRET-do-not-leak"
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": secret_key}), \
             patch("nero_core.research_agent.pipeline.is_enabled", return_value=True), \
             patch("nero_core.research_agent.pipeline.scanner.run_scan", return_value=EMPTY_SCAN), \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.load_existing_hypotheses", return_value=[]), \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.generate_hypotheses", return_value=generation_with_error), \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.generate_web_hypotheses", return_value=GenerationRunResult()), \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.persist_hypotheses"), \
             patch("nero_core.research_agent.pipeline.auto_tester.persist_test_results"), \
             patch("nero_core.research_agent.pipeline.performance.record_run"):
            out = io.StringIO()
            with redirect_stdout(out):
                main()

        printed = out.getvalue()
        self.assertIn("status=error", printed)
        self.assertIn("=== ERRORS (1) ===", printed)
        self.assertIn("[hypothesis_gen] (preflight key validation): ApiKeyRejectedError: 401 Unauthorized", printed)
        self.assertNotIn(secret_key, printed)
        self.assertNotIn("errors=none", printed)

    def test_main_prints_errors_none_and_status_clean_for_an_uneventful_run(self) -> None:
        # This test does not patch os.environ, so ANTHROPIC_API_KEY (if set in
        # the real shell environment) would otherwise flow into a REAL
        # generate_web_hypotheses call -- mocked explicitly here for the same
        # reason as every other test in this class/file.
        with patch("nero_core.research_agent.pipeline.is_enabled", return_value=True), \
             patch("nero_core.research_agent.pipeline.scanner.run_scan", return_value=EMPTY_SCAN), \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.load_existing_hypotheses", return_value=[]), \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.generate_web_hypotheses", return_value=GenerationRunResult()), \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.persist_hypotheses"), \
             patch("nero_core.research_agent.pipeline.auto_tester.persist_test_results"), \
             patch("nero_core.research_agent.pipeline.performance.record_run"):
            out = io.StringIO()
            with redirect_stdout(out):
                main()

        printed = out.getvalue()
        self.assertIn("status=clean", printed)
        self.assertIn("errors=none", printed)
        self.assertNotIn("=== ERRORS", printed)


class WebSearchChannelMergeTest(unittest.TestCase):
    """Proves the scanner and web-search channels' hypotheses are actually
    MERGED into one list and driven through the SAME per-hypothesis loop
    (candles_provider -> auto_tester.test_hypothesis) -- not two separate
    loops with different logic. This is pipeline.py's own half of the "no
    special treatment" guarantee; the gate/harness-level half is proven
    directly in test_research_agent_web_hypothesis_gen.py's
    NoSpecialTreatmentTest."""

    def test_both_channels_hypotheses_reach_auto_tester_and_counts_add_up(self) -> None:
        scanner_hyp = {
            "hypothesis_name": "SCANNER_ONE", "asset": "BTC", "timeframe": "1h",
            "generated_at": "2026-07-31T00:00:00+00:00",
            "structured_entry_rule": {"conditions": [{"field": "ret_1", "op": "gt", "value": -1.0}]},
            "structured_exit_plan": {"stop_atr_multiple": 1.5, "target_r_multiple": 2.0, "max_holding_hours": 24.0},
        }
        web_hyp = {
            "hypothesis_name": "WEB_ONE", "asset": "EUR/USD", "timeframe": "4h",
            "generated_at": "2026-07-31T00:00:00+00:00",
            "structured_entry_rule": {"conditions": [{"field": "ret_1", "op": "gt", "value": -1.0}]},
            "structured_exit_plan": {"stop_atr_multiple": 1.5, "target_r_multiple": 2.0, "max_holding_hours": 24.0},
            "discovery_channel": "web_search", "source_tier": "unknown_unverifiable",
        }
        scanner_generation = GenerationRunResult(hypotheses=[scanner_hyp], llm_calls_made=1, total_cost_usd=0.02)
        web_generation = GenerationRunResult(hypotheses=[web_hyp], llm_calls_made=1, total_cost_usd=0.05)

        seen_pairs = []

        def _candles_provider(asset, timeframe):
            seen_pairs.append((asset, timeframe))
            return None  # no_candles_available -- fine, this test is about REACHING the loop, not the verdict

        with patch("nero_core.research_agent.pipeline.is_enabled", return_value=True), \
             patch("nero_core.research_agent.pipeline.scanner.run_scan", return_value=EMPTY_SCAN), \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.load_existing_hypotheses", return_value=[]), \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.generate_hypotheses", return_value=scanner_generation), \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.generate_web_hypotheses", return_value=web_generation), \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.persist_hypotheses"), \
             patch("nero_core.research_agent.pipeline.auto_tester.persist_test_results"), \
             patch("nero_core.research_agent.pipeline.performance.record_run"):
            result = run_pipeline(api_key="fake-key", candles_provider=_candles_provider)

        # Both hypotheses' (asset, timeframe) actually reached the SAME
        # candles_provider callback -- proof the merge happened, not just two
        # separate result objects nothing ever combined.
        self.assertEqual(set(seen_pairs), {("BTC", "1h"), ("EUR/USD", "4h")})
        self.assertEqual(result.hypotheses_generated, 2)
        self.assertEqual(result.web_hypotheses_generated, 1)
        self.assertEqual(result.no_candles_available, 2)
        self.assertEqual(result.llm_calls_made, 2)
        self.assertEqual(result.web_llm_calls_made, 1)
        self.assertAlmostEqual(result.total_llm_cost_usd, 0.07, places=8)
        self.assertAlmostEqual(result.web_total_llm_cost_usd, 0.05, places=8)


class RealDefaultCandlesProviderRefusalTest(unittest.TestCase):
    """End-to-end (not just a unit check on default_candles_provider in
    isolation): a real pipeline run using the REAL default_candles_provider
    -- not a test double -- must refuse a hypothesis outside
    APPROVED_RESEARCH_UNIVERSE rather than silently scoring it against the
    200-row site export. Mirrors nero_core.eve's own
    ScoringRunCannotConsumeSiteExportTest exactly."""

    def test_gold_hypothesis_is_refused_not_scored_against_the_site_export(self) -> None:
        gold_hyp = {
            "hypothesis_name": "GOLD_ONE", "asset": "GOLD", "timeframe": "4h",
            "generated_at": "2026-07-31T00:00:00+00:00",
            "structured_entry_rule": {"conditions": [{"field": "ret_1", "op": "gt", "value": -1.0}]},
            "structured_exit_plan": {"stop_atr_multiple": 1.5, "target_r_multiple": 2.0, "max_holding_hours": 24.0},
        }
        generation = GenerationRunResult(hypotheses=[gold_hyp], llm_calls_made=1, total_cost_usd=0.02)

        with patch("nero_core.research_agent.pipeline.is_enabled", return_value=True), \
             patch("nero_core.research_agent.pipeline.scanner.run_scan", return_value=EMPTY_SCAN), \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.load_existing_hypotheses", return_value=[]), \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.generate_hypotheses", return_value=generation), \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.generate_web_hypotheses", return_value=GenerationRunResult()), \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.persist_hypotheses"), \
             patch("nero_core.research_agent.pipeline.auto_tester.persist_test_results"), \
             patch("nero_core.research_agent.pipeline.performance.record_run"):
            # deliberately NOT passing candles_provider -- exercises the REAL
            # default_candles_provider, same as a real run would.
            result = run_pipeline(api_key="fake-key")

        self.assertEqual(result.data_source_refused, 1)
        self.assertEqual(result.no_candles_available, 0)
        self.assertEqual(len(result.test_results), 0)


if __name__ == "__main__":
    unittest.main()
