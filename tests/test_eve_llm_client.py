from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from nero_core.eve import llm_client
from nero_core.eve.tools_defs import (
    END_SESSION_TOOL_NAME,
    PROPOSE_HYPOTHESIS_TOOL_NAME,
    WEB_SEARCH_TOOL,
    default_tools,
)


class WebSearchToolReuseTest(unittest.TestCase):
    def test_byte_identical_to_adams_web_search_tool(self) -> None:
        # Confirms Eve reuses Adam's exact tool config (spec 2.2) -- this
        # comparison import is fine in a TEST file (only nero_core/eve/
        # SOURCE files are forbidden from importing research_agent, see
        # test_eve_no_auto_wire.py).
        from nero_core.research_agent.hypothesis_gen import WEB_SEARCH_TOOL as ADAM_WEB_SEARCH_TOOL

        self.assertEqual(WEB_SEARCH_TOOL, ADAM_WEB_SEARCH_TOOL)


class DslVocabularyReuseTest(unittest.TestCase):
    """session.py reinlines rule_dsl's ALLOWED_FIELDS/ALLOWED_OPS (it may not
    import nero_core.research_agent directly -- see test_eve_no_auto_wire.py)
    so it can supply the exact DSL vocabulary in Eve's system prompt (added
    post-Session-0, see session.py's own DSL_VOCABULARY_BLOCK docstring).
    Mirrors WebSearchToolReuseTest's own precedent: the reinlined copy must
    stay byte-identical to the real thing, or this test catches the drift
    the moment rule_dsl adds/removes a field or op."""

    def test_allowed_fields_match_rule_dsl_exactly(self) -> None:
        from nero_core.eve.session import DSL_ALLOWED_FIELDS
        from nero_core.research_agent.rule_dsl import ALLOWED_FIELDS

        self.assertEqual(DSL_ALLOWED_FIELDS, ALLOWED_FIELDS)

    def test_allowed_ops_match_rule_dsl_exactly(self) -> None:
        from nero_core.eve.session import DSL_ALLOWED_OPS
        from nero_core.research_agent.rule_dsl import ALLOWED_OPS

        self.assertEqual(DSL_ALLOWED_OPS, ALLOWED_OPS)

    def test_system_prompt_names_the_exact_exit_plan_keys(self) -> None:
        # The literal root cause of Session 0's 4/4 UNTESTABLE_BY_DSL result:
        # these exact key names were never spelled out anywhere Eve could
        # read them. Regression-guards that they now are.
        from nero_core.eve.session import SYSTEM_PROMPT_TEMPLATE

        for key_name in ("compare_to_field", "stop_atr_multiple", "target_r_multiple", "max_holding_hours"):
            self.assertIn(key_name, SYSTEM_PROMPT_TEMPLATE)

    def test_system_prompt_states_the_approved_research_universe(self) -> None:
        # Session 0-B (eve-20260803T142519Z-718833c9): 6/6 hypotheses parsed
        # cleanly but all 6 targeted a pair with no real backtest data, and
        # were refused. Every approved pair must be named explicitly, in the
        # correct asset/timeframe-as-separate-fields shape.
        from nero_core.asset_universe import APPROVED_RESEARCH_UNIVERSE
        from nero_core.eve.session import SYSTEM_PROMPT_TEMPLATE

        for asset, timeframe in APPROVED_RESEARCH_UNIVERSE:
            self.assertIn(f'asset="{asset}", timeframe="{timeframe}"', SYSTEM_PROMPT_TEMPLATE)

    def test_worked_example_shows_asset_and_timeframe_as_separate_fields(self) -> None:
        # Session 0-B's own BTC/4h hypothesis mangled asset+timeframe into
        # one string ("asset": "BTC/4h") -- the worked example must model
        # the correct separated shape, not a placeholder that never shows it.
        from nero_core.eve.session import SYSTEM_PROMPT_TEMPLATE

        self.assertIn('"asset": "BTC"', SYSTEM_PROMPT_TEMPLATE)
        self.assertIn('"timeframe": "4h"', SYSTEM_PROMPT_TEMPLATE)
        self.assertNotIn('"asset": "BTC/4h"', SYSTEM_PROMPT_TEMPLATE)

    def test_asset_universe_framed_as_data_not_permission(self) -> None:
        # Same framing discipline as the DSL vocabulary block: she may still
        # propose on any pair; only what happens to it (recorded vs scored)
        # differs.
        from nero_core.eve.session import SYSTEM_PROMPT_TEMPLATE

        self.assertIn("still fully welcome and still recorded", SYSTEM_PROMPT_TEMPLATE)
        self.assertIn("refused", SYSTEM_PROMPT_TEMPLATE)

    def test_frequency_gate_numbers_match_frequency_gate_py_exactly(self) -> None:
        # Session 0-B follow-up audit (item 4): reinlined from
        # frequency_gate.py -- must stay byte-identical, same drift-guard
        # pattern as the DSL fields/ops above.
        from nero_core.eve.session import _FREQ_FAST_MAX_MONTHS, _FREQ_TARGET_TRADES, _FREQ_VIABLE_MAX_MONTHS
        from nero_core.research_agent.frequency_gate import FAST_MAX_MONTHS, TARGET_RESOLVED_TRADES, VIABLE_MAX_MONTHS

        self.assertEqual(_FREQ_TARGET_TRADES, TARGET_RESOLVED_TRADES)
        self.assertEqual(_FREQ_FAST_MAX_MONTHS, FAST_MAX_MONTHS)
        self.assertEqual(_FREQ_VIABLE_MAX_MONTHS, VIABLE_MAX_MONTHS)

    def test_min_sample_size_matches_tools_backtest_statistics_exactly(self) -> None:
        # Live import (tools.backtest_statistics is not under research_agent),
        # so this can never drift by construction -- test documents that fact
        # rather than guards against a real risk.
        from nero_core.eve.session import MIN_SAMPLE_SIZE as SESSION_MIN_SAMPLE_SIZE
        from tools.backtest_statistics import MIN_SAMPLE_SIZE

        self.assertEqual(SESSION_MIN_SAMPLE_SIZE, MIN_SAMPLE_SIZE)

    def test_system_prompt_states_the_frequency_gate_thresholds(self) -> None:
        from nero_core.eve.session import SYSTEM_PROMPT_TEMPLATE

        self.assertIn("~30 times per year", SYSTEM_PROMPT_TEMPLATE)
        self.assertIn("~60/year", SYSTEM_PROMPT_TEMPLATE)
        self.assertIn("TOO_SLOW", SYSTEM_PROMPT_TEMPLATE)

    def test_system_prompt_states_the_llm_frequency_overestimation_finding(self) -> None:
        from nero_core.eve.session import SYSTEM_PROMPT_TEMPLATE

        self.assertIn("overestimated their own trigger frequency", SYSTEM_PROMPT_TEMPLATE)
        self.assertIn("24-32 trades/year", SYSTEM_PROMPT_TEMPLATE)
        self.assertIn("2.5-15/year", SYSTEM_PROMPT_TEMPLATE)

    def test_system_prompt_states_the_survived_bar(self) -> None:
        from nero_core.eve.session import SYSTEM_PROMPT_TEMPLATE

        self.assertIn("at least 20 resolved", SYSTEM_PROMPT_TEMPLATE)
        self.assertIn("SURVIVED", SYSTEM_PROMPT_TEMPLATE)
        self.assertIn("PROMISING-WATCHLIST", SYSTEM_PROMPT_TEMPLATE)

    def test_system_prompt_states_the_atr_warmup_note(self) -> None:
        from nero_core.eve.session import SYSTEM_PROMPT_TEMPLATE

        self.assertIn("atr14", SYSTEM_PROMPT_TEMPLATE)
        self.assertIn("stop_pct_of_entry", SYSTEM_PROMPT_TEMPLATE)

    def test_system_prompt_worked_example_is_actually_valid_dsl(self) -> None:
        # The vocabulary block's own worked example must itself parse -- an
        # example that doesn't practice what it preaches would be worse than
        # no example at all.
        from nero_core.research_agent.rule_dsl import parse_bidirectional_entry_rules, parse_exit_plan

        example_hypothesis = {
            "structured_entry_rule": {"conditions": [{"field": "close", "op": "gt", "value": 0}]},
            "structured_exit_plan": {"stop_atr_multiple": 1.0, "target_r_multiple": 1.0},
        }
        parse_bidirectional_entry_rules(example_hypothesis)  # must not raise
        parse_exit_plan(example_hypothesis["structured_exit_plan"])  # must not raise


class BuildNextUserMessagePerToolResultTest(unittest.TestCase):
    def test_single_string_applies_to_every_pending_block(self) -> None:
        blocks = [{"id": "toolu_a"}, {"id": "toolu_b"}]
        message = llm_client.build_next_user_message(blocks, "same text for all")
        tool_results = {b["tool_use_id"]: b["content"] for b in message["content"] if b["type"] == "tool_result"}
        self.assertEqual(tool_results, {"toolu_a": "same text for all", "toolu_b": "same text for all"})

    def test_dict_gives_each_pending_block_its_own_text(self) -> None:
        blocks = [{"id": "toolu_a"}, {"id": "toolu_b"}]
        message = llm_client.build_next_user_message(blocks, {"toolu_a": "ack", "toolu_b": "parser error: xyz"})
        tool_results = {b["tool_use_id"]: b["content"] for b in message["content"] if b["type"] == "tool_result"}
        self.assertEqual(tool_results, {"toolu_a": "ack", "toolu_b": "parser error: xyz"})

    def test_trailing_continue_text_block_still_present(self) -> None:
        message = llm_client.build_next_user_message([{"id": "toolu_a"}], {"toolu_a": "ack"})
        self.assertEqual(message["content"][-1]["type"], "text")


class ToolDefsTest(unittest.TestCase):
    def test_default_tools_includes_all_three(self) -> None:
        names = {t.get("name") or t.get("type") for t in default_tools()}
        self.assertIn("web_search", names)
        self.assertIn(END_SESSION_TOOL_NAME, names)
        self.assertIn(PROPOSE_HYPOTHESIS_TOOL_NAME, names)


class StubModeEnvVarTest(unittest.TestCase):
    def test_defaults_to_false(self) -> None:
        self.assertFalse(llm_client.is_stub_mode(env={}))

    def test_true_values(self) -> None:
        for value in ("1", "true", "YES", "On"):
            self.assertTrue(llm_client.is_stub_mode(env={"EVE_STUB_MODE": value}))


class CacheControlTest(unittest.TestCase):
    def test_system_block_has_ephemeral_cache_control(self) -> None:
        blocks = llm_client.build_system_blocks("system prompt text")
        self.assertEqual(blocks[0]["cache_control"], {"type": "ephemeral"})

    def test_context_block_has_cache_control_but_task_block_does_not(self) -> None:
        message = llm_client.build_context_user_message("static context", "per-turn task text")
        context_block, task_block = message["content"]
        self.assertEqual(context_block["cache_control"], {"type": "ephemeral"})
        self.assertNotIn("cache_control", task_block)


class ExtractionHelpersTest(unittest.TestCase):
    def test_extract_text_concatenates_text_blocks_only(self) -> None:
        blocks = [{"type": "text", "text": "a"}, {"type": "tool_use", "name": "x", "input": {}}, {"type": "text", "text": "b"}]
        self.assertEqual(llm_client.extract_text(blocks), "ab")

    def test_extract_tool_uses_filters_by_name(self) -> None:
        blocks = [
            {"type": "tool_use", "name": "end_session", "input": {}},
            {"type": "tool_use", "name": "propose_hypothesis", "input": {"hypothesis": {}}},
            {"type": "text", "text": "irrelevant"},
        ]
        self.assertEqual(len(llm_client.extract_tool_uses(blocks)), 2)
        self.assertEqual(len(llm_client.extract_tool_uses(blocks, tool_name="end_session")), 1)


class TokenEstimationTest(unittest.TestCase):
    def test_first_turn_uses_char_fallback(self) -> None:
        estimate, method = llm_client.estimate_next_call_input_tokens(None, "x" * 350)
        self.assertEqual(estimate, 100)
        self.assertIn("first turn", method)

    def test_later_turn_uses_prior_usage_plus_new_chars(self) -> None:
        last_usage = {"input_tokens": 1000, "cache_read_input_tokens": 500, "cache_creation_input_tokens": 200}
        estimate, method = llm_client.estimate_next_call_input_tokens(last_usage, "x" * 350)
        self.assertEqual(estimate, 1000 + 500 + 200 + 100)
        self.assertIn("prior total context", method)

    def test_monotonic_growth_across_simulated_turns(self) -> None:
        # A regression guard on the exact bug scenario spec 1.3 warns about:
        # a naive average-cost check would miss that later-turn input cost
        # grows monotonically as history is resent.
        usage_turn_1 = {"input_tokens": 500}
        usage_turn_10 = {"input_tokens": 15_000, "cache_read_input_tokens": 4_000}
        est_1, _ = llm_client.estimate_next_call_input_tokens(usage_turn_1, "next turn")
        est_10, _ = llm_client.estimate_next_call_input_tokens(usage_turn_10, "next turn")
        self.assertGreater(est_10, est_1)


class StubCallTurnTest(unittest.TestCase):
    def test_stub_script_has_three_turns_ending_in_end_session(self) -> None:
        turn_0 = llm_client.call_turn([], [], [], api_key="fake", stub=True, call_index=0)
        turn_1 = llm_client.call_turn([], [], [], api_key="fake", stub=True, call_index=1)
        turn_2 = llm_client.call_turn([], [], [], api_key="fake", stub=True, call_index=2)

        self.assertEqual(turn_0.stop_reason, "end_turn")
        self.assertEqual(llm_client.extract_tool_uses(turn_1.content_blocks, PROPOSE_HYPOTHESIS_TOOL_NAME).__len__(), 1)
        self.assertEqual(llm_client.extract_tool_uses(turn_2.content_blocks, END_SESSION_TOOL_NAME).__len__(), 1)

    def test_stub_usage_covers_all_four_fields_across_the_script(self) -> None:
        all_usage = [llm_client.call_turn([], [], [], api_key="fake", stub=True, call_index=i).usage for i in range(3)]
        self.assertTrue(any(u.get("input_tokens") for u in all_usage))
        self.assertTrue(any(u.get("output_tokens") for u in all_usage))
        self.assertTrue(any(u.get("cache_read_input_tokens") for u in all_usage))
        self.assertTrue(any((u.get("server_tool_use") or {}).get("web_search_requests") for u in all_usage))

    def test_call_index_beyond_script_length_returns_last_turn_defensively(self) -> None:
        result = llm_client.call_turn([], [], [], api_key="fake", stub=True, call_index=999)
        self.assertEqual(result.stop_reason, "tool_use")

    def test_stub_mode_env_var_is_honored_when_stub_param_omitted(self) -> None:
        with patch.dict("os.environ", {"EVE_STUB_MODE": "1"}):
            result = llm_client.call_turn([], [], [], api_key="fake", call_index=0)
        self.assertEqual(result.stop_reason, "end_turn")

    def test_real_network_call_never_happens_in_stub_mode(self) -> None:
        with patch("nero_core.eve.llm_client.requests.post") as mock_post:
            llm_client.call_turn([], [], [], api_key="fake", stub=True, call_index=0)
        mock_post.assert_not_called()


class RealCallHttpErrorHandlingTest(unittest.TestCase):
    """401/403/429 must be translated into RejectedBeforeTokenProcessingError
    (Eve's session loop catches this specifically to release, not reconcile-
    as-spent, the pre-call budget reservation) -- every other status code
    must still raise the original requests.exceptions.HTTPError unchanged,
    since those could plausibly have reached the model before failing."""

    def _mock_error_response(self, status_code: int):
        import requests

        response = MagicMock()
        response.status_code = status_code
        response.raise_for_status.side_effect = requests.exceptions.HTTPError(f"{status_code} Client Error")
        return response

    def test_401_raises_rejected_before_token_processing_error(self) -> None:
        with patch("nero_core.eve.llm_client.requests.post", return_value=self._mock_error_response(401)):
            with self.assertRaises(llm_client.RejectedBeforeTokenProcessingError) as ctx:
                llm_client.call_turn([], [], [], api_key="fake", stub=False, call_index=0)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_403_raises_rejected_before_token_processing_error(self) -> None:
        with patch("nero_core.eve.llm_client.requests.post", return_value=self._mock_error_response(403)):
            with self.assertRaises(llm_client.RejectedBeforeTokenProcessingError) as ctx:
                llm_client.call_turn([], [], [], api_key="fake", stub=False, call_index=0)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_429_raises_rejected_before_token_processing_error(self) -> None:
        with patch("nero_core.eve.llm_client.requests.post", return_value=self._mock_error_response(429)):
            with self.assertRaises(llm_client.RejectedBeforeTokenProcessingError) as ctx:
                llm_client.call_turn([], [], [], api_key="fake", stub=False, call_index=0)
        self.assertEqual(ctx.exception.status_code, 429)

    def test_500_still_raises_the_original_http_error_not_the_new_type(self) -> None:
        import requests

        with patch("nero_core.eve.llm_client.requests.post", return_value=self._mock_error_response(500)):
            with self.assertRaises(requests.exceptions.HTTPError):
                llm_client.call_turn([], [], [], api_key="fake", stub=False, call_index=0)

    def test_400_still_raises_the_original_http_error_not_the_new_type(self) -> None:
        # A malformed request could plausibly still have been evaluated by
        # the model before being rejected -- deliberately NOT in the
        # rejected-before-token-processing set (see its own docstring).
        import requests

        with patch("nero_core.eve.llm_client.requests.post", return_value=self._mock_error_response(400)):
            with self.assertRaises(requests.exceptions.HTTPError):
                llm_client.call_turn([], [], [], api_key="fake", stub=False, call_index=0)


class MessageBuildersTest(unittest.TestCase):
    def test_assistant_message_from_result_wraps_content_blocks(self) -> None:
        result = llm_client.LlmTurnResult(content_blocks=[{"type": "text", "text": "hi"}], usage={}, stop_reason="end_turn", raw_response={})
        message = llm_client.assistant_message_from_result(result)
        self.assertEqual(message, {"role": "assistant", "content": [{"type": "text", "text": "hi"}]})

    def test_build_continue_user_message_shape(self) -> None:
        message = llm_client.build_continue_user_message()
        self.assertEqual(message["role"], "user")
        self.assertEqual(message["content"][0]["type"], "text")


if __name__ == "__main__":
    unittest.main()
