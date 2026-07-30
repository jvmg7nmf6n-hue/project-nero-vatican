from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from nero_core.research_agent.hypothesis_gen import (
    DEFAULT_PARAMETERS,
    ApiKeyRejectedError,
    check_duplicate,
    generate_hypotheses,
    load_existing_hypotheses,
    persist_hypotheses,
    validate_api_key,
)
from nero_core.research_agent.scanner import ScanFinding

NOW = datetime(2026, 7, 29, tzinfo=timezone.utc)


def _finding(asset="BTC", timeframe="1h", finding_type="extreme_zscore", description="BTC/1h extreme z-score") -> ScanFinding:
    return ScanFinding(finding_type, asset, timeframe, description, 3.0, 42.0, "measured note", NOW.isoformat())


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


def _claude_payload(data: dict, input_tokens: int = 1000, output_tokens: int = 500, with_thinking_block: bool = False) -> dict:
    content = []
    if with_thinking_block:
        content.append({"type": "thinking", "thinking": "reasoning..."})
    content.append({"type": "text", "text": json.dumps(data)})
    return {"content": content, "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens}}


VALID_HYPOTHESIS_DATA = {
    "hypothesis_name": "ZSCORE_REVERSION_BTC_1H",
    "mechanism": "Mean reversion after an extreme dislocation.",
    "entry_rule": "zscore20 < -2",
    "structured_entry_rule": {"conditions": [{"field": "zscore20", "op": "lt", "value": -2.0}]},
    "exit_rule": "zscore20 crosses back above 0",
    "stop_rule": "2x ATR",
    "asset": "BTC",
    "timeframe": "1h",
    "differs_from_graveyard": "Uses a frequent 1h zscore trigger, not the rare daily one already tested.",
    "expected_frequency_claim": 80.0,
}


class CheckDuplicateTest(unittest.TestCase):
    def test_exact_match_flagged_duplicate(self) -> None:
        existing = [{"scan_finding_type": "extreme_zscore", "asset": "BTC", "timeframe": "1h", "hypothesis_name": "EXISTING"}]
        result = check_duplicate(_finding(), existing)
        self.assertTrue(result.is_duplicate)
        self.assertEqual(result.matched_hypothesis_name, "EXISTING")
        self.assertIn("scan_finding_type", result.method)

    def test_different_asset_not_duplicate(self) -> None:
        existing = [{"scan_finding_type": "extreme_zscore", "asset": "ETH", "timeframe": "1h"}]
        self.assertFalse(check_duplicate(_finding(asset="BTC"), existing).is_duplicate)

    def test_different_finding_type_not_duplicate(self) -> None:
        existing = [{"scan_finding_type": "correlation_breakdown", "asset": "BTC", "timeframe": "1h"}]
        self.assertFalse(check_duplicate(_finding(finding_type="extreme_zscore"), existing).is_duplicate)

    def test_empty_existing_list_never_duplicate(self) -> None:
        self.assertFalse(check_duplicate(_finding(), []).is_duplicate)


class GenerateHypothesesTest(unittest.TestCase):
    def test_duplicate_finding_skips_llm_call_entirely(self) -> None:
        existing = [{"scan_finding_type": "extreme_zscore", "asset": "BTC", "timeframe": "1h"}]
        with patch("nero_core.research_agent.hypothesis_gen.requests.post") as mock_post:
            result = generate_hypotheses([_finding()], [], "fake-key", existing_hypotheses=existing, now=NOW)

        mock_post.assert_not_called()
        self.assertEqual(len(result.duplicates_skipped), 1)
        self.assertEqual(result.hypotheses, [])
        self.assertEqual(result.llm_calls_made, 0)

    def test_missing_api_key_records_error_without_calling(self) -> None:
        with patch("nero_core.research_agent.hypothesis_gen.requests.post") as mock_post:
            result = generate_hypotheses([_finding()], [], "", now=NOW)

        mock_post.assert_not_called()
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(result.llm_calls_made, 0)

    def test_successful_call_produces_hypothesis_record_and_cost(self) -> None:
        payload = _claude_payload(VALID_HYPOTHESIS_DATA, input_tokens=1_000_000, output_tokens=1_000_000)
        with patch("nero_core.research_agent.hypothesis_gen.requests.post", return_value=_FakeResponse(payload)):
            result = generate_hypotheses([_finding()], [], "fake-key", now=NOW)

        self.assertEqual(len(result.hypotheses), 1)
        record = result.hypotheses[0]
        self.assertEqual(record["hypothesis_name"], "ZSCORE_REVERSION_BTC_1H")
        self.assertEqual(record["scan_finding_type"], "extreme_zscore")
        self.assertEqual(record["structured_entry_rule"], VALID_HYPOTHESIS_DATA["structured_entry_rule"])
        # 1M input tokens @ $2.00/MTok + 1M output tokens @ $10.00/MTok == $12.00 exactly
        self.assertAlmostEqual(result.total_cost_usd, DEFAULT_PARAMETERS.input_cost_per_mtok + DEFAULT_PARAMETERS.output_cost_per_mtok)
        self.assertEqual(result.llm_calls_made, 1)

    def test_null_structured_entry_rule_is_preserved_not_forced(self) -> None:
        data = dict(VALID_HYPOTHESIS_DATA, structured_entry_rule=None)
        payload = _claude_payload(data)
        with patch("nero_core.research_agent.hypothesis_gen.requests.post", return_value=_FakeResponse(payload)):
            result = generate_hypotheses([_finding()], [], "fake-key", now=NOW)

        self.assertIsNone(result.hypotheses[0]["structured_entry_rule"])

    def test_thinking_block_prefix_does_not_break_parsing(self) -> None:
        payload = _claude_payload(VALID_HYPOTHESIS_DATA, with_thinking_block=True)
        with patch("nero_core.research_agent.hypothesis_gen.requests.post", return_value=_FakeResponse(payload)):
            result = generate_hypotheses([_finding()], [], "fake-key", now=NOW)

        self.assertEqual(len(result.hypotheses), 1)
        self.assertEqual(result.hypotheses[0]["hypothesis_name"], "ZSCORE_REVERSION_BTC_1H")

    def test_markdown_fenced_json_is_stripped(self) -> None:
        fenced_text = "```json\n" + json.dumps(VALID_HYPOTHESIS_DATA) + "\n```"
        payload = {"content": [{"type": "text", "text": fenced_text}], "usage": {"input_tokens": 10, "output_tokens": 10}}
        with patch("nero_core.research_agent.hypothesis_gen.requests.post", return_value=_FakeResponse(payload)):
            result = generate_hypotheses([_finding()], [], "fake-key", now=NOW)

        self.assertEqual(len(result.hypotheses), 1)

    def test_cost_limit_stops_run_before_exceeding_max_calls(self) -> None:
        payload = _claude_payload(VALID_HYPOTHESIS_DATA)
        findings = [_finding(asset="BTC"), _finding(asset="ETH"), _finding(asset="SOL")]
        with patch("nero_core.research_agent.hypothesis_gen.requests.post", return_value=_FakeResponse(payload)) as mock_post:
            result = generate_hypotheses(findings, [], "fake-key", max_calls_per_run=1, now=NOW)

        # 1 preflight (key validation, not counted in llm_calls_made) + 1 real call (the cap)
        self.assertEqual(mock_post.call_count, 2)
        self.assertEqual(result.llm_calls_made, 1)
        self.assertTrue(result.cost_limit_hit)
        self.assertEqual(len(result.hypotheses), 1)

    def test_api_error_is_recorded_and_counts_against_call_budget(self) -> None:
        import requests as requests_module

        # Every requests.post call (preflight AND the real per-finding call)
        # raises the same ConnectionError here -- so this now records TWO
        # error notes: the preflight's own non-fatal note (item #3's fix --
        # previously silently swallowed with zero trace) plus the real call's
        # failure. llm_calls_made only counts the real per-finding attempt.
        with patch("nero_core.research_agent.hypothesis_gen.requests.post", side_effect=requests_module.ConnectionError("down")):
            result = generate_hypotheses([_finding()], [], "fake-key", now=NOW)

        self.assertEqual(result.llm_calls_made, 1)
        self.assertEqual(len(result.errors), 2)
        self.assertIn("preflight key check did not complete", result.errors[0]["message"])
        self.assertIn("ConnectionError", result.errors[1]["message"])
        self.assertEqual(result.hypotheses, [])

    def test_malformed_json_response_still_records_the_real_billed_cost(self) -> None:
        # TIER 4 / item #4: a 2xx response IS billed by Anthropic even if the
        # text inside it isn't valid JSON -- previously this was recorded as
        # $0.00, identical to a call that never reached Anthropic at all.
        payload = {
            "content": [{"type": "text", "text": "not valid json at all"}],
            "usage": {"input_tokens": 1000, "output_tokens": 500},
        }
        with patch("nero_core.research_agent.hypothesis_gen.requests.post", return_value=_FakeResponse(payload)):
            result = generate_hypotheses([_finding()], [], "fake-key", now=NOW)

        expected_cost = (1000 / 1_000_000.0) * 2.00 + (500 / 1_000_000.0) * 10.00
        self.assertEqual(result.hypotheses, [])
        self.assertAlmostEqual(result.total_cost_usd, expected_cost, places=8)
        self.assertGreater(result.total_cost_usd, 0.0)
        self.assertIn("call WAS billed", result.errors[-1]["message"])
        self.assertIn(f"${expected_cost:.6f}", result.errors[-1]["message"])

    def test_no_text_block_response_still_records_the_real_billed_cost(self) -> None:
        payload = {
            "content": [{"type": "thinking", "thinking": "..."}],
            "usage": {"input_tokens": 200, "output_tokens": 50},
        }
        with patch("nero_core.research_agent.hypothesis_gen.requests.post", return_value=_FakeResponse(payload)):
            result = generate_hypotheses([_finding()], [], "fake-key", now=NOW)

        expected_cost = (200 / 1_000_000.0) * 2.00 + (50 / 1_000_000.0) * 10.00
        self.assertAlmostEqual(result.total_cost_usd, expected_cost, places=8)
        self.assertGreater(result.total_cost_usd, 0.0)
        self.assertIn("call WAS billed", result.errors[-1]["message"])

    def test_thinking_only_empty_string_exact_real_shape_still_records_billed_cost_distinctly(self) -> None:
        # Diagnostics finding (2026-07-30): a real Actions run returned this
        # EXACT shape -- one thinking block whose `thinking` field is the
        # empty string (claude-sonnet-5's `display: "omitted"` default) and
        # NO text block at all, having exhausted the old max_tokens=1500
        # budget before writing anything. This is a regression guard: even
        # though thinking is now explicitly disabled on the real request
        # (making this shape unreachable in production), the parsing path
        # must still turn an unparseable-but-billed response into a loud,
        # distinct error -- never "0 hypotheses, no error" (the pre-Tier-4
        # symptom this whole diagnostics effort started from).
        payload = {
            "content": [{"type": "thinking", "thinking": ""}],
            "usage": {"input_tokens": 3177, "output_tokens": 1500},
        }
        with patch("nero_core.research_agent.hypothesis_gen.requests.post", return_value=_FakeResponse(payload)):
            result = generate_hypotheses([_finding()], [], "fake-key", now=NOW)

        expected_cost = (3177 / 1_000_000.0) * 2.00 + (1500 / 1_000_000.0) * 10.00
        self.assertEqual(result.hypotheses, [])
        self.assertAlmostEqual(result.total_cost_usd, expected_cost, places=8)
        self.assertGreater(result.total_cost_usd, 0.0)
        self.assertEqual(result.llm_calls_made, 1)
        self.assertIn("call WAS billed", result.errors[-1]["message"])
        self.assertIn(f"${expected_cost:.6f}", result.errors[-1]["message"])
        self.assertIn("NoTextBlockError", result.errors[-1]["message"])

    def test_request_payload_explicitly_disables_thinking(self) -> None:
        # Primary fix: the raw request body must carry an explicit
        # thinking-disabled directive on every call (preflight AND the real
        # per-finding call) -- this is what makes the empty-thinking-block
        # failure structurally impossible in production, not just less
        # likely. Confirmed against the Claude API reference that
        # {"type": "disabled"} is cleanly supported on claude-sonnet-5.
        payload = _claude_payload(VALID_HYPOTHESIS_DATA)
        with patch("nero_core.research_agent.hypothesis_gen.requests.post", return_value=_FakeResponse(payload)) as mock_post:
            generate_hypotheses([_finding()], [], "fake-key", now=NOW)

        self.assertEqual(mock_post.call_count, 2)  # preflight + the real call
        for call in mock_post.call_args_list:
            self.assertEqual(call.kwargs["json"]["thinking"], {"type": "disabled"})
        preflight_call, real_call = mock_post.call_args_list
        self.assertEqual(preflight_call.kwargs["json"]["max_tokens"], 1)
        self.assertEqual(real_call.kwargs["json"]["max_tokens"], DEFAULT_PARAMETERS.claude_max_tokens)

    def test_max_tokens_has_real_margin_over_a_realistic_full_schema_response(self) -> None:
        # Sizing guard, not a guess-and-hope check: builds one representative
        # instance of the actual 11-key schema this call asks for (2-3
        # sentence mechanism, a 3-condition structured_entry_rule, a full
        # structured_exit_plan, a 2-sentence differs_from_graveyard -- see
        # _build_prompt's own field descriptions), measures its serialized
        # size, and asserts the configured max_tokens clears it with margin.
        # A future accidental shrink of claude_max_tokens back toward 1500
        # fails this test instead of failing silently in production again.
        realistic_response = {
            "hypothesis_name": "ZSCORE_REVERSION_BTC_1H_V2",
            "mechanism": (
                "When price deviates more than 2 standard deviations below its 20-period "
                "moving average on low timeframes, short-term liquidity providers tend to "
                "step in and absorb the imbalance, producing a mean-reverting bounce within "
                "a few candles. This effect is strongest during high-volume regimes where "
                "market makers are actively quoting both sides."
            ),
            "entry_rule": (
                "Enter long when zscore20 is less than -2.0 and rsi14 is less than 30 and "
                "volume is greater than its 20-period average, on the 1h BTC chart."
            ),
            "structured_entry_rule": {
                "conditions": [
                    {"field": "zscore20", "op": "lt", "value": -2.0},
                    {"field": "rsi14", "op": "lt", "value": 30},
                    {"field": "volume", "op": "gt", "compare_to_field": "ma20"},
                ]
            },
            "exit_rule": "Exit when price closes back above the 20-period moving average, or when the target R-multiple is reached, whichever comes first.",
            "stop_rule": "Stop loss placed at 1.5x ATR(14) below the entry price.",
            "structured_exit_plan": {"stop_atr_multiple": 1.5, "target_r_multiple": 2.0, "max_holding_hours": 24},
            "asset": "BTC",
            "timeframe": "1h",
            "differs_from_graveyard": (
                "Unlike the previously-killed RSI_OVERSOLD_BOUNCE mechanism, this variant "
                "requires a volume confirmation filter and a stricter zscore threshold, "
                "which should reduce false signals in low-liquidity chop."
            ),
            "expected_frequency_claim": 45.0,
        }
        # Conservative (undercounts real tokens -- chars/3, not chars/4) proxy
        # so this assertion errs toward requiring MORE margin, not less.
        estimated_tokens = len(json.dumps(realistic_response)) / 3.0
        self.assertGreater(
            DEFAULT_PARAMETERS.claude_max_tokens,
            estimated_tokens * 2,
            "claude_max_tokens no longer has real margin over a realistic full-schema response",
        )

        payload = {
            "content": [{"type": "text", "text": json.dumps(realistic_response)}],
            "usage": {"input_tokens": 1200, "output_tokens": round(estimated_tokens)},
        }
        with patch("nero_core.research_agent.hypothesis_gen.requests.post", return_value=_FakeResponse(payload)):
            result = generate_hypotheses([_finding()], [], "fake-key", now=NOW)

        self.assertEqual(len(result.hypotheses), 1)
        self.assertEqual(result.hypotheses[0]["hypothesis_name"], "ZSCORE_REVERSION_BTC_1H_V2")
        self.assertEqual(result.hypotheses[0]["structured_exit_plan"], realistic_response["structured_exit_plan"])

    def test_transport_failure_never_reports_a_fabricated_cost(self) -> None:
        # Regression guard: a genuine transport failure (nothing billed, no
        # usage available at all) must NOT be conflated with the billed-but-
        # unparseable case above -- it must stay $0.00, not get some
        # fabricated non-zero figure.
        import requests as requests_module

        with patch(
            "nero_core.research_agent.hypothesis_gen.requests.post",
            side_effect=[_FakeResponse({}, status_code=200), requests_module.ConnectionError("down")],
        ):
            result = generate_hypotheses([_finding()], [], "fake-key", now=NOW)

        self.assertEqual(result.total_cost_usd, 0.0)
        self.assertNotIn("call WAS billed", result.errors[-1]["message"])

    def test_within_run_duplicates_are_also_caught(self) -> None:
        # two findings that map to the SAME (finding_type, asset, timeframe) key --
        # the second must be skipped even though nothing was on disk beforehand.
        payload = _claude_payload(VALID_HYPOTHESIS_DATA)
        findings = [_finding(), _finding()]
        with patch("nero_core.research_agent.hypothesis_gen.requests.post", return_value=_FakeResponse(payload)) as mock_post:
            result = generate_hypotheses(findings, [], "fake-key", now=NOW)

        # 1 preflight + 1 real call (the second finding becomes a within-run duplicate)
        self.assertEqual(mock_post.call_count, 2)
        self.assertEqual(len(result.hypotheses), 1)
        self.assertEqual(len(result.duplicates_skipped), 1)

    def test_prompt_includes_frequency_requirement_and_dead_mechanisms(self) -> None:
        payload = _claude_payload(VALID_HYPOTHESIS_DATA)
        failure_patterns = [{"name": "FVG_REVERSION", "family": "Fair Value Gap", "failure_pattern": "edge-over-random-negative"}]
        with patch("nero_core.research_agent.hypothesis_gen.requests.post", return_value=_FakeResponse(payload)) as mock_post:
            generate_hypotheses([_finding()], failure_patterns, "fake-key", now=NOW)

        sent_prompt = mock_post.call_args.kwargs["json"]["messages"][0]["content"]
        self.assertIn("20-30 trades per", sent_prompt)
        self.assertIn("FVG_REVERSION", sent_prompt)

    def test_prompt_mentions_rsi14_and_compare_to_field(self) -> None:
        # Added 2026-07-30 alongside the DSL extension -- the prompt must actually tell
        # the LLM these capabilities exist, or the DSL fix is useless in practice.
        payload = _claude_payload(VALID_HYPOTHESIS_DATA)
        with patch("nero_core.research_agent.hypothesis_gen.requests.post", return_value=_FakeResponse(payload)) as mock_post:
            generate_hypotheses([_finding()], [], "fake-key", now=NOW)

        sent_prompt = mock_post.call_args.kwargs["json"]["messages"][0]["content"]
        self.assertIn("rsi14", sent_prompt)
        self.assertIn("compare_to_field", sent_prompt)


class ValidateApiKeyDirectTest(unittest.TestCase):
    """Unit tests on validate_api_key in isolation, added 2026-07-29 after a
    real run made 3 doomed calls (one per scan finding) against a rejected
    key before this preflight check existed."""

    def test_401_raises_api_key_rejected(self) -> None:
        with patch("nero_core.research_agent.hypothesis_gen.requests.post", return_value=_FakeResponse({}, status_code=401)):
            with self.assertRaises(ApiKeyRejectedError):
                validate_api_key("fake-key")

    def test_200_does_not_raise(self) -> None:
        with patch("nero_core.research_agent.hypothesis_gen.requests.post", return_value=_FakeResponse({}, status_code=200)):
            note = validate_api_key("fake-key")  # must not raise
        self.assertIsNone(note)

    def test_other_error_status_does_not_raise(self) -> None:
        # a 429/500/etc. is not a "key rejected" signal -- only 401 is
        with patch("nero_core.research_agent.hypothesis_gen.requests.post", return_value=_FakeResponse({}, status_code=429)):
            note = validate_api_key("fake-key")  # must not raise
        self.assertIsNone(note)

    def test_network_error_does_not_raise_but_returns_a_descriptive_note(self) -> None:
        # Item #3's fix: previously a bare `return` here left ZERO trace
        # anywhere -- a network failure on the preflight probe was
        # indistinguishable from "everything's fine." Must not raise (the
        # real per-finding calls still get their own chance), but the
        # non-None return is exactly what makes this failure visible now.
        import requests as requests_module

        with patch("nero_core.research_agent.hypothesis_gen.requests.post", side_effect=requests_module.ConnectionError("down")):
            note = validate_api_key("fake-key")  # must not raise -- let the real calls surface it

        self.assertIsNotNone(note)
        self.assertIn("ConnectionError", note)
        self.assertIn("down", note)

    def test_the_key_value_never_appears_in_the_raised_message(self) -> None:
        secret = "sk-ant-TESTSECRET-do-not-leak"
        with patch("nero_core.research_agent.hypothesis_gen.requests.post", return_value=_FakeResponse({}, status_code=401)):
            with self.assertRaises(ApiKeyRejectedError) as ctx:
                validate_api_key(secret)
        self.assertNotIn(secret, str(ctx.exception))


class PreflightIntegrationTest(unittest.TestCase):
    """Preflight behavior as wired into generate_hypotheses itself."""

    def test_401_stops_the_run_with_exactly_one_call_and_one_error(self) -> None:
        findings = [_finding(asset="BTC"), _finding(asset="ETH"), _finding(asset="SOL")]
        with patch("nero_core.research_agent.hypothesis_gen.requests.post", return_value=_FakeResponse({}, status_code=401)) as mock_post:
            result = generate_hypotheses(findings, [], "fake-key", now=NOW)

        # exactly ONE call total -- not one doomed call per finding
        mock_post.assert_called_once()
        self.assertEqual(result.llm_calls_made, 1)
        self.assertEqual(result.hypotheses, [])
        self.assertEqual(len(result.errors), 1)
        self.assertIn("401", result.errors[0]["message"])
        self.assertEqual(result.total_cost_usd, 0.0)

    def test_401_error_message_never_contains_the_key_value(self) -> None:
        secret = "sk-ant-TESTSECRET-do-not-leak"
        with patch("nero_core.research_agent.hypothesis_gen.requests.post", return_value=_FakeResponse({}, status_code=401)):
            result = generate_hypotheses([_finding()], [], secret, now=NOW)
        self.assertNotIn(secret, json.dumps(result.errors))

    def test_preflight_skipped_when_api_key_is_empty(self) -> None:
        with patch("nero_core.research_agent.hypothesis_gen.requests.post") as mock_post:
            generate_hypotheses([_finding()], [], "", now=NOW)
        mock_post.assert_not_called()

    def test_preflight_skipped_when_every_finding_is_already_a_duplicate(self) -> None:
        existing = [{"scan_finding_type": "extreme_zscore", "asset": "BTC", "timeframe": "1h"}]
        with patch("nero_core.research_agent.hypothesis_gen.requests.post") as mock_post:
            generate_hypotheses([_finding()], [], "fake-key", existing_hypotheses=existing, now=NOW)
        mock_post.assert_not_called()

    def test_preflight_network_error_does_not_block_the_real_call(self) -> None:
        import requests as requests_module

        payload = _claude_payload(VALID_HYPOTHESIS_DATA)
        # preflight raises a connection error (not a 401) -- must NOT be treated as fatal;
        # the real per-finding call still gets a chance and succeeds here.
        with patch(
            "nero_core.research_agent.hypothesis_gen.requests.post",
            side_effect=[requests_module.ConnectionError("preflight network blip"), _FakeResponse(payload)],
        ):
            result = generate_hypotheses([_finding()], [], "fake-key", now=NOW)

        self.assertEqual(len(result.hypotheses), 1)
        # Not fatal (the real call still ran and succeeded) but no longer
        # silent either -- item #3's fix records a non-fatal preflight note
        # instead of the previous bare `return` that left zero trace.
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(result.errors[0]["scan_finding"], "(preflight key validation)")
        self.assertIn("ConnectionError", result.errors[0]["message"])
        self.assertIn("preflight network blip", result.errors[0]["message"])


class PersistHypothesesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "agent_hypotheses.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_persist_is_append_only_across_calls(self) -> None:
        persist_hypotheses([{"hypothesis_name": "A"}], self.path)
        persist_hypotheses([{"hypothesis_name": "B"}], self.path)

        stored = load_existing_hypotheses(self.path)
        self.assertEqual([h["hypothesis_name"] for h in stored], ["A", "B"])

    def test_empty_list_does_not_create_file(self) -> None:
        persist_hypotheses([], self.path)
        self.assertFalse(self.path.exists())

    def test_load_missing_file_returns_empty_list(self) -> None:
        self.assertEqual(load_existing_hypotheses(self.path), [])


if __name__ == "__main__":
    unittest.main()
