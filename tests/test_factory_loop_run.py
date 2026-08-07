from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import ANY, patch

import pandas as pd

from nero_core.research_agent import graveyard_distillation, repair_lab, trial
from tools import factory_loop_run as runner

NOW = datetime(2026, 8, 5, tzinfo=timezone.utc)

VALID_ENTRY = {"conditions": [{"field": "zscore20", "op": "lt", "value": -2.0}]}
VALID_EXIT = {"stop_atr_multiple": 1.5, "target_r_multiple": 2.0, "max_holding_hours": 48.0}


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


class LoadAdamCandidatesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_joins_test_result_with_hypothesis_record(self) -> None:
        results_path = self.tmp / "results.json"
        hyps_path = self.tmp / "hyps.json"
        _write_json(results_path, [{"hypothesis_name": "X", "verdict": "SKIPPED", "measured_trades_per_year": 0.5}])
        _write_json(hyps_path, [{"hypothesis_name": "X", "structured_entry_rule": VALID_ENTRY, "structured_exit_plan": VALID_EXIT, "run_id": "run-1"}])

        candidates = runner.load_adam_candidates(results_path, hyps_path)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].hypothesis_name, "X")
        self.assertEqual(candidates[0].origin_agent, "adam")
        self.assertEqual(candidates[0].measured_trades_per_year, 0.5)
        self.assertEqual(candidates[0].session_id_or_run_ref, "run-1")

    def test_missing_hypothesis_record_is_skipped_not_crashed(self) -> None:
        results_path = self.tmp / "results.json"
        hyps_path = self.tmp / "hyps.json"
        _write_json(results_path, [{"hypothesis_name": "GHOST", "verdict": "DIED"}])
        _write_json(hyps_path, [])

        candidates = runner.load_adam_candidates(results_path, hyps_path)
        self.assertEqual(candidates, [])


class LoadEveCandidatesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_only_records_with_a_combined_verdict_are_candidates(self) -> None:
        path = self.tmp / "eve.json"
        _write_json(path, [
            {"raw_hypothesis": {"name": "NOT_YET_SCORED"}, "verdict_combined": None},
            {"raw_hypothesis": {"hypothesis_name": "SCORED_ONE"}, "verdict_combined": "DIED", "measured_trades_per_year": 12.0, "session_id": "eve-1"},
        ])

        candidates = runner.load_eve_candidates(path)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].hypothesis_name, "SCORED_ONE")
        self.assertEqual(candidates[0].origin_agent, "eve")
        self.assertEqual(candidates[0].measured_trades_per_year, 12.0)
        self.assertEqual(candidates[0].session_id_or_run_ref, "eve-1")


class EvaluateFreshAdmissionsTest(unittest.TestCase):
    def _candidate(self, name: str, entry=VALID_ENTRY, exit_plan=VALID_EXIT) -> runner.TrialCandidate:
        return runner.TrialCandidate(
            hypothesis_name=name, origin_agent="adam",
            hypothesis_record={"structured_entry_rule": entry, "structured_exit_plan": exit_plan},
            entry_verdict={"verdict": "DIED"}, measured_trades_per_year=10.0, session_id_or_run_ref="run-1",
        )

    def test_dsl_valid_candidate_is_admitted(self) -> None:
        attempts = runner.evaluate_fresh_admissions([self._candidate("A")], [], NOW)
        self.assertEqual(len(attempts), 1)
        self.assertTrue(attempts[0].admitted)
        self.assertIsNotNone(attempts[0].trial_record)
        self.assertEqual(attempts[0].trial_record["source_hypothesis_ref"]["hypothesis_name"], "A")

    def test_dsl_invalid_candidate_is_not_admitted(self) -> None:
        attempts = runner.evaluate_fresh_admissions([self._candidate("B", entry={"conditions": []}, exit_plan={})], [], NOW)
        self.assertFalse(attempts[0].admitted)
        self.assertIn("DSL-invalid", attempts[0].reason)

    def test_already_admitted_hypothesis_is_not_re_admitted(self) -> None:
        existing = [{"source_hypothesis_ref": {"hypothesis_name": "A"}}]
        attempts = runner.evaluate_fresh_admissions([self._candidate("A")], existing, NOW)
        self.assertFalse(attempts[0].admitted)
        self.assertIn("already admitted", attempts[0].reason)

    def test_verdict_never_gates_admission_even_when_too_slow(self) -> None:
        # item 2c's real finding: a SKIPPED/TOO_SLOW verdict must not block
        # admission -- the gate is DSL-validity alone.
        candidate = runner.TrialCandidate(
            hypothesis_name="TOO_SLOW_ONE", origin_agent="adam",
            hypothesis_record={"structured_entry_rule": VALID_ENTRY, "structured_exit_plan": VALID_EXIT},
            entry_verdict={"verdict": "SKIPPED", "frequency_classification": "TOO_SLOW"},
            measured_trades_per_year=0.5, session_id_or_run_ref=None,
        )
        attempts = runner.evaluate_fresh_admissions([candidate], [], NOW)
        self.assertTrue(attempts[0].admitted)
        self.assertIn("EXCEEDS the 2-year visibility horizon", attempts[0].trial_record["projected_time_to_min_sample_label"])


class EvaluateRepairAdmissionsTest(unittest.TestCase):
    def _survived_chain_events(self, chain_id: str, attempt_id: str) -> list[dict]:
        return [
            {"repair_chain_id": chain_id, "event": repair_lab.EVENT_CHAIN_OPENED, "original_hypothesis_name": "ORIG", "original_failure_type": "DIED", "opened_at": NOW.isoformat()},
            {
                "repair_chain_id": chain_id, "event": repair_lab.EVENT_ATTEMPT_LAUNCHED, "attempt_id": attempt_id,
                "structured_entry_rule": VALID_ENTRY, "structured_exit_plan": VALID_EXIT,
                "origin_agent": "adam", "fresh_data_method": "forward_tracking",
            },
            {
                "repair_chain_id": chain_id, "event": repair_lab.EVENT_ATTEMPT_RESOLVED, "attempt_id": attempt_id,
                "status": repair_lab.ATTEMPT_SURVIVED, "result": {"measured_trades_per_year": 25.0, "p_value_oos": 0.01},
            },
        ]

    def test_survived_attempt_is_admitted(self) -> None:
        events = self._survived_chain_events("chain-1", "attempt-1")
        attempts = runner.evaluate_repair_admissions(events, [], NOW)
        self.assertEqual(len(attempts), 1)
        self.assertTrue(attempts[0].admitted)
        self.assertEqual(attempts[0].trial_record["source_hypothesis_ref"]["repair_chain_id"], "chain-1")

    def test_already_admitted_attempt_is_not_re_admitted(self) -> None:
        events = self._survived_chain_events("chain-1", "attempt-1")
        existing = [{"source_hypothesis_ref": {"origin": "repaired", "attempt_id": "attempt-1"}}]
        attempts = runner.evaluate_repair_admissions(events, existing, NOW)
        self.assertFalse(attempts[0].admitted)
        self.assertIn("already admitted", attempts[0].reason)

    def test_died_attempt_is_never_a_trial_candidate(self) -> None:
        # A DIED repair attempt belongs in the Graveyard (item 5d), not
        # Trial -- it should never even appear as a candidate here, unlike a
        # duplicate/already-admitted SURVIVED one (which IS reported, as
        # "skipped").
        events = [
            {"repair_chain_id": "chain-2", "event": repair_lab.EVENT_CHAIN_OPENED, "original_hypothesis_name": "ORIG2", "original_failure_type": "DIED", "opened_at": NOW.isoformat()},
            {
                "repair_chain_id": "chain-2", "event": repair_lab.EVENT_ATTEMPT_LAUNCHED, "attempt_id": "attempt-2",
                "structured_entry_rule": VALID_ENTRY, "structured_exit_plan": VALID_EXIT,
                "origin_agent": "adam", "fresh_data_method": "forward_tracking",
            },
            {"repair_chain_id": "chain-2", "event": repair_lab.EVENT_ATTEMPT_RESOLVED, "attempt_id": "attempt-2", "status": repair_lab.ATTEMPT_DIED, "result": {}},
        ]
        attempts = runner.evaluate_repair_admissions(events, [], NOW)
        self.assertEqual(attempts, [])


class EvaluateDistillationCandidatesTest(unittest.TestCase):
    def test_family_at_trigger_is_reported(self) -> None:
        # evaluate_distillation_candidates is a thin pure wrapper around
        # graveyard_distillation's own loaders -- patched directly here
        # rather than faking their default file paths (those paths are
        # bound as function *default arguments* at import time, so patching
        # the module-level constant after the fact has no effect on an
        # already-defined function's defaults).
        died_records = [
            graveyard_distillation.DiedRecord(hypothesis_name=f"DEAD_{i}", mechanism="m", origin_agent="adam", matched_family="Test Family", p_value_oos=0.2)
            for i in range(3)
        ]
        with patch("nero_core.research_agent.graveyard_distillation.load_died_records", return_value=died_records), \
             patch("nero_core.research_agent.graveyard_distillation.load_died_repair_records", return_value=[]):
            ready = runner.evaluate_distillation_candidates([], [])

        self.assertEqual(ready, {"Test Family": 3})

    def test_family_below_trigger_is_not_reported(self) -> None:
        died_records = [
            graveyard_distillation.DiedRecord(hypothesis_name="ONLY_ONE", mechanism="m", origin_agent="adam", matched_family="Small Family", p_value_oos=0.2)
        ]
        with patch("nero_core.research_agent.graveyard_distillation.load_died_records", return_value=died_records), \
             patch("nero_core.research_agent.graveyard_distillation.load_died_repair_records", return_value=[]):
            ready = runner.evaluate_distillation_candidates([], [])

        self.assertEqual(ready, {})


class DraftReadyDistillationsTest(unittest.TestCase):
    """Regression guard on a real bug found and fixed 2026-08-06 (the first
    successful real distillation draft, after the API key fix): this
    function used to return a bare list[dict], silently discarding
    DistillationDraftResult.cost_usd on every call and .error entirely
    whenever a call was billed but produced no entry -- real spend that
    would vanish with no trace, and a real per-family failure
    indistinguishable from "no family was ready" at the call site."""

    def _died_records(self, family: str = "Test Family", n: int = 3) -> list:
        return [
            graveyard_distillation.DiedRecord(hypothesis_name=f"DEAD_{i}", mechanism="m", origin_agent="adam", matched_family=family, p_value_oos=0.2)
            for i in range(n)
        ]

    def test_real_cost_is_never_discarded(self) -> None:
        draft_result = graveyard_distillation.DistillationDraftResult(
            entry={"name": "X", "family": "Test Family", "review_status": "pending_human_approval"},
            usage={}, cost_usd=0.123456, error=None,
        )
        with patch("nero_core.research_agent.graveyard_distillation.load_died_records", return_value=self._died_records()), \
             patch("nero_core.research_agent.graveyard_distillation.load_died_repair_records", return_value=[]), \
             patch("nero_core.research_agent.graveyard_distillation.draft_distillation_entry", return_value=draft_result):
            result = runner.draft_ready_distillations([], [], "fake-key")

        self.assertEqual(len(result.drafts), 1)
        self.assertAlmostEqual(result.total_cost_usd, 0.123456)
        self.assertEqual(result.errors, [])

    def test_a_billed_but_failed_draft_reports_its_error_and_cost_not_silently_dropped(self) -> None:
        # The call WAS billed (cost_usd > 0) but produced no usable entry
        # (e.g. an invalid failure_pattern) -- this must be visible, not
        # indistinguishable from "no family was ready this run."
        draft_result = graveyard_distillation.DistillationDraftResult(
            entry=None, usage={}, cost_usd=0.05, error="LLM returned failure_pattern='not_a_real_one', outside the closed vocabulary",
        )
        with patch("nero_core.research_agent.graveyard_distillation.load_died_records", return_value=self._died_records()), \
             patch("nero_core.research_agent.graveyard_distillation.load_died_repair_records", return_value=[]), \
             patch("nero_core.research_agent.graveyard_distillation.draft_distillation_entry", return_value=draft_result):
            result = runner.draft_ready_distillations([], [], "fake-key")

        self.assertEqual(result.drafts, [])
        self.assertAlmostEqual(result.total_cost_usd, 0.05)
        self.assertEqual(len(result.errors), 1)
        self.assertIn("Test Family", result.errors[0])
        self.assertIn("outside the closed vocabulary", result.errors[0])

    def test_no_family_ready_costs_nothing_and_has_no_errors(self) -> None:
        with patch("nero_core.research_agent.graveyard_distillation.load_died_records", return_value=[]), \
             patch("nero_core.research_agent.graveyard_distillation.load_died_repair_records", return_value=[]):
            result = runner.draft_ready_distillations([], [], "fake-key")

        self.assertEqual(result.drafts, [])
        self.assertEqual(result.total_cost_usd, 0.0)
        self.assertEqual(result.errors, [])


class AdvanceOpenTrialsTest(unittest.TestCase):
    def test_dry_run_never_fetches_or_ticks(self) -> None:
        records = [{"trial_id": "t1", "status": trial.STATUS_OPEN, "source_hypothesis_ref": {"hypothesis_name": "X"}}]
        with patch("tools.factory_loop_run.fetch_timeframe_candles") as mock_fetch:
            outcomes = runner.advance_open_trials(records, NOW, live=False)
        mock_fetch.assert_not_called()
        self.assertEqual(len(outcomes), 1)
        self.assertFalse(outcomes[0].ticked)

    def test_non_open_records_are_never_ticked(self) -> None:
        records = [{"trial_id": "t2", "status": trial.STATUS_SURVIVED_TRIAL, "source_hypothesis_ref": {"hypothesis_name": "Y"}}]
        outcomes = runner.advance_open_trials(records, NOW, live=False)
        self.assertEqual(outcomes, [])

    def test_live_tick_uses_real_fetch_layer_and_logs_outcome(self) -> None:
        # Regression guard on the REAL bug found in this codebase's own
        # first --live run (2026-08-06): a TrialRecord (trial.TrialRecord.
        # to_dict()) never carries a "hypothesis" key -- only
        # source_hypothesis_ref.hypothesis_name. This fixture deliberately
        # matches that REAL shape (no "hypothesis" key on the record itself)
        # and resolves asset/timeframe via hypothesis_lookup instead, the
        # way a real caller (tools.factory_loop_run.main) now does.
        candles = pd.DataFrame({
            "date": pd.date_range("2026-01-01", periods=60, freq="4h", tz="UTC"),
            "open": [100.0] * 60, "high": [101.0] * 60, "low": [99.0] * 60, "close": [100.0] * 60, "volume": [10.0] * 60,
        })
        records = [{"trial_id": "t3", "status": trial.STATUS_OPEN, "source_hypothesis_ref": {"hypothesis_name": "Z"}}]
        hypothesis_lookup = {"Z": {"asset": "BTC", "timeframe": "4h", "structured_entry_rule": VALID_ENTRY, "structured_exit_plan": VALID_EXIT}}
        with patch("tools.factory_loop_run.fetch_timeframe_candles", return_value=(candles, "NATIVE: test")) as mock_fetch, \
             patch("nero_core.research_agent.trial.run_forward_tick") as mock_tick, \
             patch("nero_core.research_agent.trial.compute_forward_verdict", return_value=None):
            mock_tick.return_value = type("R", (), {"signal_type": "NO_TRADE"})()
            outcomes = runner.advance_open_trials(records, NOW, live=True, hypothesis_lookup=hypothesis_lookup)

        mock_fetch.assert_called_once()
        self.assertTrue(outcomes[0].ticked)
        self.assertIn("PENDING_FORWARD_DATA", outcomes[0].reason)

    def test_hypothesis_not_in_lookup_is_reported_not_crashed(self) -> None:
        # The exact real scenario the 2026-08-06 bug produced: 8 real,
        # freshly-admitted OPEN records with no matching lookup entry (an
        # empty/wrong lookup, e.g. the caller forgot to build it) must
        # degrade to a clear per-record reason, never a crash or a silent
        # skip.
        records = [{"trial_id": "t4", "status": trial.STATUS_OPEN, "source_hypothesis_ref": {"hypothesis_name": "UNKNOWN_NAME"}}]
        with patch("tools.factory_loop_run.fetch_timeframe_candles") as mock_fetch:
            outcomes = runner.advance_open_trials(records, NOW, live=True, hypothesis_lookup={})
        mock_fetch.assert_not_called()
        self.assertFalse(outcomes[0].ticked)
        self.assertIn("no hypothesis record found", outcomes[0].reason)

    def test_repaired_record_resolves_via_stripped_original_hypothesis_name(self) -> None:
        # CC-1 DIRECTIVE (2026-08-07, Part A) regression guard: a repaired
        # record's real hypothesis_name is "<original>__REPAIR_<attempt_id>"
        # (repair_to_trial.admit_repair_to_trial's own construction) and its
        # source_hypothesis_ref carries origin=ORIGIN_REPAIRED (set
        # unconditionally by trial.admit_to_trial) -- hypothesis_lookup itself
        # is keyed by the ORIGINAL, unsuffixed name (Adam/Eve's own raw
        # candidate names), exactly as it would really be built from
        # load_adam_candidates()/load_eve_candidates(). Before this fix, this
        # record would have been reported "no hypothesis record found" and
        # never ticked at all, forever.
        candles = pd.DataFrame({
            "date": pd.date_range("2026-01-01", periods=60, freq="4h", tz="UTC"),
            "open": [100.0] * 60, "high": [101.0] * 60, "low": [99.0] * 60, "close": [100.0] * 60, "volume": [10.0] * 60,
        })
        records = [{
            "trial_id": "t5", "status": trial.STATUS_OPEN,
            "source_hypothesis_ref": {
                "origin": trial.ORIGIN_REPAIRED, "hypothesis_name": "ORIGINAL_HYP__REPAIR_A1",
                "repair_chain_id": "chain-1", "attempt_id": "A1",
            },
        }]
        hypothesis_lookup = {"ORIGINAL_HYP": {"asset": "BTC", "timeframe": "4h", "structured_entry_rule": VALID_ENTRY, "structured_exit_plan": VALID_EXIT}}
        with patch("tools.factory_loop_run.fetch_timeframe_candles", return_value=(candles, "NATIVE: test")) as mock_fetch, \
             patch("nero_core.research_agent.trial.run_forward_tick") as mock_tick, \
             patch("nero_core.research_agent.trial.compute_forward_verdict", return_value=None):
            mock_tick.return_value = type("R", (), {"signal_type": "NO_TRADE"})()
            outcomes = runner.advance_open_trials(records, NOW, live=True, hypothesis_lookup=hypothesis_lookup)

        mock_fetch.assert_called_once_with(ANY, "BTC", "4h")
        self.assertTrue(outcomes[0].ticked)
        self.assertIn("PENDING_FORWARD_DATA", outcomes[0].reason)
        # run_forward_tick must receive the RESOLVED hypothesis dict (asset/
        # timeframe/structured fields), not an empty one -- proves the fix
        # actually reaches the tick, not just avoids the "not found" branch.
        mock_tick.assert_called_once_with("t5", hypothesis_lookup["ORIGINAL_HYP"], candles, NOW)

    def test_repaired_record_advances_open_to_survived_exactly_like_a_fresh_record(self) -> None:
        # A3: the repaired record's forward ticks must advance it through the
        # SAME real status machine a fresh record uses -- trial.py's own
        # real model is OPEN -> (SURVIVED_TRIAL | FAILED_TRIAL), a 2-outcome
        # terminal transition (see trial.py:74-76: STATUS_OPEN,
        # STATUS_SURVIVED_TRIAL, STATUS_FAILED_TRIAL -- there is no separate
        # EARLY_POSITIVE/PROMISING status constant in the real code). This
        # proves that once compute_forward_verdict returns a real verdict,
        # update_trial_status is invoked with the correct terminal status for
        # a repaired-origin record exactly as it would be for a fresh one.
        candles = pd.DataFrame({
            "date": pd.date_range("2026-01-01", periods=60, freq="4h", tz="UTC"),
            "open": [100.0] * 60, "high": [101.0] * 60, "low": [99.0] * 60, "close": [100.0] * 60, "volume": [10.0] * 60,
        })
        records = [{
            "trial_id": "t6", "status": trial.STATUS_OPEN,
            "source_hypothesis_ref": {
                "origin": trial.ORIGIN_REPAIRED, "hypothesis_name": "ORIGINAL_HYP__REPAIR_A2",
                "repair_chain_id": "chain-1", "attempt_id": "A2",
            },
        }]
        hypothesis_lookup = {"ORIGINAL_HYP": {"asset": "BTC", "timeframe": "4h", "structured_entry_rule": VALID_ENTRY, "structured_exit_plan": VALID_EXIT}}
        with patch("tools.factory_loop_run.fetch_timeframe_candles", return_value=(candles, "NATIVE: test")), \
             patch("nero_core.research_agent.trial.run_forward_tick") as mock_tick, \
             patch("nero_core.research_agent.trial.compute_forward_verdict", return_value={"verdict": "SURVIVED_TRIAL", "reason": "2x MIN_SAMPLE_SIZE reached, positive"}), \
             patch("nero_core.research_agent.trial.update_trial_status") as mock_update_status:
            mock_tick.return_value = type("R", (), {"signal_type": "EXIT"})()
            outcomes = runner.advance_open_trials(records, NOW, live=True, hypothesis_lookup=hypothesis_lookup)

        mock_update_status.assert_called_once_with("t6", trial.STATUS_SURVIVED_TRIAL)
        self.assertTrue(outcomes[0].ticked)
        self.assertIn("RESOLVED -> SURVIVED_TRIAL", outcomes[0].reason)

    def test_repaired_record_can_resolve_to_failed_trial_exactly_like_a_fresh_record(self) -> None:
        candles = pd.DataFrame({
            "date": pd.date_range("2026-01-01", periods=60, freq="4h", tz="UTC"),
            "open": [100.0] * 60, "high": [101.0] * 60, "low": [99.0] * 60, "close": [100.0] * 60, "volume": [10.0] * 60,
        })
        records = [{
            "trial_id": "t7", "status": trial.STATUS_OPEN,
            "source_hypothesis_ref": {
                "origin": trial.ORIGIN_REPAIRED, "hypothesis_name": "ORIGINAL_HYP__REPAIR_A3",
                "repair_chain_id": "chain-1", "attempt_id": "A3",
            },
        }]
        hypothesis_lookup = {"ORIGINAL_HYP": {"asset": "BTC", "timeframe": "4h", "structured_entry_rule": VALID_ENTRY, "structured_exit_plan": VALID_EXIT}}
        with patch("tools.factory_loop_run.fetch_timeframe_candles", return_value=(candles, "NATIVE: test")), \
             patch("nero_core.research_agent.trial.run_forward_tick") as mock_tick, \
             patch("nero_core.research_agent.trial.compute_forward_verdict", return_value={"verdict": "DIED", "reason": "negative expectancy at 2x MIN_SAMPLE_SIZE"}), \
             patch("nero_core.research_agent.trial.update_trial_status") as mock_update_status:
            mock_tick.return_value = type("R", (), {"signal_type": "EXIT"})()
            outcomes = runner.advance_open_trials(records, NOW, live=True, hypothesis_lookup=hypothesis_lookup)

        mock_update_status.assert_called_once_with("t7", trial.STATUS_FAILED_TRIAL)
        self.assertIn("RESOLVED -> FAILED_TRIAL", outcomes[0].reason)


class BuildReportTest(unittest.TestCase):
    def test_dry_run_label_appears(self) -> None:
        report = runner.build_report([], [], {}, [], live=False)
        self.assertIn("DRY-RUN", report)

    def test_live_label_appears(self) -> None:
        report = runner.build_report([], [], {}, [], live=True)
        self.assertIn("LIVE", report)


if __name__ == "__main__":
    unittest.main()
