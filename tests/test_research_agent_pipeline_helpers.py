from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from nero_core.research_agent.pipeline import _load_failure_patterns, default_candles_provider


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
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_missing_file_returns_none_silently(self) -> None:
        # Benign: this (asset, timeframe) simply hasn't been exported yet --
        # must NOT print anything.
        err = io.StringIO()
        with redirect_stderr(err):
            result = default_candles_provider("BTC", "1h", candles_dir=self.tmp)
        self.assertIsNone(result)
        self.assertEqual(err.getvalue(), "")

    def test_malformed_file_prints_a_loud_error_distinguishing_it_from_missing(self) -> None:
        # Item #12: both cases still resolve to None (-> no_candles_available),
        # but only the malformed case is a REAL problem (a broken export, not
        # simply an asset that hasn't been fetched yet) and must be
        # distinguishable in the log.
        path = self.tmp / "BTC_1h.json"
        path.write_text("{not valid json")
        err = io.StringIO()
        with redirect_stderr(err):
            result = default_candles_provider("BTC", "1h", candles_dir=self.tmp)

        self.assertIsNone(result)
        self.assertIn("ERROR", err.getvalue())
        self.assertIn("EXISTS but is malformed", err.getvalue())

    def test_valid_file_parses_silently(self) -> None:
        payload = {
            "asset": "BTC", "timeframe": "1h",
            "candles": [{"time": 1_700_000_000, "close": 100.0, "high": 101.0, "low": 99.0, "volume": 10.0}],
        }
        path = self.tmp / "BTC_1h.json"
        path.write_text(json.dumps(payload))
        err = io.StringIO()
        with redirect_stderr(err):
            result = default_candles_provider("BTC", "1h", candles_dir=self.tmp)

        self.assertIsNotNone(result)
        self.assertEqual(len(result), 1)
        self.assertEqual(err.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
