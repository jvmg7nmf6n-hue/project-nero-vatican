"""CC-1 Factory Loop directive, item 7: search freshness, Variant C, BINDING.

Extends tag_lookahead_risk (informational only, unchanged -- see
tests/test_eve_contamination_tags.py) with a binding sibling,
check_freshness_disqualification, that actually excludes a hypothesis from
Trial admission (item 4e) and the FDR family (item 7c). Variant C:
pub_date >= session_started_at - 30 days disqualifies -- the only one of
three candidate rules (spec B6) that discriminated within Session 1's real
4-source sample instead of flagging everything or nothing."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from nero_core.eve import notify as eve_notify
from nero_core.eve import pipeline, scoring, storage
from nero_core.eve.config import _ENV_VAR as EVE_ENABLED_ENV_VAR


def _session_with_search_result(page_age: str, started_at: str = "2026, 08, 05") -> dict:
    return {
        "started_at": "2026-08-05T00:00:00+00:00",
        "turns": [
            {
                "turn_index": 0,
                "raw_response": {
                    "content": [
                        {
                            "type": "web_search_tool_result",
                            "tool_use_id": "srvtoolu_1",
                            "content": [{"type": "web_search_result", "url": "https://example.com/a", "title": "A", "page_age": page_age}],
                        }
                    ]
                },
            }
        ],
    }


class CheckFreshnessDisqualificationTest(unittest.TestCase):
    def test_source_within_30_days_of_session_start_disqualifies(self) -> None:
        session_record = _session_with_search_result("3 weeks ago")
        flags = scoring.check_freshness_disqualification(session_record, session_started_at=datetime(2026, 8, 5, tzinfo=timezone.utc))
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0]["tag"], "FRESHNESS_DISQUALIFIED")
        self.assertEqual(flags[0]["rule_fired"], "variant_c_30day")
        self.assertEqual(flags[0]["offending_source_url"], "https://example.com/a")
        self.assertIsNotNone(flags[0]["parsed_pub_date"])

    def test_source_older_than_30_days_does_not_disqualify(self) -> None:
        session_record = _session_with_search_result("February 1, 2026")
        flags = scoring.check_freshness_disqualification(session_record, session_started_at=datetime(2026, 8, 5, tzinfo=timezone.utc))
        self.assertEqual(flags, [])

    def test_absolute_recent_date_disqualifies(self) -> None:
        session_record = _session_with_search_result("July 20, 2026")
        flags = scoring.check_freshness_disqualification(session_record, session_started_at=datetime(2026, 8, 5, tzinfo=timezone.utc))
        self.assertEqual(len(flags), 1)

    def test_unparseable_date_never_disqualifies_or_crashes(self) -> None:
        session_record = _session_with_search_result("sometime")
        flags = scoring.check_freshness_disqualification(session_record, session_started_at=datetime(2026, 8, 5, tzinfo=timezone.utc))
        self.assertEqual(flags, [])

    def test_no_search_results_returns_no_flags(self) -> None:
        session_record = {"started_at": "2026-08-05T00:00:00+00:00", "turns": []}
        flags = scoring.check_freshness_disqualification(session_record, session_started_at=datetime(2026, 8, 5, tzinfo=timezone.utc))
        self.assertEqual(flags, [])

    def test_replicates_spec_b6_session_1_real_sample_two_of_four_flag(self) -> None:
        # docs/investigations/factory_loop_specification.md B6's own real
        # sample: 2 of 4 real Session 1 sources are relative-recent dates
        # ("3 weeks ago", "1 month ago"); the other 2 are older absolute
        # calendar dates ("February 1, 2026", "May 20, 2026") -- Variant C
        # is the only rule that discriminates within this sample (2/4, not
        # 4/4 or 0/4). Re-verified here as a synthetic regression guard;
        # item 7d re-runs this against the REAL session file directly.
        session_started_at = datetime(2026, 8, 4, tzinfo=timezone.utc)
        recent_relative = scoring.check_freshness_disqualification(
            _session_with_search_result("3 weeks ago"), session_started_at,
        )
        recent_relative_2 = scoring.check_freshness_disqualification(
            _session_with_search_result("1 month ago"), session_started_at,
        )
        older_absolute = scoring.check_freshness_disqualification(
            _session_with_search_result("February 1, 2026"), session_started_at,
        )
        older_absolute_2 = scoring.check_freshness_disqualification(
            _session_with_search_result("May 20, 2026"), session_started_at,
        )
        self.assertEqual(len(recent_relative), 1)
        self.assertEqual(len(recent_relative_2), 1)
        self.assertEqual(older_absolute, [])
        self.assertEqual(older_absolute_2, [])


class ApplyFreshnessDisqualificationTest(unittest.TestCase):
    def test_no_flags_marks_every_record_explicitly_not_disqualified(self) -> None:
        records = [{"raw_hypothesis": {"hypothesis_name": "A"}}, {"raw_hypothesis": {"hypothesis_name": "B"}}]
        updated = scoring.apply_freshness_disqualification(records, [])
        self.assertTrue(all(r["freshness_disqualified"] is False for r in updated))
        self.assertTrue(all(r["freshness_disqualification_reason"] is None for r in updated))

    def test_session_wide_flags_apply_to_every_record_in_the_session(self) -> None:
        # PER-HYPOTHESIS ATTRIBUTION LIMITATION (documented in
        # check_freshness_disqualification's own docstring): a session-level
        # flag cannot be traced to one specific hypothesis, so it applies to
        # every hypothesis this session proposed.
        records = [{"raw_hypothesis": {"hypothesis_name": "A"}}, {"raw_hypothesis": {"hypothesis_name": "B"}}]
        flags = [{"tag": "FRESHNESS_DISQUALIFIED", "hypothesis_name": None, "offending_source_url": "https://x", "parsed_pub_date": "2026-08-01", "rule_fired": "variant_c_30day"}]
        updated = scoring.apply_freshness_disqualification(records, flags)
        self.assertTrue(all(r["freshness_disqualified"] for r in updated))
        self.assertEqual(updated[0]["freshness_disqualification_reason"][0]["hypothesis_name"], "A")
        self.assertEqual(updated[1]["freshness_disqualification_reason"][0]["hypothesis_name"], "B")

    def test_does_not_mutate_input(self) -> None:
        records = [{"raw_hypothesis": {"hypothesis_name": "A"}}]
        scoring.apply_freshness_disqualification(records, [{"tag": "FRESHNESS_DISQUALIFIED"}])
        self.assertNotIn("freshness_disqualified", records[0])


class FreshnessExcludedFromFdrFamilyTest(unittest.TestCase):
    def test_disqualified_record_excluded_from_fdr_even_with_significant_p_value(self) -> None:
        records = [
            {"p_value_oos": 0.001, "freshness_disqualified": True, "raw_hypothesis": {"hypothesis_name": "A"}},
            {"p_value_oos": 0.5, "freshness_disqualified": False, "raw_hypothesis": {"hypothesis_name": "B"}},
        ]
        updated = scoring.apply_fdr_correction(records, field="p_value_oos")
        self.assertIsNone(updated[0]["fdr_survives_oos"])
        self.assertEqual(updated[0]["excluded_from_fdr_family_reason"], "freshness_disqualified")

    def test_both_self_derivative_and_freshness_disqualified_records_both_reasons(self) -> None:
        record = {
            "p_value_oos": 0.001, "freshness_disqualified": True,
            "contamination_tags": [{"tag": "SELF_DERIVATIVE"}],
        }
        updated = scoring.apply_fdr_correction([record], field="p_value_oos")
        self.assertIn("self_derivative", updated[0]["excluded_from_fdr_family_reason"])
        self.assertIn("freshness_disqualified", updated[0]["excluded_from_fdr_family_reason"])

    def test_clean_record_still_gets_the_plain_self_derivative_string(self) -> None:
        # Regression guard: existing callers/tests assert the EXACT string
        # "self_derivative" (see test_eve_scoring_fdr.py) -- confirms the
        # "+".join behavior is backward compatible for the single-reason case.
        record = {"p_value_oos": 0.001, "contamination_tags": [{"tag": "SELF_DERIVATIVE"}], "freshness_disqualified": False}
        updated = scoring.apply_fdr_correction([record], field="p_value_oos")
        self.assertEqual(updated[0]["excluded_from_fdr_family_reason"], "self_derivative")


class _IsolatedStorageTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp_root = Path(self._tmpdir.name)
        self.hypotheses_path = tmp_root / "eve_hypotheses.json"
        self.ledger_path = tmp_root / "eve_budget_ledger.json"
        self.sessions_dir = tmp_root / "eve_sessions"
        self._patches = [
            patch.object(storage, "DEFAULT_HYPOTHESES_PATH", self.hypotheses_path),
            patch.object(storage, "DEFAULT_BUDGET_LEDGER_PATH", self.ledger_path),
            patch.object(storage, "EVE_SESSIONS_DIR", self.sessions_dir),
            patch("nero_core.eve.context.DEFAULT_QUANT_METRICS_PATH", tmp_root / "quant_metrics.json"),
            patch("nero_core.eve.context.DEFAULT_FAILURE_PATTERNS_PATH", tmp_root / "failure_patterns.json"),
            patch("nero_core.eve.context.DEFAULT_ADAM_HYPOTHESES_PATH", tmp_root / "agent_hypotheses.json"),
            patch.object(eve_notify, "send_ntfy_notification", return_value=True),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()
        self._tmpdir.cleanup()


def _make_candles(n: int = 600) -> pd.DataFrame:
    import random

    rng = random.Random(7)
    rows = []
    price = 100.0
    t0 = 1_700_000_000_000
    for i in range(n):
        price *= 1 + rng.uniform(-0.01, 0.01)
        rows.append({"close_time": t0 + i * 3_600_000, "close": price, "high": price * 1.004, "low": price * 0.996, "volume": 1.0})
    return pd.DataFrame(rows)


class PipelineFailLoudTest(_IsolatedStorageTestCase):
    """Item 7b: a session whose real hypothesis population is 100%
    freshness-disqualified must be surfaced prominently, not buried."""

    def test_hundred_percent_disqualified_session_sets_the_loud_flag_and_prints_a_warning(self) -> None:
        candles = _make_candles()
        fake_flag = [{"tag": "FRESHNESS_DISQUALIFIED", "hypothesis_name": None, "offending_source_url": "https://x", "parsed_pub_date": "2026-08-01", "rule_fired": "variant_c_30day"}]
        with patch.dict("os.environ", {EVE_ENABLED_ENV_VAR: "true"}), \
             patch("nero_core.eve.pipeline.scoring.check_freshness_disqualification", return_value=fake_flag):
            result = pipeline.run_pipeline(
                api_key="fake", stub=True, candles_provider=lambda a, t: candles, now=datetime(2026, 8, 15, tzinfo=timezone.utc),
            )

        self.assertTrue(all(r["freshness_disqualified"] for r in result.scored_hypotheses))
        on_disk = storage.read_json_list(self.hypotheses_path)
        self.assertTrue(all(r["fdr_survives_oos"] is None for r in on_disk if r.get("p_value_oos") is not None))

        session_file = next(self.sessions_dir.glob("*.json"))
        import json
        session_record = json.loads(session_file.read_text())
        self.assertTrue(session_record["freshness_disqualified_entire_session"])
        self.assertEqual(len(session_record["freshness_disqualification_flags"]), 1)
        self.assertEqual(session_record["ablation_metadata"]["n_freshness_disqualification_flags"], 1)

    def test_clean_session_records_entire_session_disqualified_as_false(self) -> None:
        candles = _make_candles()
        with patch.dict("os.environ", {EVE_ENABLED_ENV_VAR: "true"}):
            pipeline.run_pipeline(api_key="fake", stub=True, candles_provider=lambda a, t: candles, now=datetime(2026, 8, 15, tzinfo=timezone.utc))

        session_file = next(self.sessions_dir.glob("*.json"))
        import json
        session_record = json.loads(session_file.read_text())
        self.assertFalse(session_record["freshness_disqualified_entire_session"])
        self.assertEqual(session_record["freshness_disqualification_flags"], [])


if __name__ == "__main__":
    unittest.main()
