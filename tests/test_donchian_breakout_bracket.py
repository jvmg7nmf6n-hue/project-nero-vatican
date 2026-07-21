from __future__ import annotations

import unittest

import pandas as pd

from nero_core.strategies import donchian_breakout_bracket as dbb
from nero_core.strategies.mean_reversion import MeanReversionState


def _candles(rows: list[tuple[float, float, float, float]], start: str = "2024-01-01") -> pd.DataFrame:
    """rows: list of (open, high, low, close). One candle per day for simplicity."""
    out = []
    ts = pd.Timestamp(start, tz="UTC")
    for i, (o, h, l, c) in enumerate(rows):
        day = ts + pd.Timedelta(days=i)
        close_time = int(day.timestamp() * 1000)
        out.append({
            "date": day, "open_time": close_time - 86_400_000, "close_time": close_time,
            "open": o, "high": h, "low": l, "close": c, "volume": 1000.0,
        })
    return pd.DataFrame(out)


class BuildParametersForNTest(unittest.TestCase):
    def test_1week_channel_period_is_1_to_1(self) -> None:
        params = dbb.build_parameters_for_n("N20", "1week", fee_bps=10.0, slippage_bps=2.0)
        self.assertEqual(params.channel_period, 20)
        self.assertEqual(params.max_holding_hours, 30 * 168)

    def test_1day_channel_period_scales_by_trading_days_per_week(self) -> None:
        params = dbb.build_parameters_for_n("N20", "1day", fee_bps=10.0, slippage_bps=2.0)
        self.assertEqual(params.channel_period, 20 * 5)
        # Holding cap is a real-time (hours) cap, identical regardless of timeframe.
        self.assertEqual(params.max_holding_hours, 30 * 168)

    def test_mechanically_invalid_preset_raises(self) -> None:
        original = dbb.N_PRESETS["N10"]
        dbb.N_PRESETS["N10_BAD"] = {"channel_weeks": 20, "holding_weeks": 10, "thesis": "invalid"}
        try:
            with self.assertRaises(dbb.MechanicallyInvalidConfigError):
                dbb.build_parameters_for_n("N10_BAD", "1week", fee_bps=10.0, slippage_bps=2.0)
        finally:
            del dbb.N_PRESETS["N10_BAD"]
        self.assertEqual(dbb.N_PRESETS["N10"], original)


class AddIndicatorsNoLookaheadTest(unittest.TestCase):
    def test_channel_excludes_current_candle(self) -> None:
        # 5 candles, highs strictly increasing: 10,11,12,13,14. With channel_period=3,
        # row 4's donchian_high should be max(highs[1:4]) = 13, NOT 14 (its own high).
        rows = [(10, 10, 9, 10), (11, 11, 10, 11), (12, 12, 11, 12), (13, 13, 12, 13), (14, 14, 13, 14)]
        params = dbb.DonchianBracketParameters(channel_period=3)
        enriched = dbb.add_indicators(_candles(rows), params)
        self.assertEqual(enriched.iloc[4]["donchian_high"], 13.0)


class EvaluateEntryTest(unittest.TestCase):
    def _evaluable(self, rows, channel_period=3):
        params = dbb.DonchianBracketParameters(channel_period=channel_period, atr_period=3)
        enriched = dbb.add_indicators(_candles(rows), params)
        return enriched.dropna(subset=dbb.INDICATOR_COLUMNS_TO_CHECK).reset_index(drop=True), params

    def test_long_breakout_passes_with_long_direction(self) -> None:
        rows = [(10, 10, 9, 10)] * 4 + [(10, 20, 10, 20)]  # last candle breaks well above prior highs
        evaluable, params = self._evaluable(rows)
        state = MeanReversionState(equity=10000.0)
        result = dbb.evaluate_entry(evaluable.iloc[-1], state, params)
        self.assertTrue(result.passed)
        self.assertEqual(result.direction, "LONG")

    def test_short_breakdown_passes_with_short_direction(self) -> None:
        rows = [(10, 11, 10, 10)] * 4 + [(10, 10, 1, 1)]  # last candle breaks well below prior lows
        evaluable, params = self._evaluable(rows)
        state = MeanReversionState(equity=10000.0)
        result = dbb.evaluate_entry(evaluable.iloc[-1], state, params)
        self.assertTrue(result.passed)
        self.assertEqual(result.direction, "SHORT")

    def test_no_breakout_rejects(self) -> None:
        rows = [(10, 11, 9, 10)] * 5  # flat, no candle ever breaks the channel
        evaluable, params = self._evaluable(rows)
        state = MeanReversionState(equity=10000.0)
        result = dbb.evaluate_entry(evaluable.iloc[-1], state, params)
        self.assertFalse(result.passed)
        self.assertIn("NO_BREAKOUT", result.reasons)

    def test_open_trade_exists_rejects(self) -> None:
        rows = [(10, 10, 9, 10)] * 4 + [(10, 20, 10, 20)]
        evaluable, params = self._evaluable(rows)
        state = MeanReversionState(equity=10000.0)
        state.open_trade = dbb.OpenTrade(
            direction="LONG", entry_price=10.0, stop_loss=9.0, target=12.0, quantity=1.0,
            notional=10.0, risk_dollars=1.0, entry_fee=0.0, open_close_time=0, entry_atr=1.0,
        )
        result = dbb.evaluate_entry(evaluable.iloc[-1], state, params)
        self.assertFalse(result.passed)
        self.assertIn("OPEN_TRADE_EXISTS", result.reasons)


class SizeEntryTest(unittest.TestCase):
    def test_long_sizing_geometry(self) -> None:
        rows = [(10, 10, 9, 10)] * 4 + [(10, 20, 10, 20)]
        params = dbb.DonchianBracketParameters(channel_period=3, atr_period=3, atr_stop_multiple=2.0, target_r_multiple=2.0, slippage_bps=0.0)
        enriched = dbb.add_indicators(_candles(rows), params)
        evaluable = enriched.dropna(subset=dbb.INDICATOR_COLUMNS_TO_CHECK).reset_index(drop=True)
        state = MeanReversionState(equity=10000.0)
        trade = dbb.size_entry(evaluable.iloc[-1], state, params)
        self.assertIsNotNone(trade)
        self.assertEqual(trade.direction, "LONG")
        risk_distance = trade.entry_price - trade.stop_loss
        self.assertAlmostEqual(trade.target - trade.entry_price, 2.0 * risk_distance, places=6)

    def test_short_sizing_geometry_mirrors_long(self) -> None:
        rows = [(10, 11, 10, 10)] * 4 + [(10, 10, 1, 1)]
        params = dbb.DonchianBracketParameters(channel_period=3, atr_period=3, atr_stop_multiple=2.0, target_r_multiple=2.0, slippage_bps=0.0)
        enriched = dbb.add_indicators(_candles(rows), params)
        evaluable = enriched.dropna(subset=dbb.INDICATOR_COLUMNS_TO_CHECK).reset_index(drop=True)
        state = MeanReversionState(equity=10000.0)
        trade = dbb.size_entry(evaluable.iloc[-1], state, params)
        self.assertIsNotNone(trade)
        self.assertEqual(trade.direction, "SHORT")
        self.assertGreater(trade.stop_loss, trade.entry_price)
        self.assertLess(trade.target, trade.entry_price)
        risk_distance = trade.stop_loss - trade.entry_price
        self.assertAlmostEqual(trade.entry_price - trade.target, 2.0 * risk_distance, places=6)


class EvaluateExitTest(unittest.TestCase):
    def test_long_stop_takes_priority_over_target_same_candle(self) -> None:
        params = dbb.DonchianBracketParameters(slippage_bps=0.0, fee_bps=0.0)
        state = MeanReversionState(equity=10000.0)
        state.open_trade = dbb.OpenTrade(
            direction="LONG", entry_price=100.0, stop_loss=95.0, target=110.0, quantity=1.0,
            notional=100.0, risk_dollars=5.0, entry_fee=0.0, open_close_time=0, entry_atr=2.0,
        )
        candle = pd.Series({"close_time": 3600000, "low": 90.0, "high": 115.0, "close": 100.0})
        event = dbb.evaluate_exit(candle, state, params)
        self.assertEqual(event.exit_reason, "SL")

    def test_short_stop_above_entry_target_below(self) -> None:
        params = dbb.DonchianBracketParameters(slippage_bps=0.0, fee_bps=0.0)
        state = MeanReversionState(equity=10000.0)
        state.open_trade = dbb.OpenTrade(
            direction="SHORT", entry_price=100.0, stop_loss=105.0, target=90.0, quantity=1.0,
            notional=100.0, risk_dollars=5.0, entry_fee=0.0, open_close_time=0, entry_atr=2.0,
        )
        candle = pd.Series({"close_time": 3600000, "low": 88.0, "high": 92.0, "close": 89.0})
        event = dbb.evaluate_exit(candle, state, params)
        self.assertEqual(event.exit_reason, "TARGET")
        self.assertGreater(event.net_pnl, 0.0)  # short profited as price fell

    def test_time_exit_fires_past_holding_cap(self) -> None:
        params = dbb.DonchianBracketParameters(slippage_bps=0.0, fee_bps=0.0, max_holding_hours=1.0)
        state = MeanReversionState(equity=10000.0)
        state.open_trade = dbb.OpenTrade(
            direction="LONG", entry_price=100.0, stop_loss=90.0, target=120.0, quantity=1.0,
            notional=100.0, risk_dollars=10.0, entry_fee=0.0, open_close_time=0, entry_atr=2.0,
        )
        candle = pd.Series({"close_time": 2 * 3600000, "low": 99.0, "high": 101.0, "close": 100.5})
        event = dbb.evaluate_exit(candle, state, params)
        self.assertEqual(event.exit_reason, "TIME")


class NearBreakoutMaskTest(unittest.TestCase):
    def test_candle_within_2pct_of_high_is_eligible_without_breaking_out(self) -> None:
        evaluable = pd.DataFrame({
            "close": [99.0, 50.0],
            "donchian_high": [100.0, 100.0],
            "donchian_low": [10.0, 10.0],
        })
        mask = dbb.near_breakout_mask(evaluable, proximity_pct=2.0)
        self.assertTrue(bool(mask.iloc[0]))  # 99 is within 2% of 100
        self.assertFalse(bool(mask.iloc[1]))  # 50 is nowhere near either extreme

    def test_candle_within_2pct_of_low_is_eligible(self) -> None:
        evaluable = pd.DataFrame({"close": [10.1], "donchian_high": [100.0], "donchian_low": [10.0]})
        mask = dbb.near_breakout_mask(evaluable, proximity_pct=2.0)
        self.assertTrue(bool(mask.iloc[0]))


class RunDonchianBracketBacktestTest(unittest.TestCase):
    def test_end_to_end_produces_a_long_trade_that_hits_target(self) -> None:
        flat = [(10, 10, 9, 10)] * 5
        breakout = [(10, 30, 10, 30)]  # huge breakout candle -- entry here
        follow_through = [(30, 60, 30, 60)] * 3  # should hit the 2R target quickly
        rows = flat + breakout + follow_through
        params = dbb.DonchianBracketParameters(channel_period=3, atr_period=3, atr_stop_multiple=2.0, target_r_multiple=2.0)
        trades, _state = dbb.run_donchian_bracket_backtest(_candles(rows), params)
        self.assertGreaterEqual(len(trades), 1)
        self.assertEqual(trades[0].exit_reason, "TARGET")
        self.assertGreater(trades[0].r_multiple, 0)


if __name__ == "__main__":
    unittest.main()
