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
