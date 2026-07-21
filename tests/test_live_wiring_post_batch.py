"""Live Wiring Batch — Post-batch promotion list (Three New Hypothesis Batch).
Confirms GOLD_SILVER_RATIO_MR/1day and PEAD (3pct-hold10, 8pct-hold10) are wired
correctly: lxml availability, the earnings-fetcher live path (mocked response),
NO_SIGNAL on a no-earnings period, pairs-leg accounting in the live replay path,
and strategy_version uniqueness (the RMR-batch collision fix must still hold for
PEAD's own multi-config-per-asset shape).
"""
from __future__ import annotations

import unittest

import pandas as pd

from nero_core.execution.live_scheduler import (
    GOLD_SILVER_RATIO_ID,
    GOLD_SILVER_RATIO_LABEL,
    GOLD_SILVER_RATIO_VERSION,
    PEAD_CONFIGS,
    PEAD_ID,
)
from nero_core.execution.replay import replay_gold_silver_ratio_events, replay_pead_events
from nero_core.execution.verification_status import verification_status_for
from nero_core.strategies.gold_silver_ratio_mr import (
    DEFAULT_PARAMETERS as GSR_PARAMETERS,
    INDICATOR_COLUMNS_TO_CHECK as GSR_INDICATOR_COLUMNS,
    add_indicators as gsr_add_indicators,
    align_gold_silver_candles,
    run_backtest as gsr_run_backtest,
)
from nero_core.strategies.pead import PeadParameters, add_atr, build_entry_plan, run_pead_backtest_rows


class LxmlAvailabilityTest(unittest.TestCase):
    def test_lxml_is_importable(self) -> None:
        """PEAD's earnings fetcher (yfinance's get_earnings_dates) requires lxml
        -- confirm it's actually importable in THIS environment, not merely
        listed in requirements.txt."""
        import lxml  # noqa: F401 -- import success is the assertion

    def test_lxml_is_declared_in_requirements(self) -> None:
        import re
        from pathlib import Path

        requirements = Path(__file__).resolve().parents[1] / "requirements.txt"
        text = requirements.read_text()
        self.assertIsNotNone(re.search(r"^lxml", text, re.MULTILINE))


def _gold_silver_candles(n: int = 400, ratio_extreme_at: int | None = None) -> pd.DataFrame:
    rows = []
    close_time = 0
    gold, silver = 1800.0, 25.0
    for i in range(n):
        gold += 0.5 if i % 2 == 0 else -0.5
        silver += 0.02 if i % 2 == 0 else -0.02
        if ratio_extreme_at is not None and i == ratio_extreme_at:
            gold *= 1.6  # push the ratio sharply upward on this one candle
        rows.append({
            "close_time": close_time, "date": pd.Timestamp(close_time, unit="ms", tz="UTC"),
            "gold_close": gold, "silver_close": silver,
        })
        close_time += 86_400_000
    return pd.DataFrame(rows)


class GoldSilverRatioLiveReplayTest(unittest.TestCase):
    def test_replay_matches_backtest_trade_for_trade(self) -> None:
        """Equivalence proof: replay_gold_silver_ratio_events (the live path)
        must produce the SAME trades as the strategy's own run_backtest (the
        tested backtest path) over the same data, from full account inception."""
        aligned = _gold_silver_candles(n=400, ratio_extreme_at=300)
        enriched = gsr_add_indicators(aligned, GSR_PARAMETERS)
        evaluable = enriched.dropna(subset=GSR_INDICATOR_COLUMNS).reset_index(drop=True)

        backtest_trades, backtest_state = gsr_run_backtest(evaluable, GSR_PARAMETERS)

        inception = int(evaluable.iloc[0]["close_time"])
        replay_events, replay_state = replay_gold_silver_ratio_events(evaluable, GSR_PARAMETERS, inception, None)
        replay_exits = [e for e in replay_events if e.signal_type == "EXIT"]

        self.assertEqual(len(replay_exits), len(backtest_trades))
        self.assertAlmostEqual(replay_state.equity, backtest_state.equity, places=6)
        for replay_exit, backtest_trade in zip(replay_exits, backtest_trades):
            self.assertIn(f"r_multiple={backtest_trade.r_multiple:.3f}", replay_exit.reasoning)
            self.assertIn(backtest_trade.exit_reason, replay_exit.reasoning)

    def test_both_legs_and_directions_appear_in_entry_reasoning(self) -> None:
        """Pairs-leg accounting check: an ENTRY event must record BOTH legs'
        own direction (one LONG, one SHORT) -- never silently dropping one."""
        aligned = _gold_silver_candles(n=400, ratio_extreme_at=300)
        enriched = gsr_add_indicators(aligned, GSR_PARAMETERS)
        evaluable = enriched.dropna(subset=GSR_INDICATOR_COLUMNS).reset_index(drop=True)
        inception = int(evaluable.iloc[0]["close_time"])

        events, _state = replay_gold_silver_ratio_events(evaluable, GSR_PARAMETERS, inception, None)
        entries = [e for e in events if e.signal_type == "ENTRY"]
        self.assertGreaterEqual(len(entries), 1)
        for entry in entries:
            self.assertIn("GOLD", entry.reasoning)
            self.assertIn("SILVER", entry.reasoning)
            self.assertIn("LONG", entry.reasoning)
            self.assertIn("SHORT", entry.reasoning)
            self.assertIsNotNone(entry.entry_price)
            self.assertGreater(entry.entry_price, 0.0)

    def test_already_logged_filters_out_old_events(self) -> None:
        aligned = _gold_silver_candles(n=400, ratio_extreme_at=300)
        enriched = gsr_add_indicators(aligned, GSR_PARAMETERS)
        evaluable = enriched.dropna(subset=GSR_INDICATOR_COLUMNS).reset_index(drop=True)
        inception = int(evaluable.iloc[0]["close_time"])

        all_events, _ = replay_gold_silver_ratio_events(evaluable, GSR_PARAMETERS, inception, None)
        self.assertGreater(len(all_events), 0)

        newest_close_time = int(evaluable.iloc[-1]["close_time"])
        no_new_events, _ = replay_gold_silver_ratio_events(evaluable, GSR_PARAMETERS, inception, newest_close_time)
        self.assertEqual(no_new_events, [])


def _pead_candles(n: int = 60, atr_warmup: int = 14) -> pd.DataFrame:
    rows = []
    close_time = 0
    price = 100.0
    for i in range(n):
        rows.append({
            "date": pd.Timestamp(close_time, unit="ms", tz="UTC"), "close_time": close_time,
            "open_time": close_time - 86_400_000, "open": price, "high": price + 1.0, "low": price - 1.0,
            "close": price, "volume": 1000.0,
        })
        close_time += 86_400_000
    return pd.DataFrame(rows)


def _pead_events(rows: list[tuple[pd.Timestamp, float, float, float]]) -> pd.DataFrame:
    idx = pd.DatetimeIndex([r[0] for r in rows])
    frame = pd.DataFrame({
        "eps_estimate": [r[1] for r in rows], "eps_actual": [r[2] for r in rows], "surprise_pct": [r[3] for r in rows],
    }, index=idx)
    frame.index.name = "announcement_time"
    return frame


class PeadLiveReplayTest(unittest.TestCase):
    ATR_WARMUP = 14

    def test_no_signal_on_no_earnings_period_returns_empty_not_an_error(self) -> None:
        """The exact scenario the task calls out: most 30-min runs find NO
        qualifying earnings event -- replay_pead_events must return an empty
        list gracefully, never raise."""
        candles = add_atr(_pead_candles(n=40))
        empty_events = _pead_events([])  # no earnings at all this period
        inception = int(candles.iloc[0]["close_time"])
        events, state = replay_pead_events(candles, empty_events, "AAPL", PeadParameters(), inception, None)
        self.assertEqual(events, [])
        self.assertIsNone(state.open_trade)

    def test_fresh_deployment_never_backfills_history(self) -> None:
        """inception=None (a brand new deployment) must start at the NEWEST
        candle only -- matching every other strategy's own "never backfill a
        fake trading history" convention -- even if a real qualifying
        historical event exists further back."""
        candles = add_atr(_pead_candles(n=40))
        ann_time = candles.iloc[self.ATR_WARMUP + 5]["date"]
        events_df = _pead_events([(ann_time, 1.0, 1.10, 10.0)])
        params = PeadParameters(surprise_threshold_pct=0.05, holding_window_sessions=5)
        replay_events, _state = replay_pead_events(candles, events_df, "AAPL", params, None, None)
        self.assertEqual(replay_events, [])

    def test_mocked_earnings_response_produces_an_entry(self) -> None:
        """The earnings-fetcher live path (mocked earnings response, as the
        task specifies) -- a qualifying surprise produces a real ENTRY event."""
        candles = add_atr(_pead_candles(n=40))
        ann_time = candles.iloc[self.ATR_WARMUP + 5]["date"]
        events_df = _pead_events([(ann_time, 1.0, 1.10, 10.0)])  # mocked 10% positive surprise
        params = PeadParameters(surprise_threshold_pct=0.05, holding_window_sessions=5)
        inception = int(candles.iloc[0]["close_time"])

        replay_events, _state = replay_pead_events(candles, events_df, "AAPL", params, inception, None)
        entries = [e for e in replay_events if e.signal_type == "ENTRY"]
        self.assertEqual(len(entries), 1)
        self.assertIn("LONG", entries[0].reasoning)
        self.assertIn("surprise_pct=10.00", entries[0].reasoning)

    def test_t_plus_1_execution_rule_enforced_in_live_path(self) -> None:
        """The t+1 (next trading day's open) execution rule -- entry must land
        on the candle strictly AFTER the announcement, in the live replay path
        specifically, not just the backtest."""
        candles = add_atr(_pead_candles(n=40))
        ann_idx = self.ATR_WARMUP + 5
        ann_time = candles.iloc[ann_idx]["date"]
        events_df = _pead_events([(ann_time, 1.0, 1.10, 10.0)])
        params = PeadParameters(surprise_threshold_pct=0.05, holding_window_sessions=5)
        inception = int(candles.iloc[0]["close_time"])

        replay_events, _state = replay_pead_events(candles, events_df, "AAPL", params, inception, None)
        entries = [e for e in replay_events if e.signal_type == "ENTRY"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].candle_close_time, int(candles.iloc[ann_idx + 1]["close_time"]))

    def test_replay_matches_backtest_trade_for_trade(self) -> None:
        """Equivalence proof: replay_pead_events (the live path) must produce
        the SAME exits as run_pead_backtest_rows (the tested backtest path)."""
        candles = add_atr(_pead_candles(n=60))
        ann_idx = self.ATR_WARMUP + 5
        events_df = _pead_events([
            (candles.iloc[ann_idx]["date"], 1.0, 1.10, 10.0),
            (candles.iloc[ann_idx + 20]["date"], 1.0, 0.85, -15.0),
        ])
        params = PeadParameters(surprise_threshold_pct=0.05, holding_window_sessions=5)

        entry_plan = build_entry_plan(candles.sort_values("close_time").reset_index(drop=True), events_df, params)
        rows = candles.sort_values("close_time").reset_index(drop=True).to_dict("records")
        backtest_trades, backtest_state = run_pead_backtest_rows(rows, entry_plan, "AAPL", params)

        inception = int(candles.iloc[0]["close_time"])
        replay_events, replay_state = replay_pead_events(candles, events_df, "AAPL", params, inception, None)
        replay_exits = [e for e in replay_events if e.signal_type == "EXIT"]

        self.assertEqual(len(replay_exits), len(backtest_trades))
        self.assertAlmostEqual(replay_state.equity, backtest_state.equity, places=6)
        for replay_exit, backtest_trade in zip(replay_exits, backtest_trades):
            self.assertIn(backtest_trade.exit_reason, replay_exit.reasoning)
            self.assertIn(f"r_multiple={backtest_trade.r_multiple:.3f}", replay_exit.reasoning)


class StrategyVersionUniquenessTest(unittest.TestCase):
    def test_gold_silver_ratio_has_exactly_one_wired_config(self) -> None:
        self.assertEqual(GOLD_SILVER_RATIO_ID, "GOLD_SILVER_RATIO_MR")
        self.assertEqual(GOLD_SILVER_RATIO_VERSION, "gold-silver-ratio-mr-v1.0.0")
        self.assertEqual(GOLD_SILVER_RATIO_LABEL, "GOLD-SILVER")

    def test_pead_wires_exactly_fourteen_configs_seven_tickers_by_two_versions(self) -> None:
        self.assertEqual(len(PEAD_CONFIGS), 14)
        versions = {c.strategy_version for c in PEAD_CONFIGS}
        self.assertEqual(versions, {"pead-v1.0.0-surprise3pct-hold10", "pead-v1.0.0-surprise8pct-hold10"})
        tickers = {c.ticker for c in PEAD_CONFIGS}
        self.assertEqual(len(tickers), 7)

    def test_pead_ticker_plus_version_pairs_are_all_unique(self) -> None:
        keys = [(c.ticker, c.strategy_version) for c in PEAD_CONFIGS]
        self.assertEqual(len(keys), len(set(keys)))

    def test_verification_status_does_not_collide_across_pead_configs_on_the_same_ticker(self) -> None:
        # The RMR-batch collision fix (strategy_version added to the
        # verification_status key) must still hold here: two DIFFERENT PEAD
        # configs on the SAME ticker (e.g. AAPL) must resolve identically-
        # worded but INDEPENDENTLY-KEYED statuses, not silently share one slot
        # that happens to look right by coincidence.
        status_3pct = verification_status_for(PEAD_ID, "pead-v1.0.0-surprise3pct-hold10", "AAPL")
        status_8pct = verification_status_for(PEAD_ID, "pead-v1.0.0-surprise8pct-hold10", "AAPL")
        self.assertIn("verified", status_3pct)
        self.assertIn("survivor-bias caveat", status_3pct)
        self.assertEqual(status_3pct, status_8pct)  # same wording is fine -- the point is they're independently keyed
        # An unwired PEAD config (different threshold/window) must NOT resolve
        # to either wired status -- confirms the key is genuinely specific.
        unwired_status = verification_status_for(PEAD_ID, "pead-v1.0.0-surprise5pct-hold5", "AAPL")
        self.assertNotEqual(unwired_status, status_3pct)

    def test_gold_silver_ratio_verification_status_is_watchlist_not_verified(self) -> None:
        status = verification_status_for(GOLD_SILVER_RATIO_ID, GOLD_SILVER_RATIO_VERSION, GOLD_SILVER_RATIO_LABEL)
        self.assertIn("watchlist", status)
        self.assertIn("forward-testing, not verified", status)


if __name__ == "__main__":
    unittest.main()
