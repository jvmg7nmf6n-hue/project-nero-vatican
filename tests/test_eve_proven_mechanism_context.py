"""CC-1 directive Part C: the proven-mechanism reference channel
(nero_core.eve.context.load_proven_mechanisms/format_proven_mechanisms) and
its structural guard -- a hypothesis can never declare derived_from pointing
at one of the 3 survivor strategies, since none of them has ever been
proposed by Adam or Eve (no real hypothesis_name record exists for any of
them in either agent's committed data)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from nero_core.eve import context, scoring

REAL_DESCRIPTIONS_PATH = context.DEFAULT_STRATEGY_DESCRIPTIONS_PATH
REAL_STRATEGIES_PATH = context.DEFAULT_STRATEGIES_PATH
REAL_ADAM_HYPOTHESES_PATH = context.DEFAULT_ADAM_HYPOTHESES_PATH
REAL_EVE_HYPOTHESES_PATH = context.DEFAULT_EVE_HYPOTHESES_PATH


class LoadProvenMechanismsTest(unittest.TestCase):
    def test_real_committed_data_yields_all_3_survivors_with_real_entry_exit_text(self) -> None:
        mechanisms = context.load_proven_mechanisms()
        names = [m["name"] for m in mechanisms]
        self.assertEqual(names, ["BREAKOUT_MOMENTUM", "TREND_PULLBACK", "COINTEGRATION_PAIRS"])
        for m in mechanisms:
            self.assertTrue(m["entry_rule"], f"{m['name']} missing a real entry_rule")
            self.assertTrue(m["exit_rule"], f"{m['name']} missing a real exit_rule")
            self.assertTrue(m["asset"], f"{m['name']} missing a real asset")
            self.assertTrue(m["verification_status"], f"{m['name']} missing a real verification_status")

    def test_missing_files_return_empty_not_a_crash(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        mechanisms = context.load_proven_mechanisms(
            descriptions_path=tmp / "nope.json", strategies_path=tmp / "also_nope.json",
        )
        self.assertEqual(mechanisms, [])


class FormatProvenMechanismsTest(unittest.TestCase):
    def test_empty_list_renders_an_honest_none_on_file(self) -> None:
        self.assertEqual(context.format_proven_mechanisms([]), "(none on file)")

    def test_real_data_renders_name_asset_timeframe_entry_and_exit(self) -> None:
        text = context.format_proven_mechanisms(context.load_proven_mechanisms())
        self.assertIn("BREAKOUT_MOMENTUM (GOLD/1week", text)
        self.assertIn("Entry:", text)
        self.assertIn("Exit:", text)


class EveContextIncludesProvenMechanismsTest(unittest.TestCase):
    def test_load_context_populates_proven_mechanisms_and_prompt_text_labels_it_correctly(self) -> None:
        ctx = context.load_context()
        self.assertEqual(len(ctx.proven_mechanisms), 3)
        prompt = ctx.as_prompt_text()
        self.assertIn("PROVEN MECHANISM REFERENCE, NOT A PARENT HYPOTHESIS", prompt)
        self.assertIn("BREAKOUT_MOMENTUM", prompt)
        # C5: the prompt must explicitly note Eve's own already-demonstrated
        # independent macro-conditioning capability, not frame this channel
        # as the only path to a novel idea.
        self.assertIn("PAXG_RISKOFF_VIX_SPIKE_LONG_4H", prompt)


class StructuralGuardNoDerivedFromParentAmongSurvivorsTest(unittest.TestCase):
    """C4: proves, against REAL committed data, that none of the 3 survivor
    names ever appears in the real union session.py's known_hypothesis_names
    is built from (Adam's agent_hypotheses.json + Eve's own
    eve_hypotheses.json) -- so validate_derived_from must reject a
    derived_from naming any of them, exactly as it would reject any other
    never-proposed name, with no special-case code required."""

    def test_none_of_the_3_survivor_names_exist_in_either_agents_real_hypothesis_history(self) -> None:
        adam_names = {
            h.get("hypothesis_name")
            for h in json.loads(REAL_ADAM_HYPOTHESES_PATH.read_text(encoding="utf-8"))
            if isinstance(h, dict)
        }
        eve_names = {
            (r.get("raw_hypothesis") or {}).get("hypothesis_name")
            for r in json.loads(REAL_EVE_HYPOTHESES_PATH.read_text(encoding="utf-8"))
            if isinstance(r, dict)
        }
        for name in context.PROVEN_MECHANISM_NAMES:
            self.assertNotIn(name, adam_names, f"{name} unexpectedly found in Adam's real hypothesis history")
            self.assertNotIn(name, eve_names, f"{name} unexpectedly found in Eve's real hypothesis history")

    def test_derived_from_naming_a_survivor_fails_validation_even_with_the_full_real_known_names_set(self) -> None:
        adam_names = {
            h.get("hypothesis_name")
            for h in json.loads(REAL_ADAM_HYPOTHESES_PATH.read_text(encoding="utf-8"))
            if isinstance(h, dict) and h.get("hypothesis_name")
        }
        eve_names = {
            (r.get("raw_hypothesis") or {}).get("hypothesis_name")
            for r in json.loads(REAL_EVE_HYPOTHESES_PATH.read_text(encoding="utf-8"))
            if isinstance(r, dict) and (r.get("raw_hypothesis") or {}).get("hypothesis_name")
        }
        known_hypothesis_names = adam_names | eve_names

        for survivor_name in context.PROVEN_MECHANISM_NAMES:
            raw_hypothesis = {
                "derived_from": {
                    "parent_hypothesis_name": survivor_name,
                    "parent_session_id": "eve-fake-session",
                    "what_changed": "different asset",
                    "why_this_change": "testing the guard",
                }
            }
            valid, reason = scoring.validate_derived_from(raw_hypothesis, known_hypothesis_names)
            self.assertFalse(valid, f"derived_from naming survivor {survivor_name!r} was incorrectly accepted")
            self.assertIn(survivor_name, reason)

    def test_a_genuinely_known_adam_or_eve_name_still_validates_normally(self) -> None:
        # Confirms the guard above isn't accidentally rejecting everything --
        # a real, known name still passes, exactly as before this directive.
        known_hypothesis_names = {"SOME_REAL_HYPOTHESIS_NAME"}
        raw_hypothesis = {
            "derived_from": {
                "parent_hypothesis_name": "SOME_REAL_HYPOTHESIS_NAME",
                "parent_session_id": "eve-real-session",
                "what_changed": "x",
                "why_this_change": "y",
            }
        }
        valid, _reason = scoring.validate_derived_from(raw_hypothesis, known_hypothesis_names)
        self.assertTrue(valid)


if __name__ == "__main__":
    unittest.main()
