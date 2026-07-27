from __future__ import annotations

import json
import math
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from nero_core.execution import export_quant_cross_asset as eqca

FIXED_NOW = datetime(2026, 7, 27, 0, 0, 0, tzinfo=timezone.utc)


def _closes_from_returns(returns: list[float], start: float = 100.0) -> list[float]:
    closes = [start]
    for r in returns:
        closes.append(closes[-1] * math.exp(r))
    return closes


def _write_candle_file(directory: Path, filename: str, asset: str, timeframe: str, closes: list[float]) -> None:
    payload = {
        "schema_version": 1,
        "asset": asset,
        "timeframe": timeframe,
        "last_updated": "2026-07-01T00:00:00+00:00",
        "candles": [
            {"time": i, "open": c, "high": c, "low": c, "close": c, "volume": 1000.0} for i, c in enumerate(closes)
        ],
    }
    (directory / filename).write_text(json.dumps(payload))


def _two_asset_dir(tmp: str) -> Path:
    d = Path(tmp) / "candles"
    d.mkdir()
    returns = [0.01 * math.sin(i * 0.7) for i in range(70)]
    _write_candle_file(d, "AAPL_24h.json", "AAPL", "24h", _closes_from_returns(returns))
    _write_candle_file(d, "MSFT_24h.json", "MSFT", "24h", _closes_from_returns([2.0 * r for r in returns]))
    return d


class ExportSchemaTest(unittest.TestCase):
    def test_output_matches_the_documented_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candles_dir = _two_asset_dir(tmp)
            output_path = Path(tmp) / "quant_cross_asset.json"

            result = eqca.export_quant_cross_asset(candles_dir=candles_dir, output_path=output_path, now=FIXED_NOW)
            self.assertEqual(result.part_errors, [])

            payload = json.loads(output_path.read_text())
            self.assertEqual(payload["schema_version"], 1)
            self.assertEqual(payload["last_updated"], FIXED_NOW.isoformat())
            for key in ("correlation_matrix", "volatility_regimes", "cointegration", "lead_lag"):
                self.assertIn(key, payload)
                self.assertIsInstance(payload[key], list)

            self.assertEqual(len(payload["correlation_matrix"]), 1)  # AAPL vs MSFT, both 24h
            self.assertEqual(len(payload["volatility_regimes"]), 2)  # one per file
            self.assertEqual(len(payload["cointegration"]), 4)  # the 4 fixed requested pairs, regardless of data
            # lead_lag: neither AAPL nor MSFT is crypto-class -> no entries.
            self.assertEqual(payload["lead_lag"], [])

    def test_no_composite_score_field_anywhere_in_the_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candles_dir = _two_asset_dir(tmp)
            output_path = Path(tmp) / "quant_cross_asset.json"
            eqca.export_quant_cross_asset(candles_dir=candles_dir, output_path=output_path, now=FIXED_NOW)
            raw_text = output_path.read_text().lower()
            for forbidden in ("composite", "overall_score", "quantconsensus", "\"score\""):
                self.assertNotIn(forbidden, raw_text)


class FailIndependenceTest(unittest.TestCase):
    def test_one_corrupt_candle_file_does_not_prevent_other_parts_from_exporting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candles_dir = _two_asset_dir(tmp)
            (candles_dir / "CORRUPT_24h.json").write_text("{not valid json")
            output_path = Path(tmp) / "quant_cross_asset.json"

            result = eqca.export_quant_cross_asset(candles_dir=candles_dir, output_path=output_path, now=FIXED_NOW)

            self.assertEqual(result.part_errors, [])
            self.assertEqual(len(result.load_errors), 1)
            self.assertEqual(result.load_errors[0]["file"], "CORRUPT_24h.json")

            payload = json.loads(output_path.read_text())
            self.assertEqual(len(payload["correlation_matrix"]), 1)
            self.assertEqual(len(payload["volatility_regimes"]), 2)

    def test_a_catastrophic_failure_in_one_part_does_not_abort_the_other_three(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candles_dir = _two_asset_dir(tmp)
            output_path = Path(tmp) / "quant_cross_asset.json"

            def _raising_cointegration_report(_candles_dir):
                raise RuntimeError("simulated catastrophic failure")

            original = eqca.cointegration_report
            eqca.cointegration_report = _raising_cointegration_report  # type: ignore[assignment]
            try:
                result = eqca.export_quant_cross_asset(candles_dir=candles_dir, output_path=output_path, now=FIXED_NOW)
            finally:
                eqca.cointegration_report = original  # type: ignore[assignment]

            self.assertEqual(len(result.part_errors), 1)
            self.assertEqual(result.part_errors[0]["part"], "cointegration")

            payload = json.loads(output_path.read_text())
            self.assertEqual(payload["cointegration"], [])  # failed part -> empty, never missing
            self.assertEqual(len(payload["correlation_matrix"]), 1)  # untouched parts still populated
            self.assertEqual(len(payload["volatility_regimes"]), 2)


if __name__ == "__main__":
    unittest.main()
