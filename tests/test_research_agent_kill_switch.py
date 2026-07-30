from __future__ import annotations

import unittest
from unittest.mock import patch

from nero_core.research_agent.config import is_enabled
from nero_core.research_agent.pipeline import run_pipeline
from nero_core.research_agent.scanner import ScanResult


class IsEnabledTest(unittest.TestCase):
    def test_defaults_to_false_when_unset(self) -> None:
        self.assertFalse(is_enabled(env={}))

    def test_false_for_various_falsy_strings(self) -> None:
        for value in ("", "0", "false", "no", "off", "disabled", "garbage"):
            self.assertFalse(is_enabled(env={"RESEARCH_AGENT_ENABLED": value}), f"expected False for {value!r}")

    def test_true_for_various_truthy_strings_case_insensitive(self) -> None:
        for value in ("1", "true", "True", "TRUE", "yes", "YES", "on", "On"):
            self.assertTrue(is_enabled(env={"RESEARCH_AGENT_ENABLED": value}), f"expected True for {value!r}")


class KillSwitchHardTest(unittest.TestCase):
    """HARD TEST: with the flag disabled, NOTHING in the pipeline may run --
    no scan, no LLM call, no candle fetch, no file write."""

    def test_disabled_pipeline_calls_nothing_and_returns_immediately(self) -> None:
        with patch("nero_core.research_agent.pipeline.is_enabled", return_value=False), \
             patch("nero_core.research_agent.pipeline.scanner.run_scan") as mock_scan, \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.generate_hypotheses") as mock_generate, \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.persist_hypotheses") as mock_persist_hyp, \
             patch("nero_core.research_agent.pipeline.auto_tester.test_hypothesis") as mock_test, \
             patch("nero_core.research_agent.pipeline.auto_tester.persist_test_results") as mock_persist_results:
            result = run_pipeline(api_key="fake-key")

        self.assertFalse(result.enabled)
        self.assertIn("RESEARCH_AGENT_ENABLED", result.reason)
        mock_scan.assert_not_called()
        mock_generate.assert_not_called()
        mock_persist_hyp.assert_not_called()
        mock_test.assert_not_called()
        mock_persist_results.assert_not_called()

    def test_disabled_pipeline_never_touches_the_candles_provider(self) -> None:
        provider_calls = []

        def _spy_provider(asset: str, timeframe: str):
            provider_calls.append((asset, timeframe))
            return None

        with patch("nero_core.research_agent.pipeline.is_enabled", return_value=False):
            run_pipeline(candles_provider=_spy_provider)

        self.assertEqual(provider_calls, [])

    def test_enabled_pipeline_does_proceed_to_scan(self) -> None:
        # generate_web_hypotheses (the web-search discovery channel, added
        # alongside the scanner path) is NOT findings-gated the way
        # generate_hypotheses is -- it must be mocked explicitly here, or an
        # unmocked call with this test's non-empty "fake-key" would attempt a
        # REAL network request to the Claude API from inside the test suite.
        from nero_core.research_agent.hypothesis_gen import GenerationRunResult

        empty_scan = ScanResult([], [], [], [], [])
        with patch("nero_core.research_agent.pipeline.is_enabled", return_value=True), \
             patch("nero_core.research_agent.pipeline.scanner.run_scan", return_value=empty_scan) as mock_scan, \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.load_existing_hypotheses", return_value=[]), \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.generate_web_hypotheses", return_value=GenerationRunResult()) as mock_web_generate, \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.persist_hypotheses") as mock_persist_hyp, \
             patch("nero_core.research_agent.pipeline.auto_tester.persist_test_results") as mock_persist_results, \
             patch("nero_core.research_agent.pipeline.performance.record_run") as mock_record_run:
            result = run_pipeline(api_key="fake-key")

        mock_scan.assert_called_once()
        mock_web_generate.assert_called_once()
        self.assertTrue(result.enabled)
        # no findings -> no hypotheses (either channel) -> persist called once
        # per channel, both times with an empty list (harmless no-ops)
        self.assertEqual(mock_persist_hyp.call_count, 2)
        mock_persist_hyp.assert_any_call([])
        mock_persist_results.assert_called_once_with([])
        mock_record_run.assert_called_once()

    def test_disabled_pipeline_never_records_performance(self) -> None:
        # Task 5's own spec is "nothing runs when disabled" -- even a telemetry
        # write is an action, so performance.record_run must never be reached.
        with patch("nero_core.research_agent.pipeline.is_enabled", return_value=False), \
             patch("nero_core.research_agent.pipeline.performance.record_run") as mock_record_run:
            run_pipeline()

        mock_record_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
