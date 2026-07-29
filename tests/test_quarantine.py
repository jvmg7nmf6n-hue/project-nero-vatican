from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from nero_core.execution.quarantine import (
    QUARANTINE_CUTOFFS,
    exclude_quarantined,
    is_quarantined,
    list_clean_execution_log,
)
from nero_core.strategies.orderflow_imbalance import STRATEGY_ID as ORDERFLOW_ID
from nero_core.strategies.orderflow_imbalance import STRATEGY_VERSION as ORDERFLOW_VERSION
from nero_core.truth_ledger.execution_log import insert_execution_log_row

BTC_CUTOFF = QUARANTINE_CUTOFFS[(ORDERFLOW_ID, ORDERFLOW_VERSION, "BTC")]
ETH_CUTOFF = QUARANTINE_CUTOFFS[(ORDERFLOW_ID, ORDERFLOW_VERSION, "ETH")]


class QuarantineCutoffsTest(unittest.TestCase):
    """Pins the exact boundary values found during the 2026-07-29 orderflow-
    verification investigation (execution_log ids 141/BTC and 143/ETH -- the first
    candle_timestamp after the Binance-451 fix, commit c106b8d) -- a future edit to
    QUARANTINE_CUTOFFS should have to consciously break this test, not silently drift."""

    def test_btc_cutoff_matches_confirmed_boundary(self) -> None:
        self.assertEqual(BTC_CUTOFF, 1785254399999)

    def test_eth_cutoff_matches_confirmed_boundary(self) -> None:
        self.assertEqual(ETH_CUTOFF, 1785257999999)


class IsQuarantinedTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test_truth_ledger.db"
        self.addCleanup(self._tmp.cleanup)

    def test_row_strictly_before_cutoff_is_quarantined(self) -> None:
        row = insert_execution_log_row(
            run_id="run-1", strategy=ORDERFLOW_ID, strategy_version=ORDERFLOW_VERSION, asset="BTC",
            signal_type="ENTRY", reasoning="pre-fix", candle_timestamp=BTC_CUTOFF - 1, db_path=self.db_path,
        )
        self.assertTrue(is_quarantined(row))

    def test_row_at_cutoff_is_clean(self) -> None:
        row = insert_execution_log_row(
            run_id="run-1", strategy=ORDERFLOW_ID, strategy_version=ORDERFLOW_VERSION, asset="BTC",
            signal_type="ENTRY", reasoning="the boundary row itself", candle_timestamp=BTC_CUTOFF, db_path=self.db_path,
        )
        self.assertFalse(is_quarantined(row))

    def test_row_after_cutoff_is_clean(self) -> None:
        row = insert_execution_log_row(
            run_id="run-1", strategy=ORDERFLOW_ID, strategy_version=ORDERFLOW_VERSION, asset="ETH",
            signal_type="EXIT", reasoning="post-fix", candle_timestamp=ETH_CUTOFF + 1_000, db_path=self.db_path,
        )
        self.assertFalse(is_quarantined(row))

    def test_unrelated_strategy_is_never_quarantined_regardless_of_timestamp(self) -> None:
        """A (strategy, strategy_version, asset) key absent from QUARANTINE_CUTOFFS
        must never be quarantined, no matter how small its candle_timestamp is --
        quarantine is opt-in per confirmed incident, not a blanket suspicion over
        every strategy's early history."""
        row = insert_execution_log_row(
            run_id="run-1", strategy="BREAKOUT_MOMENTUM", strategy_version="breakout-momentum-v1.2.0-gold-calibrated-1week",
            asset="GOLD", signal_type="ENTRY", reasoning="unrelated strategy", candle_timestamp=0, db_path=self.db_path,
        )
        self.assertFalse(is_quarantined(row))

    def test_unrelated_asset_on_same_strategy_is_never_quarantined(self) -> None:
        """ORDERFLOW_IMBALANCE quarantine is scoped to BTC/ETH specifically -- a
        hypothetical third ORDERFLOW_IMBALANCE asset outside QUARANTINE_CUTOFFS must
        not be swept in by strategy name alone."""
        row = insert_execution_log_row(
            run_id="run-1", strategy=ORDERFLOW_ID, strategy_version=ORDERFLOW_VERSION, asset="SOL",
            signal_type="ENTRY", reasoning="hypothetical unlisted asset", candle_timestamp=0, db_path=self.db_path,
        )
        self.assertFalse(is_quarantined(row))


class ExcludeQuarantinedTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test_truth_ledger.db"
        self.addCleanup(self._tmp.cleanup)

    def test_excludes_only_quarantined_rows_preserving_order(self) -> None:
        clean_before = insert_execution_log_row(
            run_id="r", strategy="BREAKOUT_MOMENTUM", strategy_version="breakout-momentum-v1.2.0-gold-calibrated-1week",
            asset="GOLD", signal_type="ENTRY", reasoning="unrelated, always clean", candle_timestamp=1, db_path=self.db_path,
        )
        quarantined = insert_execution_log_row(
            run_id="r", strategy=ORDERFLOW_ID, strategy_version=ORDERFLOW_VERSION, asset="BTC",
            signal_type="ENTRY", reasoning="pre-fix", candle_timestamp=BTC_CUTOFF - 1, db_path=self.db_path,
        )
        clean_after = insert_execution_log_row(
            run_id="r", strategy=ORDERFLOW_ID, strategy_version=ORDERFLOW_VERSION, asset="BTC",
            signal_type="EXIT", reasoning="post-fix", candle_timestamp=BTC_CUTOFF + 1, db_path=self.db_path,
        )
        rows = [clean_before, quarantined, clean_after]
        result = exclude_quarantined(rows)
        self.assertEqual(result, [clean_before, clean_after])


class ListCleanExecutionLogTest(unittest.TestCase):
    """Integration-level: proves the actual harness entrypoint (list_clean_execution_log)
    excludes quarantined rows read back from a real database, not just the pure-function
    filter in isolation."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test_truth_ledger.db"
        self.addCleanup(self._tmp.cleanup)

    def test_harness_input_excludes_quarantined_rows(self) -> None:
        insert_execution_log_row(
            run_id="r1", strategy=ORDERFLOW_ID, strategy_version=ORDERFLOW_VERSION, asset="BTC",
            signal_type="ENTRY", reasoning="pre-fix entry", candle_timestamp=BTC_CUTOFF - 7200_000, db_path=self.db_path,
        )
        insert_execution_log_row(
            run_id="r1", strategy=ORDERFLOW_ID, strategy_version=ORDERFLOW_VERSION, asset="BTC",
            signal_type="EXIT", reasoning="pre-fix exit", candle_timestamp=BTC_CUTOFF - 3600_000, db_path=self.db_path,
        )
        insert_execution_log_row(
            run_id="r2", strategy=ORDERFLOW_ID, strategy_version=ORDERFLOW_VERSION, asset="BTC",
            signal_type="ENTRY", reasoning="post-fix entry", candle_timestamp=BTC_CUTOFF + 3600_000, db_path=self.db_path,
        )
        insert_execution_log_row(
            run_id="r2", strategy=ORDERFLOW_ID, strategy_version=ORDERFLOW_VERSION, asset="BTC",
            signal_type="EXIT", reasoning="post-fix exit", candle_timestamp=BTC_CUTOFF + 7200_000, db_path=self.db_path,
        )

        clean_rows = list_clean_execution_log(db_path=self.db_path, asset="BTC", strategy=ORDERFLOW_ID)

        self.assertEqual(len(clean_rows), 2)
        self.assertTrue(all("post-fix" in row.reasoning for row in clean_rows))


if __name__ == "__main__":
    unittest.main()
