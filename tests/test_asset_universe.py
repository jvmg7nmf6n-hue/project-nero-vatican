"""Tests for nero_core.asset_universe -- the shared search/evaluation
universe declarations both Eve and Adam import (see that module's own
docstring). The disjointness invariant is already enforced at import time
(a broken invariant would crash on import, before any test even runs) --
this file additionally asserts it explicitly and dynamically, and proves
each pipeline's own candles_provider actually refuses an evaluation-only
pair rather than relying on disjointness alone."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from nero_core.asset_universe import APPROVED_EVALUATION_UNIVERSE, APPROVED_RESEARCH_UNIVERSE

REPO_ROOT = Path(__file__).resolve().parents[1]


class DisjointUniversesTest(unittest.TestCase):
    def test_research_and_evaluation_universes_are_disjoint(self) -> None:
        self.assertEqual(APPROVED_RESEARCH_UNIVERSE & APPROVED_EVALUATION_UNIVERSE, frozenset())

    def test_both_universes_are_non_empty(self) -> None:
        # A trivially-empty universe would make the disjointness check above
        # vacuously true and hide a real configuration bug.
        self.assertTrue(APPROVED_RESEARCH_UNIVERSE)
        self.assertTrue(APPROVED_EVALUATION_UNIVERSE)

    def test_btc_4h_is_the_research_universe(self) -> None:
        self.assertIn(("BTC", "4h"), APPROVED_RESEARCH_UNIVERSE)

    def test_pre_registered_universe_is_exactly_the_four_declared_assets(self) -> None:
        # BTCUSDT, ETHUSDT, SOLUSDT, PAXGUSDT -- pre-declared as a package
        # (see nero_core.asset_universe's own docstring); NEAR/DOGE
        # deliberately excluded. Exact-set check (not just assertIn) so an
        # accidental future addition is caught here, not silently expanding
        # Eve's search space.
        self.assertEqual(APPROVED_RESEARCH_UNIVERSE, frozenset({
            ("BTC", "4h"), ("ETH", "4h"), ("SOL", "4h"), ("PAXG", "4h"),
        }))

    def test_btc_24h_is_the_evaluation_universe_not_the_research_universe(self) -> None:
        self.assertIn(("BTC", "24h"), APPROVED_EVALUATION_UNIVERSE)
        self.assertNotIn(("BTC", "24h"), APPROVED_RESEARCH_UNIVERSE)


class ResearchUniversePairHasBothExportAndBaselineTest(unittest.TestCase):
    """Every pair in APPROVED_RESEARCH_UNIVERSE must have BOTH (i) its own
    research export and (ii) its own random-baseline result on disk --
    proves the standing rule was actually honored for each addition, not
    just asserted in a docstring."""

    def test_every_research_pair_has_a_candle_export(self) -> None:
        for asset, timeframe in APPROVED_RESEARCH_UNIVERSE:
            path = REPO_ROOT / "docs" / "research_data" / "candles" / f"{asset}_{timeframe}.json"
            self.assertTrue(path.exists(), f"missing research export for {asset}/{timeframe}: {path}")

    def test_every_research_pair_has_a_random_baseline_result(self) -> None:
        for asset, timeframe in APPROVED_RESEARCH_UNIVERSE:
            path = REPO_ROOT / "docs" / "investigations" / f"{asset.lower()}_{timeframe}_random_baseline_result.json"
            self.assertTrue(path.exists(), f"missing random-baseline result for {asset}/{timeframe}: {path}")
            data = json.loads(path.read_text())
            self.assertEqual(data["k"], 200)
            self.assertEqual(data["verdict_counts"].get("SURVIVED", 0), 0)


class EvaluationUniverseNeverScorableTest(unittest.TestCase):
    """HARD CHECK: an evaluation-only pair must never reach Eve's or Adam's
    hypothesis-scoring path, even if a real export file for it happens to
    exist somewhere on disk -- the whole point of a separate universe (and a
    separate on-disk directory) is that this must hold structurally, not by
    coincidence of which files happen to be present."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp_root = Path(self._tmpdir.name)
        self.site_dir = tmp_root / "site"
        self.research_dir = tmp_root / "research"
        self.site_dir.mkdir()
        self.research_dir.mkdir()

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _write(self, directory: Path, asset: str, timeframe: str, n_candles: int = 1800) -> None:
        candles = [
            {"time": 1_500_000_000 + i * 86400, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1.0}
            for i in range(n_candles)
        ]
        payload = {"schema_version": 1, "asset": asset, "timeframe": timeframe, "last_updated": "2026-08-02T00:00:00+00:00", "candles": candles}
        (directory / f"{asset}_{timeframe}.json").write_text(json.dumps(payload))

    def test_eve_refuses_an_evaluation_only_pair_even_if_a_file_exists_at_the_research_path(self) -> None:
        from nero_core.eve import pipeline, scoring

        # Simulates the dangerous misconfiguration this test guards against:
        # someone accidentally drops a BTC/24h export into the RESEARCH
        # directory (the one Eve's provider actually reads from). Even then,
        # the explicit APPROVED_EVALUATION_UNIVERSE check must win.
        self._write(self.research_dir, "BTC", "24h")

        with self.assertRaises(scoring.DataSourceRefusedError) as ctx:
            pipeline.default_candles_provider("BTC", "24h", candles_dir=self.site_dir, research_candles_dir=self.research_dir)
        self.assertIn("APPROVED_EVALUATION_UNIVERSE", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
