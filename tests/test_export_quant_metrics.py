from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from nero_core.execution import export_quant_metrics as eqm

FIXED_NOW = datetime(2026, 7, 27, 0, 0, 0, tzinfo=timezone.utc)


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


def _good_closes(n: int = 200) -> list[float]:
    return [100.0 + 0.1 * i for i in range(n)]


class ExportQuantMetricsFailIndependentTest(unittest.TestCase):
    def test_one_corrupt_file_does_not_prevent_the_others_from_being_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candles_dir = Path(tmp) / "candles"
            candles_dir.mkdir()
            output_path = Path(tmp) / "quant_metrics.json"

            _write_candle_file(candles_dir, "BTC_24h.json", "BTC", "24h", _good_closes())
            _write_candle_file(candles_dir, "GOLD_1week.json", "GOLD", "1week", _good_closes())
            (candles_dir / "CORRUPT_24h.json").write_text("{not valid json")

            result = eqm.export_quant_metrics(
                candles_dir=candles_dir, output_path=output_path, now=FIXED_NOW, rf_fetch_fn=lambda: (0.04, "fred_dff")
            )

            self.assertEqual(sorted(result.written), ["BTC_24h.json", "GOLD_1week.json"])
            self.assertEqual(len(result.errors), 1)
            self.assertEqual(result.errors[0]["file"], "CORRUPT_24h.json")

            payload = json.loads(output_path.read_text())
            self.assertEqual({m["asset"] for m in payload["metrics"]}, {"BTC", "GOLD"})

    def test_a_file_missing_a_required_key_is_isolated_the_same_way(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candles_dir = Path(tmp) / "candles"
            candles_dir.mkdir()
            output_path = Path(tmp) / "quant_metrics.json"

            _write_candle_file(candles_dir, "BTC_24h.json", "BTC", "24h", _good_closes())
            (candles_dir / "BROKEN_24h.json").write_text(json.dumps({"schema_version": 1, "candles": []}))

            result = eqm.export_quant_metrics(
                candles_dir=candles_dir, output_path=output_path, now=FIXED_NOW, rf_fetch_fn=lambda: (0.04, "fred_dff")
            )
            self.assertEqual(result.written, ["BTC_24h.json"])
            self.assertEqual(len(result.errors), 1)


class ExportQuantMetricsSchemaTest(unittest.TestCase):
    def test_output_matches_the_documented_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candles_dir = Path(tmp) / "candles"
            candles_dir.mkdir()
            output_path = Path(tmp) / "quant_metrics.json"
            _write_candle_file(candles_dir, "GOLD_1week.json", "GOLD", "1week", _good_closes())

            result = eqm.export_quant_metrics(
                candles_dir=candles_dir, output_path=output_path, now=FIXED_NOW, rf_fetch_fn=lambda: (0.0363, "fred_dff")
            )
            self.assertEqual(result.errors, [])

            payload = json.loads(output_path.read_text())
            self.assertEqual(payload["schema_version"], 1)
            self.assertEqual(payload["last_updated"], FIXED_NOW.isoformat())
            entry = payload["metrics"][0]
            expected_fields = {
                "asset", "timeframe", "periods_per_year", "window_used", "rf_annual", "rf_source",
                "log_return_annualized", "zscore_current", "realized_vol_annualized", "sharpe", "sortino",
                "computed_at",
            }
            self.assertEqual(set(entry.keys()), expected_fields)
            self.assertEqual(entry["asset"], "GOLD")
            self.assertEqual(entry["timeframe"], "1week")
            self.assertEqual(entry["periods_per_year"], 52)
            self.assertEqual(entry["window_used"], 199)  # 200 closes - 1, clamped below the 252 target
            self.assertEqual(entry["rf_source"], "fred_dff")
            self.assertIsNotNone(entry["sharpe"])

    def test_unknown_timeframe_gets_null_annualized_metrics_but_still_reports_a_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candles_dir = Path(tmp) / "candles"
            candles_dir.mkdir()
            output_path = Path(tmp) / "quant_metrics.json"
            _write_candle_file(candles_dir, "ETH_snapshot.json", "ETH", "snapshot", _good_closes())

            eqm.export_quant_metrics(
                candles_dir=candles_dir, output_path=output_path, now=FIXED_NOW, rf_fetch_fn=lambda: (0.04, "fred_dff")
            )
            entry = json.loads(output_path.read_text())["metrics"][0]

            self.assertIsNone(entry["periods_per_year"])
            self.assertIsNone(entry["log_return_annualized"])
            self.assertIsNone(entry["realized_vol_annualized"])
            self.assertIsNone(entry["sharpe"])
            self.assertIsNone(entry["sortino"])
            self.assertEqual(entry["window_used"], 199)  # candle-count based, independent of annualization
            # z-score has no periods_per_year dependency at all -- still real.
            self.assertIsNotNone(entry["zscore_current"])

    def test_thin_history_produces_all_null_metrics_but_no_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candles_dir = Path(tmp) / "candles"
            candles_dir.mkdir()
            output_path = Path(tmp) / "quant_metrics.json"
            _write_candle_file(candles_dir, "THIN_24h.json", "THIN", "24h", _good_closes(10))

            result = eqm.export_quant_metrics(
                candles_dir=candles_dir, output_path=output_path, now=FIXED_NOW, rf_fetch_fn=lambda: (0.04, "fred_dff")
            )
            self.assertEqual(result.errors, [])
            entry = json.loads(output_path.read_text())["metrics"][0]
            self.assertIsNone(entry["log_return_annualized"])
            self.assertIsNone(entry["realized_vol_annualized"])
            self.assertIsNone(entry["sharpe"])
            self.assertIsNone(entry["sortino"])
            self.assertIsNone(entry["zscore_current"])


class FetchRiskFreeRateFallbackTest(unittest.TestCase):
    def test_falls_back_to_the_documented_constant_when_fred_raises(self) -> None:
        def _raising_fetch_policy_rate(*_args, **_kwargs):
            raise RuntimeError("network down")

        original = eqm.fetch_policy_rate
        eqm.fetch_policy_rate = _raising_fetch_policy_rate  # type: ignore[assignment]
        try:
            rf_annual, rf_source = eqm.fetch_risk_free_rate()
        finally:
            eqm.fetch_policy_rate = original  # type: ignore[assignment]

        self.assertEqual(rf_annual, eqm.FALLBACK_RF_ANNUAL)
        self.assertEqual(rf_source, "fallback_constant")

    def test_falls_back_when_the_lag_shifted_series_has_no_usable_observation(self) -> None:
        import pandas as pd

        def _empty_series_fetch(*_args, **_kwargs):
            return pd.Series(dtype=float), "NATIVE: FRED DFF", "D"

        original = eqm.fetch_policy_rate
        eqm.fetch_policy_rate = _empty_series_fetch  # type: ignore[assignment]
        try:
            rf_annual, rf_source = eqm.fetch_risk_free_rate()
        finally:
            eqm.fetch_policy_rate = original  # type: ignore[assignment]

        self.assertEqual(rf_annual, eqm.FALLBACK_RF_ANNUAL)
        self.assertEqual(rf_source, "fallback_constant")

    def test_a_real_series_produces_the_live_source_label(self) -> None:
        import pandas as pd

        def _real_series_fetch(*_args, **_kwargs):
            dates = pd.date_range("2026-01-01", periods=10, freq="D")
            return pd.Series([5.33] * 10, index=dates), "NATIVE: FRED DFF", "D"

        original = eqm.fetch_policy_rate
        eqm.fetch_policy_rate = _real_series_fetch  # type: ignore[assignment]
        try:
            rf_annual, rf_source = eqm.fetch_risk_free_rate()
        finally:
            eqm.fetch_policy_rate = original  # type: ignore[assignment]

        self.assertEqual(rf_source, "fred_dff")
        self.assertAlmostEqual(rf_annual, 0.0533, places=6)


if __name__ == "__main__":
    unittest.main()
