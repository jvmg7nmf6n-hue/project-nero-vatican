from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from nero_core.truth_ledger.models import (
    DuplicatePredictionError,
    PredictionNotFoundError,
    PredictionRecord,
    TruthLabel,
    compute_truth_label,
    delete_prediction,
    get_prediction,
    insert_prediction,
    list_predictions,
    update_prediction_result,
)


def _make_record(**overrides: object) -> PredictionRecord:
    defaults = dict(
        timestamp=datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc),
        asset="BTC",
        strategy_id="MEAN_REVERSION",
        strategy_version="v1",
        direction="LONG",
        confidence=0.7,
        entry_condition_values={"rsi": 28.4, "close": 61000.0},
        reason="RSI oversold with uptrend filter confirmed.",
    )
    defaults.update(overrides)
    return PredictionRecord(**defaults)


class TruthLedgerTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "truth_ledger.db"

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    # -- duplicate prevention --------------------------------------------------

    def test_duplicate_prediction_is_rejected(self) -> None:
        record = _make_record()
        insert_prediction(record, db_path=self.db_path)

        with self.assertRaises(DuplicatePredictionError):
            insert_prediction(record, db_path=self.db_path)

        rows = list_predictions(db_path=self.db_path, asset="BTC")
        self.assertEqual(len(rows), 1)

    def test_same_asset_different_timestamp_is_allowed(self) -> None:
        insert_prediction(_make_record(), db_path=self.db_path)
        insert_prediction(
            _make_record(timestamp=datetime(2026, 7, 15, 13, 0, tzinfo=timezone.utc)),
            db_path=self.db_path,
        )

        rows = list_predictions(db_path=self.db_path, asset="BTC")
        self.assertEqual(len(rows), 2)

    def test_same_timestamp_different_strategy_version_is_allowed(self) -> None:
        insert_prediction(_make_record(strategy_version="v1"), db_path=self.db_path)
        insert_prediction(_make_record(strategy_version="v2"), db_path=self.db_path)

        rows = list_predictions(db_path=self.db_path, asset="BTC")
        self.assertEqual(len(rows), 2)

    # -- truth-labeling logic ----------------------------------------------------

    def test_truth_label_true_positive_for_winning_trade(self) -> None:
        self.assertEqual(compute_truth_label("LONG", "WIN"), TruthLabel.TRUE_POSITIVE)

    def test_truth_label_false_positive_for_losing_trade(self) -> None:
        self.assertEqual(compute_truth_label("SHORT", "LOSS"), TruthLabel.FALSE_POSITIVE)

    def test_truth_label_true_negative_for_correctly_avoided_loss(self) -> None:
        self.assertEqual(compute_truth_label("NO_TRADE", "LOSS"), TruthLabel.TRUE_NEGATIVE)

    def test_truth_label_false_negative_for_missed_win(self) -> None:
        self.assertEqual(compute_truth_label("NO_TRADE", "WIN"), TruthLabel.FALSE_NEGATIVE)

    def test_truth_label_inconclusive_for_pending_or_breakeven(self) -> None:
        self.assertEqual(compute_truth_label("LONG", "PENDING"), TruthLabel.INCONCLUSIVE)
        self.assertEqual(compute_truth_label("LONG", "BREAKEVEN"), TruthLabel.INCONCLUSIVE)
        self.assertEqual(compute_truth_label("NO_TRADE", "BREAKEVEN"), TruthLabel.INCONCLUSIVE)

    def test_insert_sets_inconclusive_label_while_pending(self) -> None:
        inserted = insert_prediction(_make_record(), db_path=self.db_path)

        self.assertEqual(inserted.result, "PENDING")
        self.assertEqual(inserted.truth_label, TruthLabel.INCONCLUSIVE)

    def test_update_prediction_result_recomputes_truth_label(self) -> None:
        inserted = insert_prediction(_make_record(direction="LONG"), db_path=self.db_path)

        updated = update_prediction_result(
            inserted.id,
            result="WIN",
            exit_reason="Target hit",
            r_multiple=1.8,
            fees_slippage_estimate=0.001,
            db_path=self.db_path,
        )

        self.assertEqual(updated.result, "WIN")
        self.assertEqual(updated.truth_label, TruthLabel.TRUE_POSITIVE)
        self.assertEqual(updated.exit_reason, "Target hit")
        self.assertAlmostEqual(updated.r_multiple, 1.8)

    def test_update_prediction_result_for_no_trade_missed_opportunity(self) -> None:
        inserted = insert_prediction(_make_record(direction="NO_TRADE", confidence=0.2), db_path=self.db_path)

        updated = update_prediction_result(inserted.id, result="WIN", db_path=self.db_path)

        self.assertEqual(updated.truth_label, TruthLabel.FALSE_NEGATIVE)

    def test_update_prediction_result_raises_for_unknown_id(self) -> None:
        with self.assertRaises(PredictionNotFoundError):
            update_prediction_result(999, result="WIN", db_path=self.db_path)

    # -- basic CRUD ---------------------------------------------------------

    def test_insert_and_get_round_trips_entry_condition_values(self) -> None:
        inserted = insert_prediction(_make_record(), db_path=self.db_path)

        fetched = get_prediction(inserted.id, db_path=self.db_path)

        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.entry_condition_values, {"rsi": 28.4, "close": 61000.0})
        self.assertEqual(fetched.asset, "BTC")
        self.assertIsNotNone(fetched.created_at)

    def test_get_prediction_returns_none_for_unknown_id(self) -> None:
        self.assertIsNone(get_prediction(999, db_path=self.db_path))

    def test_list_predictions_filters_by_asset_and_strategy(self) -> None:
        insert_prediction(_make_record(asset="BTC", strategy_id="MEAN_REVERSION"), db_path=self.db_path)
        insert_prediction(
            _make_record(
                asset="ETH",
                strategy_id="MEAN_REVERSION",
                timestamp=datetime(2026, 7, 15, 13, 0, tzinfo=timezone.utc),
            ),
            db_path=self.db_path,
        )
        insert_prediction(
            _make_record(
                asset="BTC",
                strategy_id="BREAKOUT",
                timestamp=datetime(2026, 7, 15, 14, 0, tzinfo=timezone.utc),
            ),
            db_path=self.db_path,
        )

        btc_rows = list_predictions(db_path=self.db_path, asset="BTC")
        mean_reversion_rows = list_predictions(db_path=self.db_path, strategy_id="MEAN_REVERSION")

        self.assertEqual(len(btc_rows), 2)
        self.assertEqual(len(mean_reversion_rows), 2)
        self.assertTrue(all(row.asset == "BTC" for row in btc_rows))

    def test_delete_prediction_removes_row(self) -> None:
        inserted = insert_prediction(_make_record(), db_path=self.db_path)

        deleted = delete_prediction(inserted.id, db_path=self.db_path)
        missing_delete = delete_prediction(inserted.id, db_path=self.db_path)

        self.assertTrue(deleted)
        self.assertFalse(missing_delete)
        self.assertIsNone(get_prediction(inserted.id, db_path=self.db_path))


if __name__ == "__main__":
    unittest.main()
