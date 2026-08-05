from __future__ import annotations

import ast
import inspect
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from nero_core.eve import notify as eve_notify
from nero_core.eve import pipeline, preflight as eve_preflight, scoring, storage
from nero_core.eve.config import _ENV_VAR as EVE_ENABLED_ENV_VAR


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
            # Every test here runs stub=True (no real API call), but run_pipeline
            # unconditionally sends exactly one ntfy notification per invocation
            # (see pipeline.py's own docstring) -- mocked here so the pipeline
            # test suite never makes a real network call to ntfy.sh. The
            # notification wiring itself is covered separately, by tests that
            # patch this same target and assert on how it was called.
            patch.object(eve_notify, "send_ntfy_notification", return_value=True),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()
        self._tmpdir.cleanup()


class KillSwitchTest(_IsolatedStorageTestCase):
    def test_disabled_pipeline_runs_no_session_and_writes_nothing(self) -> None:
        with patch.dict("os.environ", {EVE_ENABLED_ENV_VAR: "false"}):
            result = pipeline.run_pipeline(api_key="fake", stub=True)

        self.assertFalse(result.enabled)
        self.assertIsNone(result.session_result)
        self.assertFalse(self.hypotheses_path.exists())
        self.assertFalse(self.ledger_path.exists())


class EnabledStubPipelineTest(_IsolatedStorageTestCase):
    def test_full_pipeline_scores_the_stub_hypothesis(self) -> None:
        candles = _make_candles()
        with patch.dict("os.environ", {EVE_ENABLED_ENV_VAR: "true"}):
            result = pipeline.run_pipeline(
                api_key="fake", stub=True, candles_provider=lambda a, t: candles, now=datetime(2026, 8, 15, tzinfo=timezone.utc)
            )

        self.assertTrue(result.enabled)
        self.assertEqual(len(result.scored_hypotheses), 1)
        scored = result.scored_hypotheses[0]
        self.assertNotEqual(scored["testability"], "UNSCORED")

    def test_scored_hypotheses_are_persisted_back_to_eve_hypotheses_json(self) -> None:
        candles = _make_candles()
        with patch.dict("os.environ", {EVE_ENABLED_ENV_VAR: "true"}):
            pipeline.run_pipeline(api_key="fake", stub=True, candles_provider=lambda a, t: candles, now=datetime(2026, 8, 15, tzinfo=timezone.utc))

        on_disk = storage.read_json_list(self.hypotheses_path)
        self.assertEqual(len(on_disk), 1)
        self.assertNotEqual(on_disk[0]["testability"], "UNSCORED")
        self.assertIn("fdr_survives_oos", on_disk[0])

    def test_fdr_correction_applied_for_both_is_and_oos(self) -> None:
        candles = _make_candles()
        with patch.dict("os.environ", {EVE_ENABLED_ENV_VAR: "true"}):
            result = pipeline.run_pipeline(api_key="fake", stub=True, candles_provider=lambda a, t: candles, now=datetime(2026, 8, 15, tzinfo=timezone.utc))

        scored = result.scored_hypotheses[0]
        self.assertIn("fdr_survives_oos", scored)
        self.assertIn("fdr_survives_is", scored)

    def test_no_candle_data_still_completes_without_crashing(self) -> None:
        with patch.dict("os.environ", {EVE_ENABLED_ENV_VAR: "true"}):
            result = pipeline.run_pipeline(api_key="fake", stub=True, candles_provider=lambda a, t: None, now=datetime(2026, 8, 15, tzinfo=timezone.utc))

        self.assertTrue(result.enabled)
        self.assertEqual(result.lookahead_risk_flags, [])


def _prior_eve_record(session_id: str, hypothesis_name: str, mechanism: str, asset: str = "BTC", timeframe: str = "1h") -> dict:
    return {
        "schema_version": storage.SCHEMA_VERSION,
        "session_id": session_id,
        "turn_index": 0,
        "tool_use_id": "toolu_prior",
        "proposed_at": "2026-08-01T00:00:00+00:00",
        "raw_hypothesis": {"hypothesis_name": hypothesis_name, "mechanism": mechanism, "asset": asset, "timeframe": timeframe},
        "testability": "TESTABLE",
        "verdict_is": None, "verdict_oos": None, "verdict_combined": None,
        "contamination_tags": [],
    }


class LoadEveHistoryExcludingSessionTest(_IsolatedStorageTestCase):
    """Direct unit coverage of pipeline._load_eve_history_excluding_session
    -- the loader must filter out the current session's own (already-
    persisted-by-session.py, still-UNSCORED) records, or a self-dedup check
    built on top of it would compare every hypothesis against itself."""

    def test_excludes_only_the_given_session_id(self) -> None:
        storage.append_json_list(self.hypotheses_path, [
            _prior_eve_record("session-A", "IDEA_A", "mechanism a"),
            _prior_eve_record("session-B", "IDEA_B", "mechanism b"),
        ])
        history = pipeline._load_eve_history_excluding_session("session-A")
        self.assertEqual([h["hypothesis_name"] for h in history], ["IDEA_B"])

    def test_empty_file_returns_empty_history(self) -> None:
        self.assertEqual(pipeline._load_eve_history_excluding_session("any-session"), [])

    def test_records_missing_raw_hypothesis_are_skipped_not_crashed_on(self) -> None:
        storage.append_json_list(self.hypotheses_path, [{"schema_version": 1, "session_id": "session-C"}])
        self.assertEqual(pipeline._load_eve_history_excluding_session("other"), [])


class SelfDedupEndToEndTest(_IsolatedStorageTestCase):
    """CC-1 review, item 1c: a concrete before/after example proving the
    self-dedup check actually catches a repeat, run through the real
    pipeline (stub mode -- the stub script's own hypothesis is
    EVE_STUB_ZSCORE_REVERSION, mechanism 'Stub mechanism for dry-run
    testing only -- not a real research claim.', see llm_client._stub_
    script), not just the isolated scoring-module unit tests."""

    def test_repeating_a_prior_sessions_hypothesis_is_tagged_and_excluded_from_fdr(self) -> None:
        # BEFORE: eve_hypotheses.json already has a near-identical prior
        # hypothesis from a different session. Uses a LARGER candle set
        # (n=5000, vs the module default 600) so the stub's own zscore20<-2
        # rule realizes enough real out-of-sample trades to get an actual
        # non-null p-value -- confirmed empirically: at n=600 this
        # hypothesis's own verdict_oos is INSUFFICIENT_SAMPLE (p_value_oos
        # already None for an unrelated reason), which would make this
        # specific assertion vacuously true regardless of whether the
        # self-derivative exclusion did anything. n=5000 gives a real
        # p_value_oos, so `excluded_from_fdr_family_reason` being set here
        # actually proves the exclusion fired.
        storage.append_json_list(self.hypotheses_path, [
            _prior_eve_record("prior-session-999", "EVE_STUB_ZSCORE_REVERSION_PRIOR", "Stub mechanism for dry-run testing only -- not a real research claim.")
        ])

        candles = _make_candles(n=5000)
        with patch.dict("os.environ", {EVE_ENABLED_ENV_VAR: "true"}):
            result = pipeline.run_pipeline(
                api_key="fake", stub=True, candles_provider=lambda a, t: candles, now=datetime(2026, 8, 15, tzinfo=timezone.utc)
            )

        # AFTER: this session's own (near-identical) stub hypothesis is
        # caught -- still scored (never discarded, never gated), but
        # excluded from the FDR family since it isn't an independent test.
        scored = result.scored_hypotheses[0]
        self.assertIsNotNone(scored["p_value_oos"], "test setup must produce a real p-value or this assertion proves nothing")
        self.assertTrue(scoring.is_self_derivative(scored))
        self.assertEqual(scored["excluded_from_fdr_family_reason"], "self_derivative")
        self.assertIsNone(scored["fdr_survives_oos"])
        self.assertNotEqual(scored["testability"], "UNSCORED", "must still be scored, never discarded")

    def test_a_genuinely_novel_hypothesis_is_never_flagged(self) -> None:
        storage.append_json_list(self.hypotheses_path, [
            _prior_eve_record("prior-session-999", "COMPLETELY_UNRELATED_IDEA", "funding rate extremes on perpetual futures force a leveraged unwind", asset="ETH", timeframe="4h")
        ])

        candles = _make_candles(n=5000)
        with patch.dict("os.environ", {EVE_ENABLED_ENV_VAR: "true"}):
            result = pipeline.run_pipeline(
                api_key="fake", stub=True, candles_provider=lambda a, t: candles, now=datetime(2026, 8, 15, tzinfo=timezone.utc)
            )

        scored = result.scored_hypotheses[0]
        self.assertFalse(scoring.is_self_derivative(scored))
        self.assertIsNotNone(scored["p_value_oos"], "test setup must produce a real p-value or this assertion proves nothing")
        self.assertIn(scored["fdr_survives_oos"], (True, False))

    def test_ablation_metadata_records_the_self_derivative_count(self) -> None:
        storage.append_json_list(self.hypotheses_path, [
            _prior_eve_record("prior-session-999", "EVE_STUB_ZSCORE_REVERSION_PRIOR", "Stub mechanism for dry-run testing only -- not a real research claim.")
        ])

        candles = _make_candles()
        with patch.dict("os.environ", {EVE_ENABLED_ENV_VAR: "true"}):
            result = pipeline.run_pipeline(
                api_key="fake", stub=True, candles_provider=lambda a, t: candles, now=datetime(2026, 8, 15, tzinfo=timezone.utc)
            )

        record = json.loads(storage.session_record_path(result.session_result.session_id).read_text(encoding="utf-8"))
        self.assertEqual(record["ablation_metadata"]["n_self_derivative_hypotheses"], 1)

    def test_zero_self_derivative_count_is_recorded_explicitly_not_omitted(self) -> None:
        candles = _make_candles()
        with patch.dict("os.environ", {EVE_ENABLED_ENV_VAR: "true"}):
            result = pipeline.run_pipeline(
                api_key="fake", stub=True, candles_provider=lambda a, t: candles, now=datetime(2026, 8, 15, tzinfo=timezone.utc)
            )

        record = json.loads(storage.session_record_path(result.session_result.session_id).read_text(encoding="utf-8"))
        self.assertIn("n_self_derivative_hypotheses", record["ablation_metadata"])
        self.assertEqual(record["ablation_metadata"]["n_self_derivative_hypotheses"], 0)


class DefaultCandlesProviderResearchFallbackTest(unittest.TestCase):
    """Renamed in spirit (not literally, to keep git blame simple) from a
    "falls back to site export" test to a "refuses rather than falls back"
    test -- see nero_core.eve.pipeline.APPROVED_RESEARCH_UNIVERSE and
    scoring.DataSourceRefusedError. The silent-fallback behavior this class
    used to assert was the actual bug: BTC/4h is the only pair with a real
    random-hypothesis baseline computed against it, so scoring ANY other
    pair against the 200-row site export produced a confident-looking
    verdict on data proven meaningless for exactly this purpose."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp_root = Path(self._tmpdir.name)
        self.site_dir = tmp_root / "site"
        self.research_dir = tmp_root / "research"
        self.site_dir.mkdir()
        self.research_dir.mkdir()

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _write(self, directory: Path, filename: str, n_candles: int, asset: str = "BTC", timeframe: str = "4h") -> None:
        import json

        candles = [{"time": 1_700_000_000 + i * 14400, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1.0} for i in range(n_candles)]
        payload = {"schema_version": 1, "asset": asset, "timeframe": timeframe, "last_updated": "2026-08-01T00:00:00+00:00", "candles": candles}
        (directory / filename).write_text(json.dumps(payload))

    def test_prefers_research_export_when_present(self) -> None:
        self._write(self.research_dir, "BTC_4h.json", n_candles=4400)
        self._write(self.site_dir, "BTC_4h.json", n_candles=200)

        frame = pipeline.default_candles_provider("BTC", "4h", candles_dir=self.site_dir, research_candles_dir=self.research_dir)
        self.assertEqual(len(frame), 4400)

    def test_research_export_frame_is_tagged_with_source_and_row_count(self) -> None:
        self._write(self.research_dir, "BTC_4h.json", n_candles=4400)

        frame = pipeline.default_candles_provider("BTC", "4h", candles_dir=self.site_dir, research_candles_dir=self.research_dir)
        self.assertEqual(frame.attrs.get("data_source"), "research_export")
        self.assertEqual(frame.attrs.get("row_count"), 4400)

    def test_refuses_rather_than_falls_back_to_site_export_when_research_export_absent(self) -> None:
        self._write(self.site_dir, "BTC_4h.json", n_candles=200)

        with self.assertRaises(scoring.DataSourceRefusedError):
            pipeline.default_candles_provider("BTC", "4h", candles_dir=self.site_dir, research_candles_dir=self.research_dir)

    def test_refuses_when_neither_export_exists(self) -> None:
        with self.assertRaises(scoring.DataSourceRefusedError):
            pipeline.default_candles_provider("BTC", "4h", candles_dir=self.site_dir, research_candles_dir=self.research_dir)

    def test_refuses_a_pair_outside_the_approved_universe_even_with_a_real_site_export(self) -> None:
        # GOLD/4h has a real 200-row site export in production (see
        # docs/site_data/candles/GOLD_4h.json) but no research export and no
        # baseline -- must be refused regardless of what files exist on disk.
        self._write(self.site_dir, "GOLD_4h.json", n_candles=200, asset="GOLD", timeframe="4h")

        with self.assertRaises(scoring.DataSourceRefusedError):
            pipeline.default_candles_provider("GOLD", "4h", candles_dir=self.site_dir, research_candles_dir=self.research_dir)

    def test_adams_own_pipeline_now_applies_the_identical_refusal_discipline(self) -> None:
        # UPDATED (item 2, Eve engine v1 follow-up session): Adam's own
        # research_agent.pipeline.default_candles_provider was originally
        # left untouched deliberately (see the old version of this test,
        # replaced here) -- it has since been pointed at the same research
        # export with the same refuse-don't-degrade discipline Eve already
        # had. Confirms parity directly: both raise the SAME way for the
        # SAME out-of-universe pair, rather than trusting two independent
        # implementations not to have quietly diverged.
        import nero_core.research_agent.pipeline as adam_pipeline

        with self.assertRaises(adam_pipeline.DataSourceRefusedError):
            adam_pipeline.default_candles_provider("GOLD", "4h", candles_dir=self.site_dir, research_candles_dir=self.research_dir)


class ScoringRunCannotConsumeSiteExportTest(unittest.TestCase):
    """End-to-end proof (not just a unit check on default_candles_provider
    in isolation) that a real scoring run -- scoring.score_hypothesis, the
    exact function run_pipeline calls -- can never silently score a
    hypothesis against the 200-row site export, even when that file exists
    on disk and only the research export is missing."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp_root = Path(self._tmpdir.name)
        self.site_dir = tmp_root / "site"
        self.research_dir = tmp_root / "research"
        self.site_dir.mkdir()
        self.research_dir.mkdir()

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _write_site_export(self, asset: str, timeframe: str, n_candles: int = 200) -> None:
        import json

        candles = [{"time": 1_700_000_000 + i * 14400, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1.0} for i in range(n_candles)]
        payload = {"schema_version": 1, "asset": asset, "timeframe": timeframe, "last_updated": "2026-08-01T00:00:00+00:00", "candles": candles}
        (self.site_dir / f"{asset}_{timeframe}.json").write_text(json.dumps(payload))

    def _provider(self, asset: str, timeframe: str):
        return pipeline.default_candles_provider(asset, timeframe, candles_dir=self.site_dir, research_candles_dir=self.research_dir)

    def test_gold_hypothesis_is_refused_not_scored_against_the_site_export(self) -> None:
        # A real 200-row GOLD/4h site export exists (mirrors production:
        # docs/site_data/candles/GOLD_4h.json is real, docs/research_data/
        # candles/GOLD_4h.json does not exist) -- the old behavior silently
        # scored against it anyway.
        self._write_site_export("GOLD", "4h")
        record = {
            "session_id": "s1", "turn_index": 0, "tool_use_id": "toolu_1",
            "raw_hypothesis": {
                "hypothesis_name": "GOLD_TEST", "asset": "GOLD", "timeframe": "4h",
                "generated_at": "2026-08-01T00:00:00+00:00",
                "structured_entry_rule": {"conditions": [{"field": "ret_1", "op": "gt", "value": -1.0}]},
                "structured_exit_plan": {"stop_atr_multiple": 1.5, "target_r_multiple": 2.0, "max_holding_hours": 24.0},
            },
        }

        scored = scoring.score_hypothesis(record, candles_provider=self._provider, now=datetime(2026, 8, 1, tzinfo=timezone.utc))

        self.assertEqual(scored["candle_data_source"], "refused")
        self.assertIsNone(scored["candle_row_count"])
        self.assertIsNone(scored["verdict_is"])
        self.assertIsNone(scored["verdict_oos"])
        self.assertIsNone(scored["verdict_combined"])
        self.assertIn("refused rather than substituted", scored["testability_reason"])

    def test_btc_4h_hypothesis_with_research_export_is_scored_and_tagged(self) -> None:
        import json

        candles = [
            {"time": 1_700_000_000 + i * 14400, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1.0}
            for i in range(600)
        ]
        payload = {"schema_version": 1, "asset": "BTC", "timeframe": "4h", "last_updated": "2026-08-01T00:00:00+00:00", "candles": candles}
        (self.research_dir / "BTC_4h.json").write_text(json.dumps(payload))
        record = {
            "session_id": "s1", "turn_index": 0, "tool_use_id": "toolu_2",
            "raw_hypothesis": {
                "hypothesis_name": "BTC_TEST", "asset": "BTC", "timeframe": "4h",
                "generated_at": "2026-08-01T00:00:00+00:00",
                "structured_entry_rule": {"conditions": [{"field": "ret_1", "op": "gt", "value": -1.0}]},
                "structured_exit_plan": {"stop_atr_multiple": 1.5, "target_r_multiple": 2.0, "max_holding_hours": 24.0},
            },
        }

        scored = scoring.score_hypothesis(record, candles_provider=self._provider, now=datetime(2026, 8, 1, tzinfo=timezone.utc))

        self.assertEqual(scored["candle_data_source"], "research_export")
        self.assertEqual(scored["candle_row_count"], 600)


class PreflightGateTest(_IsolatedStorageTestCase):
    """A stale/invalid key must be caught BEFORE session.run_session is ever
    called -- zero real spend, zero partial session file, exactly one ntfy
    failure notification. Mirrors the real Adam incident this exists to
    prevent (a bad key going unnoticed for weeks)."""

    def test_preflight_rejection_never_calls_run_session_and_writes_no_session_file(self) -> None:
        with patch.object(eve_preflight, "check_api_key", return_value=eve_preflight.PreflightResult(False, "HTTP 401: key rejected before any token was processed")), \
             patch("nero_core.eve.session.run_session") as mock_run_session, \
             patch.dict("os.environ", {EVE_ENABLED_ENV_VAR: "true"}):
            result = pipeline.run_pipeline(api_key="stale-key", stub=False)

        mock_run_session.assert_not_called()
        self.assertFalse(result.preflight_ok)
        self.assertIsNone(result.session_result)
        self.assertTrue(result.enabled)  # kill switch was on -- this is a preflight failure, not a disabled no-op
        self.assertFalse(self.sessions_dir.exists() and any(self.sessions_dir.iterdir()))

    def test_preflight_rejection_sends_exactly_one_failure_notification(self) -> None:
        with patch.object(eve_preflight, "check_api_key", return_value=eve_preflight.PreflightResult(False, "HTTP 401: key rejected before any token was processed")), \
             patch("nero_core.eve.session.run_session"), \
             patch.dict("os.environ", {EVE_ENABLED_ENV_VAR: "true"}), \
             patch.object(eve_notify, "send_ntfy_notification", return_value=True) as mock_notify:
            pipeline.run_pipeline(api_key="stale-key", stub=False)

        mock_notify.assert_called_once()
        (message,), _ = mock_notify.call_args
        self.assertIn("FAILED", message)
        self.assertIn("401", message)
        self.assertIn("$0.0000", message)

    def test_preflight_passing_lets_the_session_actually_run(self) -> None:
        candles = _make_candles()
        with patch.object(eve_preflight, "check_api_key", return_value=eve_preflight.PreflightResult(True, "ok")), \
             patch.dict("os.environ", {EVE_ENABLED_ENV_VAR: "true"}):
            result = pipeline.run_pipeline(
                api_key="fake", stub=True, candles_provider=lambda a, t: candles, now=datetime(2026, 8, 15, tzinfo=timezone.utc)
            )

        self.assertTrue(result.preflight_ok)
        self.assertIsNotNone(result.session_result)

    def test_stub_mode_skips_preflight_entirely(self) -> None:
        candles = _make_candles()
        with patch.object(eve_preflight, "check_api_key") as mock_check, \
             patch.dict("os.environ", {EVE_ENABLED_ENV_VAR: "true"}):
            pipeline.run_pipeline(api_key="fake", stub=True, candles_provider=lambda a, t: candles, now=datetime(2026, 8, 15, tzinfo=timezone.utc))

        mock_check.assert_not_called()

    def test_main_reports_a_preflight_rejection_cleanly_instead_of_crashing(self) -> None:
        # Real incident (2026-08-03): the first real (non-stub) invocation of
        # this module hit a genuine 401 (stale ANTHROPIC_API_KEY) -- preflight
        # correctly caught it and spent $0, but main()'s own success-path
        # print statement unconditionally assumed result.session_result was
        # never None once result.enabled was True, crashing with
        # AttributeError: 'NoneType' object has no attribute 'session_id' on
        # exactly the case preflight exists to handle gracefully.
        with patch.object(eve_preflight, "check_api_key", return_value=eve_preflight.PreflightResult(False, "HTTP 401: key rejected before any token was processed")), \
             patch.dict("os.environ", {EVE_ENABLED_ENV_VAR: "true", "ANTHROPIC_API_KEY": "stale-key"}), \
             patch.object(eve_notify, "send_ntfy_notification", return_value=True):
            pipeline.main()  # must not raise


class CrashNotifyTest(_IsolatedStorageTestCase):
    """An unhandled exception anywhere in the session/scoring path must still
    notify (best-effort) before the crash propagates loudly -- never a
    silent, unnoticed failure."""

    def test_a_crash_during_the_session_sends_a_failure_notification_and_still_raises(self) -> None:
        with patch("nero_core.eve.session.run_session", side_effect=RuntimeError("boom")), \
             patch.dict("os.environ", {EVE_ENABLED_ENV_VAR: "true"}), \
             patch.object(eve_notify, "send_ntfy_notification", return_value=True) as mock_notify:
            with self.assertRaises(RuntimeError):
                pipeline.run_pipeline(api_key="fake", stub=True)

        mock_notify.assert_called_once()
        (message,), _ = mock_notify.call_args
        self.assertIn("FAILED", message)
        self.assertIn("RuntimeError", message)
        self.assertIn("boom", message)

    def test_the_crash_notification_names_the_real_session_id_not_just_a_generic_message(self) -> None:
        # CC-1 Master Directive, Phase 1.1d: before this fix, send_failure
        # was called with no session_id at all (result.session_id was never
        # readable, since `result` was never assigned when session.run_session
        # itself raised) -- build_failure_message's own fallback header,
        # "Eve session FAILED (before a session id was assigned)", is
        # misleading in this exact case: a session_id WAS in fact minted
        # (nero_core.eve.pipeline.run_pipeline now mints it before calling
        # session.run_session at all), it just wasn't threaded through to
        # the notification. Confirms that fallback text no longer appears.
        with patch("nero_core.eve.session.run_session", side_effect=RuntimeError("boom")), \
             patch.dict("os.environ", {EVE_ENABLED_ENV_VAR: "true"}), \
             patch.object(eve_notify, "send_ntfy_notification", return_value=True) as mock_notify:
            with self.assertRaises(RuntimeError):
                pipeline.run_pipeline(api_key="fake", stub=True, now=datetime(2026, 8, 15, tzinfo=timezone.utc))

        (message,), _ = mock_notify.call_args
        self.assertNotIn("before a session id was assigned", message)
        self.assertIn("Eve session eve-20260815", message)


class BudgetExhaustedAtZeroTurnsNotifyTest(_IsolatedStorageTestCase):
    """A session that never got even one real turn (ledger already exhausted
    before the first call) is reported through the failure path, not the
    richer end-of-session summary -- there is nothing to summarize."""

    def test_zero_real_turns_sends_a_failure_notification(self) -> None:
        from nero_core.eve import budget_ledger as bl
        from nero_core.eve.session import SessionResult

        fake_result = SessionResult(
            session_id="eve-fake-0turns",
            terminated_because=bl.REASON_MONTH_EXHAUSTED,
            n_turns=0,
            n_searches=0,
            n_proposed=0,
            hypothesis_records=[],
            session_spent_usd=0.0,
            record={"session_id": "eve-fake-0turns", "turns": []},
        )
        with patch("nero_core.eve.session.run_session", return_value=fake_result), \
             patch.dict("os.environ", {EVE_ENABLED_ENV_VAR: "true"}), \
             patch.object(eve_notify, "send_ntfy_notification", return_value=True) as mock_notify:
            result = pipeline.run_pipeline(api_key="fake", stub=True)

        mock_notify.assert_called_once()
        (message,), _ = mock_notify.call_args
        self.assertIn("FAILED", message)
        self.assertIn(bl.REASON_MONTH_EXHAUSTED, message)
        self.assertEqual(result.session_result.n_turns, 0)


class SuccessNotifySummaryTest(_IsolatedStorageTestCase):
    """A session with at least one real turn gets the richer end-of-session
    summary -- hypotheses proposed, testable count, OOS verdict counts, real
    cost, and the transcript path -- never the bare failure message."""

    def test_a_completed_stub_session_sends_the_rich_summary(self) -> None:
        candles = _make_candles()
        with patch.dict("os.environ", {EVE_ENABLED_ENV_VAR: "true"}), \
             patch.object(eve_notify, "send_ntfy_notification", return_value=True) as mock_notify:
            result = pipeline.run_pipeline(
                api_key="fake", stub=True, candles_provider=lambda a, t: candles, now=datetime(2026, 8, 15, tzinfo=timezone.utc)
            )

        mock_notify.assert_called_once()
        (message,), _ = mock_notify.call_args
        session_id = result.session_result.session_id
        self.assertNotIn("FAILED", message)
        self.assertIn(session_id, message)
        self.assertIn("Proposed 1 hypotheses", message)
        self.assertIn(str(storage.session_record_path(session_id)), message)


class SecretHandlingTest(unittest.TestCase):
    def test_main_never_prints_the_api_key(self) -> None:
        # AST-based check (mirrors test_research_agent_secret_handling.py's
        # own convention): every print() call in main()'s source must not
        # reference the `api_key` variable directly.
        source = inspect.getsource(pipeline.main)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
                for arg in ast.walk(node):
                    if isinstance(arg, ast.Name) and arg.id == "api_key":
                        self.fail("main() must never print the api_key variable directly")


if __name__ == "__main__":
    unittest.main()
