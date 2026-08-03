from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from nero_core.research_agent.pipeline import DataSourceRefusedError, _load_failure_patterns, default_candles_provider


class LoadFailurePatternsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "failure_patterns.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_missing_file_returns_empty_list_silently(self) -> None:
        err = io.StringIO()
        with redirect_stderr(err):
            result = _load_failure_patterns(self.path)
        self.assertEqual(result, [])
        self.assertEqual(err.getvalue(), "")

    def test_corrupted_file_prints_a_loud_error_and_degrades_to_empty(self) -> None:
        # Item #11 from the diagnostics audit: previously silent -- every
        # prompt this run would lose its "known dead mechanisms" context with
        # zero indication why, risking a regenerated-and-already-killed
        # hypothesis.
        self.path.write_text("{not valid json")
        err = io.StringIO()
        with redirect_stderr(err):
            result = _load_failure_patterns(self.path)

        self.assertEqual(result, [])
        self.assertIn("ERROR", err.getvalue())
        self.assertIn("corrupted", err.getvalue())


class DefaultCandlesProviderTest(unittest.TestCase):
    """Rewritten for the refuse-don't-degrade fix (item 2, Eve engine v1
    follow-up session): default_candles_provider no longer reads the
    200-row site export at all -- it reads ONLY the full-history research
    export, for pairs in APPROVED_RESEARCH_UNIVERSE, and RAISES
    DataSourceRefusedError (never returns None as a disguised refusal) for
    everything else. This mirrors nero_core.eve.pipeline.
    default_candles_provider's own identical fix exactly."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.site_dir = self.tmp / "site"
        self.research_dir = self.tmp / "research"
        self.site_dir.mkdir()
        self.research_dir.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_refuses_a_pair_outside_the_approved_research_universe(self) -> None:
        # BTC/1h has never had a research export or a random baseline
        # computed against it -- must be refused, not silently degraded to
        # the site export (even if a site export for it exists).
        (self.site_dir / "BTC_1h.json").write_text(json.dumps({
            "asset": "BTC", "timeframe": "1h",
            "candles": [{"time": 1_700_000_000, "close": 100.0, "high": 101.0, "low": 99.0, "volume": 10.0}],
        }))
        with self.assertRaises(DataSourceRefusedError):
            default_candles_provider("BTC", "1h", candles_dir=self.site_dir, research_candles_dir=self.research_dir)

    def test_refuses_an_evaluation_only_pair(self) -> None:
        with self.assertRaises(DataSourceRefusedError) as ctx:
            default_candles_provider("BTC", "24h", candles_dir=self.site_dir, research_candles_dir=self.research_dir)
        self.assertIn("APPROVED_EVALUATION_UNIVERSE", str(ctx.exception))

    def test_refuses_when_research_export_file_is_missing(self) -> None:
        with self.assertRaises(DataSourceRefusedError):
            default_candles_provider("BTC", "4h", candles_dir=self.site_dir, research_candles_dir=self.research_dir)

    def test_malformed_research_file_prints_a_loud_error_and_still_refuses(self) -> None:
        (self.research_dir / "BTC_4h.json").write_text("{not valid json")
        err = io.StringIO()
        with redirect_stderr(err):
            with self.assertRaises(DataSourceRefusedError):
                default_candles_provider("BTC", "4h", candles_dir=self.site_dir, research_candles_dir=self.research_dir)
        self.assertIn("ERROR", err.getvalue())
        self.assertIn("EXISTS but is malformed", err.getvalue())

    def test_valid_research_export_for_an_approved_pair_is_tagged_and_returned(self) -> None:
        payload = {
            "asset": "BTC", "timeframe": "4h",
            "candles": [{"time": 1_700_000_000, "close": 100.0, "high": 101.0, "low": 99.0, "volume": 10.0}],
        }
        (self.research_dir / "BTC_4h.json").write_text(json.dumps(payload))
        err = io.StringIO()
        with redirect_stderr(err):
            result = default_candles_provider("BTC", "4h", candles_dir=self.site_dir, research_candles_dir=self.research_dir)

        self.assertIsNotNone(result)
        self.assertEqual(len(result), 1)
        self.assertEqual(result.attrs.get("data_source"), "research_export")
        self.assertEqual(result.attrs.get("row_count"), 1)
        self.assertEqual(err.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
