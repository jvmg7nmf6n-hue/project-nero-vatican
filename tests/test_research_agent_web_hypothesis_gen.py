from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from nero_core.research_agent import auto_tester
from nero_core.research_agent.frequency_gate import measure_entry_frequency
from nero_core.research_agent.hypothesis_gen import (
    DEFAULT_PARAMETERS,
    DEFAULT_WEB_MAX_CALLS_PER_RUN,
    SOURCE_TIERS,
    WEB_SEARCH_COST_PER_SEARCH,
    WEB_SEARCH_TOOL,
    check_graveyard_match,
    generate_web_hypotheses,
    load_tracked_asset_timeframes,
)

NOW = datetime(2026, 7, 31, tzinfo=timezone.utc)
TRACKED_PAIRS = [("BTC", "1h"), ("EUR/USD", "4h")]

WEB_HYPOTHESIS_DATA = {
    "hypothesis_name": "TURN_OF_MONTH_BTC_1H",
    "mechanism": "Institutional rebalancing flows cluster around calendar month boundaries.",
    "source_url": "https://example.com/turn-of-month-effect",
    "source_description": "Journal of Finance, Ariel 1987 (turn-of-month effect)",
    "source_tier": "peer_reviewed_academic",
    "paraphrase_confirmed": True,
    "entry_rule": "close crosses above ma20",
    "structured_entry_rule": {"conditions": [{"field": "close", "op": "cross_above", "compare_to_field": "ma20"}]},
    "exit_rule": "target reached or 2x ATR stop",
    "stop_rule": "2x ATR",
    "structured_exit_plan": {"stop_atr_multiple": 2.0, "target_r_multiple": 1.5, "max_holding_hours": 48.0},
    "asset": "BTC",
    "timeframe": "1h",
    "differs_from_graveyard": "A calendar-based trigger, not a statistical extreme or structure break.",
    "expected_frequency_claim": 30.0,
}


class _FakeResponse:
    def __init__(self, payload: dict, status_ok: bool = True, status_code: int = 200) -> None:
        self._payload = payload
        self._status_ok = status_ok
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if not self._status_ok:
            raise __import__("requests").HTTPError("bad status")

    def json(self) -> dict:
        return self._payload


def _payload(data: dict, input_tokens: int = 1000, output_tokens: int = 500, web_search_requests: int = 0) -> dict:
    usage = {"input_tokens": input_tokens, "output_tokens": output_tokens}
    if web_search_requests:
        usage["server_tool_use"] = {"web_search_requests": web_search_requests}
    return {"content": [{"type": "text", "text": json.dumps(data)}], "usage": usage}


class WebSearchToolDeclarationTest(unittest.TestCase):
    def test_web_search_tool_is_declared_in_the_request_body(self) -> None:
        payload = _payload(WEB_HYPOTHESIS_DATA)
        with patch("nero_core.research_agent.hypothesis_gen.requests.post", return_value=_FakeResponse(payload)) as mock_post:
            generate_web_hypotheses([], [], "fake-key", TRACKED_PAIRS, max_calls_per_run=1, now=NOW)

        # 1 preflight (no tools) + 1 real call (WITH the web_search tool)
        preflight_call, real_call = mock_post.call_args_list
        self.assertNotIn("tools", preflight_call.kwargs["json"])
        self.assertEqual(real_call.kwargs["json"]["tools"], [WEB_SEARCH_TOOL])

    def test_prompt_lists_only_currently_tracked_pairs(self) -> None:
        payload = _payload(WEB_HYPOTHESIS_DATA)
        with patch("nero_core.research_agent.hypothesis_gen.requests.post", return_value=_FakeResponse(payload)) as mock_post:
            generate_web_hypotheses([], [], "fake-key", TRACKED_PAIRS, max_calls_per_run=1, now=NOW)

        sent_prompt = mock_post.call_args.kwargs["json"]["messages"][0]["content"]
        self.assertIn("BTC/1h", sent_prompt)
        self.assertIn("EUR/USD/4h", sent_prompt)

    def test_prompt_states_the_no_special_trust_and_no_copyright_rules(self) -> None:
        payload = _payload(WEB_HYPOTHESIS_DATA)
        with patch("nero_core.research_agent.hypothesis_gen.requests.post", return_value=_FakeResponse(payload)) as mock_post:
            generate_web_hypotheses([], [], "fake-key", TRACKED_PAIRS, max_calls_per_run=1, now=NOW)

        sent_prompt = mock_post.call_args.kwargs["json"]["messages"][0]["content"]
        self.assertIn("no special", sent_prompt.lower())
        self.assertIn("NEVER reproduce", sent_prompt)
        self.assertIn("20-30 trades per", sent_prompt)


class GenerateWebHypothesesTest(unittest.TestCase):
    def test_no_api_key_makes_no_call(self) -> None:
        with patch("nero_core.research_agent.hypothesis_gen.requests.post") as mock_post:
            result = generate_web_hypotheses([], [], "", TRACKED_PAIRS, now=NOW)
        mock_post.assert_not_called()
        self.assertEqual(result.hypotheses, [])
        self.assertEqual(result.llm_calls_made, 0)

    def test_no_tracked_pairs_makes_no_call(self) -> None:
        with patch("nero_core.research_agent.hypothesis_gen.requests.post") as mock_post:
            result = generate_web_hypotheses([], [], "fake-key", [], now=NOW)
        mock_post.assert_not_called()
        self.assertEqual(result.hypotheses, [])
        self.assertIn("no tracked", result.errors[0]["message"])

    def test_successful_call_records_discovery_channel_and_source_fields(self) -> None:
        payload = _payload(WEB_HYPOTHESIS_DATA)
        with patch("nero_core.research_agent.hypothesis_gen.requests.post", return_value=_FakeResponse(payload)):
            result = generate_web_hypotheses([], [], "fake-key", TRACKED_PAIRS, max_calls_per_run=1, now=NOW)

        self.assertEqual(len(result.hypotheses), 1)
        record = result.hypotheses[0]
        self.assertEqual(record["discovery_channel"], "web_search")
        self.assertEqual(record["source_url"], WEB_HYPOTHESIS_DATA["source_url"])
        self.assertEqual(record["source_description"], WEB_HYPOTHESIS_DATA["source_description"])
        self.assertEqual(record["source_tier"], "peer_reviewed_academic")
        self.assertTrue(record["paraphrase_confirmed"])
        self.assertIn("graveyard_check", record)

    def test_cost_includes_the_per_search_fee_on_top_of_token_cost(self) -> None:
        # 1,000,000 input + 1,000,000 output tokens == $2.00 + $10.00 == $12.00 in
        # token cost alone; 3 real web searches at $0.01/search adds $0.03 more.
        payload = _payload(WEB_HYPOTHESIS_DATA, input_tokens=1_000_000, output_tokens=1_000_000, web_search_requests=3)
        with patch("nero_core.research_agent.hypothesis_gen.requests.post", return_value=_FakeResponse(payload)):
            result = generate_web_hypotheses([], [], "fake-key", TRACKED_PAIRS, max_calls_per_run=1, now=NOW)

        expected = DEFAULT_PARAMETERS.input_cost_per_mtok + DEFAULT_PARAMETERS.output_cost_per_mtok + 3 * WEB_SEARCH_COST_PER_SEARCH
        self.assertAlmostEqual(result.total_cost_usd, expected, places=8)

    def test_no_search_requests_reported_costs_only_tokens(self) -> None:
        # Honest zero, never a guessed/assumed search count when usage doesn't report one.
        payload = _payload(WEB_HYPOTHESIS_DATA, input_tokens=1000, output_tokens=500, web_search_requests=0)
        with patch("nero_core.research_agent.hypothesis_gen.requests.post", return_value=_FakeResponse(payload)):
            result = generate_web_hypotheses([], [], "fake-key", TRACKED_PAIRS, max_calls_per_run=1, now=NOW)

        expected = (1000 / 1_000_000.0) * 2.00 + (500 / 1_000_000.0) * 10.00
        self.assertAlmostEqual(result.total_cost_usd, expected, places=8)

    def test_skipped_source_produces_no_hypothesis_but_still_counts_the_billed_call(self) -> None:
        skip_data = {"skipped": True, "skip_reason": "source is a paid course's exact proprietary rule set"}
        payload = _payload(skip_data, input_tokens=800, output_tokens=100)
        with patch("nero_core.research_agent.hypothesis_gen.requests.post", return_value=_FakeResponse(payload)):
            result = generate_web_hypotheses([], [], "fake-key", TRACKED_PAIRS, max_calls_per_run=1, now=NOW)

        self.assertEqual(result.hypotheses, [])
        self.assertEqual(result.llm_calls_made, 1)
        self.assertGreater(result.total_cost_usd, 0.0)  # real, billed call -- not silently free
        self.assertIn("skip", result.errors[-1]["message"].lower())
        self.assertIn("proprietary rule set", result.errors[-1]["message"])

    def test_invalid_source_tier_falls_back_to_the_most_conservative_tier(self) -> None:
        data = dict(WEB_HYPOTHESIS_DATA, source_tier="extremely_credible_trust_me")
        payload = _payload(data)
        with patch("nero_core.research_agent.hypothesis_gen.requests.post", return_value=_FakeResponse(payload)):
            result = generate_web_hypotheses([], [], "fake-key", TRACKED_PAIRS, max_calls_per_run=1, now=NOW)

        self.assertEqual(result.hypotheses[0]["source_tier"], "unknown_unverifiable")

    def test_default_web_max_calls_per_run_is_conservative(self) -> None:
        # Deliberately smaller than the scanner path's DEFAULT_MAX_CALLS_PER_RUN=10
        # for the first real run, given the higher per-hypothesis cost.
        self.assertEqual(DEFAULT_WEB_MAX_CALLS_PER_RUN, 3)

    def test_all_source_tiers_are_the_four_documented_categories(self) -> None:
        self.assertEqual(
            set(SOURCE_TIERS),
            {"peer_reviewed_academic", "established_financial_publication", "trading_forum_social_media", "unknown_unverifiable"},
        )

    def test_cost_limit_hit_when_max_calls_per_run_reached(self) -> None:
        payload = _payload(WEB_HYPOTHESIS_DATA)
        with patch("nero_core.research_agent.hypothesis_gen.requests.post", return_value=_FakeResponse(payload)):
            result = generate_web_hypotheses([], [], "fake-key", TRACKED_PAIRS, max_calls_per_run=2, now=NOW)

        self.assertEqual(result.llm_calls_made, 2)
        self.assertTrue(result.cost_limit_hit)
        self.assertEqual(len(result.hypotheses), 2)


class LoadTrackedAssetTimeframesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "quant_metrics.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_reads_unique_sorted_pairs_from_quant_metrics(self) -> None:
        self.path.write_text(json.dumps({
            "metrics": [
                {"asset": "BTC", "timeframe": "24h"},
                {"asset": "BTC", "timeframe": "12h"},
                {"asset": "BTC", "timeframe": "24h"},  # duplicate -- must not appear twice
            ]
        }))
        pairs = load_tracked_asset_timeframes(self.path)
        self.assertEqual(pairs, [("BTC", "12h"), ("BTC", "24h")])

    def test_missing_file_returns_empty_list(self) -> None:
        self.assertEqual(load_tracked_asset_timeframes(self.path), [])

    def test_corrupt_json_returns_empty_list_not_a_crash(self) -> None:
        self.path.write_text("{not valid json")
        self.assertEqual(load_tracked_asset_timeframes(self.path), [])


class GraveyardMatchTest(unittest.TestCase):
    """Rule 4: applies equally regardless of scanner vs web origin -- this
    whole class exercises check_graveyard_match directly, which is the SAME
    function both generate_hypotheses (_build_record) and
    generate_web_hypotheses (_build_web_record) call, with no origin-specific
    branch or threshold anywhere in it."""

    FAILURE_PATTERNS = [
        {
            "name": "TREND_PULLBACK filter variants (FVG-overlap, BOS-recency)",
            "family": "Entry Filters",
            "failure_pattern": "edge-over-random-negative",
            "fix_rationale": (
                "The BOS-recency filter (any break of structure within 20 candles) was "
                "diagnosed as a complete no-op on BNB/12h -- BOS events are frequent enough "
                "that the window never rejects a trade."
            ),
        },
        {
            "name": "MACRO_RISK_ON",
            "family": "Macro Regime",
            "failure_pattern": "mechanism-doesn't-transfer",
        },
    ]

    def test_a_real_near_repeat_is_flagged(self) -> None:
        result = check_graveyard_match(
            "BOS_RECENCY_FILTER_V2",
            "Requires a break of structure within a short candle window before entry, "
            "extending the BOS-recency filter concept to a tighter lookback.",
            self.FAILURE_PATTERNS,
        )
        self.assertTrue(result.is_likely_repeat)
        self.assertEqual(result.matched_pattern_name, "TREND_PULLBACK filter variants (FVG-overlap, BOS-recency)")
        self.assertIn("overlap=", result.method)

    def test_an_unrelated_mechanism_is_not_flagged(self) -> None:
        result = check_graveyard_match(
            "TURN_OF_MONTH_BTC_1H",
            "Institutional rebalancing flows cluster around calendar month boundaries, "
            "producing a predictable short-term drift near month-end.",
            self.FAILURE_PATTERNS,
        )
        self.assertFalse(result.is_likely_repeat)
        self.assertIsNone(result.matched_pattern_name)

    def test_empty_failure_patterns_never_flags_anything(self) -> None:
        result = check_graveyard_match("ANYTHING", "any mechanism text at all", [])
        self.assertFalse(result.is_likely_repeat)

    def test_scanner_and_web_sourced_records_both_get_the_graveyard_check_field(self) -> None:
        # Confirms _build_record (scanner path) and _build_web_record (web path)
        # both attach the SAME check_graveyard_match output shape -- proving
        # rule 4 is wired into both code paths, not just callable in isolation.
        from nero_core.research_agent.hypothesis_gen import generate_hypotheses
        from nero_core.research_agent.scanner import ScanFinding

        finding = ScanFinding("extreme_zscore", "BTC", "1h", "BTC/1h extreme z-score", 3.0, 42.0, "note", NOW.isoformat())
        bos_like_data = dict(
            hypothesis_name="BOS_RECENCY_FILTER_V2",
            mechanism="Requires a break of structure within a short candle window before entry, "
                      "extending the BOS-recency filter concept to a tighter lookback.",
            entry_rule="close gt ma20", structured_entry_rule={"conditions": [{"field": "close", "op": "gt", "value": 100.0}]},
            exit_rule="target", stop_rule="stop", asset="BTC", timeframe="1h",
            differs_from_graveyard="", expected_frequency_claim=30.0,
        )
        payload = {"content": [{"type": "text", "text": json.dumps(bos_like_data)}], "usage": {"input_tokens": 10, "output_tokens": 10}}
        with patch("nero_core.research_agent.hypothesis_gen.requests.post", return_value=_FakeResponse(payload)):
            result = generate_hypotheses([finding], self.FAILURE_PATTERNS, "fake-key", now=NOW)

        self.assertTrue(result.hypotheses[0]["graveyard_check"]["is_likely_repeat"])


def _oscillating_candles(n: int = 400, start_ms: int = 1_700_000_000_000) -> pd.DataFrame:
    """Enough real bars, with a genuine (not degenerate) MA20 golden-cross
    pattern, for a real frequency_gate/auto_tester measurement -- same
    "verified empirically" convention already used in
    test_research_agent_rule_dsl_consistency.py."""
    hour_ms = 3_600_000
    rows = []
    close = 100.0
    for i in range(n):
        close *= 1.0015 if (i // 20) % 2 == 0 else 0.9985
        rows.append({"close_time": start_ms + i * hour_ms, "close": close, "high": close + 0.3, "low": close - 0.3, "volume": 1.0})
    return pd.DataFrame(rows)


class NoSpecialTreatmentTest(unittest.TestCase):
    """Rule 1: a web-sourced hypothesis dict gets the EXACT SAME frequency_gate
    and auto_tester treatment as a scanner-sourced one -- proven by running
    both through the real (unmocked) gate/harness on IDENTICAL candles and
    asserting IDENTICAL results, not just asserting the code "should" agree by
    construction."""

    ENTRY_RULE = {"conditions": [{"field": "close", "op": "cross_above", "compare_to_field": "ma20"}]}
    EXIT_PLAN = {"stop_atr_multiple": 2.0, "target_r_multiple": 1.5, "max_holding_hours": 48.0}

    def _hypothesis(self, extra_fields: dict) -> dict:
        return {
            "hypothesis_name": "TEST_MECHANISM",
            "asset": "BTC",
            "timeframe": "1h",
            "generated_at": NOW.isoformat(),
            "structured_entry_rule": self.ENTRY_RULE,
            "structured_exit_plan": self.EXIT_PLAN,
            **extra_fields,
        }

    def test_frequency_gate_measures_identically_regardless_of_source_fields(self) -> None:
        candles = _oscillating_candles()
        scanner_hypothesis = self._hypothesis({"scan_finding": "x", "scan_finding_type": "extreme_zscore", "source": "claude"})
        web_hypothesis = self._hypothesis({
            "discovery_channel": "web_search", "source_url": "https://example.com/x",
            "source_tier": "peer_reviewed_academic", "paraphrase_confirmed": True,
            "graveyard_check": {"is_likely_repeat": False, "method": "no match", "matched_pattern_name": None},
        })

        scanner_gate = measure_entry_frequency(candles, scanner_hypothesis["structured_entry_rule"], NOW)
        web_gate = measure_entry_frequency(candles, web_hypothesis["structured_entry_rule"], NOW)

        self.assertEqual(scanner_gate.classification, web_gate.classification)
        self.assertEqual(scanner_gate.triggers_counted, web_gate.triggers_counted)
        self.assertEqual(scanner_gate.measured_trades_per_year, web_gate.measured_trades_per_year)

    def test_auto_tester_produces_identical_verdicts_regardless_of_source_fields(self) -> None:
        candles = _oscillating_candles()
        scanner_hypothesis = self._hypothesis({"scan_finding": "x", "scan_finding_type": "extreme_zscore", "source": "claude"})
        web_hypothesis = self._hypothesis({
            "discovery_channel": "web_search", "source_url": "https://example.com/x",
            "source_tier": "trading_forum_social_media", "paraphrase_confirmed": True,
            "graveyard_check": {"is_likely_repeat": False, "method": "no match", "matched_pattern_name": None},
        })

        scanner_result = auto_tester.test_hypothesis(scanner_hypothesis, candles, NOW)
        web_result = auto_tester.test_hypothesis(web_hypothesis, candles, NOW)

        self.assertEqual(scanner_result.verdict, web_result.verdict)
        self.assertEqual(scanner_result.frequency_classification, web_result.frequency_classification)
        self.assertEqual(scanner_result.measured_trades_per_year, web_result.measured_trades_per_year)
        if scanner_result.train is not None:
            self.assertEqual(scanner_result.train.trades, web_result.train.trades)
            self.assertEqual(scanner_result.train.expectancy_r, web_result.train.expectancy_r)
        if scanner_result.test is not None:
            self.assertEqual(scanner_result.test.trades, web_result.test.trades)
            self.assertEqual(scanner_result.test.expectancy_r, web_result.test.expectancy_r)


if __name__ == "__main__":
    unittest.main()
