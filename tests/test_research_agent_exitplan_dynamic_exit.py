"""feature/exitplan-dynamic-target-and-hysteresis: ExitPlan's dynamic-target and
regime-break-hysteresis extension (RMR_LONG_ONLY_EURUSD_4H's own exit shape),
plus the no-time-cap ("max_holding_hours omitted") mechanism. See rule_dsl.py's
own EXIT PLAN docstring section and auto_tester._make_exit_evaluator/_evaluate_
exit_for_hypothesis for the design.

BACKWARD COMPATIBILITY is the primary concern here: every one of ~27 existing
live configs never touches ExitPlan at all (it's research_agent-only -- see
test_research_agent_no_auto_wire.py's own HARD TEST), and every EXISTING
research_agent hypothesis's structured_exit_plan uses the original fixed-
three-number shape. _make_exit_evaluator's own contract (proven directly
below, not just asserted by construction) is what guarantees that shape's
behavior stays byte-identical: it returns mean_reversion.evaluate_exit ITSELF
for such a plan, not a re-derived equivalent.
"""
from __future__ import annotations

import unittest

import pandas as pd

from nero_core.research_agent import auto_tester
from nero_core.research_agent.rule_dsl import Condition, ExitPlan, compute_indicator_frame, parse_exit_plan, parse_structured_rule
from nero_core.strategies.mean_reversion import MeanReversionParameters, MeanReversionState, OpenTrade, evaluate_exit

HOUR_MS = 3_600_000
START_MS = 1_700_000_000_000


def _row(close_time: int, close: float, high: float, low: float, **extra) -> pd.Series:
    data = {"close_time": close_time, "close": close, "high": high, "low": low}
    data.update(extra)
    return pd.Series(data)


def _open_trade(entry_price: float, stop_loss: float, target: float, open_close_time: int) -> OpenTrade:
    return OpenTrade(
        entry_price=entry_price, stop_loss=stop_loss, target=target, quantity=1.0,
        notional=entry_price, risk_dollars=entry_price - stop_loss, entry_fee=0.0,
        open_close_time=open_close_time, entry_rsi=0.0, entry_ma20=0.0, entry_bb_lower=0.0,
        entry_ma200=0.0, entry_atr=1.0,
    )


class MakeExitEvaluatorBackwardCompatibilityTest(unittest.TestCase):
    def test_old_shape_plan_returns_evaluate_exit_itself(self) -> None:
        plan = parse_exit_plan({"stop_atr_multiple": 1.5, "target_r_multiple": 2.0, "max_holding_hours": 24.0})
        evaluator = auto_tester._make_exit_evaluator(plan)
        self.assertIs(evaluator, evaluate_exit)  # the literal same function object, not a reimplementation

    def test_dynamic_target_plan_does_not_use_evaluate_exit_directly(self) -> None:
        plan = parse_exit_plan({
            "stop_atr_multiple": 2.0,
            "dynamic_target_condition": {"field": "close", "op": "gte", "compare_to_field": "ma20"},
        })
        evaluator = auto_tester._make_exit_evaluator(plan)
        self.assertIsNot(evaluator, evaluate_exit)

    def test_regime_break_plan_does_not_use_evaluate_exit_directly(self) -> None:
        plan = parse_exit_plan({
            "stop_atr_multiple": 2.0, "target_r_multiple": 2.0,
            "regime_break_condition": {"field": "adx14", "op": "gte", "value": 28.0},
            "regime_break_consecutive_bars": 2,
        })
        evaluator = auto_tester._make_exit_evaluator(plan)
        self.assertIsNot(evaluator, evaluate_exit)

    def test_no_time_cap_plan_does_not_use_evaluate_exit_directly(self) -> None:
        # max_holding_hours=None alone (no dynamic target, no regime break) still
        # can't safely delegate to evaluate_exit -- that function's own TIME check
        # would crash comparing hours_held against None.
        plan = parse_exit_plan({"stop_atr_multiple": 2.0, "target_r_multiple": 2.0})
        evaluator = auto_tester._make_exit_evaluator(plan)
        self.assertIsNot(evaluator, evaluate_exit)


class DynamicTargetExitTest(unittest.TestCase):
    """Real candle data, real compute_indicator_frame, real run_backtest --
    matches RMR_LONG_ONLY_EURUSD_4H's own actual mechanism: LONG entry on a
    dip, exit when close crosses back up to (the CURRENT, moving) ma20."""

    def _candles(self) -> pd.DataFrame:
        rows = []
        close = 100.0
        # Warmup: 25 flat-ish candles so ma20/atr14 are populated (period 20/14).
        for i in range(25):
            close = 100.0 + 0.05 * ((i % 3) - 1)
            rows.append({"close_time": START_MS + i * HOUR_MS, "close": close, "high": close + 0.3, "low": close - 0.3, "volume": 1.0})
        # A sharp one-candle dip (entry trigger: close < 95), then a steady recovery
        # back up across ma20 over several candles (so ma20 itself is still moving
        # while price recovers -- a REAL test of "dynamic", not "frozen-looking" by
        # coincidence).
        dip_index = 25
        close = 90.0
        rows.append({"close_time": START_MS + dip_index * HOUR_MS, "close": close, "high": close + 0.3, "low": close - 0.3, "volume": 1.0})
        for j in range(1, 15):
            close += 0.9
            i = dip_index + j
            rows.append({"close_time": START_MS + i * HOUR_MS, "close": close, "high": close + 0.3, "low": close - 0.3, "volume": 1.0})
        return pd.DataFrame(rows)

    def test_target_exit_fires_when_close_crosses_the_dynamic_ma20_and_executes_at_close(self) -> None:
        candles = self._candles()
        frame = compute_indicator_frame(candles)
        rule = parse_structured_rule({"conditions": [{"field": "close", "op": "lt", "value": 95.0}]})
        exit_plan = parse_exit_plan({
            "stop_atr_multiple": 5.0,  # generous -- this test isolates the TARGET path, not the stop
            "dynamic_target_condition": {"field": "close", "op": "gte", "compare_to_field": "ma20"},
        })
        params = MeanReversionParameters()

        trades, _state = auto_tester.run_backtest(frame, rule, exit_plan, params)

        self.assertEqual(len(trades), 1, "expected exactly one resolved trade (one dip, one recovery)")
        trade = trades[0]
        self.assertEqual(trade.exit_reason, "TARGET")
        # Exit price must be the candle's own CLOSE (Vatican's own range_mean_reversion.
        # evaluate_exit convention), NOT the compared field's (ma20's) own value -- the
        # deliberate convention match documented in ExitPlan's own docstring.
        exit_row = frame[frame["close_time"] == trade.exit_close_time].iloc[0]
        self.assertNotEqual(trade.exit_price, float(exit_row["ma20"]))
        self.assertAlmostEqual(trade.exit_price, float(exit_row["close"]) * (1.0 - params.slippage_bps / 10000.0), places=6)

    def test_stop_still_wins_over_dynamic_target_on_the_same_candle(self) -> None:
        # A candle whose low breaches the stop AND whose close has already crossed
        # back above ma20 (dynamic target would also fire) -- SL must win, matching
        # every other exit shape's "stop checked first" convention.
        exit_plan = ExitPlan(
            stop_atr_multiple=1.0,
            dynamic_target_condition=Condition(field="close", op="gte", compare_to_field="ma20"),
        )
        params = MeanReversionParameters()
        state = MeanReversionState(equity=10_000.0)
        state.open_trade = _open_trade(entry_price=100.0, stop_loss=99.0, target=float("nan"), open_close_time=START_MS)

        # low=98.5 breaches stop_loss=99.0; close=99.5 >= ma20=99.0 (dynamic target condition also true).
        row = _row(START_MS + HOUR_MS, close=99.5, high=99.8, low=98.5, ma20=99.0, atr14=1.0)
        event = auto_tester._evaluate_exit_for_hypothesis(row, state, params, exit_plan)

        self.assertIsNotNone(event)
        self.assertEqual(event.exit_reason, "SL")


class RegimeBreakConsecutiveBarsTest(unittest.TestCase):
    """Hand-built rows with exact adx14 values (not derived from a real price
    series -- ADX's own formula is fiddly to hit an exact "high for exactly N
    bars" shape reliably) -- exercises _evaluate_exit_for_hypothesis directly,
    matching test_research_agent_rule_dsl.py's own FieldVsFieldEvaluationTest
    convention for isolated, exact-value condition testing."""

    EXIT_PLAN = ExitPlan(
        stop_atr_multiple=5.0, target_r_multiple=5.0,  # generous -- isolates REGIME_BREAK
        regime_break_condition=Condition(field="adx14", op="gte", value=28.0),
        regime_break_consecutive_bars=2,
    )
    PARAMS = MeanReversionParameters()

    def test_fires_exactly_on_the_second_of_two_consecutive_qualifying_bars(self) -> None:
        state = MeanReversionState(equity=10_000.0)
        state.open_trade = _open_trade(entry_price=100.0, stop_loss=90.0, target=200.0, open_close_time=START_MS)

        # bar 1: adx14=30 (>=28) -- streak becomes 1, not yet 2 -- no exit.
        row1 = _row(START_MS + HOUR_MS, close=101.0, high=101.3, low=100.7, ma20=95.0, adx14=30.0, atr14=1.0)
        event1 = auto_tester._evaluate_exit_for_hypothesis(row1, state, self.PARAMS, self.EXIT_PLAN)
        self.assertIsNone(event1)
        self.assertEqual(state.regime_break_streak, 1)

        # bar 2: adx14=29 (>=28) -- streak becomes 2 -- REGIME_BREAK fires.
        row2 = _row(START_MS + 2 * HOUR_MS, close=101.5, high=101.8, low=101.2, ma20=95.5, adx14=29.0, atr14=1.0)
        event2 = auto_tester._evaluate_exit_for_hypothesis(row2, state, self.PARAMS, self.EXIT_PLAN)
        self.assertIsNotNone(event2)
        self.assertEqual(event2.exit_reason, "REGIME_BREAK")
        self.assertIsNone(state.open_trade)
        self.assertEqual(state.regime_break_streak, 0)

    def test_a_single_qualifying_bar_alone_never_fires(self) -> None:
        state = MeanReversionState(equity=10_000.0)
        state.open_trade = _open_trade(entry_price=100.0, stop_loss=90.0, target=200.0, open_close_time=START_MS)

        row1 = _row(START_MS + HOUR_MS, close=101.0, high=101.3, low=100.7, ma20=95.0, adx14=30.0, atr14=1.0)
        auto_tester._evaluate_exit_for_hypothesis(row1, state, self.PARAMS, self.EXIT_PLAN)
        # bar 2 breaks the streak (adx14 back below 28) -- reset to 0.
        row2 = _row(START_MS + 2 * HOUR_MS, close=101.2, high=101.5, low=100.9, ma20=95.5, adx14=20.0, atr14=1.0)
        event2 = auto_tester._evaluate_exit_for_hypothesis(row2, state, self.PARAMS, self.EXIT_PLAN)
        self.assertIsNone(event2)
        self.assertEqual(state.regime_break_streak, 0)

        # bar 3 alone qualifying again -- streak restarts at 1, still no exit.
        row3 = _row(START_MS + 3 * HOUR_MS, close=101.4, high=101.7, low=101.1, ma20=96.0, adx14=31.0, atr14=1.0)
        event3 = auto_tester._evaluate_exit_for_hypothesis(row3, state, self.PARAMS, self.EXIT_PLAN)
        self.assertIsNone(event3)
        self.assertEqual(state.regime_break_streak, 1)
        self.assertIsNotNone(state.open_trade)  # trade still open -- only 1 consecutive bar so far

    def test_streak_updates_even_when_no_trade_is_open(self) -> None:
        # Matches range_mean_reversion.evaluate_exit's own convention: the counter
        # reflects real consecutive candles, independent of position state.
        state = MeanReversionState(equity=10_000.0)
        self.assertIsNone(state.open_trade)

        row1 = _row(START_MS + HOUR_MS, close=101.0, high=101.3, low=100.7, ma20=95.0, adx14=30.0, atr14=1.0)
        event = auto_tester._evaluate_exit_for_hypothesis(row1, state, self.PARAMS, self.EXIT_PLAN)
        self.assertIsNone(event)  # no open trade -- nothing to close
        self.assertEqual(state.regime_break_streak, 1)  # but the streak still advanced

    def test_stop_still_wins_over_regime_break_on_the_same_candle(self) -> None:
        state = MeanReversionState(equity=10_000.0)
        state.open_trade = _open_trade(entry_price=100.0, stop_loss=99.0, target=200.0, open_close_time=START_MS)
        state.regime_break_streak = 1  # already primed -- this candle would be the qualifying 2nd bar

        row = _row(START_MS + HOUR_MS, close=98.0, high=99.5, low=98.5, ma20=95.0, adx14=30.0, atr14=1.0)  # low breaches stop=99.0
        event = auto_tester._evaluate_exit_for_hypothesis(row, state, self.PARAMS, self.EXIT_PLAN)
        self.assertIsNotNone(event)
        self.assertEqual(event.exit_reason, "SL")


class NoTimeCapTest(unittest.TestCase):
    """max_holding_hours=None -- a trade must never be forcibly closed by time,
    only by stop/target/regime-break, matching RANGE_MEAN_REVERSION's own
    deliberate no-time-cap precedent (see ExitPlan's docstring)."""

    def test_trade_stays_open_indefinitely_with_no_time_cap(self) -> None:
        exit_plan = ExitPlan(stop_atr_multiple=5.0, target_r_multiple=5.0, max_holding_hours=None)
        params = MeanReversionParameters()
        state = MeanReversionState(equity=10_000.0)
        state.open_trade = _open_trade(entry_price=100.0, stop_loss=90.0, target=500.0, open_close_time=START_MS)

        # 2000 hours later -- far past any real strategy's own holding cap -- with
        # price never touching stop or target: must still be open.
        far_future = START_MS + 2000 * HOUR_MS
        row = _row(far_future, close=101.0, high=101.3, low=100.7)
        event = auto_tester._evaluate_exit_for_hypothesis(row, state, params, exit_plan)
        self.assertIsNone(event)
        self.assertIsNotNone(state.open_trade)

    def test_same_scenario_with_a_real_time_cap_does_force_close(self) -> None:
        # Contrast case: an identical scenario but WITH a real (short) time cap
        # must close via TIME -- proving the None-vs-real-number distinction
        # actually changes behavior, not just accepted-and-ignored.
        exit_plan = ExitPlan(stop_atr_multiple=5.0, target_r_multiple=5.0, max_holding_hours=24.0)
        params = MeanReversionParameters()
        state = MeanReversionState(equity=10_000.0)
        state.open_trade = _open_trade(entry_price=100.0, stop_loss=90.0, target=500.0, open_close_time=START_MS)

        later = START_MS + 30 * HOUR_MS  # past the 24h cap
        row = _row(later, close=101.0, high=101.3, low=100.7)
        event = auto_tester._evaluate_exit_for_hypothesis(row, state, params, exit_plan)
        self.assertIsNotNone(event)
        self.assertEqual(event.exit_reason, "TIME")


if __name__ == "__main__":
    unittest.main()
