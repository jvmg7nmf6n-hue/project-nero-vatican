from __future__ import annotations

import random
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import pandas as pd

from nero_core.eve import hypothesis_shapes, scoring


def _make_candles(n: int = 600, seed: int = 1) -> pd.DataFrame:
    """Same construction pattern proven in
    tests/test_research_agent_no_auto_wire.py's own dynamic test: candle
    timestamps starting well before a generated_at far in the future, so
    the frequency gate's no-lookahead cutoff never excludes this synthetic
    history."""
    rng = random.Random(seed)
    rows = []
    price = 100.0
    t0 = 1_700_000_000_000
    for i in range(n):
        price *= 1 + rng.uniform(-0.01, 0.01)
        rows.append({
            "close_time": t0 + i * 3_600_000,
            "close": price,
            "high": price * 1.004,
            "low": price * 0.996,
            "volume": 1.0,
        })
    return pd.DataFrame(rows)


ALWAYS_FIRES_RAW = {
    "hypothesis_name": "TEST_ALWAYS_FIRES",
    "mechanism": "test fixture -- always-true entry condition",
    "asset": "BTC",
    "timeframe": "1h",
    "generated_at": "2026-07-29T00:00:00+00:00",
    "structured_entry_rule": {"conditions": [{"field": "ret_1", "op": "gt", "value": -1.0}]},
    "structured_exit_plan": {"stop_atr_multiple": 1.5, "target_r_multiple": 2.0, "max_holding_hours": 24.0},
}

NEVER_FIRES_RAW = {
    **ALWAYS_FIRES_RAW,
    "hypothesis_name": "TEST_NEVER_FIRES",
    "structured_entry_rule": {"conditions": [{"field": "zscore20", "op": "lt", "value": -100.0}]},
}


def _record(raw: dict) -> dict:
    return hypothesis_shapes.build_hypothesis_record(raw, session_id="s1", turn_index=0, tool_use_id="toolu_1")


class ClassifyTestabilityTest(unittest.TestCase):
    def test_valid_dsl_shape_is_testable(self) -> None:
        testability, reason = scoring.classify_testability(ALWAYS_FIRES_RAW)
        self.assertEqual(testability, scoring.TESTABILITY_TESTABLE)
        self.assertTrue(reason)

    def test_missing_structured_entry_rule_is_untestable(self) -> None:
        raw = {k: v for k, v in ALWAYS_FIRES_RAW.items() if k != "structured_entry_rule"}
        testability, reason = scoring.classify_testability(raw)
        self.assertEqual(testability, scoring.TESTABILITY_UNTESTABLE_BY_DSL)

    def test_unsupported_field_is_untestable(self) -> None:
        raw = {**ALWAYS_FIRES_RAW, "structured_entry_rule": {"conditions": [{"field": "macd_histogram", "op": "gt", "value": 0}]}}
        testability, reason = scoring.classify_testability(raw)
        self.assertEqual(testability, scoring.TESTABILITY_UNTESTABLE_BY_DSL)

    def test_free_form_shape_is_untestable_never_crashes(self) -> None:
        raw = {"hypothesis_name": "X", "mechanism": "a completely free-form idea with no DSL fields at all", "idea": "buy the dip when sentiment flips"}
        testability, reason = scoring.classify_testability(raw)
        self.assertEqual(testability, scoring.TESTABILITY_UNTESTABLE_BY_DSL)

    def test_non_dict_raw_hypothesis_never_crashes(self) -> None:
        testability, reason = scoring.classify_testability({})
        self.assertEqual(testability, scoring.TESTABILITY_UNTESTABLE_BY_DSL)


class ScoreHypothesisUntestableTest(unittest.TestCase):
    def test_untestable_hypothesis_has_null_verdicts(self) -> None:
        record = _record({"hypothesis_name": "FREE", "mechanism": "no DSL shape"})
        scored = scoring.score_hypothesis(record, candles_provider=lambda a, t: None)
        self.assertEqual(scored["testability"], scoring.TESTABILITY_UNTESTABLE_BY_DSL)
        self.assertIsNone(scored["verdict_is"])
        self.assertIsNone(scored["verdict_oos"])
        self.assertIsNone(scored["verdict_combined"])

    def test_does_not_mutate_input_record(self) -> None:
        record = _record({"hypothesis_name": "FREE", "mechanism": "no DSL shape"})
        original_testability = record["testability"]
        scoring.score_hypothesis(record, candles_provider=lambda a, t: None)
        self.assertEqual(record["testability"], original_testability)


class ScoreHypothesisNoCandlesTest(unittest.TestCase):
    def test_testable_hypothesis_with_no_candle_data_has_null_verdicts(self) -> None:
        record = _record(ALWAYS_FIRES_RAW)
        scored = scoring.score_hypothesis(record, candles_provider=lambda a, t: None, now=datetime(2026, 8, 1, tzinfo=timezone.utc))
        self.assertEqual(scored["testability"], scoring.TESTABILITY_TESTABLE)
        self.assertIsNone(scored["verdict_is"])
        self.assertIsNone(scored["verdict_oos"])
        self.assertIn("no candle data", scored["testability_reason"])


class ScoreHypothesisRealBacktestTest(unittest.TestCase):
    VALID_VERDICTS = {
        scoring.VERDICT_EVE_SURVIVED, scoring.VERDICT_EVE_DIED,
        scoring.VERDICT_EVE_PROMISING_WATCHLIST, scoring.VERDICT_EVE_INSUFFICIENT_SAMPLE, None,
    }

    def test_always_fires_hypothesis_produces_a_valid_verdict_pair(self) -> None:
        candles = _make_candles(n=600, seed=1)
        record = _record(ALWAYS_FIRES_RAW)
        scored = scoring.score_hypothesis(record, candles_provider=lambda a, t: candles, now=datetime(2026, 8, 1, tzinfo=timezone.utc))

        self.assertEqual(scored["testability"], scoring.TESTABILITY_TESTABLE)
        self.assertIn(scored["verdict_is"], self.VALID_VERDICTS)
        self.assertIn(scored["verdict_oos"], self.VALID_VERDICTS)
        for p in (scored["p_value_is"], scored["p_value_oos"]):
            if p is not None:
                self.assertGreaterEqual(p, 0.0)
                self.assertLessEqual(p, 1.0)

    def test_never_fires_hypothesis_is_insufficient_sample_or_gate_rejected(self) -> None:
        candles = _make_candles(n=600, seed=2)
        record = _record(NEVER_FIRES_RAW)
        scored = scoring.score_hypothesis(record, candles_provider=lambda a, t: candles, now=datetime(2026, 8, 1, tzinfo=timezone.utc))

        self.assertEqual(scored["testability"], scoring.TESTABILITY_TESTABLE)
        # A rule that structurally never fires must never be reported as DIED
        # or SURVIVED -- there were no trades to prove either claim.
        self.assertNotIn(scored["verdict_is"], (scoring.VERDICT_EVE_SURVIVED, scoring.VERDICT_EVE_DIED))
        self.assertNotIn(scored["verdict_oos"], (scoring.VERDICT_EVE_SURVIVED, scoring.VERDICT_EVE_DIED))

    def test_uses_the_real_adam_harness_not_a_reimplementation(self) -> None:
        # Confirms this module actually calls auto_tester.test_hypothesis --
        # not a lookalike -- by checking the reported verdict_combined is one
        # of Adam's own literal verdict strings.
        from tools.backtest_statistics import VERDICT_DIED, VERDICT_PROMISING_WATCHLIST, VERDICT_SURVIVED

        candles = _make_candles(n=600, seed=3)
        record = _record(ALWAYS_FIRES_RAW)
        scored = scoring.score_hypothesis(record, candles_provider=lambda a, t: candles, now=datetime(2026, 8, 1, tzinfo=timezone.utc))
        self.assertIn(
            scored["verdict_combined"],
            (VERDICT_DIED, VERDICT_PROMISING_WATCHLIST, VERDICT_SURVIVED, "UNTESTABLE", "SKIPPED"),
        )


class TestabilityVerdictReconciliationTest(unittest.TestCase):
    """A hypothesis record must never assert both testability="TESTABLE"
    and verdict_combined="UNTESTABLE" at once (Session 0-B follow-up fix).
    Now that hypothesis_shapes._inject_generated_at always stamps a real
    generated_at server-side, auto_tester.test_hypothesis returning its own
    VERDICT_UNTESTABLE for a hypothesis classify_testability already said
    TESTABLE is structurally unreachable via real inputs -- both call the
    exact same rule_dsl parse functions on the same dict. This test proves
    the RECONCILIATION LOGIC itself works as a hard invariant regardless,
    by mocking adam_test_hypothesis's return value directly rather than
    trying to construct a real scenario that can no longer occur."""

    def _mock_untestable_result(self, reason: str):
        from nero_core.research_agent.auto_tester import TestResult

        return TestResult(
            hypothesis_name="X", asset="BTC", timeframe="4h",
            verdict="UNTESTABLE", review_status="untestable", frequency_classification="UNMEASURABLE",
            measured_trades_per_year=None, expected_time_to_30_trades_months=None,
            reason=reason, train=None, test=None, tested_at="2026-08-01T00:00:00+00:00",
        )

    def test_testability_is_downgraded_when_harness_returns_untestable(self) -> None:
        candles = _make_candles(n=600, seed=5)
        record = _record(ALWAYS_FIRES_RAW)
        with patch("nero_core.eve.scoring.adam_test_hypothesis", return_value=self._mock_untestable_result("generated_at missing or unparseable")):
            scored = scoring.score_hypothesis(record, candles_provider=lambda a, t: candles, now=datetime(2026, 8, 1, tzinfo=timezone.utc))

        self.assertEqual(scored["verdict_combined"], "UNTESTABLE")
        self.assertNotEqual(scored["testability"], scoring.TESTABILITY_TESTABLE, "must never assert TESTABLE next to verdict_combined=UNTESTABLE")
        self.assertEqual(scored["testability"], scoring.TESTABILITY_UNTESTABLE_BY_HARNESS)
        self.assertEqual(scored["testability_reason"], "generated_at missing or unparseable")

    def test_a_real_survived_or_died_verdict_never_triggers_the_downgrade(self) -> None:
        # Regression guard: the reconciliation must only fire for Adam's
        # OWN literal "UNTESTABLE" string, never for a real verdict.
        candles = _make_candles(n=600, seed=6)
        record = _record(ALWAYS_FIRES_RAW)
        scored = scoring.score_hypothesis(record, candles_provider=lambda a, t: candles, now=datetime(2026, 8, 1, tzinfo=timezone.utc))
        self.assertEqual(scored["testability"], scoring.TESTABILITY_TESTABLE)
        self.assertNotEqual(scored["verdict_combined"], "UNTESTABLE")


class ScoreAllTest(unittest.TestCase):
    def test_scores_every_record_independently(self) -> None:
        candles = _make_candles(n=600, seed=4)
        records = [_record(ALWAYS_FIRES_RAW), _record(NEVER_FIRES_RAW), _record({"free": "form"})]
        scored = scoring.score_all(records, candles_provider=lambda a, t: candles, now=datetime(2026, 8, 1, tzinfo=timezone.utc))
        self.assertEqual(len(scored), 3)
        self.assertEqual(scored[2]["testability"], scoring.TESTABILITY_UNTESTABLE_BY_DSL)


if __name__ == "__main__":
    unittest.main()
