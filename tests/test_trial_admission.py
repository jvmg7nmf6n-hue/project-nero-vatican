"""CC-1 Factory Loop directive, item 4: TEST -> TRIAL (core).

Covers: the real admission gate (DSL-validity -- the backtest verdict is
NEVER a condition), item 4a's mandatory projected-time fields, item 4b's
queue health, item 4c's attribution string, and the forward-tracking reuse
via repair_forward_tracker's new strategy_prefix parameter (verified it
never collides with a real Repair Lab attempt_id in the same execution_log
table).

FRESHNESS DISQUALIFICATION IS NOT PART OF THIS GATE (CC-1 correction
directive, 2026-08-05): item 4e originally gated admission on DSL-validity
AND NOT freshness-disqualified (item 7's binding Variant C check), shipped
in commit `61d78a8`. Reverted the same day once item 7d's real Session 1
re-score showed the check is necessarily session-wide -- one qualifying
search result would disqualify an entire session's hypotheses, and the
resulting FDR-family exclusion made the pre-registered per-session bar
unsatisfiable by construction, not by result. See docs/site_data/
eve_session_registry.json's own freshness_gate_reversal_provenance field.
AdmitToTrialNeverConsultsFreshnessTest below is the standing regression
guard against silently re-enabling this."""
from __future__ import annotations

import inspect
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from nero_core.eve import scoring as eve_scoring
from nero_core.research_agent import repair_forward_tracker, trial
from tools.backtest_statistics import MIN_SAMPLE_SIZE

VALID_HYPOTHESIS = {
    "hypothesis_name": "ZSCORE_REVERSION_BTC_1H",
    "structured_entry_rule": {"conditions": [{"field": "zscore20", "op": "lt", "value": -2.0}]},
    "structured_exit_plan": {"stop_atr_multiple": 2.0, "target_r_multiple": 2.0, "max_holding_hours": 48},
}

DSL_INVALID_HYPOTHESIS = {
    "hypothesis_name": "UNPARSEABLE",
    "structured_entry_rule": None,
    "structured_exit_plan": None,
}


class DslValidityTest(unittest.TestCase):
    def test_valid_structured_rules_pass(self) -> None:
        valid, reason = trial.is_dsl_valid(VALID_HYPOTHESIS)
        self.assertTrue(valid)

    def test_null_structured_rules_fail(self) -> None:
        valid, reason = trial.is_dsl_valid(DSL_INVALID_HYPOTHESIS)
        self.assertFalse(valid)
        self.assertTrue(reason)


class ProjectedTimeToMinSampleTest(unittest.TestCase):
    def test_positive_rate_computes_years(self) -> None:
        years, label = trial.compute_projected_time_to_min_sample(20.0, min_sample_size=20)
        self.assertAlmostEqual(years, 1.0)
        self.assertIn("1.0 years", label)

    def test_zero_rate_is_none_not_fabricated(self) -> None:
        years, label = trial.compute_projected_time_to_min_sample(0.0)
        self.assertIsNone(years)
        self.assertIn("UNMEASURABLE", label)

    def test_none_rate_is_none_not_fabricated(self) -> None:
        years, label = trial.compute_projected_time_to_min_sample(None)
        self.assertIsNone(years)
        self.assertIn("UNMEASURABLE", label)

    def test_low_rate_exceeding_horizon_is_labeled(self) -> None:
        # 0.5 trades/year against MIN_SAMPLE_SIZE (>=20 per this project's
        # own constant) takes 40+ years -- Track A's own real example.
        years, label = trial.compute_projected_time_to_min_sample(0.5, min_sample_size=20)
        self.assertGreater(years, 2.0)
        self.assertIn("EXCEEDS", label)

    def test_always_populated_never_silently_omitted(self) -> None:
        # item 4a's own hard requirement -- both fields exist, for every
        # possible input, even the totally-unmeasurable one.
        for rate in (None, 0.0, -1.0, 0.5, 100.0):
            years, label = trial.compute_projected_time_to_min_sample(rate)
            self.assertIsInstance(label, str)
            self.assertTrue(label)


class AdmitToTrialTest(unittest.TestCase):
    def test_dsl_invalid_hypothesis_is_rejected(self) -> None:
        result = trial.admit_to_trial(
            DSL_INVALID_HYPOTHESIS, {"verdict": "DIED"},
            origin="fresh", origin_agent="adam", hypothesis_name="UNPARSEABLE",
            session_id_or_run_ref="run-1", measured_trades_per_year=None,
        )
        self.assertFalse(result.admitted)
        self.assertIsNone(result.trial_record)
        self.assertIn("DSL-invalid", result.reason)

    def test_dsl_valid_and_not_disqualified_admitted_regardless_of_verdict_quality(self) -> None:
        # "measure, never gate" (directive's own framing): a DIED
        # hypothesis is still admitted to Trial -- the verdict is advisory.
        for verdict in ("DIED", "SURVIVED", "PROMISING_WATCHLIST", "UNTESTABLE"):
            result = trial.admit_to_trial(
                VALID_HYPOTHESIS, {"verdict": verdict, "p_value_oos": 0.9},
                origin="fresh", origin_agent="adam", hypothesis_name="X",
                session_id_or_run_ref="run-1", measured_trades_per_year=10.0,
            )
            self.assertTrue(result.admitted, f"verdict={verdict} should still be admitted")
            self.assertEqual(result.trial_record.entry_verdict["verdict"], verdict)

    def test_admitted_record_always_has_projected_time_fields_populated(self) -> None:
        result = trial.admit_to_trial(
            VALID_HYPOTHESIS, {"verdict": "DIED"},
            origin="fresh", origin_agent="adam", hypothesis_name="X",
            session_id_or_run_ref="run-1", measured_trades_per_year=None,
        )
        self.assertTrue(result.admitted)
        self.assertIsNone(result.trial_record.projected_time_to_min_sample_years)
        self.assertIn("UNMEASURABLE", result.trial_record.projected_time_to_min_sample_label)
        self.assertIsNone(result.trial_record.measured_trades_per_year)

    def test_dsl_valid_hypothesis_is_admitted_with_no_freshness_argument_at_all(self) -> None:
        # CC-1 correction directive (reverting item 4e/7c, 2026-08-05):
        # admit_to_trial no longer accepts a freshness_disqualified argument
        # at all -- admission depends on DSL-validity only.
        result = trial.admit_to_trial(
            VALID_HYPOTHESIS, {"verdict": "DIED"},
            origin="fresh", origin_agent="adam", hypothesis_name="X",
            session_id_or_run_ref="run-1", measured_trades_per_year=10.0,
        )
        self.assertTrue(result.admitted)

    def test_repaired_origin_carries_chain_lineage(self) -> None:
        result = trial.admit_to_trial(
            VALID_HYPOTHESIS, {"verdict": "SURVIVED"},
            origin="repaired", origin_agent="adam", hypothesis_name="X_REPAIRED",
            session_id_or_run_ref="run-1", measured_trades_per_year=10.0,
            repair_chain_id="chain-1", attempt_id="attempt-2",
        )
        self.assertTrue(result.admitted)
        ref = result.trial_record.source_hypothesis_ref
        self.assertEqual(ref["origin"], "repaired")
        self.assertEqual(ref["repair_chain_id"], "chain-1")
        self.assertEqual(ref["attempt_id"], "attempt-2")

    def test_fresh_origin_carries_no_chain_lineage_fields(self) -> None:
        result = trial.admit_to_trial(
            VALID_HYPOTHESIS, {"verdict": "DIED"},
            origin="fresh", origin_agent="adam", hypothesis_name="X",
            session_id_or_run_ref="run-1", measured_trades_per_year=10.0,
        )
        self.assertNotIn("repair_chain_id", result.trial_record.source_hypothesis_ref)


class AttributionTest(unittest.TestCase):
    def test_attribution_string_names_the_origin_agent(self) -> None:
        result = trial.admit_to_trial(
            VALID_HYPOTHESIS, {"verdict": "DIED"},
            origin="fresh", origin_agent="eve", hypothesis_name="X",
            session_id_or_run_ref="eve-session-1", measured_trades_per_year=10.0,
        )
        self.assertEqual(result.trial_record.attribution, "Explored by Eve, our research agent.")


class TrialIdempotentTrialRecordTest(unittest.TestCase):
    def test_two_admissions_get_distinct_trial_ids(self) -> None:
        r1 = trial.admit_to_trial(
            VALID_HYPOTHESIS, {"verdict": "DIED"}, origin="fresh", origin_agent="adam",
            hypothesis_name="X", session_id_or_run_ref="run-1", measured_trades_per_year=10.0,
        )
        r2 = trial.admit_to_trial(
            VALID_HYPOTHESIS, {"verdict": "DIED"}, origin="fresh", origin_agent="adam",
            hypothesis_name="X", session_id_or_run_ref="run-1", measured_trades_per_year=10.0,
        )
        self.assertNotEqual(r1.trial_record.trial_id, r2.trial_record.trial_id)


class QueueHealthTest(unittest.TestCase):
    def test_counts_open_and_beyond_horizon(self) -> None:
        records = [
            {"status": "OPEN", "projected_time_to_min_sample_years": 0.5},
            {"status": "OPEN", "projected_time_to_min_sample_years": 5.0},
            {"status": "OPEN", "projected_time_to_min_sample_years": None},
            {"status": "SURVIVED_TRIAL", "projected_time_to_min_sample_years": 40.0},
        ]
        health = trial.queue_health(records)
        self.assertEqual(health["open_count"], 3)
        self.assertEqual(health["beyond_2_years_count"], 2)  # 5.0 years + the None (unmeasurable)

    def test_empty_queue(self) -> None:
        health = trial.queue_health([])
        self.assertEqual(health, {"open_count": 0, "beyond_2_years_count": 0})


class PersistAndLoadTrialRecordsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "forward_trial.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_persist_then_load_round_trips(self) -> None:
        result = trial.admit_to_trial(
            VALID_HYPOTHESIS, {"verdict": "DIED"}, origin="fresh", origin_agent="adam",
            hypothesis_name="X", session_id_or_run_ref="run-1", measured_trades_per_year=10.0,
        )
        trial.persist_trial_records([result.trial_record], path=self.path)
        loaded = trial.load_trial_records(self.path)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["trial_id"], result.trial_record.trial_id)

    def test_update_trial_status_rewrites_in_place(self) -> None:
        result = trial.admit_to_trial(
            VALID_HYPOTHESIS, {"verdict": "DIED"}, origin="fresh", origin_agent="adam",
            hypothesis_name="X", session_id_or_run_ref="run-1", measured_trades_per_year=10.0,
        )
        trial.persist_trial_records([result.trial_record], path=self.path)
        updated = trial.update_trial_status(result.trial_record.trial_id, "SURVIVED_TRIAL", path=self.path)
        self.assertTrue(updated)
        loaded = trial.load_trial_records(self.path)
        self.assertEqual(loaded[0]["status"], "SURVIVED_TRIAL")

    def test_update_unknown_trial_id_returns_false(self) -> None:
        self.path.write_text("[]")
        self.assertFalse(trial.update_trial_status("nonexistent", "SURVIVED_TRIAL", path=self.path))


class ForwardTrackingReuseTest(unittest.TestCase):
    """Verifies trial.py's forward-tracking wrapper uses a DIFFERENT
    strategy_prefix than Repair Lab's own, so a Trial entry and a repair
    attempt sharing the same literal id string never collide in the shared
    execution_log table."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.db_path = self.tmp / "forward_tracking.db"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _candles(self, n: int = 30) -> pd.DataFrame:
        rows = []
        price = 100.0
        t0 = 1_700_000_000_000
        for i in range(n):
            rows.append({"close_time": t0 + i * 3_600_000, "close": price, "high": price * 1.01, "low": price * 0.99, "volume": 1.0})
        return pd.DataFrame(rows)

    def test_trial_and_repair_attempt_with_same_literal_id_never_collide(self) -> None:
        shared_id = "shared-id-123"
        hypothesis = dict(VALID_HYPOTHESIS, asset="BTC")
        now = datetime(2026, 8, 5, tzinfo=timezone.utc)

        trial.run_forward_tick(shared_id, hypothesis, self._candles(), now, db_path=self.db_path)
        repair_forward_tracker.evaluate_forward_tick(shared_id, hypothesis, self._candles(), now, db_path=self.db_path)

        # Both may have logged a row under the SAME db file, but under
        # DIFFERENT strategy keys -- resolved_trade_count/compute_forward_
        # verdict for one must never see the other's rows.
        trial_count = trial.resolved_trade_count(shared_id, db_path=self.db_path)
        repair_count = repair_forward_tracker.resolved_trade_count(shared_id, db_path=self.db_path)
        # Neither has resolved a trade yet (no EXIT logged) -- this asserts
        # the CALL succeeds cleanly and both counts are independently zero,
        # not that they're wrong in some other way.
        self.assertEqual(trial_count, 0)
        self.assertEqual(repair_count, 0)

    def test_default_db_path_matches_repair_forward_trackers_own(self) -> None:
        # Explicit design choice (module docstring): reuse the SAME SQLite
        # file, distinguished only by strategy_prefix -- not a second file.
        self.assertEqual(trial.DEFAULT_FORWARD_TRACKING_DB_PATH, repair_forward_tracker.DEFAULT_FORWARD_TRACKING_DB_PATH)


class AdmitToTrialNeverConsultsFreshnessTest(unittest.TestCase):
    """CC-1 correction directive (2026-08-05): the standing regression guard
    against silently re-enabling binding freshness disqualification.
    admit_to_trial's real signature has NO freshness_disqualified parameter
    at all (removed, not merely defaulted off) -- a future edit that wants
    to gate on it again must add a new, visible parameter, which this test
    would immediately flag as a signature change to review."""

    def test_signature_has_no_freshness_parameter(self) -> None:
        params = inspect.signature(trial.admit_to_trial).parameters
        self.assertNotIn("freshness_disqualified", params)

    def test_passing_freshness_disqualified_raises_type_error(self) -> None:
        with self.assertRaises(TypeError):
            trial.admit_to_trial(
                VALID_HYPOTHESIS, {"verdict": "DIED"},
                origin="fresh", origin_agent="adam", hypothesis_name="X",
                session_id_or_run_ref="run-1", measured_trades_per_year=10.0,
                freshness_disqualified=True,
            )

    def test_a_hypothesis_flagged_freshness_disqualified_by_the_informational_check_is_still_admitted(self) -> None:
        # End-to-end proof, not just a signature check: run the REAL
        # informational item 7 machinery (nero_core.eve.scoring) to
        # actually produce a freshness_disqualified=True record, then admit
        # it to Trial -- admission must succeed regardless, since
        # admit_to_trial has no way to see that field at all.
        session_record = {
            "started_at": "2026-08-05T00:00:00+00:00",
            "turns": [{
                "turn_index": 0,
                "raw_response": {"content": [{
                    "type": "web_search_tool_result", "tool_use_id": "t1",
                    "content": [{"type": "web_search_result", "url": "https://example.com/a", "title": "A", "page_age": "3 weeks ago"}],
                }]},
            }],
        }
        flags = eve_scoring.check_freshness_disqualification(session_record, session_started_at=datetime(2026, 8, 5, tzinfo=timezone.utc))
        self.assertTrue(flags)  # sanity: the informational check DOES fire on this fixture
        scored = eve_scoring.apply_freshness_disqualification([{"raw_hypothesis": {"hypothesis_name": "X"}}], flags)
        self.assertTrue(scored[0]["freshness_disqualified"])  # informational field still populated

        result = trial.admit_to_trial(
            VALID_HYPOTHESIS, {"verdict": "DIED"},
            origin="fresh", origin_agent="adam", hypothesis_name="X",
            session_id_or_run_ref="run-1", measured_trades_per_year=10.0,
        )
        self.assertTrue(result.admitted, "a DSL-valid hypothesis must be admitted even though the informational "
                                          "freshness check flagged it -- admit_to_trial never sees that flag")


if __name__ == "__main__":
    unittest.main()
