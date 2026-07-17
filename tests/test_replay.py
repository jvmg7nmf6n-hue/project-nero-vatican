from __future__ import annotations

import unittest

import pandas as pd

from nero_core.execution.replay import find_account_start_index, replay_pairs_events, replay_single_asset_events
from nero_core.strategies.cointegration_pairs import CointegrationPairsParameters
from nero_core.strategies.cointegration_pairs import add_indicators as pairs_add_indicators
from nero_core.strategies.cointegration_pairs import align_pair_candles
from tests.test_cointegration_pairs import _cointegrated_pair_frames
from tests.test_council_engine import _make_candle_row
from tools.backtest_compare import INDICATOR_COLUMNS_TO_CHECK, VARIANT_SPECS


def _weekly_breakout_history(n_flat: int = 220, n_breakout: int = 15) -> pd.DataFrame:
    rows: list[dict[str, float]] = []
    close_time = 0
    for i in range(n_flat):
        close = 100.0 + 0.01 * i
        rows.append(_make_candle_row(close_time, close))
        close_time += 7 * 86_400_000
    price = rows[-1]["close"]
    for _ in range(n_breakout):
        price *= 1.05
        rows.append(_make_candle_row(close_time, price))
        close_time += 7 * 86_400_000
    return pd.DataFrame(rows)


def _evaluable_gold_breakout_momentum():
    spec = VARIANT_SPECS["breakout_momentum_gold_calibrated_1week"]
    history = _weekly_breakout_history()
    enriched = spec.add_indicators_fn(history, spec.params)
    dropna_columns = [c for c in INDICATOR_COLUMNS_TO_CHECK if c in enriched.columns]
    evaluable = enriched.dropna(subset=dropna_columns).reset_index(drop=True)
    return spec, evaluable


class FindAccountStartIndexTest(unittest.TestCase):
    def test_empty_frame_returns_none(self) -> None:
        self.assertIsNone(find_account_start_index(pd.DataFrame(columns=["close_time"]), None))

    def test_no_inception_starts_at_newest_row(self) -> None:
        frame = pd.DataFrame({"close_time": [100, 200, 300]})
        self.assertEqual(find_account_start_index(frame, None), 2)

    def test_inception_matches_the_right_row(self) -> None:
        frame = pd.DataFrame({"close_time": [100, 200, 300]})
        self.assertEqual(find_account_start_index(frame, 200), 1)

    def test_inception_not_found_falls_back_to_earliest_row(self) -> None:
        frame = pd.DataFrame({"close_time": [100, 200, 300]})
        self.assertEqual(find_account_start_index(frame, 999), 0)


class ReplaySingleAssetEventsTest(unittest.TestCase):
    def test_first_run_only_emits_the_newest_candle(self) -> None:
        spec, evaluable = _evaluable_gold_breakout_momentum()

        events, _state = replay_single_asset_events(evaluable, spec, "GOLD", None, None)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].candle_close_time, int(evaluable.iloc[-1]["close_time"]))

    def test_second_run_with_no_new_candle_emits_nothing(self) -> None:
        spec, evaluable = _evaluable_gold_breakout_momentum()
        first_events, _ = replay_single_asset_events(evaluable, spec, "GOLD", None, None)
        anchor = first_events[0].candle_close_time

        events, _ = replay_single_asset_events(evaluable, spec, "GOLD", anchor, anchor)

        self.assertEqual(events, [])

    def test_new_candle_after_inception_is_emitted(self) -> None:
        spec, evaluable = _evaluable_gold_breakout_momentum()
        truncated = evaluable.iloc[:-1].reset_index(drop=True)
        first_events, _ = replay_single_asset_events(truncated, spec, "GOLD", None, None)
        anchor = first_events[0].candle_close_time

        events, _ = replay_single_asset_events(evaluable, spec, "GOLD", anchor, anchor)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].candle_close_time, int(evaluable.iloc[-1]["close_time"]))

    def test_replay_is_deterministic_across_repeated_calls(self) -> None:
        spec, evaluable = _evaluable_gold_breakout_momentum()
        inception = int(evaluable.iloc[0]["close_time"])

        events_a, state_a = replay_single_asset_events(evaluable, spec, "GOLD", inception, None)
        events_b, state_b = replay_single_asset_events(evaluable, spec, "GOLD", inception, None)

        self.assertEqual(state_a.equity, state_b.equity)
        self.assertEqual(len(events_a), len(events_b))
        self.assertEqual([e.signal_type for e in events_a], [e.signal_type for e in events_b])

    def test_full_replay_from_inception_produces_an_entry(self) -> None:
        spec, evaluable = _evaluable_gold_breakout_momentum()
        inception = int(evaluable.iloc[0]["close_time"])

        events, _state = replay_single_asset_events(evaluable, spec, "GOLD", inception, None)

        self.assertIn("ENTRY", {e.signal_type for e in events})


class ReplayPairsEventsTest(unittest.TestCase):
    def setUp(self) -> None:
        x_df, y_df = _cointegrated_pair_frames(500)
        aligned = align_pair_candles(x_df, y_df, "BTC", "ETH")
        self.params = CointegrationPairsParameters(window=60, entry_z=1.5, stop_z=3.0, exit_z=0.0)
        enriched = pairs_add_indicators(aligned, self.params, "BTC", "ETH")
        self.evaluable = enriched.dropna(subset=["zscore"]).reset_index(drop=True)

    def test_first_run_only_emits_the_newest_row(self) -> None:
        events, _state = replay_pairs_events(self.evaluable, self.params, "BTC", "ETH", None, None)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].candle_close_time, int(self.evaluable.iloc[-1]["close_time"]))

    def test_full_replay_from_first_row_produces_entries_and_exits(self) -> None:
        inception = int(self.evaluable.iloc[0]["close_time"])

        events, _state = replay_pairs_events(self.evaluable, self.params, "BTC", "ETH", inception, None)

        signal_types = {e.signal_type for e in events}
        self.assertIn("ENTRY", signal_types)
        self.assertIn("EXIT", signal_types)

    def test_no_new_row_emits_nothing_on_a_repeat_run(self) -> None:
        inception = int(self.evaluable.iloc[0]["close_time"])
        already_logged = int(self.evaluable.iloc[-1]["close_time"])

        events, _state = replay_pairs_events(self.evaluable, self.params, "BTC", "ETH", inception, already_logged)

        self.assertEqual(events, [])

    def test_every_entry_event_has_an_entry_price_and_no_exit_price(self) -> None:
        inception = int(self.evaluable.iloc[0]["close_time"])

        events, _state = replay_pairs_events(self.evaluable, self.params, "BTC", "ETH", inception, None)

        for event in events:
            if event.signal_type == "ENTRY":
                self.assertIsNotNone(event.entry_price)
                self.assertIsNone(event.exit_price)
            elif event.signal_type == "EXIT":
                self.assertIsNotNone(event.exit_price)
                self.assertIsNone(event.entry_price)


if __name__ == "__main__":
    unittest.main()
