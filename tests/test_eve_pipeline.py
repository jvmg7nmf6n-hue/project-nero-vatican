from __future__ import annotations

import ast
import inspect
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from nero_core.eve import pipeline, scoring, storage
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
    """Renamed in spirit (not literally, to keep git blame simple) from a
    "falls back to site export" test to a "refuses rather than falls back"
    test -- see nero_core.eve.pipeline.APPROVED_RESEARCH_UNIVERSE and
    scoring.DataSourceRefusedError. The silent-fallback behavior this class
    used to assert was the actual bug: BTC/4h is the only pair with a real
    random-hypothesis baseline computed against it, so scoring ANY other
    pair against the 200-row site export produced a confident-looking
    verdict on data proven meaningless for exactly this purpose."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp_root = Path(self._tmpdir.name)
        self.site_dir = tmp_root / "site"
        self.research_dir = tmp_root / "research"
        self.site_dir.mkdir()
        self.research_dir.mkdir()

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _write(self, directory: Path, filename: str, n_candles: int, asset: str = "BTC", timeframe: str = "4h") -> None:
        import json

        candles = [{"time": 1_700_000_000 + i * 14400, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1.0} for i in range(n_candles)]
        payload = {"schema_version": 1, "asset": asset, "timeframe": timeframe, "last_updated": "2026-08-01T00:00:00+00:00", "candles": candles}
        (directory / filename).write_text(json.dumps(payload))

    def test_prefers_research_export_when_present(self) -> None:
        self._write(self.research_dir, "BTC_4h.json", n_candles=4400)
        self._write(self.site_dir, "BTC_4h.json", n_candles=200)

        frame = pipeline.default_candles_provider("BTC", "4h", candles_dir=self.site_dir, research_candles_dir=self.research_dir)
        self.assertEqual(len(frame), 4400)

    def test_research_export_frame_is_tagged_with_source_and_row_count(self) -> None:
        self._write(self.research_dir, "BTC_4h.json", n_candles=4400)

        frame = pipeline.default_candles_provider("BTC", "4h", candles_dir=self.site_dir, research_candles_dir=self.research_dir)
        self.assertEqual(frame.attrs.get("data_source"), "research_export")
        self.assertEqual(frame.attrs.get("row_count"), 4400)

    def test_refuses_rather_than_falls_back_to_site_export_when_research_export_absent(self) -> None:
        self._write(self.site_dir, "BTC_4h.json", n_candles=200)

        with self.assertRaises(scoring.DataSourceRefusedError):
            pipeline.default_candles_provider("BTC", "4h", candles_dir=self.site_dir, research_candles_dir=self.research_dir)

    def test_refuses_when_neither_export_exists(self) -> None:
        with self.assertRaises(scoring.DataSourceRefusedError):
            pipeline.default_candles_provider("BTC", "4h", candles_dir=self.site_dir, research_candles_dir=self.research_dir)

    def test_refuses_a_pair_outside_the_approved_universe_even_with_a_real_site_export(self) -> None:
        # GOLD/4h has a real 200-row site export in production (see
        # docs/site_data/candles/GOLD_4h.json) but no research export and no
        # baseline -- must be refused regardless of what files exist on disk.
        self._write(self.site_dir, "GOLD_4h.json", n_candles=200, asset="GOLD", timeframe="4h")

        with self.assertRaises(scoring.DataSourceRefusedError):
            pipeline.default_candles_provider("GOLD", "4h", candles_dir=self.site_dir, research_candles_dir=self.research_dir)

    def test_adams_own_pipeline_default_provider_is_unchanged(self) -> None:
        # Explicit confirmation this change was scoped to Eve only -- Adam's
        # own research_agent.pipeline.default_candles_provider still reads
        # ONLY the 200-row site export, no research-export awareness at all.
        import inspect

        from nero_core.research_agent.pipeline import default_candles_provider as adam_provider

        source = inspect.getsource(adam_provider)
        self.assertNotIn("research", source.lower())


class ScoringRunCannotConsumeSiteExportTest(unittest.TestCase):
    """End-to-end proof (not just a unit check on default_candles_provider
    in isolation) that a real scoring run -- scoring.score_hypothesis, the
    exact function run_pipeline calls -- can never silently score a
    hypothesis against the 200-row site export, even when that file exists
    on disk and only the research export is missing."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp_root = Path(self._tmpdir.name)
        self.site_dir = tmp_root / "site"
        self.research_dir = tmp_root / "research"
        self.site_dir.mkdir()
        self.research_dir.mkdir()

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _write_site_export(self, asset: str, timeframe: str, n_candles: int = 200) -> None:
        import json

        candles = [{"time": 1_700_000_000 + i * 14400, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1.0} for i in range(n_candles)]
        payload = {"schema_version": 1, "asset": asset, "timeframe": timeframe, "last_updated": "2026-08-01T00:00:00+00:00", "candles": candles}
        (self.site_dir / f"{asset}_{timeframe}.json").write_text(json.dumps(payload))

    def _provider(self, asset: str, timeframe: str):
        return pipeline.default_candles_provider(asset, timeframe, candles_dir=self.site_dir, research_candles_dir=self.research_dir)

    def test_gold_hypothesis_is_refused_not_scored_against_the_site_export(self) -> None:
        # A real 200-row GOLD/4h site export exists (mirrors production:
        # docs/site_data/candles/GOLD_4h.json is real, docs/research_data/
        # candles/GOLD_4h.json does not exist) -- the old behavior silently
        # scored against it anyway.
        self._write_site_export("GOLD", "4h")
        record = {
            "session_id": "s1", "turn_index": 0, "tool_use_id": "toolu_1",
            "raw_hypothesis": {
                "hypothesis_name": "GOLD_TEST", "asset": "GOLD", "timeframe": "4h",
                "generated_at": "2026-08-01T00:00:00+00:00",
                "structured_entry_rule": {"conditions": [{"field": "ret_1", "op": "gt", "value": -1.0}]},
                "structured_exit_plan": {"stop_atr_multiple": 1.5, "target_r_multiple": 2.0, "max_holding_hours": 24.0},
            },
        }

        scored = scoring.score_hypothesis(record, candles_provider=self._provider, now=datetime(2026, 8, 1, tzinfo=timezone.utc))

        self.assertEqual(scored["candle_data_source"], "refused")
        self.assertIsNone(scored["candle_row_count"])
        self.assertIsNone(scored["verdict_is"])
        self.assertIsNone(scored["verdict_oos"])
        self.assertIsNone(scored["verdict_combined"])
        self.assertIn("refused rather than substituted", scored["testability_reason"])

    def test_btc_4h_hypothesis_with_research_export_is_scored_and_tagged(self) -> None:
        import json

        candles = [
            {"time": 1_700_000_000 + i * 14400, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1.0}
            for i in range(600)
        ]
        payload = {"schema_version": 1, "asset": "BTC", "timeframe": "4h", "last_updated": "2026-08-01T00:00:00+00:00", "candles": candles}
        (self.research_dir / "BTC_4h.json").write_text(json.dumps(payload))
        record = {
            "session_id": "s1", "turn_index": 0, "tool_use_id": "toolu_2",
            "raw_hypothesis": {
                "hypothesis_name": "BTC_TEST", "asset": "BTC", "timeframe": "4h",
                "generated_at": "2026-08-01T00:00:00+00:00",
                "structured_entry_rule": {"conditions": [{"field": "ret_1", "op": "gt", "value": -1.0}]},
                "structured_exit_plan": {"stop_atr_multiple": 1.5, "target_r_multiple": 2.0, "max_holding_hours": 24.0},
            },
        }

        scored = scoring.score_hypothesis(record, candles_provider=self._provider, now=datetime(2026, 8, 1, tzinfo=timezone.utc))

        self.assertEqual(scored["candle_data_source"], "research_export")
        self.assertEqual(scored["candle_row_count"], 600)


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
