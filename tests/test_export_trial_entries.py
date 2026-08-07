"""CC-1 Part D6a/D6: tests for nero_core.execution.export_trial_entries -- the
Forward Trial ENTRY event export (D6a's own definition: an execution_log row
with strategy TRIAL:<trial_id> and signal_type ENTRY, distinct from mere Trial
admission)."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from nero_core.execution.export_trial_entries import build_trial_entries, write_trial_entries
from nero_core.truth_ledger.execution_log import insert_execution_log_row


class ExportTrialEntriesTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp_path = Path(self._tmp.name)
        self.db_path = tmp_path / "forward_tracking.db"
        self.trial_records_path = tmp_path / "forward_trial.json"
        self.agent_hypotheses_path = tmp_path / "agent_hypotheses.json"
        self.eve_hypotheses_path = tmp_path / "eve_hypotheses.json"
        self.addCleanup(self._tmp.cleanup)

    def _write_trial_records(self, records: list[dict]) -> None:
        self.trial_records_path.write_text(json.dumps(records))

    def _write_agent_hypotheses(self, records: list[dict]) -> None:
        self.agent_hypotheses_path.write_text(json.dumps(records))

    def _write_eve_hypotheses(self, records: list[dict]) -> None:
        self.eve_hypotheses_path.write_text(json.dumps(records))

    def _build(self) -> list[dict]:
        return build_trial_entries(
            db_path=self.db_path,
            trial_records_path=self.trial_records_path,
            agent_hypotheses_path=self.agent_hypotheses_path,
            eve_hypotheses_path=self.eve_hypotheses_path,
        )


class GenuineEntryDetectionTest(ExportTrialEntriesTestCase):
    def test_trial_entry_row_is_included_with_full_context(self) -> None:
        self._write_trial_records([{
            "trial_id": "abc123",
            "source_hypothesis_ref": {"hypothesis_name": "ETH_TEST_HYPOTHESIS", "origin_agent": "eve"},
        }])
        self._write_eve_hypotheses([])
        self._write_agent_hypotheses([{"hypothesis_name": "ETH_TEST_HYPOTHESIS", "asset": "ETH", "timeframe": "4h"}])
        insert_execution_log_row(
            run_id="r1", strategy="TRIAL:abc123", strategy_version="v1", asset="ETH",
            signal_type="ENTRY", reasoning=json.dumps({"direction": "SHORT", "stop_loss": 100.0, "target": 90.0}),
            candle_timestamp=1, entry_price=95.0,
            timestamp=datetime(2026, 8, 5, tzinfo=timezone.utc), db_path=self.db_path,
        )
        entries = self._build()
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual(e["trial_id"], "abc123")
        self.assertEqual(e["hypothesis_name"], "ETH_TEST_HYPOTHESIS")
        self.assertEqual(e["origin_agent"], "eve")
        self.assertEqual(e["asset"], "ETH")
        self.assertEqual(e["timeframe"], "4h")
        self.assertEqual(e["direction"], "SHORT")
        self.assertEqual(e["entry_price"], 95.0)
        self.assertEqual(e["stop_loss"], 100.0)
        self.assertEqual(e["target"], 90.0)

    def test_non_trial_strategies_are_excluded(self) -> None:
        """D6a's own scope guard: this export must never pick up unrelated
        execution_log rows (e.g. ORDERFLOW_IMBALANCE, or Repair Lab attempts
        under REPAIR_LAB_ATTEMPT:) just because they share the same table
        shape."""
        self._write_trial_records([])
        self._write_agent_hypotheses([])
        self._write_eve_hypotheses([])
        insert_execution_log_row(
            run_id="r1", strategy="ORDERFLOW_IMBALANCE", strategy_version="v1", asset="BTC",
            signal_type="ENTRY", reasoning="direction=LONG stop_loss=1.0", candle_timestamp=1,
            entry_price=100.0, db_path=self.db_path,
        )
        insert_execution_log_row(
            run_id="r1", strategy="REPAIR_LAB_ATTEMPT:xyz", strategy_version="v1", asset="BTC",
            signal_type="ENTRY", reasoning="{}", candle_timestamp=2, entry_price=100.0, db_path=self.db_path,
        )
        self.assertEqual(self._build(), [])

    def test_exit_and_no_trade_rows_are_excluded_even_for_trial_strategies(self) -> None:
        """The core D6a distinction: only signal_type == ENTRY counts as a
        genuine new position opening -- EXIT/NO_TRADE rows for the same
        trial must never be mistaken for a fresh entry."""
        self._write_trial_records([{
            "trial_id": "abc123",
            "source_hypothesis_ref": {"hypothesis_name": "H", "origin_agent": "adam"},
        }])
        self._write_agent_hypotheses([])
        self._write_eve_hypotheses([])
        insert_execution_log_row(
            run_id="r1", strategy="TRIAL:abc123", strategy_version="v1", asset="BTC",
            signal_type="NO_TRADE", reasoning="no entry", candle_timestamp=1, db_path=self.db_path,
        )
        insert_execution_log_row(
            run_id="r1", strategy="TRIAL:abc123", strategy_version="v1", asset="BTC",
            signal_type="EXIT", reasoning="{}", candle_timestamp=2, exit_price=100.0, db_path=self.db_path,
        )
        self.assertEqual(self._build(), [])

    def test_a_second_real_entry_for_the_same_trial_after_an_exit_is_also_included(self) -> None:
        """A trial can genuinely re-enter after exiting -- each real ENTRY
        row is its own event, not deduplicated by trial_id."""
        self._write_trial_records([{
            "trial_id": "abc123",
            "source_hypothesis_ref": {"hypothesis_name": "H", "origin_agent": "adam"},
        }])
        self._write_agent_hypotheses([])
        self._write_eve_hypotheses([])
        insert_execution_log_row(
            run_id="r1", strategy="TRIAL:abc123", strategy_version="v1", asset="BTC",
            signal_type="ENTRY", reasoning="{}", candle_timestamp=1, entry_price=100.0, db_path=self.db_path,
        )
        insert_execution_log_row(
            run_id="r1", strategy="TRIAL:abc123", strategy_version="v1", asset="BTC",
            signal_type="EXIT", reasoning="{}", candle_timestamp=2, exit_price=105.0, db_path=self.db_path,
        )
        insert_execution_log_row(
            run_id="r1", strategy="TRIAL:abc123", strategy_version="v1", asset="BTC",
            signal_type="ENTRY", reasoning="{}", candle_timestamp=3, entry_price=103.0, db_path=self.db_path,
        )
        entries = self._build()
        self.assertEqual(len(entries), 2)

    def test_missing_hypothesis_context_degrades_honestly_not_fatally(self) -> None:
        """A TRIAL: entry whose trial_id isn't found in forward_trial.json (or
        whose hypothesis_name isn't found in either hypotheses export) must
        still be included, with None for the fields that couldn't be
        resolved -- never dropped, never guessed."""
        self._write_trial_records([])
        self._write_agent_hypotheses([])
        self._write_eve_hypotheses([])
        insert_execution_log_row(
            run_id="r1", strategy="TRIAL:unknown-id", strategy_version="v1", asset="BTC",
            signal_type="ENTRY", reasoning="{}", candle_timestamp=1, entry_price=100.0, db_path=self.db_path,
        )
        entries = self._build()
        self.assertEqual(len(entries), 1)
        self.assertIsNone(entries[0]["hypothesis_name"])
        self.assertIsNone(entries[0]["timeframe"])
        self.assertEqual(entries[0]["asset"], "BTC")  # asset comes straight from execution_log, always resolvable


class WriteTrialEntriesTest(ExportTrialEntriesTestCase):
    def test_writes_schema_versioned_json(self) -> None:
        self._write_trial_records([])
        self._write_agent_hypotheses([])
        self._write_eve_hypotheses([])
        out_path = Path(self._tmp.name) / "trial_entries.json"
        write_trial_entries(
            output_path=out_path, db_path=self.db_path, trial_records_path=self.trial_records_path,
            agent_hypotheses_path=self.agent_hypotheses_path, eve_hypotheses_path=self.eve_hypotheses_path,
        )
        payload = json.loads(out_path.read_text())
        self.assertEqual(payload["schema_version"], 1)
        self.assertIn("last_updated", payload)
        self.assertEqual(payload["entries"], [])

    def test_never_leaks_a_local_filesystem_path(self) -> None:
        """Regression guard for the known, disclosed forward_trial.json leak
        (forward_tracking_db_ref) -- this export must never repeat it."""
        self._write_trial_records([{
            "trial_id": "abc123",
            "source_hypothesis_ref": {"hypothesis_name": "H", "origin_agent": "adam"},
            "forward_tracking_db_ref": str(self.db_path),
        }])
        self._write_agent_hypotheses([])
        self._write_eve_hypotheses([])
        insert_execution_log_row(
            run_id="r1", strategy="TRIAL:abc123", strategy_version="v1", asset="BTC",
            signal_type="ENTRY", reasoning="{}", candle_timestamp=1, entry_price=100.0, db_path=self.db_path,
        )
        out_path = Path(self._tmp.name) / "trial_entries.json"
        write_trial_entries(
            output_path=out_path, db_path=self.db_path, trial_records_path=self.trial_records_path,
            agent_hypotheses_path=self.agent_hypotheses_path, eve_hypotheses_path=self.eve_hypotheses_path,
        )
        raw_text = out_path.read_text()
        self.assertNotIn(str(self.db_path), raw_text)
        self.assertNotIn("forward_tracking_db_ref", raw_text)


if __name__ == "__main__":
    unittest.main()
