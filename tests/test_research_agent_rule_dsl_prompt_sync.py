"""CC-1 directive (2026-08-06): regression guard against
hypothesis_gen.py's two LLM prompts silently drifting away from
rule_dsl.py's own real ALLOWED_FIELDS/ALLOWED_OPS again.

Real incident this guards against: the scanner-path prompt was missing
adx14/bb_lower/bb_upper, and the web-search-path prompt was missing
bb_lower/bb_upper -- both real, already-computed DSL fields the model was
never told it could use, discovered only by manually diffing the prompt
text against ALLOWED_FIELDS. hypothesis_gen.py now builds both prompts'
field/op lists directly from rule_dsl.ALLOWED_FIELDS/ALLOWED_OPS (see
_DSL_FIELDS_PROMPT_TEXT/_DSL_OPS_PROMPT_TEXT), which makes this class of
drift structurally impossible, not just tested-for -- this test is
insurance against a future edit reverting to a hand-typed list."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from nero_core.research_agent.hypothesis_gen import _build_prompt, _build_web_search_prompt
from nero_core.research_agent.rule_dsl import ALLOWED_FIELDS, ALLOWED_OPS
from nero_core.research_agent.scanner import ScanFinding

NOW = datetime(2026, 7, 31, tzinfo=timezone.utc)


def _finding() -> ScanFinding:
    return ScanFinding("extreme_zscore", "BTC", "1h", "BTC/1h extreme z-score", 3.0, 42.0, "measured note", NOW.isoformat())


class PromptFieldSyncTest(unittest.TestCase):
    def test_scanner_prompt_mentions_every_allowed_field(self) -> None:
        prompt = _build_prompt(_finding(), [])
        for field in ALLOWED_FIELDS:
            self.assertIn(field, prompt, f"{field!r} missing from the scanner-path prompt")

    def test_scanner_prompt_mentions_every_allowed_op(self) -> None:
        prompt = _build_prompt(_finding(), [])
        for op in ALLOWED_OPS:
            self.assertIn(op, prompt, f"{op!r} missing from the scanner-path prompt")

    def test_web_search_prompt_mentions_every_allowed_field(self) -> None:
        prompt = _build_web_search_prompt([("BTC", "1h")], [], [])
        for field in ALLOWED_FIELDS:
            self.assertIn(field, prompt, f"{field!r} missing from the web-search-path prompt")

    def test_web_search_prompt_mentions_every_allowed_op(self) -> None:
        prompt = _build_web_search_prompt([("BTC", "1h")], [], [])
        for op in ALLOWED_OPS:
            self.assertIn(op, prompt, f"{op!r} missing from the web-search-path prompt")
