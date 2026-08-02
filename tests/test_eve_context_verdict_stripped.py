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


if __name__ == "__main__":
    unittest.main()
