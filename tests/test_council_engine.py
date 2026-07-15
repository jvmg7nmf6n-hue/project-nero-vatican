from __future__ import annotations

import unittest

import pandas as pd

from nero_core.council.engine import TOTAL_PLANNED_INPUTS, build_council_verdict
from nero_core.strategies.mean_reversion import MeanReversionState


def _make_candle_row(close_time: int, close: float) -> dict[str, float]:
    return {
        "date": pd.Timestamp(close_time, unit="ms", tz="UTC"),
        "close_time": close_time,
        "open": close,
        "high": close * 1.001,
        "low": close * 0.999,
        "close": close,
        "volume": 10.0,
    }


def _flat_then_pullback_history() -> pd.DataFrame:
    """200 candles of a steady uptrend (100 -> 300, so MA200 sits well below the recent
    price) followed by a sharp pullback in the last few candles: RSI drops, close falls
    below the lower Bollinger band, but MA20 and MA200 both stay above the final close.
    This is the textbook mean-reversion-in-an-uptrend setup the strategy is built for."""
    rows: list[dict[str, float]] = []
    close_time = 0
    # Long-term uptrend: 200 candles from 100 to 300.
    for i in range(200):
        close = 100.0 + (200.0 * i / 199)
        rows.append(_make_candle_row(close_time, close))
        close_time += 3_600_000

    # Last 20 candles: flat near the peak, then a sharp pullback in the final 5.
    tail_closes = [300.0] * 15 + [295.0, 285.0, 270.0, 255.0, 240.0]
    for close in tail_closes:
        rows.append(_make_candle_row(close_time, close))
        close_time += 3_600_000

    return pd.DataFrame(rows)


class CouncilEngineInsufficientDataTest(unittest.TestCase):
    def test_empty_price_history_yields_honest_no_trade_verdict(self) -> None:
        verdict = build_council_verdict("BTC", pd.DataFrame())

        self.assertEqual(verdict.stance, "NO_TRADE")
        self.assertEqual(verdict.directional_bias, "NEUTRAL")
        self.assertEqual(verdict.global_score, 0.0)
        self.assertEqual(verdict.confidence, 0.0)
        self.assertEqual(verdict.recommended_strategy, "")
        self.assertTrue(any("insufficient data" in blocker.lower() for blocker in verdict.top_blockers))

    def test_short_price_history_reports_insufficient_data_not_fake_values(self) -> None:
        short_history = pd.DataFrame(
            [_make_candle_row(i * 3_600_000, 100.0 + i) for i in range(10)]
        )

        verdict = build_council_verdict("ETH", short_history)

        self.assertEqual(verdict.stance, "NO_TRADE")
        self.assertEqual(verdict.recommended_strategy, "")
        blocker_text = " ".join(verdict.top_blockers).lower()
        self.assertIn("insufficient data", blocker_text)

    def test_unported_inputs_are_always_disclosed_never_silently_dropped(self) -> None:
        history = _flat_then_pullback_history()

        verdict = build_council_verdict("BTC", history)

        self.assertTrue(any("not yet ported" in blocker for blocker in verdict.top_blockers))

    def test_top_blockers_are_capped_at_five(self) -> None:
        verdict = build_council_verdict("BTC", pd.DataFrame())

        self.assertLessEqual(len(verdict.top_blockers), 5)

    def test_high_quality_setup_is_never_reachable_in_this_skeleton(self) -> None:
        # Structural guarantee: with only 2 of TOTAL_PLANNED_INPUTS wired up, the engine
        # must never claim the strongest stance regardless of how favorable the two
        # available inputs look.
        history = _flat_then_pullback_history()

        verdict = build_council_verdict("BTC", history, MeanReversionState(equity=10000.0))

        self.assertNotEqual(verdict.stance, "HIGH_QUALITY_SETUP")


class CouncilEngineConfirmedSignalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.history = _flat_then_pullback_history()
        self.state = MeanReversionState(equity=10000.0)

    def test_confirmed_mean_reversion_signal_drives_long_bias_and_recommendation(self) -> None:
        verdict = build_council_verdict("BTC", self.history, self.state)

        self.assertEqual(verdict.directional_bias, "LONG")
        self.assertEqual(verdict.recommended_strategy, "MEAN_REVERSION@mean-reversion-v1.0.0")
        self.assertIn(verdict.stance, {"WATCH", "PAPER_TEST_READY"})
        self.assertTrue(any("Mean Reversion" in factor for factor in verdict.top_supportive_factors))

    def test_confidence_reflects_fraction_of_all_planned_inputs(self) -> None:
        verdict = build_council_verdict("BTC", self.history, self.state)

        # At most 2 of TOTAL_PLANNED_INPUTS can ever be supportive in this phase.
        self.assertLessEqual(verdict.confidence, round(2 / TOTAL_PLANNED_INPUTS, 2))
        self.assertGreater(verdict.confidence, 0.0)

    def test_open_trade_does_not_generate_a_new_recommendation(self) -> None:
        # Simulate a trade that's already open going into this evaluation: the engine
        # should note that fact but must not recommend opening a second one.
        first_pass_state = MeanReversionState(equity=10000.0)
        build_council_verdict("BTC", self.history, first_pass_state)
        self.assertIsNone(first_pass_state.open_trade)  # evaluate_entry alone never opens a trade

        # Directly simulate "already in a trade" for the recommendation-suppression check.
        from nero_core.strategies.mean_reversion import OpenTrade

        state_with_open_trade = MeanReversionState(
            equity=10000.0,
            open_trade=OpenTrade(
                entry_price=240.0,
                stop_loss=230.0,
                target=290.0,
                quantity=1.0,
                notional=240.0,
                risk_dollars=10.0,
                entry_fee=0.1,
                open_close_time=0,
                entry_rsi=25.0,
                entry_ma20=290.0,
                entry_bb_lower=248.0,
                entry_ma200=200.0,
                entry_atr=5.0,
            ),
        )

        verdict = build_council_verdict("BTC", self.history, state_with_open_trade)

        self.assertEqual(verdict.recommended_strategy, "")
        self.assertTrue(any("currently open" in factor.lower() for factor in verdict.top_supportive_factors))

    def test_global_score_is_bounded_and_json_shape_matches_spec(self) -> None:
        verdict = build_council_verdict("BTC", self.history, self.state)
        payload = verdict.model_dump()

        expected_keys = {
            "asset",
            "global_score",
            "stance",
            "directional_bias",
            "confidence",
            "risk",
            "top_supportive_factors",
            "top_blockers",
            "recommended_strategy",
            "summary",
        }
        self.assertEqual(set(payload.keys()), expected_keys)
        self.assertGreaterEqual(payload["global_score"], 0.0)
        self.assertLessEqual(payload["global_score"], 100.0)
        self.assertGreaterEqual(payload["confidence"], 0.0)
        self.assertLessEqual(payload["confidence"], 1.0)
        self.assertGreaterEqual(payload["risk"], 0.0)
        self.assertLessEqual(payload["risk"], 1.0)


if __name__ == "__main__":
    unittest.main()
