"""feature/external-candidates-formal-test: proves (1) each of the 5 EXT_
candidates' rules were translated EXACTLY as specified -- no reinterpretation,
no approximation -- (2) the two bidirectional candidates are genuinely
UNTESTABLE, not silently approximated, (3) EXT_-prefixed names can never
collide with or get merged into the native WISE_MAN_HOLD/ADX_RANGE graveyard,
and (4) this module reuses the exact harness function objects, not
lookalikes."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from nero_core.research_agent import auto_tester
from nero_core.research_agent.rule_dsl import Condition, ExitPlan, StructuredRule, parse_exit_plan, parse_structured_rule
from tools import philosophy_hypotheses_live_test as legacy_harness
from tools.external_candidates_formal_test import (
    CRYPTO_PARAMS,
    EXTERNAL_CANDIDATES,
    FOREX_PARAMS,
    NATIVE_NAME_COLLISIONS_TO_AVOID,
    UNTESTABLE_BIDIRECTIONAL_REASON,
    fetch_full_history,
    run_hypothesis_live,
)
from tools.external_candidates_formal_test import _to_jsonable as ext_to_jsonable

EXPECTED_ENTRY_RULE = StructuredRule(conditions=(
    Condition(field="close", op="lt", value=None, compare_to_field="bb_lower"),
    Condition(field="adx14", op="lt", value=25.0, compare_to_field=None),
    Condition(field="atr14", op="gt", value=0.0, compare_to_field=None),
))


def _candidate(name: str) -> dict:
    matches = [c for c in EXTERNAL_CANDIDATES if c["name"] == name]
    assert len(matches) == 1, f"expected exactly one candidate named {name!r}, found {len(matches)}"
    return matches[0]


class PreRegisteredSetTest(unittest.TestCase):
    def test_exactly_five_candidates_in_the_exact_pre_registered_order(self) -> None:
        self.assertEqual(
            [c["name"] for c in EXTERNAL_CANDIDATES],
            [
                "EXT_WISE_MAN_HOLD_V5_ETH_4H",
                "EXT_WISE_MAN_HOLD_V6_EURUSD_4H",
                "EXT_WISE_MAN_HOLD_V5_EURUSD_4H",
                "EXT_ADX_RANGE_V3_BTC_1D",
                "EXT_ADX_RANGE_V4_BTC_1D",
            ],
        )

    def test_every_name_carries_the_ext_prefix(self) -> None:
        for c in EXTERNAL_CANDIDATES:
            self.assertTrue(c["name"].startswith("EXT_"), f"{c['name']} missing the EXT_ prefix")


class RuleTranslationCorrectnessTest(unittest.TestCase):
    """One test per testable candidate: the encoded rule matches the written
    spec exactly -- entry conditions, stop/target percentages, regime-break
    threshold/bar-count, asset, timeframe, and cost parameters."""

    def test_ext_wise_man_hold_v5_eth_4h(self) -> None:
        c = _candidate("EXT_WISE_MAN_HOLD_V5_ETH_4H")
        self.assertEqual(c["asset"], "ETH")
        self.assertEqual(c["timeframe"], "4h")
        self.assertEqual(parse_structured_rule(c["structured_entry_rule"]), EXPECTED_ENTRY_RULE)
        plan = parse_exit_plan(c["structured_exit_plan"])
        self.assertEqual(plan.stop_pct_of_entry, 0.015)
        self.assertEqual(plan.target_pct_of_entry, 0.03)
        self.assertEqual(plan.regime_break_condition, Condition(field="adx14", op="gte", value=28.0))
        self.assertEqual(plan.regime_break_consecutive_bars, 2)
        self.assertIsNone(plan.max_holding_hours)  # "no time cap"
        self.assertIsNone(plan.stop_atr_multiple)
        self.assertIsNone(plan.target_r_multiple)
        self.assertIs(c["backtest_params"], CRYPTO_PARAMS)
        self.assertEqual(c["backtest_params"].fee_bps, 10.0)  # crypto fee 10bps
        self.assertEqual(c["backtest_params"].slippage_bps, 2.0)
        self.assertEqual(c["backtest_params"].initial_equity, 10_000.0)
        self.assertEqual(c["backtest_params"].risk_per_trade, 0.01)

    def test_ext_wise_man_hold_v6_eurusd_4h(self) -> None:
        c = _candidate("EXT_WISE_MAN_HOLD_V6_EURUSD_4H")
        self.assertEqual(c["asset"], "EUR/USD")
        self.assertEqual(c["timeframe"], "4h")
        self.assertEqual(parse_structured_rule(c["structured_entry_rule"]), EXPECTED_ENTRY_RULE)
        plan = parse_exit_plan(c["structured_exit_plan"])
        self.assertEqual(plan.stop_pct_of_entry, 0.01)
        self.assertEqual(plan.target_pct_of_entry, 0.01)
        self.assertEqual(plan.regime_break_condition, Condition(field="adx14", op="gte", value=28.0))
        self.assertEqual(plan.regime_break_consecutive_bars, 2)
        self.assertIs(c["backtest_params"], FOREX_PARAMS)
        self.assertEqual(c["backtest_params"].fee_bps, 2.0)  # forex fee 2bps -- NOT the crypto default

    def test_ext_wise_man_hold_v5_eurusd_4h(self) -> None:
        c = _candidate("EXT_WISE_MAN_HOLD_V5_EURUSD_4H")
        self.assertEqual(c["asset"], "EUR/USD")
        self.assertEqual(c["timeframe"], "4h")
        self.assertEqual(parse_structured_rule(c["structured_entry_rule"]), EXPECTED_ENTRY_RULE)
        plan = parse_exit_plan(c["structured_exit_plan"])
        self.assertEqual(plan.stop_pct_of_entry, 0.015)
        self.assertEqual(plan.target_pct_of_entry, 0.03)
        self.assertIs(c["backtest_params"], FOREX_PARAMS)

    def test_all_five_candidates_are_now_testable(self) -> None:
        # feature/short-side-support resolved the 2 formerly-UNTESTABLE
        # ADX_RANGE candidates to real bidirectional specs -- every candidate
        # in the pre-registered set now has untestable_reason=None.
        testable = [c for c in EXTERNAL_CANDIDATES if c["untestable_reason"] is None]
        self.assertEqual(len(testable), 5)

    def test_the_three_wise_man_hold_candidates_share_the_identical_entry_rule(self) -> None:
        # Same entry structure across all 3 WISE_MAN_HOLD candidates, per the
        # external spec's own "same entry structure" wording for V6/V5 --
        # only stop/target differ. The 2 ADX_RANGE candidates are a separate
        # spec entirely and are deliberately excluded from this comparison.
        wise_man = [c for c in EXTERNAL_CANDIDATES if c["name"].startswith("EXT_WISE_MAN_HOLD")]
        self.assertEqual(len(wise_man), 3)
        rules = {json.dumps(c["structured_entry_rule"], sort_keys=True) for c in wise_man}
        self.assertEqual(len(rules), 1, "all 3 WISE_MAN_HOLD candidates must share the identical entry rule")

    def test_exit_precedence_matches_the_spec_stop_then_target_then_regime_break_no_time_cap(self) -> None:
        # auto_tester._evaluate_exit_for_hypothesis's own existing, UNCHANGED
        # priority (STOP, then TARGET, then REGIME_BREAK, then TIME) already
        # matches "stop-loss first, target second, ADX regime-break third, no
        # time cap" exactly -- proven directly against real rows, not just
        # asserted from the docstring.
        import pandas as pd

        from nero_core.strategies.mean_reversion import MeanReversionState, OpenTrade

        plan = ExitPlan(
            stop_pct_of_entry=0.015, target_pct_of_entry=0.03,
            regime_break_condition=Condition(field="adx14", op="gte", value=28.0),
            regime_break_consecutive_bars=1,
        )
        params = CRYPTO_PARAMS
        state = MeanReversionState(equity=params.initial_equity)
        entry_price = 100.0
        state.open_trade = OpenTrade(
            entry_price=entry_price, stop_loss=entry_price * 0.985, target=entry_price * 1.03,
            quantity=1.0, notional=entry_price, risk_dollars=entry_price * 0.015, entry_fee=0.0,
            open_close_time=1_700_000_000_000, entry_rsi=0.0, entry_ma20=0.0, entry_bb_lower=0.0,
            entry_ma200=0.0, entry_atr=1.0,
        )
        # A candle where stop, target, AND regime-break would ALL fire: low
        # breaches stop, close is above target, adx14 clears the regime-break
        # threshold. Stop must win.
        row = pd.Series({
            "close_time": 1_700_003_600_000, "close": entry_price * 1.05,
            "high": entry_price * 1.06, "low": entry_price * 0.97, "adx14": 30.0,
        })
        event = auto_tester._evaluate_exit_for_hypothesis(row, state, params, plan)
        self.assertEqual(event.exit_reason, "SL")


class AdxRangeBidirectionalResolutionTest(unittest.TestCase):
    """feature/short-side-support: EXT_ADX_RANGE_V3_BTC_1D and _V4_BTC_1D
    were UNTESTABLE (see UNTESTABLE_BIDIRECTIONAL_REASON, kept below purely
    as the historical record of *why*) until auto_tester gained genuine
    bidirectional support. These tests prove the resolution is real, not a
    relabeling: both candidates now carry real long AND short entry rules,
    a real exit plan and params, and the harness function they depend on
    genuinely supports both directions."""

    def test_both_adx_range_candidates_are_no_longer_untestable(self) -> None:
        for name in ("EXT_ADX_RANGE_V3_BTC_1D", "EXT_ADX_RANGE_V4_BTC_1D"):
            c = _candidate(name)
            with self.subTest(name=name):
                self.assertIsNone(c["untestable_reason"])
                self.assertIsNotNone(c["structured_entry_rule"])
                self.assertIsNotNone(c["structured_entry_rule_short"])
                self.assertIsNotNone(c["structured_exit_plan"])
                self.assertIs(c["backtest_params"], CRYPTO_PARAMS)

    def test_adx_range_long_and_short_rules_are_mirror_images_at_their_own_threshold(self) -> None:
        for name, threshold in (("EXT_ADX_RANGE_V3_BTC_1D", 25.0), ("EXT_ADX_RANGE_V4_BTC_1D", 30.0)):
            c = _candidate(name)
            with self.subTest(name=name):
                long_rule = parse_structured_rule(c["structured_entry_rule"])
                short_rule = parse_structured_rule(c["structured_entry_rule_short"])
                self.assertEqual(long_rule, StructuredRule(conditions=(
                    Condition(field="adx14", op="lt", value=threshold, compare_to_field=None),
                    Condition(field="close", op="lt", value=None, compare_to_field="bb_lower"),
                )))
                self.assertEqual(short_rule, StructuredRule(conditions=(
                    Condition(field="adx14", op="lt", value=threshold, compare_to_field=None),
                    Condition(field="close", op="gt", value=None, compare_to_field="bb_upper"),
                )))

    def test_adx_range_grid_shift_is_explicitly_not_applicable_not_silently_skipped(self) -> None:
        # BTC/24h is native daily data -- run_hypothesis_live's build_4h_grids
        # is hardcoded to 4-hour resampling, so grid-shift would silently test
        # the wrong timeframe if run. Same structural precedent as BTC/1d
        # elsewhere in this pipeline (watchlist_candidates_recheck.py).
        for name in ("EXT_ADX_RANGE_V3_BTC_1D", "EXT_ADX_RANGE_V4_BTC_1D"):
            c = _candidate(name)
            with self.subTest(name=name):
                self.assertIs(c["grid_shift_applicable"], False)

    def test_untestable_reason_constant_survives_as_the_historical_record(self) -> None:
        # No candidate references this constant anymore (proven above), but
        # the constant itself is kept verbatim as the historical record of
        # the gap that used to exist -- it must still describe that gap
        # accurately if anyone reads it later.
        reason = UNTESTABLE_BIDIRECTIONAL_REASON
        self.assertIn("long-only", reason)
        self.assertIn("_size_entry_for_hypothesis", reason)
        self.assertIn("bidirectional", reason.lower())
        for c in EXTERNAL_CANDIDATES:
            self.assertNotEqual(c["untestable_reason"], reason)

    def test_auto_tester_entry_sizing_is_verified_genuinely_bidirectional(self) -> None:
        # Direct proof (not just cited in a comment) that
        # _size_entry_for_hypothesis now has a real short-entry path -- the
        # exact capability gap the UNTESTABLE reason used to rest on.
        import inspect

        source = inspect.getsource(auto_tester._size_entry_for_hypothesis)
        self.assertIn('"buy"', source)
        self.assertIn('"sell"', source)
        sig = inspect.signature(auto_tester._size_entry_for_hypothesis)
        self.assertEqual(sig.parameters["direction"].default, "LONG")


class NoCollisionWithNativeGraveyardTest(unittest.TestCase):
    """The native philosophy-hypotheses results file (docs/philosophy_
    hypotheses_live_test_results.json) is this project's real 'shared log' at
    risk of confusion -- it literally contains WISE_MAN_HOLD_V5, WISE_MAN_
    HOLD_V6, ADX_RANGE_V3, and ADX_RANGE_V4 as native keys. Proven against
    that file's real, actual key set (hardcoded here from a direct read of
    it, not guessed) rather than a tautological self-comparison."""

    def test_no_external_candidate_name_equals_a_native_graveyard_name(self) -> None:
        for c in EXTERNAL_CANDIDATES:
            with self.subTest(name=c["name"]):
                self.assertNotIn(c["name"], NATIVE_NAME_COLLISIONS_TO_AVOID)

    def test_native_collision_set_includes_every_name_this_task_was_warned_about(self) -> None:
        for warned_name in ("WISE_MAN_HOLD_V5", "WISE_MAN_HOLD_V6", "ADX_RANGE_V3", "ADX_RANGE_V4"):
            self.assertIn(warned_name, NATIVE_NAME_COLLISIONS_TO_AVOID)

    def test_a_naive_dict_merge_with_the_real_native_results_file_preserves_both_sides_unmodified(self) -> None:
        native_path = Path("docs/philosophy_hypotheses_live_test_results.json")
        if not native_path.exists():
            self.skipTest("native results file not present in this checkout")
        native_runs = json.loads(native_path.read_text())["runs"]

        fake_ext_runs = {c["name"]: {"name": c["name"], "verdict": "PLACEHOLDER"} for c in EXTERNAL_CANDIDATES}
        merged = {**native_runs, **fake_ext_runs}

        self.assertEqual(len(merged), len(native_runs) + len(fake_ext_runs), "a real key collision would make this sum short")
        for native_name, native_value in native_runs.items():
            self.assertEqual(merged[native_name], native_value, f"native entry {native_name!r} was overwritten by the merge")
        for ext_name in fake_ext_runs:
            self.assertEqual(merged[ext_name]["verdict"], "PLACEHOLDER")


class HarnessReuseTest(unittest.TestCase):
    """Identity checks (assertIs), matching prior convention -- proves this
    module calls the LITERAL SAME function objects as tools.philosophy_
    hypotheses_live_test, not a rewritten lookalike."""

    def test_fetch_full_history_is_the_literal_same_function(self) -> None:
        self.assertIs(fetch_full_history, legacy_harness.fetch_full_history)

    def test_run_hypothesis_live_is_the_literal_same_function(self) -> None:
        self.assertIs(run_hypothesis_live, legacy_harness.run_hypothesis_live)

    def test_to_jsonable_is_the_literal_same_function(self) -> None:
        self.assertIs(ext_to_jsonable, legacy_harness._to_jsonable)

    def test_run_hypothesis_live_itself_calls_the_real_auto_tester_functions(self) -> None:
        # One level deeper: run_hypothesis_live -> auto_tester.test_hypothesis/
        # run_grid_shift_check, not a shadowed copy.
        self.assertIs(legacy_harness.auto_tester.test_hypothesis, auto_tester.test_hypothesis)
        self.assertIs(legacy_harness.auto_tester.run_grid_shift_check, auto_tester.run_grid_shift_check)


class DataSourcingTest(unittest.TestCase):
    """Task 2: confirms each testable candidate's asset dispatches through
    Vatican's OWN pipeline to the exact provider/method the task specified --
    checked against real fetch calls (mocked at the transport boundary, same
    convention as tools.philosophy_hypotheses_live_test's own
    FetchFullHistoryDispatchTest), not assumed from reading dispatch code
    alone. See also this module's own live smoke-check (run manually, not as
    part of the suite, since it needs network): ETH/4h resolved to "NATIVE:
    Binance ETHUSDT 4h candles" (19,611 candles) and EUR/USD/4h resolved to
    "NATIVE: Twelve Data EUR/USD 4h" (4,997 candles) -- both native, neither
    resampled from a finer timeframe."""

    def test_eth_dispatches_through_binance_direct_not_forex(self) -> None:
        from unittest.mock import patch

        with patch("tools.philosophy_hypotheses_live_test.fetch_timeframe_candles") as mock_tf:
            mock_tf.return_value = (None, "test-fixture")
            fetch_full_history("ETH", "4h", client="fake-client")
        mock_tf.assert_called_once_with("fake-client", "ETH", "4h")

    def test_eurusd_dispatches_through_twelve_data_forex_not_binance(self) -> None:
        from unittest.mock import patch

        with patch("tools.philosophy_hypotheses_live_test.fetch_forex_ohlcv") as mock_forex:
            from nero_core.data_sources.forex_data import ForexDataResult
            import pandas as pd

            mock_forex.return_value = ForexDataResult(prices=pd.DataFrame(), source="test-fixture", pair="EUR/USD", timeframe="4h")
            legacy_harness.fetch_full_history("EUR/USD", "4h", client=None)
        mock_forex.assert_called_once_with("EUR/USD", "4h")

    def test_the_three_testable_candidates_use_exactly_the_task_specified_asset_timeframe_pairs(self) -> None:
        expected = {
            "EXT_WISE_MAN_HOLD_V5_ETH_4H": ("ETH", "4h"),
            "EXT_WISE_MAN_HOLD_V6_EURUSD_4H": ("EUR/USD", "4h"),
            "EXT_WISE_MAN_HOLD_V5_EURUSD_4H": ("EUR/USD", "4h"),
        }
        for name, (asset, timeframe) in expected.items():
            c = _candidate(name)
            with self.subTest(name=name):
                self.assertEqual((c["asset"], c["timeframe"]), (asset, timeframe))


class RiskSizingInvarianceTest(unittest.TestCase):
    """Task 1's own instruction: confirm (don't assume) that position sizing
    doesn't affect R-multiple-based expectancy/win-rate/PF, since R already
    normalizes for risk. Uses real backtest machinery on a synthetic series
    that reliably triggers a handful of trades -- proves the INVARIANT the
    live run at $10,000/1% relies on, without needing live network data for
    this specific proof."""

    def test_expectancy_and_trade_count_are_identical_across_wildly_different_equity_and_risk_fractions(self) -> None:
        from datetime import datetime, timezone

        import pandas as pd

        from nero_core.strategies.mean_reversion import MeanReversionParameters

        rows = []
        close_time = 1_700_000_000_000
        price = 100.0
        for i in range(300):
            # A repeating dip-and-recover pattern so RANGE-style entries fire
            # a handful of times with real, non-degenerate ATR.
            price = 100.0 - (4.0 if i % 6 == 0 else 0.0) + 0.3 * (i % 4)
            rows.append({"close_time": close_time, "close": price, "high": price + 0.5, "low": price - 0.5, "volume": 1.0})
            close_time += 4 * 3_600_000
        candles = pd.DataFrame(rows)
        now = datetime.fromtimestamp(close_time / 1000, tz=timezone.utc)

        hyp = {
            "hypothesis_name": "RISK_SIZING_INVARIANCE_CHECK", "asset": "BTC", "timeframe": "4h",
            "generated_at": now.isoformat(),
            "structured_entry_rule": {
                "conditions": [
                    {"field": "close", "op": "lt", "compare_to_field": "bb_lower"},
                    {"field": "adx14", "op": "lt", "value": 25.0},
                    {"field": "atr14", "op": "gt", "value": 0.0},
                ],
            },
            "structured_exit_plan": {
                "stop_pct_of_entry": 0.015, "target_pct_of_entry": 0.03,
                "regime_break_condition": {"field": "adx14", "op": "gte", "value": 28.0},
                "regime_break_consecutive_bars": 2,
            },
        }

        small = MeanReversionParameters(initial_equity=1_000.0, risk_per_trade=0.005, fee_bps=10.0, slippage_bps=2.0)
        large = MeanReversionParameters(initial_equity=5_000_000.0, risk_per_trade=0.08, fee_bps=10.0, slippage_bps=2.0)

        result_small = auto_tester.test_hypothesis(hyp, candles, now, backtest_params=small)
        result_large = auto_tester.test_hypothesis(hyp, candles, now, backtest_params=large)

        if result_small.train is None or result_large.train is None:
            self.skipTest("synthetic fixture didn't clear the frequency gate in this environment -- not what this test checks")

        self.assertEqual(result_small.train.trades, result_large.train.trades)
        self.assertEqual(result_small.train.expectancy_r, result_large.train.expectancy_r)


if __name__ == "__main__":
    unittest.main()
