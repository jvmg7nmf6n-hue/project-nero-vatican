"""CC-1 Part C: tests for nero_core.truth_ledger.macro_reads -- the structurally
separate macro_reads / macro_conflict_flags tables and their CRUD/no-lookahead
guarantees."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nero_core.truth_ledger.macro_reads import (
    get_latest_macro_read_before,
    has_flag_for_entry,
    insert_macro_conflict_flag,
    insert_macro_read,
    list_macro_conflict_flags,
    list_macro_reads,
)


class MacroReadsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test_truth_ledger.db"
        self.addCleanup(self._tmp.cleanup)

    def _insert(self, run_id="run-1", asset="BITCOIN", bias="BEARISH", agreement=0.7,
               coverage=0.3, timestamp=None):
        return insert_macro_read(
            run_id=run_id, asset=asset, bias=bias, confidence=0.5, agreement=agreement,
            coverage=coverage, probability_up=0.4,
            provenance_breakdown={"bitcoin_analysis": "mixed"}, reasoning="test reasoning",
            risks=["risk 1"], alternative_scenarios=[{"name": "base", "probability": 1.0}],
            data_mode="live", timestamp=timestamp, db_path=self.db_path,
        )


class InsertMacroReadTest(MacroReadsTestCase):
    def test_insert_and_read_back(self) -> None:
        row = self._insert()
        self.assertIsNotNone(row.id)
        rows = list_macro_reads(asset="BITCOIN", db_path=self.db_path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].bias, "BEARISH")
        self.assertEqual(rows[0].provenance_breakdown, {"bitcoin_analysis": "mixed"})

    def test_duplicate_run_id_asset_is_a_no_op_not_an_error(self) -> None:
        first = self._insert(run_id="run-1")
        second = self._insert(run_id="run-1")
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(len(list_macro_reads(db_path=self.db_path)), 1)


class GetLatestMacroReadBeforeTest(MacroReadsTestCase):
    def test_never_returns_a_read_from_after_the_cutoff(self) -> None:
        """NO LOOKAHEAD: a read timestamped AFTER `before` must never be returned,
        even though it's the most recent read overall."""
        t0 = datetime(2026, 8, 1, tzinfo=timezone.utc)
        t1 = datetime(2026, 8, 5, tzinfo=timezone.utc)
        self._insert(run_id="early", timestamp=t0, bias="NEUTRAL")
        self._insert(run_id="late", timestamp=t1, bias="STRONG_BEARISH")

        # Querying for a moment BEFORE the late read must only see the early one.
        result = get_latest_macro_read_before("BITCOIN", t0 + timedelta(hours=1), db_path=self.db_path)
        self.assertEqual(result.bias, "NEUTRAL")

    def test_returns_none_when_nothing_exists_before_cutoff(self) -> None:
        t1 = datetime(2026, 8, 5, tzinfo=timezone.utc)
        self._insert(run_id="late", timestamp=t1)
        result = get_latest_macro_read_before("BITCOIN", t1 - timedelta(days=1), db_path=self.db_path)
        self.assertIsNone(result)

    def test_picks_the_most_recent_of_multiple_prior_reads(self) -> None:
        t0 = datetime(2026, 8, 1, tzinfo=timezone.utc)
        t1 = datetime(2026, 8, 3, tzinfo=timezone.utc)
        t2 = datetime(2026, 8, 5, tzinfo=timezone.utc)
        self._insert(run_id="r0", timestamp=t0, bias="NEUTRAL")
        self._insert(run_id="r1", timestamp=t1, bias="BEARISH")
        result = get_latest_macro_read_before("BITCOIN", t2, db_path=self.db_path)
        self.assertEqual(result.bias, "BEARISH")


class MacroConflictFlagTest(MacroReadsTestCase):
    def test_insert_and_list(self) -> None:
        read = self._insert()
        flag = insert_macro_conflict_flag(
            execution_log_id=42, strategy="ORDERFLOW_IMBALANCE", asset="BTC",
            conflicted=True, status="evaluated", reason="test", macro_read_id=read.id,
            entry_direction="LONG", db_path=self.db_path,
        )
        self.assertIsNotNone(flag)
        self.assertTrue(has_flag_for_entry(42, db_path=self.db_path))
        flags = list_macro_conflict_flags(db_path=self.db_path)
        self.assertEqual(len(flags), 1)
        self.assertTrue(flags[0].conflicted)

    def test_same_execution_log_id_never_flagged_twice(self) -> None:
        first = insert_macro_conflict_flag(
            execution_log_id=1, strategy="ORDERFLOW_IMBALANCE", asset="BTC",
            conflicted=False, status="evaluated", reason="first", db_path=self.db_path,
        )
        second = insert_macro_conflict_flag(
            execution_log_id=1, strategy="ORDERFLOW_IMBALANCE", asset="BTC",
            conflicted=True, status="evaluated", reason="second", db_path=self.db_path,
        )
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(len(list_macro_conflict_flags(db_path=self.db_path)), 1)

    def test_conflicted_only_filter(self) -> None:
        insert_macro_conflict_flag(execution_log_id=1, strategy="ORDERFLOW_IMBALANCE", asset="BTC",
                                   conflicted=False, status="evaluated", reason="no conflict",
                                   db_path=self.db_path)
        insert_macro_conflict_flag(execution_log_id=2, strategy="ORDERFLOW_IMBALANCE", asset="BTC",
                                   conflicted=True, status="evaluated", reason="conflict",
                                   db_path=self.db_path)
        flags = list_macro_conflict_flags(conflicted_only=True, db_path=self.db_path)
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0].execution_log_id, 2)


if __name__ == "__main__":
    unittest.main()
