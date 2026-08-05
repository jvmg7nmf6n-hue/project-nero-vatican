"""CC-1 Factory Loop directive, items 1+2: run_id + provenance fields.

Before this, Adam's hypothesis records (docs/site_data/agent_hypotheses.json)
carried no back-reference to the specific `run_pipeline()` invocation that
produced them -- Eve's own records have carried `session_id` since inception
(see nero_core.eve.hypothesis_shapes), but Adam's had nothing analogous
(docs/investigations/factory_loop_specification.md, B1). Without a run_id, a
Trial entry (item 4) sourced from Adam could never be traced back to which
run produced it.

This file proves: (1) run_pipeline mints exactly one UUID per call, stamped
identically on every hypothesis record that call produces across BOTH
channels (scanner + web search); (2) two separate run_pipeline() calls mint
two different run_ids; (3) every hypothesis record (Adam scanner-sourced,
Adam web-sourced, Eve) carries origin_agent and origin_chain, distinguishing
provenance from contamination_tags (which is reserved for similarity-to-a-
specific-prior-hypothesis, a different kind of fact -- see
nero_core.eve.scoring's own module docstring)."""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from nero_core.eve.hypothesis_shapes import build_hypothesis_record
from nero_core.research_agent.hypothesis_gen import GenerationRunResult, generate_hypotheses, generate_web_hypotheses
from nero_core.research_agent.pipeline import run_pipeline
from nero_core.research_agent.scanner import ScanFinding, ScanResult

NOW = datetime(2026, 8, 5, tzinfo=timezone.utc)


def _finding() -> ScanFinding:
    return ScanFinding("extreme_zscore", "BTC", "1h", "BTC/1h extreme z-score", 3.0, 42.0, "note", NOW.isoformat())


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def _claude_payload(data: dict) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(data)}], "usage": {"input_tokens": 100, "output_tokens": 100}}


VALID_HYPOTHESIS_DATA = {
    "hypothesis_name": "ZSCORE_REVERSION_BTC_1H",
    "mechanism": "Mean reversion after an extreme dislocation.",
    "entry_rule": "zscore20 < -2",
    "structured_entry_rule": {"conditions": [{"field": "zscore20", "op": "lt", "value": -2.0}]},
    "exit_rule": "zscore20 crosses back above 0",
    "stop_rule": "2x ATR",
    "asset": "BTC",
    "timeframe": "1h",
    "differs_from_graveyard": "n/a",
    "expected_frequency_claim": 80.0,
}


class ScannerChannelProvenanceTest(unittest.TestCase):
    def test_run_id_and_origin_agent_stamped_on_scanner_sourced_record(self) -> None:
        payload = _claude_payload(VALID_HYPOTHESIS_DATA)
        with patch("nero_core.research_agent.hypothesis_gen.requests.post", return_value=_FakeResponse(payload)):
            result = generate_hypotheses([_finding()], [], "fake-key", now=NOW, run_id="run-abc-123")

        self.assertEqual(len(result.hypotheses), 1)
        record = result.hypotheses[0]
        self.assertEqual(record["run_id"], "run-abc-123")
        self.assertEqual(record["origin_agent"], "adam")
        self.assertIsNone(record["origin_chain"])

    def test_run_id_defaults_to_none_when_caller_supplies_none(self) -> None:
        payload = _claude_payload(VALID_HYPOTHESIS_DATA)
        with patch("nero_core.research_agent.hypothesis_gen.requests.post", return_value=_FakeResponse(payload)):
            result = generate_hypotheses([_finding()], [], "fake-key", now=NOW)

        self.assertIsNone(result.hypotheses[0]["run_id"])


class WebChannelProvenanceTest(unittest.TestCase):
    def test_run_id_and_origin_agent_stamped_on_web_sourced_record(self) -> None:
        data = dict(
            VALID_HYPOTHESIS_DATA,
            source_url="https://example.com/article",
            source_description="an article",
            source_tier="tier_1_data_provider",
            paraphrase_confirmed=True,
        )
        payload = _claude_payload(data)
        with patch("nero_core.research_agent.hypothesis_gen.requests.post", return_value=_FakeResponse(payload)):
            result = generate_web_hypotheses(
                [], [], "fake-key", [("BTC", "4h")], max_calls_per_run=1, now=NOW, run_id="run-web-456",
            )

        self.assertEqual(len(result.hypotheses), 1)
        record = result.hypotheses[0]
        self.assertEqual(record["run_id"], "run-web-456")
        self.assertEqual(record["origin_agent"], "adam")
        self.assertIsNone(record["origin_chain"])


class EveProvenanceTest(unittest.TestCase):
    def test_origin_agent_is_eve_and_origin_chain_is_none(self) -> None:
        record = build_hypothesis_record({"hypothesis_name": "X"}, session_id="eve-session-1", turn_index=0, tool_use_id="tu_1", now=NOW)
        self.assertEqual(record["origin_agent"], "eve")
        self.assertIsNone(record["origin_chain"])


class PipelineRunIdTest(unittest.TestCase):
    """HARD TEST: one UUID per run_pipeline() call, identical across every
    hypothesis record that call produces (both channels), distinct across
    two separate calls."""

    def test_run_id_identical_across_both_channels_within_one_call(self) -> None:
        empty_scan = ScanResult([], [], [], [], [])
        with patch("nero_core.research_agent.pipeline.is_enabled", return_value=True), \
             patch("nero_core.research_agent.pipeline.scanner.run_scan", return_value=empty_scan), \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.load_existing_hypotheses", return_value=[]), \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.generate_hypotheses", return_value=GenerationRunResult()) as mock_scanner_gen, \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.generate_web_hypotheses", return_value=GenerationRunResult()) as mock_web_gen, \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.persist_hypotheses"), \
             patch("nero_core.research_agent.pipeline.auto_tester.persist_test_results"), \
             patch("nero_core.research_agent.pipeline.performance.record_run"):
            result = run_pipeline(api_key="fake-key", now=NOW)

        self.assertTrue(result.run_id)
        self.assertEqual(mock_scanner_gen.call_args.kwargs["run_id"], result.run_id)
        self.assertEqual(mock_web_gen.call_args.kwargs["run_id"], result.run_id)

    def test_two_separate_calls_mint_different_run_ids(self) -> None:
        empty_scan = ScanResult([], [], [], [], [])
        with patch("nero_core.research_agent.pipeline.is_enabled", return_value=True), \
             patch("nero_core.research_agent.pipeline.scanner.run_scan", return_value=empty_scan), \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.load_existing_hypotheses", return_value=[]), \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.generate_web_hypotheses", return_value=GenerationRunResult()), \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.persist_hypotheses"), \
             patch("nero_core.research_agent.pipeline.auto_tester.persist_test_results"), \
             patch("nero_core.research_agent.pipeline.performance.record_run"):
            first = run_pipeline(api_key="fake-key", now=NOW)
            second = run_pipeline(api_key="fake-key", now=NOW)

        self.assertTrue(first.run_id)
        self.assertTrue(second.run_id)
        self.assertNotEqual(first.run_id, second.run_id)

    def test_disabled_pipeline_reports_empty_run_id(self) -> None:
        with patch("nero_core.research_agent.pipeline.is_enabled", return_value=False):
            result = run_pipeline(api_key="fake-key")
        self.assertEqual(result.run_id, "")


if __name__ == "__main__":
    unittest.main()
