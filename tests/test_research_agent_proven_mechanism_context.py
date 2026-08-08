"""CC-1 directive Part C5: Adam's own prompts (scanner-triggered and
web-search) include the same real proven-mechanism reference channel Eve's
system prompt carries -- independently implemented (no cross-import), same
real source files."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from nero_core.research_agent import hypothesis_gen
from nero_core.research_agent.scanner import ScanFinding

NOW = datetime(2026, 8, 8, tzinfo=timezone.utc)


def _finding() -> ScanFinding:
    return ScanFinding("extreme_zscore", "BTC", "4h", "BTC/4h extreme z-score", -2.3, 40.0, "measured note", NOW.isoformat())


class LoadProvenMechanismsTest(unittest.TestCase):
    def test_real_committed_data_yields_all_3_survivors(self) -> None:
        mechanisms = hypothesis_gen.load_proven_mechanisms()
        self.assertEqual(
            [m["name"] for m in mechanisms], ["BREAKOUT_MOMENTUM", "TREND_PULLBACK", "COINTEGRATION_PAIRS"],
        )

    def test_missing_files_return_empty_not_a_crash(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        mechanisms = hypothesis_gen.load_proven_mechanisms(
            descriptions_path=tmp / "nope.json", strategies_path=tmp / "also_nope.json",
        )
        self.assertEqual(mechanisms, [])


class PromptsIncludeProvenMechanismsTest(unittest.TestCase):
    def test_scanner_prompt_includes_the_real_channel_when_mechanisms_are_passed(self) -> None:
        mechanisms = hypothesis_gen.load_proven_mechanisms()
        prompt = hypothesis_gen._build_prompt(_finding(), [], mechanisms)
        self.assertIn("PROVEN MECHANISM REFERENCE", prompt)
        self.assertIn("BREAKOUT_MOMENTUM", prompt)

    def test_scanner_prompt_omits_the_block_entirely_when_no_mechanisms_given(self) -> None:
        # Backward-compatible default: every existing call site that doesn't
        # pass proven_mechanisms must render exactly as before this directive.
        prompt = hypothesis_gen._build_prompt(_finding(), [])
        self.assertNotIn("PROVEN MECHANISM REFERENCE", prompt)

    def test_web_search_prompt_includes_the_real_channel_when_mechanisms_are_passed(self) -> None:
        mechanisms = hypothesis_gen.load_proven_mechanisms()
        prompt = hypothesis_gen._build_web_search_prompt([("BTC", "4h")], [], [], mechanisms)
        self.assertIn("PROVEN MECHANISM REFERENCE", prompt)
        self.assertIn("COINTEGRATION_PAIRS", prompt)

    def test_web_search_prompt_omits_the_block_entirely_when_no_mechanisms_given(self) -> None:
        prompt = hypothesis_gen._build_web_search_prompt([("BTC", "4h")], [], [])
        self.assertNotIn("PROVEN MECHANISM REFERENCE", prompt)


if __name__ == "__main__":
    unittest.main()
