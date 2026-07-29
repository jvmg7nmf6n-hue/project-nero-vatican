"""Tests for pipeline.main() -- the CLI entrypoint added 2026-07-30 to close
the gap flagged in docs/research_agent_real_run_followup.md: nothing in
nero_core/research_agent previously read ANTHROPIC_API_KEY from the
environment itself (every function took `api_key` as an explicit parameter
only). `main()` reads it once via `os.getenv`, matching nero_core.execution.
live_scheduler.py's own `claude_key = os.getenv("ANTHROPIC_API_KEY", "")`
pattern, and must never print the value it read."""
from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from nero_core.research_agent.pipeline import PipelineRunResult, main

FAKE_SECRET = "sk-ant-TESTSECRET-do-not-leak-4f9a2b7c"


def _dummy_result(**overrides) -> PipelineRunResult:
    base = dict(
        enabled=True, reason="", hypotheses_generated=2, duplicates_skipped=1,
        llm_calls_made=2, total_llm_cost_usd=0.0123, cost_limit_hit=False,
        too_slow_rejected=1, unmeasurable_rejected=0, survived=0,
        promising_watchlist=1, died=0, untestable=0, no_candles_available=0,
    )
    base.update(overrides)
    return PipelineRunResult(**base)


class MainEntrypointTest(unittest.TestCase):
    def test_main_reads_api_key_from_environment_and_passes_it_through(self) -> None:
        with patch("nero_core.research_agent.pipeline.os.getenv", return_value=FAKE_SECRET) as mock_getenv, \
             patch("nero_core.research_agent.pipeline.run_pipeline", return_value=_dummy_result()) as mock_run:
            main()

        mock_getenv.assert_called_once_with("ANTHROPIC_API_KEY", "")
        mock_run.assert_called_once_with(api_key=FAKE_SECRET)

    def test_main_defaults_to_empty_string_when_env_var_unset(self) -> None:
        with patch("nero_core.research_agent.pipeline.os.getenv", return_value="") as mock_getenv, \
             patch("nero_core.research_agent.pipeline.run_pipeline", return_value=_dummy_result()) as mock_run:
            main()

        mock_run.assert_called_once_with(api_key="")

    def test_main_never_prints_the_api_key_value(self) -> None:
        buffer = io.StringIO()
        with patch("nero_core.research_agent.pipeline.os.getenv", return_value=FAKE_SECRET), \
             patch("nero_core.research_agent.pipeline.run_pipeline", return_value=_dummy_result()):
            with redirect_stdout(buffer):
                main()

        self.assertNotIn(FAKE_SECRET, buffer.getvalue())

    def test_main_prints_only_aggregate_non_secret_counts(self) -> None:
        buffer = io.StringIO()
        with patch("nero_core.research_agent.pipeline.os.getenv", return_value=FAKE_SECRET), \
             patch("nero_core.research_agent.pipeline.run_pipeline", return_value=_dummy_result(survived=3, died=5)):
            with redirect_stdout(buffer):
                main()

        output = buffer.getvalue()
        self.assertIn("hypotheses_generated=2", output)
        self.assertIn("survived=3", output)
        self.assertIn("died=5", output)


if __name__ == "__main__":
    unittest.main()
