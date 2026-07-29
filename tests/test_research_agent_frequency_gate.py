from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

import pandas as pd

from nero_core.research_agent.frequency_gate import (
    FAST,
    MIN_CANDLES_FOR_MEASUREMENT,
    TOO_SLOW,
    UNMEASURABLE,
    VIABLE,
    measure_entry_frequency,
)

DAY_MS = 86_400_000
SIMPLE_RULE = {"conditions": [{"field": "close", "op": "gt", "value": 50.0}]}


def _daily_candles(n: int, trigger_indices: set[int], start: datetime = datetime(2020, 1, 1, tzinfo=timezone.utc)) -> pd.DataFrame:
    """`n` daily candles; rows in `trigger_indices` get close=100 (fires
    SIMPLE_RULE's close > 50), every other row gets close=10 (does not)."""
    start_ms = int(start.timestamp() * 1000)
    rows = []
    for i in range(n):
        close = 100.0 if i in trigger_indices else 10.0
        rows.append({"close_time": start_ms + i * DAY_MS, "close": close, "high": close + 1, "low": close - 1})
    return pd.DataFrame(rows)


class FrequencyClassificationTest(unittest.TestCase):
    def test_fast_classification(self) -> None:
        # every row fires -> 200 triggers over ~199 days -> ~367 trades/year -> well under 6 months
        candles = _daily_candles(200, trigger_indices=set(range(200)))
        generated_at = datetime(2020, 1, 1, tzinfo=timezone.utc) + timedelta(days=250)

        result = measure_entry_frequency(candles, SIMPLE_RULE, generated_at)

        self.assertEqual(result.classification, FAST)
        self.assertLessEqual(result.expected_months_to_30_trades, 6.0)
        self.assertEqual(result.triggers_counted, 200)

    def test_viable_classification(self) -> None:
        # 20 triggers over ~199 days -> ~36.7 trades/year -> ~9.8 months (6 < months <= 12)
        candles = _daily_candles(200, trigger_indices=set(range(0, 200, 10)))
        generated_at = datetime(2020, 1, 1, tzinfo=timezone.utc) + timedelta(days=250)

        result = measure_entry_frequency(candles, SIMPLE_RULE, generated_at)

        self.assertEqual(result.classification, VIABLE)
        self.assertGreater(result.expected_months_to_30_trades, 6.0)
        self.assertLessEqual(result.expected_months_to_30_trades, 12.0)

    def test_too_slow_classification_with_measured_frequency_recorded(self) -> None:
        # 1 trigger over ~199 days -> ~1.8 trades/year -> ~196 months -- REJECTED
        candles = _daily_candles(200, trigger_indices={5})
        generated_at = datetime(2020, 1, 1, tzinfo=timezone.utc) + timedelta(days=250)

        result = measure_entry_frequency(candles, SIMPLE_RULE, generated_at)

        self.assertEqual(result.classification, TOO_SLOW)
        self.assertIsNotNone(result.measured_trades_per_year)
        self.assertGreater(result.expected_months_to_30_trades, 12.0)
        self.assertIn("1", result.reason)  # the measured trigger count is in the human-readable reason

    def test_zero_triggers_is_too_slow_not_unmeasurable(self) -> None:
        # the rule is perfectly well-formed and measurable -- it has just never fired.
        # That's a measured TOO_SLOW verdict, not ambiguity.
        candles = _daily_candles(200, trigger_indices=set())
        generated_at = datetime(2020, 1, 1, tzinfo=timezone.utc) + timedelta(days=250)

        result = measure_entry_frequency(candles, SIMPLE_RULE, generated_at)

        self.assertEqual(result.classification, TOO_SLOW)
        self.assertEqual(result.triggers_counted, 0)

    def test_unmeasurable_when_too_little_eligible_history(self) -> None:
        candles = _daily_candles(200, trigger_indices=set(range(200)))
        # cutoff after only 10 candles have closed -- far below MIN_CANDLES_FOR_MEASUREMENT
        generated_at = datetime(2020, 1, 1, tzinfo=timezone.utc) + timedelta(days=10)

        result = measure_entry_frequency(candles, SIMPLE_RULE, generated_at)

        self.assertEqual(result.classification, UNMEASURABLE)
        self.assertIsNone(result.measured_trades_per_year)
        self.assertLess(result.eligible_candle_count, MIN_CANDLES_FOR_MEASUREMENT)

    def test_unmeasurable_when_entry_rule_is_ambiguous(self) -> None:
        candles = _daily_candles(200, trigger_indices=set(range(200)))
        generated_at = datetime(2020, 1, 1, tzinfo=timezone.utc) + timedelta(days=250)

        result = measure_entry_frequency(candles, {"conditions": [{"field": "rsi14", "op": "lt", "value": 30.0}]}, generated_at)

        self.assertEqual(result.classification, UNMEASURABLE)
        self.assertIn("ambiguous", result.reason.lower())

    def test_unmeasurable_when_entry_rule_is_free_text(self) -> None:
        candles = _daily_candles(200, trigger_indices=set(range(200)))
        generated_at = datetime(2020, 1, 1, tzinfo=timezone.utc) + timedelta(days=250)

        result = measure_entry_frequency(candles, {"description": "z-score below -2, no structured form"}, generated_at)

        self.assertEqual(result.classification, UNMEASURABLE)


class LookaheadProtectionHardTest(unittest.TestCase):
    """HARD TEST (per the branch's own task spec): the gate must measure
    frequency using ONLY data strictly before the hypothesis's generation
    timestamp. If it leaked post-generation data, a hypothesis whose true
    pre-generation history is TOO_SLOW could flip to FAST/VIABLE just because
    a burst of triggers happened to occur right after the scan finding that
    produced it -- exactly the circularity the module docstring warns about."""

    def test_post_cutoff_burst_of_triggers_does_not_change_the_verdict(self) -> None:
        start = datetime(2020, 1, 1, tzinfo=timezone.utc)
        # First 200 days (indices 0-199): only ONE trigger -> TOO_SLOW on its own.
        # Next 200 days (indices 200-399, all AFTER the cutoff below): EVERY row triggers --
        # if this leaked into the measurement, the combined rate would easily be FAST.
        trigger_indices = {5} | set(range(200, 400))
        candles = _daily_candles(400, trigger_indices=trigger_indices, start=start)
        generated_at = start + timedelta(days=200)  # cutoff sits exactly at the boundary

        result = measure_entry_frequency(candles, SIMPLE_RULE, generated_at)

        self.assertEqual(result.classification, TOO_SLOW)
        self.assertEqual(result.triggers_counted, 1)
        self.assertEqual(result.eligible_candle_count, 200)  # only the pre-cutoff candles were ever considered

    def test_eligible_candle_count_never_exceeds_pre_cutoff_rows(self) -> None:
        start = datetime(2020, 1, 1, tzinfo=timezone.utc)
        candles = _daily_candles(300, trigger_indices=set(range(300)), start=start)
        generated_at = start + timedelta(days=100)

        result = measure_entry_frequency(candles, SIMPLE_RULE, generated_at)

        self.assertEqual(result.eligible_candle_count, 100)

    def test_naive_frequency_over_the_full_series_would_have_differed(self) -> None:
        """Sanity check that this test actually exercises the protection --
        i.e. that measuring over the FULL series (no cutoff) really would
        have produced a different verdict, so a regression that deletes the
        cutoff filter is caught rather than passing by coincidence."""
        start = datetime(2020, 1, 1, tzinfo=timezone.utc)
        trigger_indices = {5} | set(range(200, 400))
        candles = _daily_candles(400, trigger_indices=trigger_indices, start=start)

        cutoff_generated_at = start + timedelta(days=200)
        restricted = measure_entry_frequency(candles, SIMPLE_RULE, cutoff_generated_at)

        far_future_generated_at = start + timedelta(days=1000)  # effectively "no cutoff" -- everything is eligible
        unrestricted = measure_entry_frequency(candles, SIMPLE_RULE, far_future_generated_at)

        self.assertEqual(restricted.classification, TOO_SLOW)
        self.assertNotEqual(restricted.classification, unrestricted.classification)
        self.assertEqual(unrestricted.triggers_counted, 201)


if __name__ == "__main__":
    unittest.main()
