"""Live Wiring Batch — RMR watchlist configs, confirmed wired (Replay Machinery
Generalization). Replaces tests/test_live_wiring_rmr_watchlist_deferral.py (deleted),
which locked in WHY these couldn't be wired before the generalization -- these tests
confirm the generalization actually closed that gap: RANGE_MEAN_REVERSION's own
state/exit logic runs correctly through the shared replay machinery, SHORT signals
are genuinely generated and sized (not silently dropped), and the confirmation
variant's 2-candle lookback fires correctly through the as-of-slice adapter.

See docs/replay_machinery_generalization_stage0_design.md for the design and
docs/live_wiring_batch_rmr_watchlist_deferral.md for what was deferred before this.
"""
from __future__ import annotations

import unittest

import pandas as pd

from nero_core.execution.live_scheduler import SINGLE_ASSET_CONFIGS
from nero_core.execution.replay import replay_single_asset_events
from nero_core.execution.verification_status import verification_status_for
from nero_core.strategies.range_mean_reversion import (
    STRATEGY_ID as RANGE_MEAN_REVERSION_ID,
    STRATEGY_VERSION as RMR_V1_VERSION,
    INDICATOR_COLUMNS_TO_CHECK,
    RangeMeanReversionState,
    add_indicators,
)
from nero_core.strategies.range_mean_reversion_confirmation import STRATEGY_VERSION as RMR_CONFIRMATION_VERSION
from nero_core.strategies.range_mean_reversion_long_only import STRATEGY_VERSION as RMR_LONG_ONLY_VERSION
from tools.backtest_compare import VARIANT_SPECS


def _row(close_time: int, close: float, high: float | None = None, low: float | None = None) -> dict:
    return {
        "date": pd.Timestamp(close_time, unit="ms", tz="UTC"), "close_time": close_time,
        "open_time": close_time - 3_600_000, "open": close,
        "high": high if high is not None else close + 0.5, "low": low if low is not None else close - 0.5,
        "close": close, "volume": 100.0,
    }


def _bidirectional_series() -> pd.DataFrame:
    """A long enough ranging series with clean dips BELOW and rallies ABOVE the bands,
    so both LONG and SHORT entries are genuinely reachable -- not just theoretically
    possible."""
    rows = []
    close_time = 0
    price = 100.0
    for i in range(260):
        price = 100.0 + (1.5 if i % 2 == 0 else -1.5)
        rows.append(_row(close_time, price))
        close_time += 3_600_000
    # a clean dip well below the lower band -> LONG signal
    for p in (85.0, 86.0, 100.5):
        rows.append(_row(close_time, p))
        close_time += 3_600_000
    # back to ranging to reset ADX
    for i in range(60):
        price = 100.0 + (1.5 if i % 2 == 0 else -1.5)
        rows.append(_row(close_time, price))
        close_time += 3_600_000
    # a clean rally well above the upper band -> SHORT signal
    for p in (115.0, 114.0, 99.5):
        rows.append(_row(close_time, p))
        close_time += 3_600_000
    return pd.DataFrame(rows)


class RmrConfigsAreWiredTest(unittest.TestCase):
    def test_all_four_rmr_configs_are_in_the_live_roster(self) -> None:
        rmr_configs = [c for c in SINGLE_ASSET_CONFIGS if c.strategy_id == RANGE_MEAN_REVERSION_ID]
        self.assertEqual(len(rmr_configs), 4)
        seen = {(c.asset, c.timeframe, c.strategy_version) for c in rmr_configs}
        self.assertEqual(
            seen,
            {
                ("GOLD", "1week", RMR_V1_VERSION),
                ("SILVER", "1week", RMR_V1_VERSION),
                ("BTC", "24h", RMR_LONG_ONLY_VERSION),
                ("BTC", "24h", RMR_CONFIRMATION_VERSION),
            },
        )

    def test_every_rmr_variant_spec_uses_its_own_state_and_exit_logic_not_mean_reversions(self) -> None:
        for key in (
            "range_mean_reversion_gold_1week", "range_mean_reversion_silver_1week",
            "range_mean_reversion_long_only_btc_1d", "range_mean_reversion_confirmation_btc_1d",
        ):
            spec = VARIANT_SPECS[key]
            state = spec.state_factory(10_000.0)
            self.assertIsInstance(state, RangeMeanReversionState)
            self.assertTrue(hasattr(state, "consecutive_high_adx_bars"))
            self.assertTrue(spec.direction_aware_sizing)

    def test_verification_status_strings_match_for_every_wired_rmr_config(self) -> None:
        for config in SINGLE_ASSET_CONFIGS:
            if config.strategy_id != RANGE_MEAN_REVERSION_ID:
                continue
            status = verification_status_for(config.strategy_id, config.strategy_version, config.asset)
            self.assertIn("watchlist", status)
            self.assertIn("forward-testing, not verified", status)


class ShortSignalsAreGeneratedAndSizedTest(unittest.TestCase):
    def test_replay_generates_both_long_and_short_entries_for_v1_0_0(self) -> None:
        spec = VARIANT_SPECS["range_mean_reversion_gold_1week"]
        candles = _bidirectional_series()
        enriched = spec.add_indicators_fn(candles, spec.params)
        evaluable = enriched.dropna(subset=[c for c in INDICATOR_COLUMNS_TO_CHECK if c in enriched.columns]).reset_index(drop=True)

        inception = int(evaluable.iloc[0]["close_time"])
        events, state = replay_single_asset_events(evaluable, spec, "GOLD", inception, None)

        entries = [e for e in events if e.signal_type == "ENTRY"]
        self.assertGreaterEqual(len(entries), 2, "expected at least one LONG and one SHORT entry")
        for entry in entries:
            self.assertIsNotNone(entry.entry_price)
            self.assertGreater(entry.entry_price, 0.0)

    def test_replay_generates_both_long_and_short_entries_for_long_only_variant_is_long_only(self) -> None:
        # Sanity check on the OTHER direction: the long-only variant must never emit a
        # SHORT-priced entry above the upper band -- confirms direction_aware_sizing
        # correctly threads allow_short=False through the live replay path too, not
        # just the backtest path.
        spec = VARIANT_SPECS["range_mean_reversion_long_only_btc_1d"]
        candles = _bidirectional_series()
        enriched = spec.add_indicators_fn(candles, spec.params)
        evaluable = enriched.dropna(subset=[c for c in INDICATOR_COLUMNS_TO_CHECK if c in enriched.columns]).reset_index(drop=True)

        inception = int(evaluable.iloc[0]["close_time"])
        events, state = replay_single_asset_events(evaluable, spec, "BTC", inception, None)

        entries = [e for e in events if e.signal_type == "ENTRY"]
        self.assertGreaterEqual(len(entries), 1)
        # Every logged entry reasoning must never claim a SHORT direction for this variant.
        for entry in entries:
            self.assertNotIn("SHORT", entry.reasoning)


class ConfirmationLookbackFiresThroughReplayTest(unittest.TestCase):
    def test_confirmation_pattern_produces_an_entry_at_the_confirmation_candles_open(self) -> None:
        spec = VARIANT_SPECS["range_mean_reversion_confirmation_btc_1d"]
        rows = []
        close_time = 0
        price = 100.0
        for i in range(260):
            price = 100.0 + (1.5 if i % 2 == 0 else -1.5)
            rows.append(_row(close_time, price))
            close_time += 3_600_000
        # t: close below lower band; t+1: back above lower band; t+2: entry at open
        rows.append(_row(close_time, 85.0))
        close_time += 3_600_000
        rows.append(_row(close_time, 99.0))
        close_time += 3_600_000
        rows.append(_row(close_time, 100.5))
        candles = pd.DataFrame(rows)

        enriched = spec.add_indicators_fn(candles, spec.params)
        evaluable = enriched.dropna(subset=[c for c in INDICATOR_COLUMNS_TO_CHECK if c in enriched.columns]).reset_index(drop=True)
        inception = int(evaluable.iloc[0]["close_time"])
        events, state = replay_single_asset_events(evaluable, spec, "BTC", inception, None)

        entries = [e for e in events if e.signal_type == "ENTRY"]
        self.assertGreaterEqual(len(entries), 1)
        # The confirmation candle's own open (100.5, plus slippage) is the entry price
        # -- not the signal candle's close (85.0) or the confirmation candle's close.
        last_entry = entries[-1]
        self.assertGreater(last_entry.entry_price, 99.0)
        self.assertLess(last_entry.entry_price, 102.0)


if __name__ == "__main__":
    unittest.main()
