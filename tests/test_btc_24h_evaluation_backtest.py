"""Regression test for the BTC/24h evaluation-universe backtest (item 1,
Eve engine v1 follow-up session): proves the two live RANGE_MEAN_REVERSION
BTC variants (range-mean-reversion-v1.1.0-long-only,
range-mean-reversion-v1.3.0-confirmation) -- chosen and wired live by a
human months ago, accruing real paper trades in truth_ledger.db -- were
actually run against real multi-year history (docs/research_data/
evaluation_candles/BTC_24h.json, 1800 daily candles, 2021-08-28 to
2026-08-01) through the SAME statistical apparatus Adam/Eve hypotheses use
(tools.backtest_train_test_split.split_chronological,
tools.backtest_statistics.bootstrap_mean_r_ci/classify_verdict,
MIN_SAMPLE_SIZE), applied to trades produced by these strategies' OWN real
entry/exit/sizing logic (tools.backtest_compare.run_backtest) rather than
forced through rule_dsl (which cannot express RANGE_MEAN_REVERSION's ADX
regime gate / SMA20 reversion target / direction-aware sizing at all).

Every number here is deterministic (fixed candle file, fixed bootstrap seed,
fixed random-baseline seed) -- if this test ever produces different
verdicts or trade counts, either the evaluation export was regenerated with
different data, or something in the shared harness
(split_chronological/bootstrap_mean_r_ci/classify_verdict/run_backtest)
changed -- both worth knowing about immediately, which is the whole point
of a frozen regression test here."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

import pandas as pd

from tools.backtest_compare import VARIANT_SPECS, run_backtest
from tools.backtest_statistics import (
    MIN_SAMPLE_SIZE,
    VERDICT_DIED,
    VERDICT_SURVIVED,
    bootstrap_mean_r_ci,
    classify_verdict,
)
from tools.backtest_train_test_split import split_chronological

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPORT_PATH = REPO_ROOT / "docs" / "research_data" / "evaluation_candles" / "BTC_24h.json"

VERDICT_INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"


def _load_evaluation_candles(path: Path) -> pd.DataFrame:
    data = json.loads(path.read_text())
    rows = data["candles"]
    open_time_ms = [int(c["time"]) * 1000 for c in rows]
    close_time_ms = [t + 86_400_000 for t in open_time_ms]
    frame = pd.DataFrame({
        "open_time": open_time_ms,
        "close_time": close_time_ms,
        "open": [float(c["open"]) for c in rows],
        "high": [float(c["high"]) for c in rows],
        "low": [float(c["low"]) for c in rows],
        "close": [float(c["close"]) for c in rows],
        "volume": [float(c.get("volume") or 0.0) for c in rows],
    })
    frame["date"] = pd.to_datetime(frame["close_time"], unit="ms", utc=True)
    return frame


def _half_stats(raw: pd.DataFrame, spec) -> dict:
    trades, _state = run_backtest(raw, spec, asset="BTC")
    n = len(trades)
    expectancy_r = sum(t.r_multiple for t in trades) / n if n else 0.0
    ci = bootstrap_mean_r_ci([t.r_multiple for t in trades]) if n else None
    return {"trades": n, "expectancy_r": expectancy_r, "ci": ci}


def _map_half_verdict(stats: dict) -> str:
    """Mirrors nero_core.eve.scoring._map_half_verdict exactly (self-compared
    classify_verdict, then split a thin-but-positive half into
    INSUFFICIENT_SAMPLE using trades alone) -- applied here for the SAME
    reason Eve applies it, so this report's verdicts stay methodologically
    consistent with the rest of this project's own convention."""
    if stats["trades"] == 0:
        return VERDICT_INSUFFICIENT_SAMPLE
    verdict = classify_verdict(stats, stats, min_sample_size=MIN_SAMPLE_SIZE)
    if verdict in (VERDICT_DIED, VERDICT_SURVIVED):
        return verdict
    if stats["trades"] < MIN_SAMPLE_SIZE:
        return VERDICT_INSUFFICIENT_SAMPLE
    return "PROMISING-WATCHLIST"


@unittest.skipUnless(EXPORT_PATH.exists(), "BTC/24h evaluation export not present -- run the export before this test")
class Btc24hEvaluationBacktestTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.candles = _load_evaluation_candles(EXPORT_PATH)
        cls.train_raw, cls.test_raw = split_chronological(cls.candles)

    def test_export_shape_is_the_recorded_1800_daily_candles(self) -> None:
        self.assertEqual(len(self.candles), 1800)
        self.assertEqual(self.candles["date"].iloc[0].date().isoformat(), "2021-08-29")
        self.assertEqual(self.candles["date"].iloc[-1].date().isoformat(), "2026-08-02")

    def test_long_only_variant_died_in_sample_insufficient_sample_out_of_sample(self) -> None:
        spec = VARIANT_SPECS["range_mean_reversion_long_only_btc_1d"]
        train_stats = _half_stats(self.train_raw, spec)
        test_stats = _half_stats(self.test_raw, spec)

        self.assertEqual(train_stats["trades"], 10)
        self.assertLess(train_stats["expectancy_r"], 0.0)
        self.assertEqual(test_stats["trades"], 5)
        self.assertGreater(test_stats["expectancy_r"], 0.0)

        self.assertEqual(_map_half_verdict(train_stats), VERDICT_DIED)
        self.assertEqual(_map_half_verdict(test_stats), VERDICT_INSUFFICIENT_SAMPLE)
        self.assertEqual(classify_verdict(train_stats, test_stats, min_sample_size=MIN_SAMPLE_SIZE), VERDICT_DIED)

    def test_confirmation_variant_died_in_sample_insufficient_sample_out_of_sample(self) -> None:
        spec = VARIANT_SPECS["range_mean_reversion_confirmation_btc_1d"]
        train_stats = _half_stats(self.train_raw, spec)
        test_stats = _half_stats(self.test_raw, spec)

        self.assertEqual(train_stats["trades"], 9)
        self.assertLess(train_stats["expectancy_r"], 0.0)
        self.assertEqual(test_stats["trades"], 7)
        self.assertGreater(test_stats["expectancy_r"], 0.0)

        self.assertEqual(_map_half_verdict(train_stats), VERDICT_DIED)
        self.assertEqual(_map_half_verdict(test_stats), VERDICT_INSUFFICIENT_SAMPLE)
        self.assertEqual(classify_verdict(train_stats, test_stats, min_sample_size=MIN_SAMPLE_SIZE), VERDICT_DIED)

    def test_both_variants_would_have_been_rejected_too_slow_by_the_frequency_gate(self) -> None:
        # Neither variant has a rule_dsl representation (see this module's own
        # docstring), so frequency_gate.measure_entry_frequency cannot run
        # against them directly -- this applies its own thresholds
        # (TARGET_RESOLVED_TRADES=30, FAST_MAX_MONTHS=6, VIABLE_MAX_MONTHS=12)
        # to the OBSERVED combined-halves trade rate instead, exactly as the
        # closing report states as a flagged methodology deviation.
        span_days = (self.candles["close_time"].iloc[-1] - self.candles["close_time"].iloc[0]) / 86_400_000.0
        for key, expected_total_trades in (
            ("range_mean_reversion_long_only_btc_1d", 15),
            ("range_mean_reversion_confirmation_btc_1d", 16),
        ):
            spec = VARIANT_SPECS[key]
            train_stats = _half_stats(self.train_raw, spec)
            test_stats = _half_stats(self.test_raw, spec)
            total_trades = train_stats["trades"] + test_stats["trades"]
            self.assertEqual(total_trades, expected_total_trades)

            trades_per_year = total_trades / (span_days / 365.25)
            months_to_30 = (30 / trades_per_year) * 12
            self.assertGreater(months_to_30, 12.0, f"{key} should classify TOO_SLOW (>12 months to 30 trades)")


if __name__ == "__main__":
    unittest.main()
