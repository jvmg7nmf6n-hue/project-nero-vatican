from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from nero_core.research_agent.scanner import (
    run_scan,
    scan_correlation_breakdowns,
    scan_extreme_zscore,
    scan_low_strategy_coverage,
    scan_regime_transitions,
)

HOUR_S = 3600
NOW = datetime(2026, 7, 29, tzinfo=timezone.utc)


def _write_candle_file(directory: Path, asset: str, timeframe: str, closes: list[float], start_s: int = 1_700_000_000) -> None:
    candles = []
    t = start_s
    for close in closes:
        candles.append({"time": t, "open": close, "high": close + 0.5, "low": close - 0.5, "close": close, "volume": 10.0})
        t += HOUR_S
    payload = {"schema_version": 1, "asset": asset, "timeframe": timeframe, "last_updated": NOW.isoformat(), "candles": candles}
    (directory / f"{asset}_{timeframe}.json").write_text(json.dumps(payload))


class ScanExtremeZscoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_extreme_zscore_flagged_with_measured_frequency(self) -> None:
        # A flat series with a handful of sharp one-candle spikes: guarantees the
        # rolling zscore20 crosses the +/-2 threshold a known, non-zero number of times.
        closes = [100.0] * 40
        for i in range(20, 40, 5):
            closes[i] = 200.0  # sharp spike relative to the flat trailing window
        _write_candle_file(self.tmp, "BTC", "1h", closes)

        quant_metrics = {"metrics": [{"asset": "BTC", "timeframe": "1h", "zscore_current": 3.1}]}
        findings = scan_extreme_zscore(quant_metrics, self.tmp, NOW)

        self.assertEqual(len(findings), 1)
        finding = findings[0]
        self.assertEqual(finding.finding_type, "extreme_zscore")
        self.assertEqual(finding.asset, "BTC")
        self.assertAlmostEqual(finding.magnitude, 3.1)
        self.assertIsNotNone(finding.measured_frequency_per_year)
        self.assertGreater(finding.measured_frequency_per_year, 0.0)

    def test_non_extreme_zscore_not_flagged(self) -> None:
        quant_metrics = {"metrics": [{"asset": "ETH", "timeframe": "1h", "zscore_current": 0.5}]}
        findings = scan_extreme_zscore(quant_metrics, self.tmp, NOW)
        self.assertEqual(findings, [])

    def test_null_zscore_not_flagged(self) -> None:
        quant_metrics = {"metrics": [{"asset": "ETH", "timeframe": "1h", "zscore_current": None}]}
        findings = scan_extreme_zscore(quant_metrics, self.tmp, NOW)
        self.assertEqual(findings, [])

    def test_missing_candle_file_still_flags_but_frequency_is_honest_none(self) -> None:
        quant_metrics = {"metrics": [{"asset": "NOFILE", "timeframe": "1h", "zscore_current": 2.5}]}
        findings = scan_extreme_zscore(quant_metrics, self.tmp, NOW)
        self.assertEqual(len(findings), 1)
        self.assertIsNone(findings[0].measured_frequency_per_year)

    def test_findings_ranked_by_magnitude_descending(self) -> None:
        quant_metrics = {
            "metrics": [
                {"asset": "A", "timeframe": "1h", "zscore_current": 2.1},
                {"asset": "B", "timeframe": "1h", "zscore_current": 4.0},
                {"asset": "C", "timeframe": "1h", "zscore_current": -3.0},
            ]
        }
        findings = scan_extreme_zscore(quant_metrics, self.tmp, NOW)
        magnitudes = [f.magnitude for f in findings]
        self.assertEqual(magnitudes, sorted(magnitudes, reverse=True))


class ScanRegimeTransitionsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.state_path = self.tmp / "state.json"
        self.candles_dir = self.tmp / "candles"
        self.candles_dir.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_first_observation_raises_no_finding_but_persists_state(self) -> None:
        current = [{"asset": "BTC", "timeframe": "12h", "regime": "HIGH"}]
        findings = scan_regime_transitions(current, self.candles_dir, NOW, self.state_path)

        self.assertEqual(findings, [])
        self.assertTrue(self.state_path.exists())
        state = json.loads(self.state_path.read_text())
        self.assertEqual(state["last_regime"]["BTC|12h"], "HIGH")

    def test_calm_to_turbulent_transition_is_flagged_on_second_run(self) -> None:
        scan_regime_transitions(
            [{"asset": "BTC", "timeframe": "12h", "regime": "LOW"}], self.candles_dir, NOW, self.state_path
        )
        findings = scan_regime_transitions(
            [{"asset": "BTC", "timeframe": "12h", "regime": "EXTREME"}], self.candles_dir, NOW, self.state_path
        )

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].finding_type, "regime_transition")
        self.assertIn("LOW", findings[0].description)
        self.assertIn("EXTREME", findings[0].description)

    def test_same_category_transition_not_flagged(self) -> None:
        # NORMAL -> LOW are both CALM -- not a CALM<->TURBULENT crossing
        scan_regime_transitions([{"asset": "ETH", "timeframe": "12h", "regime": "NORMAL"}], self.candles_dir, NOW, self.state_path)
        findings = scan_regime_transitions(
            [{"asset": "ETH", "timeframe": "12h", "regime": "LOW"}], self.candles_dir, NOW, self.state_path
        )
        self.assertEqual(findings, [])

    def test_no_data_regime_never_treated_as_a_category(self) -> None:
        scan_regime_transitions([{"asset": "X", "timeframe": "1d", "regime": "HIGH"}], self.candles_dir, NOW, self.state_path)
        findings = scan_regime_transitions(
            [{"asset": "X", "timeframe": "1d", "regime": "NO_DATA"}], self.candles_dir, NOW, self.state_path
        )
        self.assertEqual(findings, [])

    def test_missing_candle_file_yields_honest_none_frequency(self) -> None:
        scan_regime_transitions([{"asset": "BTC", "timeframe": "12h", "regime": "LOW"}], self.candles_dir, NOW, self.state_path)
        findings = scan_regime_transitions(
            [{"asset": "BTC", "timeframe": "12h", "regime": "HIGH"}], self.candles_dir, NOW, self.state_path
        )
        self.assertEqual(len(findings), 1)
        self.assertIsNone(findings[0].measured_frequency_per_year)
        self.assertIn("No candle file", findings[0].measurement_note)


class ScanCorrelationBreakdownTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_recent_divergence_from_long_run_correlation_is_flagged(self) -> None:
        # 190 candles where both assets move in lockstep (highly correlated long-run),
        # then 30 candles where B inverts A's move (strongly anti-correlated recently).
        closes_a = [100.0]
        for i in range(219):
            closes_a.append(closes_a[-1] * (1.01 if i % 2 == 0 else 0.995))
        closes_b = [close for close in closes_a]  # start identical (long-run: near-perfect correlation)
        for i in range(190, 220):
            # invert the recent 30-candle relationship: B moves opposite A's recent direction
            direction = 1.0 if closes_a[i] >= closes_a[i - 1] else -1.0
            closes_b[i] = closes_b[i - 1] * (0.99 if direction > 0 else 1.01)

        _write_candle_file(self.tmp, "ALPHA", "1h", closes_a)
        _write_candle_file(self.tmp, "BETA", "1h", closes_b)

        findings = scan_correlation_breakdowns(self.tmp, NOW)

        self.assertEqual(len(findings), 1)
        finding = findings[0]
        self.assertEqual(finding.finding_type, "correlation_breakdown")
        self.assertGreater(finding.magnitude, 0.4)
        self.assertIsNone(finding.measured_frequency_per_year)  # point-in-time, not a per-year rate

    def test_consistently_correlated_pair_not_flagged(self) -> None:
        closes_a = [100.0]
        for i in range(219):
            closes_a.append(closes_a[-1] * (1.01 if i % 2 == 0 else 0.995))
        closes_b = [c * 2.0 for c in closes_a]  # always perfectly proportional -- corr ~1.0 everywhere

        _write_candle_file(self.tmp, "GAMMA", "1h", closes_a)
        _write_candle_file(self.tmp, "DELTA", "1h", closes_b)

        findings = scan_correlation_breakdowns(self.tmp, NOW)
        self.assertEqual(findings, [])


class ScanLowStrategyCoverageTest(unittest.TestCase):
    def test_asset_with_no_registered_strategy_is_flagged(self) -> None:
        quant_metrics = {"metrics": [{"asset": "NEAR", "timeframe": "2h"}, {"asset": "BTC", "timeframe": "12h"}]}
        strategies = {"strategies": [{"asset": "BTC", "name": "MEAN_REVERSION"}]}

        findings = scan_low_strategy_coverage(strategies, quant_metrics, NOW)

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].asset, "NEAR")
        self.assertIsNone(findings[0].measured_frequency_per_year)

    def test_fully_covered_universe_yields_no_findings(self) -> None:
        quant_metrics = {"metrics": [{"asset": "BTC", "timeframe": "12h"}]}
        strategies = {"strategies": [{"asset": "BTC", "name": "MEAN_REVERSION"}]}
        findings = scan_low_strategy_coverage(strategies, quant_metrics, NOW)
        self.assertEqual(findings, [])


class RunScanTest(unittest.TestCase):
    def test_missing_export_files_reported_as_scan_errors_not_a_crash(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        try:
            result = run_scan(
                candles_dir=tmp / "candles",
                quant_metrics_path=tmp / "quant_metrics.json",
                quant_cross_asset_path=tmp / "quant_cross_asset.json",
                strategies_path=tmp / "strategies.json",
                state_path=tmp / "state.json",
                now=NOW,
            )
            self.assertEqual(result.extreme_zscore, [])
            self.assertEqual(len(result.scan_errors), 2)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
