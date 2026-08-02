from __future__ import annotations

import ast
import inspect
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from nero_core.eve import pipeline, storage
from nero_core.eve.config import _ENV_VAR as EVE_ENABLED_ENV_VAR


def _make_candles(n: int = 600) -> pd.DataFrame:
    import random

    rng = random.Random(7)
    rows = []
    price = 100.0
    t0 = 1_700_000_000_000
    for i in range(n):
        price *= 1 + rng.uniform(-0.01, 0.01)
        rows.append({"close_time": t0 + i * 3_600_000, "close": price, "high": price * 1.004, "low": price * 0.996, "volume": 1.0})
    return pd.DataFrame(rows)


class _IsolatedStorageTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp_root = Path(self._tmpdir.name)
        self.hypotheses_path = tmp_root / "eve_hypotheses.json"
        self.ledger_path = tmp_root / "eve_budget_ledger.json"
        self.sessions_dir = tmp_root / "eve_sessions"
        self._patches = [
            patch.object(storage, "DEFAULT_HYPOTHESES_PATH", self.hypotheses_path),
            patch.object(storage, "DEFAULT_BUDGET_LEDGER_PATH", self.ledger_path),
            patch.object(storage, "EVE_SESSIONS_DIR", self.sessions_dir),
            patch("nero_core.eve.context.DEFAULT_QUANT_METRICS_PATH", tmp_root / "quant_metrics.json"),
            patch("nero_core.eve.context.DEFAULT_FAILURE_PATTERNS_PATH", tmp_root / "failure_patterns.json"),
            patch("nero_core.eve.context.DEFAULT_ADAM_HYPOTHESES_PATH", tmp_root / "agent_hypotheses.json"),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()
        self._tmpdir.cleanup()


class KillSwitchTest(_IsolatedStorageTestCase):
    def test_disabled_pipeline_runs_no_session_and_writes_nothing(self) -> None:
        with patch.dict("os.environ", {EVE_ENABLED_ENV_VAR: "false"}):
            result = pipeline.run_pipeline(api_key="fake", stub=True)

        self.assertFalse(result.enabled)
        self.assertIsNone(result.session_result)
        self.assertFalse(self.hypotheses_path.exists())
        self.assertFalse(self.ledger_path.exists())


class EnabledStubPipelineTest(_IsolatedStorageTestCase):
    def test_full_pipeline_scores_the_stub_hypothesis(self) -> None:
        candles = _make_candles()
        with patch.dict("os.environ", {EVE_ENABLED_ENV_VAR: "true"}):
            result = pipeline.run_pipeline(
                api_key="fake", stub=True, candles_provider=lambda a, t: candles, now=datetime(2026, 8, 15, tzinfo=timezone.utc)
            )

        self.assertTrue(result.enabled)
        self.assertEqual(len(result.scored_hypotheses), 1)
        scored = result.scored_hypotheses[0]
        self.assertNotEqual(scored["testability"], "UNSCORED")

    def test_scored_hypotheses_are_persisted_back_to_eve_hypotheses_json(self) -> None:
        candles = _make_candles()
        with patch.dict("os.environ", {EVE_ENABLED_ENV_VAR: "true"}):
            pipeline.run_pipeline(api_key="fake", stub=True, candles_provider=lambda a, t: candles, now=datetime(2026, 8, 15, tzinfo=timezone.utc))

        on_disk = storage.read_json_list(self.hypotheses_path)
        self.assertEqual(len(on_disk), 1)
        self.assertNotEqual(on_disk[0]["testability"], "UNSCORED")
        self.assertIn("fdr_survives_oos", on_disk[0])

    def test_fdr_correction_applied_for_both_is_and_oos(self) -> None:
        candles = _make_candles()
        with patch.dict("os.environ", {EVE_ENABLED_ENV_VAR: "true"}):
            result = pipeline.run_pipeline(api_key="fake", stub=True, candles_provider=lambda a, t: candles, now=datetime(2026, 8, 15, tzinfo=timezone.utc))

        scored = result.scored_hypotheses[0]
        self.assertIn("fdr_survives_oos", scored)
        self.assertIn("fdr_survives_is", scored)

    def test_no_candle_data_still_completes_without_crashing(self) -> None:
        with patch.dict("os.environ", {EVE_ENABLED_ENV_VAR: "true"}):
            result = pipeline.run_pipeline(api_key="fake", stub=True, candles_provider=lambda a, t: None, now=datetime(2026, 8, 15, tzinfo=timezone.utc))

        self.assertTrue(result.enabled)
        self.assertEqual(result.lookahead_risk_flags, [])


class DefaultCandlesProviderResearchFallbackTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp_root = Path(self._tmpdir.name)
        self.site_dir = tmp_root / "site"
        self.research_dir = tmp_root / "research"
        self.site_dir.mkdir()
        self.research_dir.mkdir()

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _write(self, directory: Path, filename: str, n_candles: int) -> None:
        import json

        candles = [{"time": 1_700_000_000 + i * 14400, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1.0} for i in range(n_candles)]
        payload = {"schema_version": 1, "asset": "BTC", "timeframe": "4h", "last_updated": "2026-08-01T00:00:00+00:00", "candles": candles}
        (directory / filename).write_text(json.dumps(payload))

    def test_prefers_research_export_when_present(self) -> None:
        self._write(self.research_dir, "BTC_4h.json", n_candles=4400)
        self._write(self.site_dir, "BTC_4h.json", n_candles=200)

        frame = pipeline.default_candles_provider("BTC", "4h", candles_dir=self.site_dir, research_candles_dir=self.research_dir)
        self.assertEqual(len(frame), 4400)

    def test_falls_back_to_site_export_when_research_export_absent(self) -> None:
        self._write(self.site_dir, "BTC_4h.json", n_candles=200)

        frame = pipeline.default_candles_provider("BTC", "4h", candles_dir=self.site_dir, research_candles_dir=self.research_dir)
        self.assertEqual(len(frame), 200)

    def test_returns_none_when_neither_export_exists(self) -> None:
        frame = pipeline.default_candles_provider("BTC", "4h", candles_dir=self.site_dir, research_candles_dir=self.research_dir)
        self.assertIsNone(frame)

    def test_adams_own_pipeline_default_provider_is_unchanged(self) -> None:
        # Explicit confirmation this change was scoped to Eve only -- Adam's
        # own research_agent.pipeline.default_candles_provider still reads
        # ONLY the 200-row site export, no research-export awareness at all.
        import inspect

        from nero_core.research_agent.pipeline import default_candles_provider as adam_provider

        source = inspect.getsource(adam_provider)
        self.assertNotIn("research", source.lower())


class SecretHandlingTest(unittest.TestCase):
    def test_main_never_prints_the_api_key(self) -> None:
        # AST-based check (mirrors test_research_agent_secret_handling.py's
        # own convention): every print() call in main()'s source must not
        # reference the `api_key` variable directly.
        source = inspect.getsource(pipeline.main)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
                for arg in ast.walk(node):
                    if isinstance(arg, ast.Name) and arg.id == "api_key":
                        self.fail("main() must never print the api_key variable directly")


if __name__ == "__main__":
    unittest.main()
