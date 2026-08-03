from __future__ import annotations

import unittest
from datetime import datetime, timezone

from nero_core.eve import random_baseline


class AllowedFieldsCopyTest(unittest.TestCase):
    def test_byte_identical_to_adams_allowed_fields(self) -> None:
        from nero_core.research_agent.rule_dsl import ALLOWED_FIELDS as ADAM_ALLOWED_FIELDS

        self.assertEqual(random_baseline.ALLOWED_FIELDS_COPY, ADAM_ALLOWED_FIELDS)


class GenerateRandomBaselineTest(unittest.TestCase):
    def test_generates_at_least_200_by_default(self) -> None:
        result = random_baseline.generate_random_baseline("BTC", "1h", now=datetime(2026, 8, 1, tzinfo=timezone.utc))
        self.assertGreaterEqual(len(result), 200)

    def test_deterministic_for_same_seed(self) -> None:
        now = datetime(2026, 8, 1, tzinfo=timezone.utc)
        a = random_baseline.generate_random_baseline("BTC", "1h", now=now, k=20, seed=42)
        b = random_baseline.generate_random_baseline("BTC", "1h", now=now, k=20, seed=42)
        self.assertEqual(a, b)

    def test_different_seed_gives_different_output(self) -> None:
        now = datetime(2026, 8, 1, tzinfo=timezone.utc)
        a = random_baseline.generate_random_baseline("BTC", "1h", now=now, k=20, seed=1)
        b = random_baseline.generate_random_baseline("BTC", "1h", now=now, k=20, seed=2)
        self.assertNotEqual(a, b)

    def test_every_hypothesis_has_asset_and_timeframe_set(self) -> None:
        result = random_baseline.generate_random_baseline("GOLD", "4h", now=datetime(2026, 8, 1, tzinfo=timezone.utc), k=10)
        self.assertTrue(all(h["asset"] == "GOLD" and h["timeframe"] == "4h" for h in result))

    def test_hypothesis_names_are_unique(self) -> None:
        result = random_baseline.generate_random_baseline("BTC", "1h", now=datetime(2026, 8, 1, tzinfo=timezone.utc), k=50)
        names = [h["hypothesis_name"] for h in result]
        self.assertEqual(len(names), len(set(names)))


class SampledHypothesisShapeTest(unittest.TestCase):
    def test_structured_entry_rule_is_parseable_by_adams_dsl(self) -> None:
        # The whole point of this generator: its output must actually run
        # through the real rule_dsl parser unmodified, not just look
        # plausible. This confirms it, without duplicating the parser here.
        from nero_core.research_agent.rule_dsl import parse_structured_rule

        result = random_baseline.generate_random_baseline("BTC", "1h", now=datetime(2026, 8, 1, tzinfo=timezone.utc), k=100)
        parsed_ok = 0
        for h in result:
            try:
                parse_structured_rule(h["structured_entry_rule"])
                parsed_ok += 1
            except Exception as exc:  # pragma: no cover - diagnostic on failure
                self.fail(f"sampled structured_entry_rule failed to parse: {h['structured_entry_rule']} ({exc})")
        self.assertEqual(parsed_ok, 100)

    def test_structured_exit_plan_is_parseable_by_adams_dsl(self) -> None:
        from nero_core.research_agent.rule_dsl import parse_exit_plan

        result = random_baseline.generate_random_baseline("BTC", "1h", now=datetime(2026, 8, 1, tzinfo=timezone.utc), k=100)
        for h in result:
            parse_exit_plan(h["structured_exit_plan"])  # raises on failure -- no try/except needed

    def test_price_scale_fields_never_compared_against_a_fixed_value(self) -> None:
        result = random_baseline.generate_random_baseline("BTC", "1h", now=datetime(2026, 8, 1, tzinfo=timezone.utc), k=200)
        for h in result:
            for cond in h["structured_entry_rule"]["conditions"]:
                if cond["field"] in random_baseline._FIELD_VS_FIELD_ONLY:
                    self.assertIn("compare_to_field", cond, f"price-scale field {cond['field']!r} must never use a fixed value")


class NoLlmCallsOrLedgerImpactTest(unittest.TestCase):
    def test_module_never_imports_llm_client_or_budget_ledger(self) -> None:
        import ast
        import inspect

        tree = ast.parse(inspect.getsource(random_baseline))
        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.add(alias.name)
        self.assertNotIn("nero_core.eve.llm_client", imported_modules)
        self.assertNotIn("nero_core.eve.budget_ledger", imported_modules)

    def test_generating_a_baseline_writes_no_ledger_entries(self) -> None:
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from nero_core.eve import storage

        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "eve_budget_ledger.json"
            with patch.object(storage, "DEFAULT_BUDGET_LEDGER_PATH", ledger_path):
                random_baseline.generate_random_baseline("BTC", "1h", now=datetime(2026, 8, 1, tzinfo=timezone.utc), k=50)
            self.assertFalse(ledger_path.exists(), "baseline generation must never touch the budget ledger -- $0.00 cost")


if __name__ == "__main__":
    unittest.main()
