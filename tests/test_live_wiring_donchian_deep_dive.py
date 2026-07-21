"""Live Wiring Batch — Donchian Cross-Asset Deep-Dive promotion list, confirmed
wired. GOLD/1week/N20 goes through the standard SINGLE_ASSET_CONFIGS /
process_single_asset path (fetch_timeframe_candles); EUR/USD, GBP/USD/1week/N20 and
USD/JPY/1week/N40 go through the new DONCHIAN_FOREX_CONFIGS / process_donchian_forex_
config path (fetch_forex_ohlcv — MarketDataClient has no forex routing). Both paths
converge on the same generic nero_core.execution.replay.replay_single_asset_events.

These tests confirm: (1) the N-period lookback never leaks the current candle into
its own breakout threshold through the LIVE wiring path (not just the strategy's own
unit tests), (2) each config's holding cap matches its own N preset, not a shared
default, (3) SHORT signals are genuinely generated and correctly sized (not silently
dropped or mis-costed via the wrong evaluate_exit_fn), (4) all 4 (strategy_id,
strategy_version, asset) keys are unique across the WHOLE live roster, not just among
themselves, (5) GOLD and the 3 forex configs share the identical 1week
candle_boundary_due gate, and (6) verification_status.py / export_site_data.py pick
up all 4 entries with the exact task-specified wording.
"""
from __future__ import annotations

import unittest

import pandas as pd

from nero_core.execution.export_site_data import _roster_entries, _trading_roster_keys
from nero_core.execution.live_scheduler import (
    DONCHIAN_FOREX_CONFIGS,
    DONCHIAN_FOREX_TIMEFRAME,
    DONCHIAN_TREND_ID,
    SINGLE_ASSET_CONFIGS,
)
from nero_core.execution.replay import replay_single_asset_events
from nero_core.execution.verification_status import verification_status_for
from tools.backtest_compare import VARIANT_SPECS

GOLD_SPEC = VARIANT_SPECS["donchian_bracket_gold_n20_1week"]
EURUSD_SPEC = VARIANT_SPECS["donchian_bracket_eurusd_n20_1week"]
GBPUSD_SPEC = VARIANT_SPECS["donchian_bracket_gbpusd_n20_1week"]
USDJPY_SPEC = VARIANT_SPECS["donchian_bracket_usdjpy_n40_1week"]
ALL_4_SPECS = (GOLD_SPEC, EURUSD_SPEC, GBPUSD_SPEC, USDJPY_SPEC)

WEEK_MS = 604_800_000


def _weekly_row(week_index: int, close: float, high: float | None = None, low: float | None = None) -> dict:
    close_time = week_index * WEEK_MS
    return {
        "date": pd.Timestamp(close_time, unit="ms", tz="UTC"), "close_time": close_time,
        "open_time": close_time - WEEK_MS, "open": close,
        "high": high if high is not None else close + 1.0, "low": low if low is not None else close - 1.0,
        "close": close, "volume": 1000.0,
    }


def _flat_then_breakout(n_flat: int, flat_price: float, breakout_price: float) -> pd.DataFrame:
    rows = [_weekly_row(i, flat_price) for i in range(n_flat)]
    rows.append(_weekly_row(n_flat, breakout_price, high=breakout_price + 1.0, low=breakout_price - 1.0))
    return pd.DataFrame(rows)


def _flat_then_breakdown(n_flat: int, flat_price: float, breakdown_price: float) -> pd.DataFrame:
    rows = [_weekly_row(i, flat_price) for i in range(n_flat)]
    rows.append(_weekly_row(n_flat, breakdown_price, high=breakdown_price + 1.0, low=breakdown_price - 1.0))
    return pd.DataFrame(rows)


def _replay_from_start(evaluable: pd.DataFrame, spec, asset: str):
    """replay_single_asset_events with inception_close_time_ms=None starts a FRESH
    account at the NEWEST row only (never backfilling history -- see that function's
    own docstring), which is the correct production behavior but wrong for a test that
    wants to replay a WHOLE synthetic history from its first row. Anchoring inception
    at the first evaluable row's own close_time simulates "this account has been
    trading since the start of this series" -- every event across the whole range is
    then new (already_logged_close_time_ms=None)."""
    inception = int(evaluable.iloc[0]["close_time"])
    return replay_single_asset_events(evaluable, spec, asset, inception, None)


class ConfigsAreWiredTest(unittest.TestCase):
    def test_gold_n20_is_in_single_asset_configs(self) -> None:
        matches = [c for c in SINGLE_ASSET_CONFIGS if c.strategy_id == DONCHIAN_TREND_ID]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].asset, "GOLD")
        self.assertEqual(matches[0].timeframe, "1week")

    def test_all_3_forex_configs_are_in_donchian_forex_configs(self) -> None:
        pairs = {c.pair for c in DONCHIAN_FOREX_CONFIGS}
        self.assertEqual(pairs, {"EUR/USD", "GBP/USD", "USD/JPY"})

    def test_all_4_specs_use_the_donchian_exit_not_the_long_only_default(self) -> None:
        # Every one of the 4 VariantSpec entries must override evaluate_exit_fn to
        # donchian_bracket_evaluate_exit -- leaving any one at the default long-only
        # mean_reversion.evaluate_exit would compile and run without error (OpenTrade
        # has a .target field either way) but silently apply the wrong stop/target
        # logic to that config's SHORT trades. None of the 4 is direction_aware_sizing
        # (Donchian infers direction internally, unlike RANGE_MEAN_REVERSION).
        for spec in ALL_4_SPECS:
            self.assertEqual(spec.evaluate_exit_fn.__name__, "evaluate_exit")
            self.assertEqual(spec.evaluate_exit_fn.__module__, "nero_core.strategies.donchian_breakout_bracket")
            self.assertFalse(spec.direction_aware_sizing)


class NPeriodLookbackNoLookaheadTest(unittest.TestCase):
    def test_flat_history_produces_no_entry_through_live_replay(self) -> None:
        # 25 flat weekly candles -- channel never breaks, so NO ENTRY should fire
        # anywhere, confirmed through the actual live replay path, not just the
        # strategy module's own isolated unit tests.
        candles = pd.DataFrame([_weekly_row(i, 100.0) for i in range(25)])
        enriched = GOLD_SPEC.add_indicators_fn(candles, GOLD_SPEC.params)
        evaluable = enriched.dropna(subset=["donchian_high", "donchian_low", "atr"]).reset_index(drop=True)
        events, _state = _replay_from_start(evaluable, GOLD_SPEC, "GOLD")
        entries = [e for e in events if e.signal_type == "ENTRY"]
        self.assertEqual(entries, [])

    def test_breakout_candle_does_not_count_its_own_high_toward_its_own_threshold(self) -> None:
        # 25 flat candles at 100, then one candle breaking out to 150. The breakout
        # candle's OWN high (151) must not be part of the channel it's being judged
        # against -- if it leaked in, entry_channel_high would include 151 and this
        # exact candle's close (150) would fail its own breakout test.
        candles = _flat_then_breakout(n_flat=25, flat_price=100.0, breakout_price=150.0)
        enriched = GOLD_SPEC.add_indicators_fn(candles, GOLD_SPEC.params)
        evaluable = enriched.dropna(subset=["donchian_high", "donchian_low", "atr"]).reset_index(drop=True)
        events, _state = _replay_from_start(evaluable, GOLD_SPEC, "GOLD")
        entries = [e for e in events if e.signal_type == "ENTRY"]
        self.assertEqual(len(entries), 1)
        self.assertAlmostEqual(entries[0].entry_price, 150.0 * (1 + GOLD_SPEC.params.slippage_bps / 10000.0), places=4)


class HoldingCapPerNTest(unittest.TestCase):
    def test_n20_and_n40_configs_carry_different_caps_not_a_shared_default(self) -> None:
        self.assertEqual(GOLD_SPEC.params.max_holding_hours, 30 * 168)
        self.assertEqual(USDJPY_SPEC.params.max_holding_hours, 52 * 168)
        self.assertNotEqual(GOLD_SPEC.params.max_holding_hours, USDJPY_SPEC.params.max_holding_hours)

    def test_n20_position_time_exits_at_its_own_30_week_cap_through_live_replay(self) -> None:
        # Entry breakout at week 25, then 35 more flat weeks (no stop/target hit) --
        # comfortably past N20's 30-week cap, so a TIME exit must fire through the
        # actual live replay path (not force a stop/target).
        rows = [_weekly_row(i, 100.0) for i in range(25)]
        rows.append(_weekly_row(25, 150.0, high=151.0, low=149.0))  # breakout -> LONG entry
        for i in range(26, 26 + 35):
            rows.append(_weekly_row(i, 150.0, high=150.5, low=149.5))  # flat, inside stop/target
        candles = pd.DataFrame(rows)
        enriched = GOLD_SPEC.add_indicators_fn(candles, GOLD_SPEC.params)
        evaluable = enriched.dropna(subset=["donchian_high", "donchian_low", "atr"]).reset_index(drop=True)
        events, _state = _replay_from_start(evaluable, GOLD_SPEC, "GOLD")
        exit_events = [e for e in events if e.signal_type == "EXIT"]
        self.assertEqual(len(exit_events), 1)
        self.assertIn("TIME", exit_events[0].reasoning)


class ShortSignalNotSilentlyDroppedTest(unittest.TestCase):
    def test_breakdown_candle_produces_a_genuine_short_entry_through_live_replay(self) -> None:
        candles = _flat_then_breakdown(n_flat=25, flat_price=100.0, breakdown_price=50.0)
        enriched = GOLD_SPEC.add_indicators_fn(candles, GOLD_SPEC.params)
        evaluable = enriched.dropna(subset=["donchian_high", "donchian_low", "atr"]).reset_index(drop=True)
        events, state = _replay_from_start(evaluable, GOLD_SPEC, "GOLD")
        entries = [e for e in events if e.signal_type == "ENTRY"]
        self.assertEqual(len(entries), 1)
        # A genuine SHORT entry (not silently dropped, not mis-costed as LONG): the
        # size_entry "sell to open" slippage direction makes entry_price SLIGHTLY
        # BELOW the raw close, the opposite direction from a LONG entry's "buy" slippage.
        self.assertLess(entries[0].entry_price, 50.0)
        self.assertEqual(state.open_trade.direction, "SHORT")
        self.assertGreater(state.open_trade.stop_loss, state.open_trade.entry_price)  # stop ABOVE entry for a short
        self.assertLess(state.open_trade.target, state.open_trade.entry_price)  # target BELOW entry for a short

    def test_short_exit_uses_donchian_evaluate_exit_not_the_long_only_default(self) -> None:
        # If evaluate_exit_fn had been left at the default long-only mean_reversion.
        # evaluate_exit, this SHORT position's stop (ABOVE entry) would never be
        # correctly checked against candle HIGHS the way donchian_bracket_evaluate_exit
        # does -- it would silently apply the wrong (LONG-shaped) stop/target logic.
        candles = _flat_then_breakdown(n_flat=25, flat_price=100.0, breakdown_price=50.0)
        enriched = GOLD_SPEC.add_indicators_fn(candles, GOLD_SPEC.params)
        evaluable = enriched.dropna(subset=["donchian_high", "donchian_low", "atr"]).reset_index(drop=True)
        # A big rally back up through the SHORT's stop level -- only correctly
        # detected as a stop-out if evaluate_exit_fn is donchian_bracket_evaluate_exit
        # (checks candle HIGH against a stop ABOVE entry for a short).
        rally_row = _weekly_row(26, 90.0, high=200.0, low=80.0)
        full = pd.concat([evaluable, pd.DataFrame([rally_row])], ignore_index=True)
        events, _state = _replay_from_start(full, GOLD_SPEC, "GOLD")
        exit_events = [e for e in events if e.signal_type == "EXIT"]
        self.assertEqual(len(exit_events), 1)
        self.assertIn("SL", exit_events[0].reasoning)


class StrategyVersionUniquenessAcrossFullRosterTest(unittest.TestCase):
    def test_no_key_collision_against_the_entire_live_roster(self) -> None:
        keys = [(c.strategy_id, c.strategy_version, c.asset) for c in SINGLE_ASSET_CONFIGS]
        keys.extend((DONCHIAN_TREND_ID, c.strategy_version, c.pair) for c in DONCHIAN_FOREX_CONFIGS)
        self.assertEqual(len(keys), len(set(keys)), "duplicate (strategy_id, strategy_version, asset) key found")

    def test_all_4_donchian_keys_specifically_are_distinct(self) -> None:
        donchian_keys = [
            (c.strategy_id, c.strategy_version, c.asset) for c in SINGLE_ASSET_CONFIGS if c.strategy_id == DONCHIAN_TREND_ID
        ]
        donchian_keys.extend((DONCHIAN_TREND_ID, c.strategy_version, c.pair) for c in DONCHIAN_FOREX_CONFIGS)
        self.assertEqual(len(donchian_keys), 4)
        self.assertEqual(len(donchian_keys), len(set(donchian_keys)))


class WeeklyBoundaryConventionSharedTest(unittest.TestCase):
    def test_gold_and_forex_configs_use_the_identical_1week_timeframe_constant(self) -> None:
        gold_config = next(c for c in SINGLE_ASSET_CONFIGS if c.strategy_id == DONCHIAN_TREND_ID)
        self.assertEqual(gold_config.timeframe, "1week")
        self.assertEqual(DONCHIAN_FOREX_TIMEFRAME, "1week")
        # Both feed the SAME candle_boundary_due("1week", now) gate in run_once() --
        # this equality is what makes that shared gate call correct, not two
        # independently-drifting timeframe strings.
        self.assertEqual(gold_config.timeframe, DONCHIAN_FOREX_TIMEFRAME)


class VerificationStatusWiredTest(unittest.TestCase):
    def test_all_4_configs_have_a_registered_non_default_status(self) -> None:
        cases = [
            ("donchian-trend-v2.0.0-bracket-gold-n20-1week", "GOLD"),
            ("donchian-trend-v2.0.0-bracket-eurusd-n20-1week", "EUR/USD"),
            ("donchian-trend-v2.0.0-bracket-gbpusd-n20-1week", "GBP/USD"),
            ("donchian-trend-v2.0.0-bracket-usdjpy-n40-1week", "USD/JPY"),
        ]
        for version, asset in cases:
            status = verification_status_for(DONCHIAN_TREND_ID, version, asset)
            self.assertNotEqual(status, "unverified")
            self.assertIn("watchlist", status)
            self.assertIn("grid-shift structurally unavailable at 1week", status)

    def test_gold_status_mentions_the_ci_and_timing_confirmation(self) -> None:
        status = verification_status_for(DONCHIAN_TREND_ID, "donchian-trend-v2.0.0-bracket-gold-n20-1week", "GOLD")
        self.assertIn("CI clears zero both halves", status)
        self.assertIn("breakout-timing edge confirmed", status)


class ExportSiteDataPicksUpAll4Test(unittest.TestCase):
    def test_trading_roster_keys_include_all_4(self) -> None:
        keys = _trading_roster_keys()
        donchian_keys = [k for k in keys if k[0] == DONCHIAN_TREND_ID]
        self.assertEqual(len(donchian_keys), 4)

    def test_roster_entries_include_all_4_with_correct_status_strings(self) -> None:
        entries = [e for e in _roster_entries() if e["name"] == DONCHIAN_TREND_ID]
        self.assertEqual(len(entries), 4)
        for entry in entries:
            self.assertNotEqual(entry["verification_status"], "unverified")
            self.assertEqual(entry["timeframe"], "1week")


if __name__ == "__main__":
    unittest.main()
