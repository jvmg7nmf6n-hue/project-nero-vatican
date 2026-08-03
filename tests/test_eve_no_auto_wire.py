"""HARD TEST (per this branch's own spec): Eve must never auto-wire into
Adam's live scheduler or strategy registry, and -- Eve's OWN, additional
isolation requirement beyond what Repair Lab needed -- nero_core/eve/ must
never import from nero_core/research_agent/ at all, with exactly ONE
documented, narrow exception (nero_core.eve.scoring, which must reuse
Adam's real statistical harness per spec 3.1 -- see that module's own
extensive docstring for why).

THREE independent checks, extending tests/test_research_agent_no_auto_wire.py's
own proven static+dynamic pattern:
1. STATIC (live_scheduler/default_registry) -- reuses _forbidden_references
   from that module directly, unmodified, pointed at nero_core/eve/*.py.
2. STATIC (research_agent import boundary) -- every nero_core/eve/*.py file
   is scanned for ANY `from nero_core.research_agent...` / `import
   nero_core.research_agent...`. Every file except scoring.py must have
   ZERO such imports. scoring.py's own imports must be EXACTLY the named
   allowlist below -- not "scoring.py gets a free pass," a bounded one.
3. DYNAMIC -- a full stubbed Eve pipeline run (LLM calls stubbed, kill
   switch forced on) leaves nero_core.strategies.registry.default_registry's
   variant count completely unchanged, exactly like the Repair Lab/Research
   Agent's own dynamic check.
"""
from __future__ import annotations

import ast
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from nero_core.eve import pipeline, storage
from tests.test_research_agent_no_auto_wire import _forbidden_references

EVE_DIR = Path(__file__).resolve().parents[1] / "nero_core" / "eve"

# The ONLY nero_core.research_agent imports any nero_core/eve/*.py file may
# have -- all in scoring.py, all named, public (non-underscore) functions
# needed to reuse Adam's real harness. Anything else is an offense.
SCORING_ALLOWED_IMPORTS = {
    ("nero_core.research_agent.rule_dsl", "RuleAmbiguousError"),
    ("nero_core.research_agent.rule_dsl", "parse_bidirectional_entry_rules"),
    ("nero_core.research_agent.rule_dsl", "parse_exit_plan"),
    ("nero_core.research_agent.auto_tester", "test_hypothesis"),
    # Added for the testability/verdict_combined reconciliation (Session
    # 0-B follow-up): scoring.py must compare against Adam's own literal
    # VERDICT_UNTESTABLE string, reused directly rather than re-typed as a
    # magic "UNTESTABLE" literal that could silently drift from it.
    ("nero_core.research_agent.auto_tester", "VERDICT_UNTESTABLE"),
}


def _research_agent_imports(path: Path) -> set[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("nero_core.research_agent"):
            for alias in node.names:
                found.add((node.module, alias.name))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("nero_core.research_agent"):
                    found.add((alias.name, "*"))
    return found


def _make_candles(n: int = 600) -> pd.DataFrame:
    import random

    rng = random.Random(11)
    rows = []
    price = 100.0
    t0 = 1_700_000_000_000
    for i in range(n):
        price *= 1 + rng.uniform(-0.01, 0.01)
        rows.append({"close_time": t0 + i * 3_600_000, "close": price, "high": price * 1.004, "low": price * 0.996, "volume": 1.0})
    return pd.DataFrame(rows)


class StaticLiveSchedulerRegistryTest(unittest.TestCase):
    def test_no_eve_source_file_references_the_live_scheduler_or_registry(self) -> None:
        py_files = sorted(EVE_DIR.glob("*.py"))
        self.assertGreater(len(py_files), 0, "expected to find nero_core/eve/*.py source files -- test setup is broken")

        offenders: dict[str, list[str]] = {}
        for path in py_files:
            hits = _forbidden_references(path)
            if hits:
                offenders[path.name] = hits
        self.assertEqual(offenders, {}, f"forbidden live-scheduler/registry references found: {offenders}")


class StaticResearchAgentImportBoundaryTest(unittest.TestCase):
    def test_only_scoring_imports_from_research_agent_and_only_the_named_targets(self) -> None:
        py_files = sorted(EVE_DIR.glob("*.py"))
        offenders: dict[str, set] = {}
        for path in py_files:
            imports = _research_agent_imports(path)
            if not imports:
                continue
            if path.name != "scoring.py":
                offenders[path.name] = imports
                continue
            unexpected = imports - SCORING_ALLOWED_IMPORTS
            if unexpected:
                offenders[path.name] = unexpected
        self.assertEqual(offenders, {}, f"unexpected nero_core.research_agent imports: {offenders}")

    def test_scoring_module_actually_imports_the_expected_targets(self) -> None:
        # Sanity check: this test isn't vacuously passing because scoring.py
        # imports nothing from research_agent at all.
        imports = _research_agent_imports(EVE_DIR / "scoring.py")
        self.assertTrue(SCORING_ALLOWED_IMPORTS.issubset(imports), f"scoring.py is missing expected imports: {SCORING_ALLOWED_IMPORTS - imports}")

    def test_the_check_itself_would_catch_a_real_offender(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("from nero_core.research_agent.repair_lab import check_eligibility\n")
            temp_path = Path(f.name)
        try:
            imports = _research_agent_imports(temp_path)
            self.assertIn(("nero_core.research_agent.repair_lab", "check_eligibility"), imports)
        finally:
            temp_path.unlink(missing_ok=True)


class DynamicNoAutoWireTest(unittest.TestCase):
    def test_full_stub_pipeline_never_changes_the_strategy_registry(self) -> None:
        from nero_core.strategies.registry import default_registry

        before_count = len(default_registry.all_variants())

        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            candles = _make_candles()
            with patch.object(storage, "DEFAULT_HYPOTHESES_PATH", tmp_root / "eve_hypotheses.json"), \
                 patch.object(storage, "DEFAULT_BUDGET_LEDGER_PATH", tmp_root / "eve_budget_ledger.json"), \
                 patch.object(storage, "EVE_SESSIONS_DIR", tmp_root / "eve_sessions"), \
                 patch("nero_core.eve.context.DEFAULT_QUANT_METRICS_PATH", tmp_root / "quant_metrics.json"), \
                 patch("nero_core.eve.context.DEFAULT_FAILURE_PATTERNS_PATH", tmp_root / "failure_patterns.json"), \
                 patch("nero_core.eve.context.DEFAULT_ADAM_HYPOTHESES_PATH", tmp_root / "agent_hypotheses.json"), \
                 patch("nero_core.eve.notify.send_ntfy_notification", return_value=True), \
                 patch.dict("os.environ", {"EVE_ENABLED": "true"}):
                result = pipeline.run_pipeline(
                    api_key="fake", stub=True, candles_provider=lambda a, t: candles, now=datetime(2026, 8, 15, tzinfo=timezone.utc)
                )

        # this stub run proposes a hypothesis engineered to plausibly test
        # cleanly through the real harness -- the whole point of this test
        # is that even a strong-looking, fully-scored result never touches
        # the registry.
        self.assertTrue(result.enabled)
        after_count = len(default_registry.all_variants())
        self.assertEqual(before_count, after_count)


if __name__ == "__main__":
    unittest.main()
