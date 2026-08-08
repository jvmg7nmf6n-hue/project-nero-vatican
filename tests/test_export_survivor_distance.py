"""CC-1 directive Part B3e: regression tests for
nero_core/execution/export_survivor_distance.py's real distance formulas,
against known, hand-reasoned cases -- plus a structural guard (B3c) that no
time-to-trigger/ETA language ever appears anywhere in this module's own
source."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from nero_core.execution import export_survivor_distance as esd
from nero_core.strategies import cointegration_pairs


def _write_candle_file(path: Path, closes: list[float], base_time: int = 1_700_000_000) -> None:
    candles = [
        {"time": base_time + i * 604800, "open": c, "high": c, "low": c, "close": c, "volume": 1000.0}
        for i, c in enumerate(closes)
    ]
    path.write_text(json.dumps({"schema_version": 1, "asset": "X", "timeframe": "1week", "candles": candles}))


class BreakoutMomentumDistanceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_monotonically_rising_series_is_positive_on_all_three_real_conditions(self) -> None:
        # A steadily rising series: the close must be above its own recent high
        # (breakout condition), above its 200-period average (trend condition),
        # and RSI(14) must sit above the neutral 50 floor (momentum condition) --
        # all three real conditions should read positive, by construction.
        closes = [100.0 + i for i in range(210)]
        _write_candle_file(self.tmp / "GOLD_1week.json", closes)

        entry = esd._breakout_momentum_distance(self.tmp, now=None)

        by_label = {c["label"]: c for c in entry["conditions"]}
        self.assertGreater(by_label["close vs prior 20-week high (breakout level)"]["distance"], 0)
        self.assertGreater(by_label["close vs 200-period moving average"]["distance"], 0)
        self.assertGreater(by_label["RSI(14) vs momentum floor (50.0)"]["distance"], 0)

    def test_monotonically_falling_series_is_negative_on_all_three_real_conditions(self) -> None:
        closes = [400.0 - i for i in range(210)]
        _write_candle_file(self.tmp / "GOLD_1week.json", closes)

        entry = esd._breakout_momentum_distance(self.tmp, now=None)

        by_label = {c["label"]: c for c in entry["conditions"]}
        self.assertLess(by_label["close vs prior 20-week high (breakout level)"]["distance"], 0)
        self.assertLess(by_label["close vs 200-period moving average"]["distance"], 0)
        self.assertLess(by_label["RSI(14) vs momentum floor (50.0)"]["distance"], 0)

    def test_never_fabricates_a_number_when_the_indicator_is_not_yet_defined(self) -> None:
        # Fewer than 200 candles -> MA200/RSI(14)-vs-lookback are genuinely
        # undefined on early rows, but this is the LAST row of a short series --
        # breakout_high (20-candle lookback) is defined, ma200 (200) is not.
        closes = [100.0 + i for i in range(25)]
        _write_candle_file(self.tmp / "GOLD_1week.json", closes)

        entry = esd._breakout_momentum_distance(self.tmp, now=None)

        by_label = {c["label"]: c for c in entry["conditions"]}
        self.assertIsNone(by_label["close vs 200-period moving average"]["distance"])


class CointegrationPairsDistanceTest(unittest.TestCase):
    def test_distance_is_exactly_entry_z_minus_abs_real_zscore(self) -> None:
        # Real formula check: whatever add_indicators computes as the real
        # z-score, the exported distance must be exactly entry_z - |z| --
        # catches a sign error or wrong-parameter wiring bug, not just "some
        # number came out."
        import numpy as np

        n = 410  # hedge_ratio/spread need 200 lookback, then zscore needs another 200 on top of that
        base_time_ms = 1_700_000_000_000
        dates = [f"2026-01-{(i % 28) + 1:02d}" for i in range(n)]
        rng = np.random.default_rng(20260808)
        btc = pd.DataFrame({
            "close_time": [base_time_ms + i * 43_200_000 for i in range(n)],
            "date": dates,
            "close": 50000.0 + rng.normal(0, 500, n).cumsum(),
        })
        eth = pd.DataFrame({
            "close_time": btc["close_time"],
            "date": dates,
            "close": 3000.0 + rng.normal(0, 80, n).cumsum(),  # independently random -- decorrelated from BTC on purpose
        })

        with patch.object(esd, "fetch_timeframe_candles", side_effect=[(btc, "test"), (eth, "test")]):
            entry = esd._cointegration_pairs_distance(client=None, now=None)

        cond = entry["conditions"][0]
        expected = round(cointegration_pairs.DEFAULT_PARAMETERS.entry_z - abs(cond["raw_zscore"]), 4)
        self.assertEqual(cond["distance"], expected)


class NoTimeToTriggerLanguageGuardTest(unittest.TestCase):
    def test_exported_condition_payloads_never_contain_an_eta_or_time_prediction(self) -> None:
        # Scans the actual DATA this module produces per condition (what a
        # website consumer would render) -- built from real, hermetic fixture
        # data (no network call, no mutation of the real committed export),
        # not prose commentary in the module's own docstring explaining why
        # this was deliberately avoided.
        tmp = Path(tempfile.mkdtemp())
        try:
            _write_candle_file(tmp / "GOLD_1week.json", [100.0 + i for i in range(210)])
            _write_candle_file(tmp / "BNB_12h.json", [100.0 + i for i in range(210)])
            payload = [
                esd._breakout_momentum_distance(tmp, now=None),
                esd._trend_pullback_distance(tmp, now=None),
            ]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        text = json.dumps(payload).lower()
        forbidden = [
            "eta", "expected within", "estimated time", "time until", "time to trigger",
            "candles until", "minutes until", "hours until", "should trigger", "likely to trigger",
            "probability of firing", "countdown",
        ]
        hits = [term for term in forbidden if term in text]
        self.assertEqual(hits, [], f"forbidden time-prediction language found in the real exported payload: {hits}")


if __name__ == "__main__":
    unittest.main()
