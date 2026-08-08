from __future__ import annotations

import ast
import inspect
import json
import tempfile
import unittest
from pathlib import Path

from nero_core.eve import context


def _non_docstring_string_constants(tree: ast.AST) -> list[str]:
    """Every string literal in `tree` that is NOT a module/function/class
    docstring -- an ast-based scan (like test_research_agent_no_auto_wire.py's
    own _forbidden_references), not a substring scan, because this module's
    docstrings legitimately NAME "agent_test_results.json" in prose to
    explain why it's avoided (the exact situation that test's own docstring
    warns a naive substring scan would misflag)."""
    docstring_node_ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                docstring_node_ids.add(id(body[0].value))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstring_node_ids
    ]


class NeverReadsTestResultsTest(unittest.TestCase):
    def test_module_never_constructs_a_path_to_agent_test_results(self) -> None:
        # Structural guarantee: no REAL code (as opposed to docstring prose)
        # in this module ever references "agent_test_results" -- the export
        # that actually carries verdicts.
        tree = ast.parse(inspect.getsource(context))
        offenders = [s for s in _non_docstring_string_constants(tree) if "agent_test_results" in s]
        self.assertEqual(offenders, [])

    def test_whitelist_tuple_excludes_verdict_like_fields(self) -> None:
        banned = {"verdict", "review_status", "cost_usd", "verdict_is", "verdict_oos", "truth_label"}
        self.assertEqual(banned & set(context._ADAM_HISTORY_FIELDS), set())


class VerdictStrippingBehaviorTest(unittest.TestCase):
    def test_whitelisted_fields_only_survive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent_hypotheses.json"
            path.write_text(json.dumps([
                {
                    "hypothesis_name": "X", "mechanism": "because reasons", "asset": "BTC", "timeframe": "1h",
                    # Simulates a FUTURE schema drift where a verdict-like
                    # field gets added to agent_hypotheses.json directly --
                    # the whitelist must exclude it even though it's present
                    # in the raw record.
                    "verdict": "SURVIVED", "review_status": "pending_human_approval", "cost_usd": 0.01,
                }
            ]))
            stripped = context.load_adam_history_verdict_stripped(path=path)

        self.assertEqual(len(stripped), 1)
        record = stripped[0]
        self.assertNotIn("verdict", record)
        self.assertNotIn("review_status", record)
        self.assertNotIn("cost_usd", record)
        self.assertEqual(record["hypothesis_name"], "X")
        self.assertEqual(record["mechanism"], "because reasons")

    def test_missing_file_returns_empty_list(self) -> None:
        self.assertEqual(context.load_adam_history_verdict_stripped(path=Path("/nonexistent/agent_hypotheses.json")), [])

    def test_formatted_history_text_contains_no_verdict_language(self) -> None:
        stripped = [{"hypothesis_name": "X", "mechanism": "reasoning here", "asset": "BTC", "timeframe": "1h"}]
        text = context.format_adam_history(stripped)
        for banned in ("SURVIVED", "DIED", "PROMISING-WATCHLIST", "UNTESTABLE"):
            self.assertNotIn(banned, text)


class TrackedPairsAndGraveyardTest(unittest.TestCase):
    def test_load_tracked_asset_timeframes_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "quant_metrics.json"
            path.write_text(json.dumps({"metrics": [{"asset": "BTC", "timeframe": "1h"}, {"asset": "GOLD", "timeframe": "4h"}]}))
            pairs = context.load_tracked_asset_timeframes(path=path)
        self.assertEqual(pairs, [("BTC", "1h"), ("GOLD", "4h")])

    def test_load_tracked_asset_timeframes_missing_file(self) -> None:
        self.assertEqual(context.load_tracked_asset_timeframes(path=Path("/nonexistent/quant_metrics.json")), [])

    def test_load_graveyard_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "failure_patterns.json"
            path.write_text(json.dumps([{"name": "FVG_REVERSION", "family": "edge-over-random-negative"}]))
            patterns = context.load_graveyard(path=path)
        self.assertEqual(patterns[0]["name"], "FVG_REVERSION")


class PromptTextTest(unittest.TestCase):
    def test_as_prompt_text_handles_empty_context_gracefully(self) -> None:
        ctx = context.EveContext(tracked_pairs=[], graveyard=[], adam_history=[])
        text = ctx.as_prompt_text()
        self.assertIn("none currently tracked", text)
        self.assertIn("none on file", text)
        self.assertIn("REFERENCE ONLY", text)

    def test_as_prompt_text_never_a_constraint_language_present(self) -> None:
        ctx = context.EveContext(tracked_pairs=[("BTC", "1h")], graveyard=[], adam_history=[])
        text = ctx.as_prompt_text()
        self.assertIn("none of it constrains what", text)


class NearMissDefinitionTest(unittest.TestCase):
    """CC-1 directive, item B2 (2026-08-06): _is_near_miss's two real,
    data-derived halves."""

    def test_half_1_fdr_is_significant_oos_not(self) -> None:
        # The directive's own canonical example shape (BTC_MOMENTUM_
        # IGNITION): keyed off fdr_survives_is/fdr_survives_oos, NOT
        # verdict_is/verdict_oos -- a record's overall verdict can be DIED
        # even with an FDR-significant p_value_is (real, confirmed).
        record = {"fdr_survives_is": True, "fdr_survives_oos": False, "verdict_is": "DIED", "verdict_oos": "PROMISING_WATCHLIST"}
        self.assertTrue(context._is_near_miss(record))

    def test_half_1_fdr_oos_none_also_counts_as_not_true(self) -> None:
        record = {"fdr_survives_is": True, "fdr_survives_oos": None}
        self.assertTrue(context._is_near_miss(record))

    def test_half_2_positive_is_verdict_with_insufficient_oos_sample(self) -> None:
        record = {"verdict_is": "PROMISING_WATCHLIST", "verdict_oos": "INSUFFICIENT_SAMPLE"}
        self.assertTrue(context._is_near_miss(record))

    def test_half_2_survived_is_verdict_also_counts(self) -> None:
        record = {"verdict_is": "SURVIVED", "verdict_oos": "INSUFFICIENT_SAMPLE"}
        self.assertTrue(context._is_near_miss(record))

    def test_half_2_died_is_verdict_does_not_count_even_with_insufficient_oos_sample(self) -> None:
        # Real, confirmed data (PAXG_PEG_REVERSION): verdict_is=DIED,
        # verdict_oos=INSUFFICIENT_SAMPLE matches the DIRECTIVE'S LITERAL
        # wording ("IS produced a real verdict") but is not a promising
        # near-miss -- a died in-sample half is not an invitation to
        # refine. This is the refinement to the literal definition this
        # directive's own investigation found necessary.
        record = {"verdict_is": "DIED", "verdict_oos": "INSUFFICIENT_SAMPLE"}
        self.assertFalse(context._is_near_miss(record))

    def test_neither_half_matches_is_not_a_near_miss(self) -> None:
        record = {"fdr_survives_is": False, "fdr_survives_oos": False, "verdict_is": "DIED", "verdict_oos": "DIED"}
        self.assertFalse(context._is_near_miss(record))


class LoadNearMissesTest(unittest.TestCase):
    def _write(self, tmp, records) -> Path:
        path = Path(tmp) / "eve_hypotheses.json"
        path.write_text(json.dumps(records))
        return path

    def test_real_committed_data_yields_two_near_misses(self) -> None:
        # CC-1 directive, item B2: real count against the actual, currently
        # committed docs/site_data/eve_hypotheses.json -- re-derived here,
        # not assumed, so this test fails the moment that file's real
        # content changes in a way that changes the real count. Re-derived
        # 2026-08-08: ATR_EXHAUSTION_SNAPBACK_SOL_4H (proposed 2026-08-07,
        # fdr_survives_is=True/fdr_survives_oos=False, verdict_combined=DIED)
        # is a second, genuine near-miss added after BTC_MOMENTUM_IGNITION.
        near_misses = context.load_near_misses()
        names = [m["hypothesis_name"] for m in near_misses]
        self.assertEqual(names, ["BTC_MOMENTUM_IGNITION", "ATR_EXHAUSTION_SNAPBACK_SOL_4H"])

    def test_cap_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            records = [
                {
                    "raw_hypothesis": {"hypothesis_name": f"NM_{i}", "mechanism": "m"},
                    "fdr_survives_is": True, "fdr_survives_oos": False,
                }
                for i in range(15)
            ]
            path = self._write(tmp, records)
            near_misses = context.load_near_misses(path=path, cap=10)
        self.assertEqual(len(near_misses), 10)

    def test_non_near_miss_records_are_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            records = [
                {"raw_hypothesis": {"hypothesis_name": "DEAD", "mechanism": "m"}, "verdict_is": "DIED", "verdict_oos": "DIED"},
                {"raw_hypothesis": {"hypothesis_name": "REAL_NEAR_MISS", "mechanism": "m"}, "fdr_survives_is": True, "fdr_survives_oos": False},
            ]
            path = self._write(tmp, records)
            near_misses = context.load_near_misses(path=path)
        self.assertEqual([m["hypothesis_name"] for m in near_misses], ["REAL_NEAR_MISS"])

    def test_missing_file_returns_empty_list(self) -> None:
        self.assertEqual(context.load_near_misses(path=Path("/nonexistent/eve_hypotheses.json")), [])


class NearMissPromptTextTest(unittest.TestCase):
    def test_near_misses_appear_in_prompt_text_with_invitation_framing_not_verdict_language(self) -> None:
        near_misses = [{"hypothesis_name": "BTC_MOMENTUM_IGNITION", "mechanism": "m", "p_value_is": 0.0044, "p_value_oos": 0.224}]
        ctx = context.EveContext(tracked_pairs=[], graveyard=[], adam_history=[], near_misses=near_misses)
        text = ctx.as_prompt_text()
        self.assertIn("BTC_MOMENTUM_IGNITION", text)
        self.assertIn("INVITATION TO REFINE", text)
        self.assertIn("not a verdict", text)
        self.assertIn("derived_from", text)

    def test_near_miss_section_is_textually_distinct_from_the_graveyard_section(self) -> None:
        # "Keep strictly separate from the graveyard -- a near-miss is not
        # a death" (directive's own words) -- confirmed the two sections
        # use different framing language, not a shared/merged block.
        ctx = context.EveContext(
            tracked_pairs=[], graveyard=[{"name": "X", "family": "Y"}],
            adam_history=[], near_misses=[{"hypothesis_name": "Z", "mechanism": "m"}],
        )
        text = ctx.as_prompt_text()
        self.assertIn("KNOWN DEAD MECHANISMS", text)
        self.assertIn("NEAR-MISSES", text)
        self.assertIn("NOT dead", text)

    def test_empty_near_misses_shows_none_on_file(self) -> None:
        ctx = context.EveContext(tracked_pairs=[], graveyard=[], adam_history=[])
        text = ctx.as_prompt_text()
        self.assertIn("none on file", text)


if __name__ == "__main__":
    unittest.main()
