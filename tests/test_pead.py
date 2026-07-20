from __future__ import annotations

import unittest
from dataclasses import replace

import pandas as pd

from nero_core.strategies.pead import (
    DEFAULT_PARAMETERS,
    HOLDING_WINDOWS_SESSIONS,
    STRATEGY_ID,
    SURPRISE_THRESHOLDS_PCT,
    PeadParameters,
    add_atr,
    register_default_variant,
    register_variant,
    run_pead_backtest,
    strategy_version_for,
)
from nero_core.strategies.registry import StrategyAlreadyRegisteredError, StrategyRegistry

ATR_WARMUP = 14  # DEFAULT_PARAMETERS.atr_period


def _daily_candles(n: int = 50, start_ms: int = 0, price: float = 100.0) -> pd.DataFrame:
    rows = []
    ts = start_ms
    p = price
    for i in range(n):
        rows.append({
            "date": pd.Timestamp(ts, unit="ms", tz="UTC"), "close_time": ts, "open_time": ts - 86_400_000,
            "open": p, "high": p + 1.0, "low": p - 1.0, "close": p, "volume": 1000.0,
        })
        ts += 86_400_000
    return pd.DataFrame(rows)


def _events(rows: list[tuple[pd.Timestamp, float, float, float]]) -> pd.DataFrame:
    """[(announcement_timestamp, eps_estimate, eps_actual, surprise_pct), ...]"""
    idx = pd.DatetimeIndex([r[0] for r in rows])
    frame = pd.DataFrame({
        "eps_estimate": [r[1] for r in rows], "eps_actual": [r[2] for r in rows], "surprise_pct": [r[3] for r in rows],
    }, index=idx)
    frame.index.name = "announcement_time"
    return frame


def _replace_params(**kwargs) -> PeadParameters:
    return replace(DEFAULT_PARAMETERS, **kwargs)


class StrategyVersionForTest(unittest.TestCase):
    def test_encodes_threshold_and_window(self) -> None:
        self.assertEqual(strategy_version_for(0.05, 5), "pead-v1.0.0-surprise5pct-hold5")
        self.assertEqual(strategy_version_for(0.08, 10), "pead-v1.0.0-surprise8pct-hold10")
        self.assertEqual(strategy_version_for(0.03, 5), "pead-v1.0.0-surprise3pct-hold5")


class RunPeadBacktestTest(unittest.TestCase):
    """All announcement timestamps are placed at ATR_WARMUP + a safe margin, so
    the resulting entry candle always has a valid (non-NaN) ATR -- avoids a
    warmup-timing bug where an announcement too close to the start of history
    lands on a candle whose ATR(14) hasn't yet warmed up."""

    def test_no_entry_when_surprise_below_threshold(self) -> None:
        candles = add_atr(_daily_candles(n=40))
        ann_time = candles.iloc[ATR_WARMUP + 5]["date"]
        events = _events([(ann_time, 1.0, 1.02, 2.0)])  # 2% surprise, below 5% default threshold
        trades, state = run_pead_backtest(candles, events, "TEST", DEFAULT_PARAMETERS)
        self.assertEqual(trades, [])

    def test_long_entry_on_positive_surprise_above_threshold(self) -> None:
        candles = add_atr(_daily_candles(n=40))
        ann_time = candles.iloc[ATR_WARMUP + 5]["date"]
        events = _events([(ann_time, 1.0, 1.10, 10.0)])  # 10% positive surprise
        params = _replace_params(surprise_threshold_pct=0.05, holding_window_sessions=5)
        trades, state = run_pead_backtest(candles, events, "TEST", params)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].exit_reason, "TIME")
        self.assertEqual(trades[0].holding_sessions, 5)

    def test_short_entry_on_negative_surprise_above_threshold(self) -> None:
        candles = add_atr(_daily_candles(n=40))
        ann_time = candles.iloc[ATR_WARMUP + 5]["date"]
        events = _events([(ann_time, 1.0, 0.85, -15.0)])  # -15% surprise
        params = _replace_params(surprise_threshold_pct=0.05, holding_window_sessions=5)
        trades, state = run_pead_backtest(candles, events, "TEST", params)
        self.assertEqual(len(trades), 1)

    def test_entry_executes_at_the_candle_strictly_after_announcement(self) -> None:
        candles = add_atr(_daily_candles(n=40))
        ann_idx = ATR_WARMUP + 5
        ann_time = candles.iloc[ann_idx]["date"]  # matches candle ann_idx's own close_time exactly
        events = _events([(ann_time, 1.0, 1.10, 10.0)])
        params = _replace_params(surprise_threshold_pct=0.05, holding_window_sessions=5)
        trades, _state = run_pead_backtest(candles, events, "TEST", params)
        self.assertEqual(len(trades), 1)
        # entry candle is ann_idx+1 -> exits at ann_idx+1+5 (TIME) -- confirms no
        # lookahead into the announcement candle itself.
        self.assertEqual(trades[0].exit_close_time, int(candles.iloc[ann_idx + 1 + 5]["close_time"]))

    def test_stop_fires_before_holding_window_completes(self) -> None:
        candles = _daily_candles(n=40, price=100.0)
        ann_idx = ATR_WARMUP + 5
        candles.loc[ann_idx + 2, "low"] = 50.0  # a violent drop 2 sessions after entry
        candles = add_atr(candles)
        ann_time = candles.iloc[ann_idx]["date"]
        events = _events([(ann_time, 1.0, 1.10, 10.0)])  # positive surprise -> LONG
        params = _replace_params(surprise_threshold_pct=0.05, holding_window_sessions=5)
        trades, _state = run_pead_backtest(candles, events, "TEST", params)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].exit_reason, "STOP")
        self.assertLess(trades[0].holding_sessions, 5)

    def test_one_position_at_a_time_overlapping_event_is_skipped(self) -> None:
        candles = add_atr(_daily_candles(n=40))
        ann_idx = ATR_WARMUP + 5
        events = _events([
            (candles.iloc[ann_idx]["date"], 1.0, 1.10, 10.0),
            (candles.iloc[ann_idx + 1]["date"], 1.0, 1.10, 10.0),  # still within the first trade's holding window
        ])
        params = _replace_params(surprise_threshold_pct=0.05, holding_window_sessions=10)
        trades, _state = run_pead_backtest(candles, events, "TEST", params)
        self.assertEqual(len(trades), 1)  # the second event was skipped, not stacked

    def test_insufficient_forward_history_is_discarded_not_counted(self) -> None:
        candles = add_atr(_daily_candles(n=ATR_WARMUP + 3))  # too short to complete a 5-session hold
        ann_time = candles.iloc[ATR_WARMUP + 1]["date"]
        events = _events([(ann_time, 1.0, 1.10, 10.0)])
        params = _replace_params(surprise_threshold_pct=0.05, holding_window_sessions=5)
        trades, state = run_pead_backtest(candles, events, "TEST", params)
        self.assertEqual(trades, [])
        self.assertIsNone(state.open_trade)

    def test_direction_override_forces_the_random_baseline_direction(self) -> None:
        candles = add_atr(_daily_candles(n=40))
        ann_time = candles.iloc[ATR_WARMUP + 5]["date"]
        events = _events([(ann_time, 1.0, 1.10, 10.0)])  # real surprise is positive
        params = _replace_params(surprise_threshold_pct=0.05, holding_window_sessions=5)
        override = {ann_time: "SHORT"}
        trades, _state = run_pead_backtest(candles, events, "TEST", params, direction_override=override)
        self.assertEqual(len(trades), 1)

    def test_short_pnl_correctly_inverted(self) -> None:
        candles = _daily_candles(n=40, price=100.0)
        ann_idx = ATR_WARMUP + 5
        # Entry candle (ann_idx+1) stays at 100 (the SHORT opens here); the price
        # only drops AFTER entry, on the candles the position is actually held
        # through -- a real decline during the hold, not one baked into the
        # entry price itself.
        for i in range(ann_idx + 2, ann_idx + 7):
            candles.loc[i, ["open", "high", "low", "close"]] = [90.0, 91.0, 89.0, 90.0]
        candles = add_atr(candles)
        ann_time = candles.iloc[ann_idx]["date"]
        events = _events([(ann_time, 1.0, 0.85, -15.0)])  # SHORT
        params = _replace_params(surprise_threshold_pct=0.05, holding_window_sessions=5)
        trades, _state = run_pead_backtest(candles, events, "TEST", params)
        self.assertEqual(len(trades), 1)
        self.assertGreater(trades[0].gross_pnl, 0.0)  # price fell -- short profits


class AddAtrTest(unittest.TestCase):
    def test_produces_atr_column(self) -> None:
        candles = _daily_candles(n=30)
        enriched = add_atr(candles)
        self.assertIn("atr", enriched.columns)


class RegistrationTest(unittest.TestCase):
    def test_register_variant_uses_correct_id_and_version(self) -> None:
        registry = StrategyRegistry()
        variant = register_variant(0.05, 5, registry)
        self.assertEqual(variant.strategy_id, STRATEGY_ID)
        self.assertEqual(variant.version, "pead-v1.0.0-surprise5pct-hold5")

    def test_registering_the_same_config_twice_is_rejected(self) -> None:
        registry = StrategyRegistry()
        register_variant(0.05, 5, registry)
        with self.assertRaises(StrategyAlreadyRegisteredError):
            register_variant(0.05, 5, registry)

    def test_all_six_configs_register_without_collision(self) -> None:
        registry = StrategyRegistry()
        for threshold in SURPRISE_THRESHOLDS_PCT:
            for window in HOLDING_WINDOWS_SESSIONS:
                register_variant(threshold, window, registry)
        versions = {v.version for v in registry.list_versions(STRATEGY_ID)}
        self.assertEqual(len(versions), 6)

    def test_register_default_variant_works(self) -> None:
        registry = StrategyRegistry()
        variant = register_default_variant(registry)
        self.assertEqual(variant.strategy_id, STRATEGY_ID)


if __name__ == "__main__":
    unittest.main()
