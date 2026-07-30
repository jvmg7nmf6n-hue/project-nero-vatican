"""HARD TEST (required by the branch's own task spec): nothing in
nero_core.research_agent may automatically write to the live scheduler's
config or to the strategy registry. SURVIVED/PROMISING-WATCHLIST hypotheses
get review_status="pending_human_approval" and stop there -- a human, not
this code, decides whether anything ever gets registered or scheduled.

Two independent checks:
1. STATIC -- every .py source file under nero_core/research_agent/ is parsed
   with `ast` (not a text/substring scan -- several of these modules' own
   safety docstrings NAME live_scheduler/default_registry in prose to explain
   why they're avoided, which a substring scan would misflag) and walked for
   an actual import of live_scheduler, an actual import of
   default_registry, or any Name/Attribute reference to default_registry.
   This is also import-order-independent, unlike a dynamic sys.modules check,
   which would be contaminated by whatever other test files already imported
   earlier in the same `python -m unittest discover` process.
2. DYNAMIC -- running the full pipeline end-to-end (LLM/network calls mocked
   out, kill switch forced on) leaves nero_core.strategies.registry.
   default_registry's variant count completely unchanged.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path
from unittest.mock import patch

from nero_core.research_agent.pipeline import run_pipeline
from nero_core.research_agent.scanner import ScanFinding, ScanResult
from nero_core.strategies.registry import default_registry

RESEARCH_AGENT_DIR = Path(__file__).resolve().parents[1] / "nero_core" / "research_agent"


def _forbidden_references(path: Path) -> list[str]:
    """Real code references only -- comments and docstrings (plain string
    literals to `ast`) are structurally invisible to this walk."""
    tree = ast.parse(path.read_text(), filename=str(path))
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if "live_scheduler" in alias.name:
                    hits.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if "live_scheduler" in module:
                hits.append(f"from {module} import ...")
            if module.endswith("strategies.registry"):
                for alias in node.names:
                    if alias.name == "default_registry":
                        hits.append(f"from {module} import default_registry")
        elif isinstance(node, ast.Name) and node.id == "default_registry":
            hits.append("reference to name 'default_registry'")
        elif isinstance(node, ast.Attribute) and node.attr == "default_registry":
            hits.append("attribute access .default_registry")
    return hits


class StaticNoAutoWireTest(unittest.TestCase):
    def test_no_research_agent_source_file_references_the_live_scheduler_or_registry(self) -> None:
        py_files = sorted(RESEARCH_AGENT_DIR.glob("*.py"))
        self.assertGreater(len(py_files), 0, "expected to find research_agent source files -- test setup is broken")

        offenders: dict[str, list[str]] = {}
        for path in py_files:
            hits = _forbidden_references(path)
            if hits:
                offenders[path.name] = hits

        self.assertEqual(offenders, {}, f"forbidden live-scheduler/registry references found: {offenders}")

    def test_the_check_itself_would_catch_a_real_offender(self) -> None:
        """Sanity check on the AST walk: a file that genuinely imports
        default_registry must be flagged, proving this isn't a no-op check."""
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("from nero_core.strategies.registry import default_registry\n")
            f.write("default_registry.register('X', 'v1', {})\n")
            temp_path = Path(f.name)
        try:
            hits = _forbidden_references(temp_path)
            self.assertGreater(len(hits), 0)
        finally:
            temp_path.unlink(missing_ok=True)


class DynamicNoAutoWireTest(unittest.TestCase):
    def test_full_pipeline_run_never_changes_the_strategy_registry(self) -> None:
        before_count = len(default_registry.all_variants())

        finding = ScanFinding(
            "extreme_zscore", "BTC", "1h", "BTC/1h extreme z-score", 3.0, 40.0, "measured note", "2026-07-29T00:00:00+00:00"
        )
        scan_result = ScanResult([finding], [], [], [], [])
        hypothesis_record = {
            "hypothesis_name": "SURVIVED_CANDIDATE", "asset": "BTC", "timeframe": "1h",
            "generated_at": "2026-07-29T00:00:00+00:00",
            "structured_entry_rule": {"conditions": [{"field": "ret_1", "op": "gt", "value": -1.0}]},
            "structured_exit_plan": {"stop_atr_multiple": 1.5, "target_r_multiple": 2.0, "max_holding_hours": 24.0},
        }

        import pandas as pd

        n = 400
        rows = []
        price = 100.0
        for i in range(n):
            price *= 1.003
            rows.append({"close_time": 1_700_000_000_000 + i * 3_600_000, "close": price, "high": price * 1.004, "low": price * 0.999, "volume": 1.0})
        fake_candles = pd.DataFrame(rows)

        with patch("nero_core.research_agent.pipeline.is_enabled", return_value=True), \
             patch("nero_core.research_agent.pipeline.scanner.run_scan", return_value=scan_result), \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.load_existing_hypotheses", return_value=[]), \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.generate_hypotheses") as mock_generate, \
             patch("nero_core.research_agent.pipeline.hypothesis_gen.persist_hypotheses"), \
             patch("nero_core.research_agent.pipeline.auto_tester.persist_test_results"), \
             patch("nero_core.research_agent.pipeline.performance.record_run"):
            from nero_core.research_agent.hypothesis_gen import GenerationRunResult

            mock_generate.return_value = GenerationRunResult(hypotheses=[hypothesis_record])
            result = run_pipeline(candles_provider=lambda asset, timeframe: fake_candles)

        # this hypothesis is engineered to plausibly SURVIVE/WATCHLIST -- the whole point
        # of this test is that even a strong-looking result never touches the registry.
        self.assertTrue(result.enabled)
        after_count = len(default_registry.all_variants())
        self.assertEqual(before_count, after_count)


if __name__ == "__main__":
    unittest.main()
