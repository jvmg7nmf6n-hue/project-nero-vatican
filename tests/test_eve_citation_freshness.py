"""CC-1 directive (2026-08-05): per-hypothesis freshness attribution via
explicit source citation.

Covers: item 1 (supporting_source_urls always present, validated against
real session search data, and -- CRITICALLY -- never a DSL-validity or
Trial-admission requirement), item 2 (per-hypothesis freshness attribution,
distinct from check_freshness_disqualification's session-wide check), item 5
(pre-citation records marked, never fabricated), item 6 (the incentive
analysis's own structural claim: scoring never feeds back into session
context), and item 7 (still strictly informational -- no bar constant
touched, no new binding path)."""
from __future__ import annotations

import inspect
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from nero_core.eve import hypothesis_shapes, scoring, storage
from nero_core.research_agent import trial
from tools import backfill_eve_pre_citation_status as backfill_mod

VALID_RAW = {
    "hypothesis_name": "ZSCORE_REVERSION_BTC_1H",
    "structured_entry_rule": {"conditions": [{"field": "zscore20", "op": "lt", "value": -2.0}]},
    "structured_exit_plan": {"stop_atr_multiple": 2.0, "target_r_multiple": 2.0, "max_holding_hours": 48},
}


def _session_record(started_at: str, search_results: list[dict]) -> dict:
    """search_results: list of {"url": ..., "page_age": ...}"""
    return {
        "started_at": started_at,
        "turns": [
            {
                "turn_index": 0,
                "raw_response": {
                    "content": [
                        {
                            "type": "web_search_tool_result",
                            "tool_use_id": "srvtoolu_1",
                            "content": [
                                {"type": "web_search_result", "url": r["url"], "title": "x", "page_age": r["page_age"]}
                                for r in search_results
                            ],
                        }
                    ]
                },
            }
        ],
    }


class SupportingSourceUrlsNeverGatesDslOrTrialTest(unittest.TestCase):
    """item 1's CRITICAL requirement: a hypothesis with an empty (or
    entirely missing) supporting_source_urls must remain DSL-valid and
    Trial-admissible -- the exact validation path checked is classify_
    testability (nero_core.eve.scoring, the same parser session.py's
    pre-submit validator and scoring.score_hypothesis both use) and
    trial.is_dsl_valid / trial.admit_to_trial (nero_core.research_agent.trial,
    item 4's real admission gate)."""

    def test_missing_supporting_source_urls_key_is_still_testable(self) -> None:
        raw = dict(VALID_RAW)
        self.assertNotIn("supporting_source_urls", raw)
        testability, _ = scoring.classify_testability(raw)
        self.assertEqual(testability, scoring.TESTABILITY_TESTABLE)

    def test_empty_supporting_source_urls_is_still_testable(self) -> None:
        raw = {**VALID_RAW, "supporting_source_urls": []}
        testability, _ = scoring.classify_testability(raw)
        self.assertEqual(testability, scoring.TESTABILITY_TESTABLE)

    def test_built_record_normalizes_missing_supporting_source_urls_to_empty_list(self) -> None:
        record = hypothesis_shapes.build_hypothesis_record(VALID_RAW, session_id="s1", turn_index=0, tool_use_id="t1")
        self.assertEqual(record["supporting_source_urls"], [])
        # raw_hypothesis itself stays byte-verbatim except generated_at --
        # the field is never injected there (see hypothesis_shapes's own
        # docstring on why that must stay the ONE deliberate exception).
        self.assertNotIn("supporting_source_urls", record["raw_hypothesis"])

    def test_missing_supporting_source_urls_is_still_trial_admissible(self) -> None:
        dsl_valid, _ = trial.is_dsl_valid(VALID_RAW)
        self.assertTrue(dsl_valid)
        result = trial.admit_to_trial(
            VALID_RAW, {"verdict": "DIED"}, origin="fresh", origin_agent="eve",
            hypothesis_name="ZSCORE_REVERSION_BTC_1H", session_id_or_run_ref="s1",
            measured_trades_per_year=40.0,
        )
        self.assertTrue(result.admitted)

    def test_empty_supporting_source_urls_is_still_trial_admissible(self) -> None:
        raw = {**VALID_RAW, "supporting_source_urls": []}
        result = trial.admit_to_trial(
            raw, {"verdict": "DIED"}, origin="fresh", origin_agent="eve",
            hypothesis_name="ZSCORE_REVERSION_BTC_1H", session_id_or_run_ref="s1",
            measured_trades_per_year=40.0,
        )
        self.assertTrue(result.admitted)

    def test_admit_to_trial_signature_has_no_citation_parameter(self) -> None:
        # Same standing-regression-guard shape as AdmitToTrialNeverConsultsFreshnessTest
        # in test_trial_admission.py -- confirms this directive did not
        # introduce a second back door into the admission gate.
        params = inspect.signature(trial.admit_to_trial).parameters
        self.assertNotIn("citation_status", params)
        self.assertNotIn("supporting_source_urls", params)
        self.assertNotIn("per_hypothesis_freshness", params)


class ValidateSupportingSourceUrlsTest(unittest.TestCase):
    def test_url_present_in_session_search_results_is_valid(self) -> None:
        session = _session_record("2026-08-05T00:00:00+00:00", [{"url": "https://real.example/a", "page_age": "February 1, 2026"}])
        valid, invalid = scoring.validate_supporting_source_urls(
            ["https://real.example/a"], session, datetime(2026, 8, 5, tzinfo=timezone.utc)
        )
        self.assertEqual(valid, ["https://real.example/a"])
        self.assertEqual(invalid, [])

    def test_url_never_returned_by_a_search_this_session_is_a_hard_validation_error(self) -> None:
        session = _session_record("2026-08-05T00:00:00+00:00", [{"url": "https://real.example/a", "page_age": "February 1, 2026"}])
        valid, invalid = scoring.validate_supporting_source_urls(
            ["https://fabricated.example/never-searched"], session, datetime(2026, 8, 5, tzinfo=timezone.utc)
        )
        self.assertEqual(valid, [])
        self.assertEqual(invalid, ["https://fabricated.example/never-searched"])

    def test_mix_of_valid_and_invalid_urls_are_split_correctly(self) -> None:
        session = _session_record("2026-08-05T00:00:00+00:00", [{"url": "https://real.example/a", "page_age": "February 1, 2026"}])
        valid, invalid = scoring.validate_supporting_source_urls(
            ["https://real.example/a", "https://fake.example/b"], session, datetime(2026, 8, 5, tzinfo=timezone.utc)
        )
        self.assertEqual(valid, ["https://real.example/a"])
        self.assertEqual(invalid, ["https://fake.example/b"])


class ClassifyCitationStatusTest(unittest.TestCase):
    def test_no_searches_in_session(self) -> None:
        session = _session_record("2026-08-05T00:00:00+00:00", [])
        record = {"supporting_source_urls": []}
        result = scoring.classify_citation_status(record, session, datetime(2026, 8, 5, tzinfo=timezone.utc))
        self.assertEqual(result["citation_status"], scoring.CITATION_STATUS_NO_SEARCHES)

    def test_no_sources_claimed_when_searches_happened_but_hypothesis_cites_nothing(self) -> None:
        session = _session_record("2026-08-05T00:00:00+00:00", [{"url": "https://real.example/a", "page_age": "February 1, 2026"}])
        record = {"supporting_source_urls": []}
        result = scoring.classify_citation_status(record, session, datetime(2026, 8, 5, tzinfo=timezone.utc))
        self.assertEqual(result["citation_status"], scoring.CITATION_STATUS_NO_SOURCES_CLAIMED)

    def test_cited_when_at_least_one_valid_url_is_claimed(self) -> None:
        session = _session_record("2026-08-05T00:00:00+00:00", [{"url": "https://real.example/a", "page_age": "February 1, 2026"}])
        record = {"supporting_source_urls": ["https://real.example/a"]}
        result = scoring.classify_citation_status(record, session, datetime(2026, 8, 5, tzinfo=timezone.utc))
        self.assertEqual(result["citation_status"], scoring.CITATION_STATUS_CITED)

    def test_only_invalid_urls_claimed_falls_back_to_no_sources_claimed(self) -> None:
        # After validation strips the fabricated URL, nothing real remains
        # cited -- citation_status reflects the VALIDATED list, while
        # supporting_source_urls_invalid still separately records the error.
        session = _session_record("2026-08-05T00:00:00+00:00", [{"url": "https://real.example/a", "page_age": "February 1, 2026"}])
        record = {"supporting_source_urls": ["https://fake.example/b"]}
        result = scoring.classify_citation_status(record, session, datetime(2026, 8, 5, tzinfo=timezone.utc))
        self.assertEqual(result["citation_status"], scoring.CITATION_STATUS_NO_SOURCES_CLAIMED)
        self.assertEqual(result["supporting_source_urls_invalid"], ["https://fake.example/b"])

    def test_classify_citation_status_never_returns_pre_citation(self) -> None:
        # unscoreable_pre_citation is exclusively a backfill-migration value
        # -- a record run through this live classifier always has the
        # mechanism available and can never land there.
        session = _session_record("2026-08-05T00:00:00+00:00", [])
        for claimed in ([], ["https://x"]):
            result = scoring.classify_citation_status({"supporting_source_urls": claimed}, session, datetime(2026, 8, 5, tzinfo=timezone.utc))
            self.assertNotEqual(result["citation_status"], scoring.CITATION_STATUS_UNSCOREABLE_PRE_CITATION)


class CheckPerHypothesisFreshnessTest(unittest.TestCase):
    def test_nothing_to_check_when_no_sources_claimed(self) -> None:
        session = _session_record("2026-08-05T00:00:00+00:00", [{"url": "https://real.example/a", "page_age": "3 weeks ago"}])
        record = {"raw_hypothesis": {"hypothesis_name": "H1"}, "supporting_source_urls": []}
        result = scoring.check_per_hypothesis_freshness(record, session, datetime(2026, 8, 5, tzinfo=timezone.utc))
        self.assertEqual(result["per_hypothesis_freshness"]["result"], scoring.PER_HYPOTHESIS_FRESHNESS_NOTHING_TO_CHECK)

    def test_checked_clean_when_cited_source_predates_the_freshness_window(self) -> None:
        session = _session_record("2026-08-05T00:00:00+00:00", [{"url": "https://real.example/old", "page_age": "February 1, 2026"}])
        record = {"raw_hypothesis": {"hypothesis_name": "H1"}, "supporting_source_urls": ["https://real.example/old"]}
        result = scoring.check_per_hypothesis_freshness(record, session, datetime(2026, 8, 5, tzinfo=timezone.utc))
        self.assertEqual(result["per_hypothesis_freshness"]["result"], scoring.PER_HYPOTHESIS_FRESHNESS_CHECKED_CLEAN)

    def test_checked_disqualified_when_cited_source_is_within_the_freshness_window(self) -> None:
        session = _session_record("2026-08-05T00:00:00+00:00", [{"url": "https://real.example/recent", "page_age": "3 weeks ago"}])
        record = {"raw_hypothesis": {"hypothesis_name": "H1"}, "supporting_source_urls": ["https://real.example/recent"]}
        result = scoring.check_per_hypothesis_freshness(record, session, datetime(2026, 8, 5, tzinfo=timezone.utc))
        freshness = result["per_hypothesis_freshness"]
        self.assertEqual(freshness["result"], scoring.PER_HYPOTHESIS_FRESHNESS_CHECKED_DISQUALIFIED)
        self.assertEqual(freshness["offending_source_url"], "https://real.example/recent")
        self.assertEqual(freshness["rule_fired"], scoring.FRESHNESS_DISQUALIFICATION_RULE)
        self.assertIsNotNone(freshness["parsed_pub_date"])
        self.assertEqual(freshness["hypothesis_name"], "H1")

    def test_per_hypothesis_attribution_is_narrower_than_the_session_wide_check(self) -> None:
        # The core point of item 2: in a session with ONE recent search
        # result, the session-wide check flags EVERY hypothesis, but the
        # per-hypothesis check only flags the one that actually cited it.
        session = _session_record(
            "2026-08-05T00:00:00+00:00",
            [{"url": "https://real.example/recent", "page_age": "3 weeks ago"}],
        )
        session_started_at = datetime(2026, 8, 5, tzinfo=timezone.utc)

        session_wide_flags = scoring.check_freshness_disqualification(session, session_started_at)
        self.assertEqual(len(session_wide_flags), 1)  # session-wide: this session IS flagged

        cited_record = {"raw_hypothesis": {"hypothesis_name": "CITED"}, "supporting_source_urls": ["https://real.example/recent"]}
        uncited_record = {"raw_hypothesis": {"hypothesis_name": "UNCITED"}, "supporting_source_urls": []}

        cited_result = scoring.check_per_hypothesis_freshness(cited_record, session, session_started_at)
        uncited_result = scoring.check_per_hypothesis_freshness(uncited_record, session, session_started_at)

        self.assertEqual(cited_result["per_hypothesis_freshness"]["result"], scoring.PER_HYPOTHESIS_FRESHNESS_CHECKED_DISQUALIFIED)
        self.assertEqual(uncited_result["per_hypothesis_freshness"]["result"], scoring.PER_HYPOTHESIS_FRESHNESS_NOTHING_TO_CHECK)


class ApplyPerHypothesisFreshnessTest(unittest.TestCase):
    def test_applies_to_every_record_and_always_sets_the_fields(self) -> None:
        session = _session_record("2026-08-05T00:00:00+00:00", [])
        records = [
            {"raw_hypothesis": {"hypothesis_name": "A"}, "supporting_source_urls": []},
            {"raw_hypothesis": {"hypothesis_name": "B"}, "supporting_source_urls": []},
        ]
        updated = scoring.apply_per_hypothesis_freshness(records, session, datetime(2026, 8, 5, tzinfo=timezone.utc))
        for r in updated:
            self.assertIn("citation_status", r)
            self.assertIn("per_hypothesis_freshness", r)

    def test_does_not_mutate_input(self) -> None:
        session = _session_record("2026-08-05T00:00:00+00:00", [])
        records = [{"raw_hypothesis": {"hypothesis_name": "A"}, "supporting_source_urls": []}]
        scoring.apply_per_hypothesis_freshness(records, session, datetime(2026, 8, 5, tzinfo=timezone.utc))
        self.assertNotIn("citation_status", records[0])

    def test_missing_session_started_at_never_fabricates_a_result(self) -> None:
        session = _session_record("2026-08-05T00:00:00+00:00", [])
        records = [{"raw_hypothesis": {"hypothesis_name": "A"}, "supporting_source_urls": []}]
        updated = scoring.apply_per_hypothesis_freshness(records, session, None)
        self.assertIsNone(updated[0]["citation_status"])
        self.assertIsNone(updated[0]["per_hypothesis_freshness"]["result"])


class NeverBindingRegressionTest(unittest.TestCase):
    """item 7: strictly informational, no matter how a hypothesis's
    per-hypothesis freshness result comes out."""

    def test_apply_fdr_correction_ignores_per_hypothesis_freshness_entirely(self) -> None:
        records = [
            {
                "p_value_oos": 0.001,
                "citation_status": scoring.CITATION_STATUS_CITED,
                "per_hypothesis_freshness": {"result": scoring.PER_HYPOTHESIS_FRESHNESS_CHECKED_DISQUALIFIED},
            }
        ]
        updated = scoring.apply_fdr_correction(records, field="p_value_oos")
        self.assertIsNotNone(updated[0]["fdr_survives_oos"])
        self.assertNotIn("excluded_from_fdr_family_reason", updated[0])

    def test_apply_fdr_correction_signature_has_no_citation_parameter(self) -> None:
        params = inspect.signature(scoring.apply_fdr_correction).parameters
        self.assertNotIn("citation_status", params)
        self.assertNotIn("per_hypothesis_freshness", params)


class ConstantsUncnhangedTest(unittest.TestCase):
    """item 7 (out of scope): confirms this directive touched none of the
    evidence-bar constants."""

    def test_evidence_bar_constants_unchanged(self) -> None:
        from tools.backtest_statistics import MIN_SAMPLE_SIZE
        from nero_core.research_agent.frequency_gate import TARGET_RESOLVED_TRADES, FAST_MAX_MONTHS, VIABLE_MAX_MONTHS

        self.assertEqual(MIN_SAMPLE_SIZE, 20)
        self.assertEqual(TARGET_RESOLVED_TRADES, 30)
        self.assertEqual(FAST_MAX_MONTHS, 6.0)
        self.assertEqual(VIABLE_MAX_MONTHS, 12.0)
        self.assertEqual(scoring.DEFAULT_FDR_ALPHA, 0.05)
        self.assertEqual(scoring.FRESHNESS_DISQUALIFICATION_WINDOW_DAYS, 30)


class BackfillPreCitationStatusTest(unittest.TestCase):
    """item 5: the one-time migration script (tools/backfill_eve_pre_
    citation_status.py) that marked the 16 real, already-committed
    eve_hypotheses.json records predating this mechanism."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.path = Path(self._tmpdir.name) / "eve_hypotheses.json"
        # Eve's storage module refuses (DisallowedWritePathError) any write
        # outside its own 3-path allowlist -- see storage.py's own
        # module docstring. Patching DEFAULT_HYPOTHESES_PATH to this test's
        # own tmp file is what makes it an allowed path, matching the same
        # isolation pattern test_eve_freshness_disqualification.py's own
        # _IsolatedStorageTestCase already uses.
        self._patcher = patch.object(storage, "DEFAULT_HYPOTHESES_PATH", self.path)
        self._patcher.start()

    def tearDown(self) -> None:
        self._patcher.stop()
        self._tmpdir.cleanup()

    def test_marks_records_lacking_citation_status(self) -> None:
        storage.atomic_write_json_list(self.path, [
            {"session_id": "s0", "raw_hypothesis": {"hypothesis_name": "OLD1"}},
            {"session_id": "s0", "raw_hypothesis": {"hypothesis_name": "OLD2"}},
        ])
        n_marked = backfill_mod.backfill(self.path)
        self.assertEqual(n_marked, 2)
        updated = storage.read_json_list(self.path)
        self.assertTrue(all(r["citation_status"] == scoring.CITATION_STATUS_UNSCOREABLE_PRE_CITATION for r in updated))

    def test_never_fabricates_a_supporting_source_urls_list(self) -> None:
        storage.atomic_write_json_list(self.path, [{"session_id": "s0", "raw_hypothesis": {"hypothesis_name": "OLD1"}}])
        backfill_mod.backfill(self.path)
        updated = storage.read_json_list(self.path)
        self.assertNotIn("supporting_source_urls", updated[0])  # never invented
        self.assertIsNone(updated[0]["supporting_source_urls_validated"])

    def test_leaves_a_record_that_already_has_citation_status_untouched(self) -> None:
        storage.atomic_write_json_list(self.path, [
            {"session_id": "s1", "raw_hypothesis": {"hypothesis_name": "NEW1"}, "citation_status": scoring.CITATION_STATUS_CITED},
        ])
        n_marked = backfill_mod.backfill(self.path)
        self.assertEqual(n_marked, 0)
        updated = storage.read_json_list(self.path)
        self.assertEqual(updated[0]["citation_status"], scoring.CITATION_STATUS_CITED)

    def test_idempotent_second_run_marks_nothing(self) -> None:
        storage.atomic_write_json_list(self.path, [{"session_id": "s0", "raw_hypothesis": {"hypothesis_name": "OLD1"}}])
        backfill_mod.backfill(self.path)
        second_run = backfill_mod.backfill(self.path)
        self.assertEqual(second_run, 0)

class RealCommittedDataBackfilledTest(unittest.TestCase):
    """Deliberately OUTSIDE BackfillPreCitationStatusTest's isolated-storage
    patching -- reads the real, committed docs/site_data/eve_hypotheses.json
    to confirm the actual migration (tools/backfill_eve_pre_citation_status.py)
    was really run against real data, not just proven correct against a
    synthetic fixture."""

    def test_the_real_committed_eve_hypotheses_file_has_been_backfilled(self) -> None:
        real_path = Path(__file__).resolve().parents[1] / "docs" / "site_data" / "eve_hypotheses.json"
        records = storage.read_json_list(real_path)
        self.assertEqual(len(records), 16)
        self.assertTrue(all(r.get("citation_status") == scoring.CITATION_STATUS_UNSCOREABLE_PRE_CITATION for r in records))


if __name__ == "__main__":
    unittest.main()
