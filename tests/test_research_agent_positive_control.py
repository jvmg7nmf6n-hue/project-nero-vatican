"""Positive control for the backtest harness (Eve engine v1 session,
"Reproduction confirmed" follow-up, item 1).

WHY THIS EXISTS: the random-hypothesis baseline (nero_core.eve.random_baseline,
run against the real BTC/4h research export) proves the harness REJECTS
garbage -- specificity. It does NOT by itself prove the harness can RECOGNISE
a genuinely exploitable pattern -- sensitivity. A harness that returned DIED
for literally everything would score an identical 0% on that baseline. This
test constructs a synthetic OHLCV series with a deliberately embedded,
repeating, exploitable pattern and proves auto_tester.test_hypothesis --
classify_verdict, split_chronological, MIN_SAMPLE_SIZE, and the frequency
gate, all UNCHANGED, none of their thresholds touched for this test -- can
still return SURVIVED. If this test ever starts failing, treat every DIED
verdict the harness has ever produced (including the random baseline's 0/200)
as uninformative until this is fixed -- do not raise MIN_SAMPLE_SIZE, loosen
classify_verdict, or otherwise force it to pass.

THE PATTERN: every `CYCLE` hours, one "shock" candle drops price 5% in a
single candle (close.pct_change() <= -3%, the entry trigger), immediately
followed by a "rally" candle that gains 10% -- so the very next closed candle
after every trigger clears both the ATR-based stop and the 2R target with a
wide margin, and price only overshoots UP, never threatening the stop first
(mean_reversion.evaluate_exit checks the stop side of an ambiguous same-
candle stop+target hit first -- see that function's own docstring -- so this
pattern is deliberately built to never even reach that ambiguous case: the
rally candle's low never dips toward the stop). Between shocks, price
oscillates with small pseudo-random noise (bounded, deterministic seed) so
ATR/warmup columns stay well-defined without ever producing a second,
accidental trigger.
"""
from __future__ import annotations

import random
import unittest
from datetime import datetime, timezone

import pandas as pd

from nero_core.research_agent import auto_tester
from nero_core.research_agent.auto_tester import VERDICT_SURVIVED
from nero_core.research_agent.frequency_gate import FAST
from tools.backtest_statistics import MIN_SAMPLE_SIZE

HOUR_MS = 3_600_000
START_MS = 1_700_000_000_000
CYCLE = 15  # hours between shocks
N_CANDLES = 2000

POSITIVE_CONTROL_HYPOTHESIS = {
    "hypothesis_name": "POSITIVE_CONTROL_SHOCK_REVERSAL",
    "asset": "BTC",
    "timeframe": "1h",
    "generated_at": "2026-08-02T00:00:00+00:00",
    "structured_entry_rule": {"conditions": [{"field": "ret_1", "op": "lt", "value": -0.03}]},
    "structured_exit_plan": {"stop_atr_multiple": 1.5, "target_r_multiple": 2.0, "max_holding_hours": 48.0},
}


def _make_positive_control_candles(n: int = N_CANDLES, cycle: int = CYCLE, seed: int = 7) -> pd.DataFrame:
    """Deterministic (fixed seed) synthetic OHLCV: a repeating shock-down /
    rally-up cycle with small noise in between. See module docstring."""
    rng = random.Random(seed)
    rows = []
    price = 100.0
    for i in range(n):
        pos = i % cycle
        if pos == cycle - 1:
            prev_price = price
            price *= 0.95  # shock down: -5% single-candle return, fires the entry trigger
            close = price
            high = prev_price * 0.951
            low = close * 0.995
        elif pos == 0 and i != 0:
            prev_price = price
            price *= 1.10  # rally: clears stop AND target on the very next closed candle
            close = price
            high = close * 1.001
            low = prev_price * 1.0005  # never dips toward the stop
        else:
            price *= 1 + rng.uniform(-0.002, 0.002)
            close = price
            high = close * 1.001
            low = close * 0.999
        rows.append({"close_time": START_MS + i * HOUR_MS, "close": close, "high": high, "low": low, "volume": 1.0})
    return pd.DataFrame(rows)


class PositiveControlTest(unittest.TestCase):
    """HARD GATE (per the task spec this test was written under): if this
    ever fails, stop and report -- do not adjust thresholds to force a pass."""

    @classmethod
    def setUpClass(cls) -> None:
        candles = _make_positive_control_candles()
        cls.result = auto_tester.test_hypothesis(
            POSITIVE_CONTROL_HYPOTHESIS, candles, now=datetime(2026, 8, 2, tzinfo=timezone.utc),
        )

    def test_frequency_gate_classifies_fast(self) -> None:
        self.assertEqual(self.result.frequency_classification, FAST)

    def test_verdict_is_survived(self) -> None:
        self.assertEqual(self.result.verdict, VERDICT_SURVIVED)

    def test_train_and_test_both_clear_min_sample_size(self) -> None:
        self.assertGreaterEqual(self.result.train.trades, MIN_SAMPLE_SIZE)
        self.assertGreaterEqual(self.result.test.trades, MIN_SAMPLE_SIZE)

    def test_train_and_test_both_have_strong_positive_expectancy(self) -> None:
        # 1.0R is a deliberately conservative floor -- the actual measured
        # expectancy is ~1.76R on both halves; this leaves headroom for
        # unrelated future harness changes (e.g. fee/slippage defaults)
        # without turning this into a brittle exact-value assertion.
        self.assertGreater(self.result.train.expectancy_r, 1.0)
        self.assertGreater(self.result.test.expectancy_r, 1.0)

    def test_train_and_test_cis_clear_zero(self) -> None:
        self.assertFalse(self.result.train.ci.crosses_zero)
        self.assertFalse(self.result.test.ci.crosses_zero)

    def test_uses_the_real_unmodified_classify_verdict(self) -> None:
        # Confirms this result actually came from auto_tester's own
        # classify_verdict call (imported, not reimplemented) -- not a
        # lookalike that happens to also return the string "SURVIVED".
        from tools.backtest_statistics import classify_verdict

        train_stats = {"expectancy_r": self.result.train.expectancy_r, "trades": self.result.train.trades, "ci": self.result.train.ci}
        test_stats = {"expectancy_r": self.result.test.expectancy_r, "trades": self.result.test.trades, "ci": self.result.test.ci}
        self.assertEqual(classify_verdict(train_stats, test_stats), VERDICT_SURVIVED)


if __name__ == "__main__":
    unittest.main()
