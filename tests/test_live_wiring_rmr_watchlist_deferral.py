"""Live Wiring Batch (RMR watchlist configs) — this batch's own explicit instruction
was to defer, not force-fit, any config whose logic doesn't match the existing
replay machinery ("no bespoke infrastructure in this batch"). See
docs/live_wiring_batch_rmr_watchlist_deferral.md for the full investigation.

These tests lock in WHY RANGE_MEAN_REVERSION v1.0.0 (and its BTC/1d long-only/
confirmation variants) cannot be wired through nero_core.execution.replay.
replay_single_asset_events / nero_core.strategies.registry-backed VariantSpec as
they exist today, so a future contributor sees a concrete, executable reason rather
than re-discovering it from scratch — and so this test suite starts failing the
moment someone generalizes the replay machinery enough to close the gap (a welcome
signal to revisit the deferral, not a bug in this test).
"""
from __future__ import annotations

import unittest
from dataclasses import fields

from nero_core.execution.live_scheduler import SINGLE_ASSET_CONFIGS
from nero_core.strategies.mean_reversion import MeanReversionState
from nero_core.strategies.mean_reversion import OpenTrade as MeanReversionOpenTrade
from nero_core.strategies.range_mean_reversion import OpenTrade as RangeOpenTrade
from nero_core.strategies.range_mean_reversion import RangeMeanReversionState


class NotYetWiredTest(unittest.TestCase):
    def test_range_mean_reversion_is_not_in_the_live_roster(self) -> None:
        strategy_ids = {config.strategy_id for config in SINGLE_ASSET_CONFIGS}
        self.assertNotIn("RANGE_MEAN_REVERSION", strategy_ids)


class StateClassMismatchTest(unittest.TestCase):
    """replay_single_asset_events hardcodes `state = MeanReversionState(...)` and a
    hardcoded call to nero_core.strategies.mean_reversion.evaluate_exit — never
    RANGE_MEAN_REVERSION's own state or evaluate_exit. RANGE_MEAN_REVERSION's own,
    CORRECT evaluate_exit needs a field MeanReversionState doesn't have."""

    def test_mean_reversion_state_lacks_the_adx_hysteresis_counter(self) -> None:
        field_names = {f.name for f in fields(MeanReversionState)}
        self.assertNotIn("consecutive_high_adx_bars", field_names)
        # ...but RangeMeanReversionState (what RANGE_MEAN_REVERSION's own, correct
        # evaluate_exit actually requires) has it:
        range_field_names = {f.name for f in fields(RangeMeanReversionState)}
        self.assertIn("consecutive_high_adx_bars", range_field_names)


class ExitLogicMismatchTest(unittest.TestCase):
    """replay_single_asset_events' hardcoded exit call is
    nero_core.strategies.mean_reversion.evaluate_exit, which unconditionally reads
    trade.target (a FIXED price level) -- RANGE_MEAN_REVERSION's OpenTrade has no
    such field at all (its profit exit is a floating SMA20 cross, computed fresh each
    candle, never stored on the trade). Wiring RANGE_MEAN_REVERSION through the
    hardcoded mean_reversion.evaluate_exit would raise AttributeError the moment any
    trade survives past its entry candle -- not a style nitpick, a hard crash risk in
    a live paper-tracking system."""

    def test_range_mean_reversion_open_trade_has_no_target_field(self) -> None:
        field_names = {f.name for f in fields(RangeOpenTrade)}
        self.assertNotIn("target", field_names)
        # ...but nero_core.strategies.mean_reversion.evaluate_exit's own OpenTrade
        # contract requires exactly that field:
        base_field_names = {f.name for f in fields(MeanReversionOpenTrade)}
        self.assertIn("target", base_field_names)


class EntrySignatureMismatchTest(unittest.TestCase):
    """tools.backtest_compare.VariantSpec.size_entry_fn's contract is a strict
    3-argument callable: (candle, state, params) -> trade. RANGE_MEAN_REVERSION's own
    size_entry needs a 4th argument (direction), since it is genuinely bidirectional
    (LONG or SHORT) unlike every strategy currently wired through this machinery
    (BREAKOUT_MOMENTUM, TREND_PULLBACK, VOLATILITY_SQUEEZE, MEAN_REVERSION are all
    long-only or have direction baked into the entry rule itself). There is no way to
    thread `direction` through the existing 3-argument contract without silently
    hardcoding one side -- which would silently drop every SHORT signal from the
    ledger, not merely fail loudly."""

    def test_size_entry_requires_a_direction_argument_the_shared_contract_lacks(self) -> None:
        import inspect

        from nero_core.strategies.range_mean_reversion import size_entry

        signature = inspect.signature(size_entry)
        self.assertIn("direction", signature.parameters)


if __name__ == "__main__":
    unittest.main()
