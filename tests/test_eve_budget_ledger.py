from __future__ import annotations

import unittest
from datetime import datetime, timezone

from nero_core.eve import budget_ledger as bl


def _entry(session_id="s1", month="2026-08", status="actual", projected=0.0, actual=0.0, turn_index=0):
    return {
        "schema_version": 1,
        "entry_id": f"{session_id}-{turn_index}-{status}-{projected}-{actual}",
        "session_id": session_id,
        "turn_index": turn_index,
        "status": status,
        "month": month,
        "projected_cost_usd": projected,
        "actual_cost_usd": actual if status == "actual" else None,
        "usage": None,
        "created_at": "2026-08-01T00:00:00+00:00",
        "reconciled_at": None,
    }


class HelperFunctionsTest(unittest.TestCase):
    def test_current_utc_month_format(self) -> None:
        self.assertEqual(bl.current_utc_month(datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)), "2026-08")

    def test_current_utc_month_uses_utc_not_local(self) -> None:
        # 2026-08-31 23:30 UTC is still August in UTC even if a local PKT
        # (UTC+5) clock would already show 2026-09-01 04:30 -- this function
        # must scope to UTC regardless of what timezone `now` is passed in.
        from datetime import timedelta

        pkt = timezone(timedelta(hours=5))
        # 2026-08-31 23:30 UTC == 2026-09-01 04:30 PKT
        now_pkt = datetime(2026, 9, 1, 4, 30, tzinfo=pkt)
        self.assertEqual(bl.current_utc_month(now_pkt), "2026-08")

    def test_project_call_cost_usd_matches_formula(self) -> None:
        params = bl.DEFAULT_COST_PARAMETERS
        cost = bl.project_call_cost_usd(
            current_history_tokens=100_000, expected_tool_result_tokens=0, max_tokens=2048, max_searches_per_turn=1, params=params
        )
        expected = (100_000 / 1_000_000.0) * params.input_cost_per_mtok + (2048 / 1_000_000.0) * params.output_cost_per_mtok + 1 * params.web_search_cost_per_search
        self.assertAlmostEqual(cost, expected, places=6)

    def test_month_spent_ignores_other_months(self) -> None:
        entries = [_entry(month="2026-07", status="actual", actual=5.0), _entry(month="2026-08", status="actual", actual=3.0)]
        self.assertAlmostEqual(bl.month_spent_usd(entries, "2026-08"), 3.0, places=6)

    def test_session_spent_ignores_other_sessions(self) -> None:
        entries = [_entry(session_id="s1", status="actual", actual=1.0), _entry(session_id="s2", status="actual", actual=9.0)]
        self.assertAlmostEqual(bl.session_spent_usd(entries, "s1"), 1.0, places=6)


class PreCallCheckTest(unittest.TestCase):
    def test_a_session_that_would_exceed_the_month_ceiling_stops_before_doing_so(self) -> None:
        entries = [_entry(session_id="s1", month="2026-08", status="actual", actual=19.99)]
        result = bl.pre_call_check(entries, session_id="s1", projected_cost_usd=0.05, now=datetime(2026, 8, 15, tzinfo=timezone.utc))
        self.assertFalse(result.allowed)
        self.assertIn(bl.REASON_MONTH_EXHAUSTED, result.reason)

    def test_a_session_that_would_exceed_the_session_budget_stops_before_doing_so(self) -> None:
        entries = [_entry(session_id="s1", month="2026-08", status="actual", actual=1.45)]
        result = bl.pre_call_check(
            entries, session_id="s1", projected_cost_usd=0.10, session_budget=1.50, now=datetime(2026, 8, 15, tzinfo=timezone.utc)
        )
        self.assertFalse(result.allowed)
        self.assertIn(bl.REASON_SESSION_EXHAUSTED, result.reason)

    def test_a_call_comfortably_within_both_budgets_is_allowed(self) -> None:
        entries = [_entry(session_id="s1", month="2026-08", status="actual", actual=0.10)]
        result = bl.pre_call_check(
            entries, session_id="s1", projected_cost_usd=0.05, session_budget=1.50, now=datetime(2026, 8, 15, tzinfo=timezone.utc)
        )
        self.assertTrue(result.allowed)

    def test_projected_bound_refuses_a_call_whose_actual_cost_would_have_breached_the_ceiling(self) -> None:
        # A steady stream of cheap early-turn calls (avg $0.02) sets a low
        # AVERAGE cost per call. If the pre-call check used that average as
        # its margin, a huge later turn (full history resent, as happens in
        # a real multi-turn loop) would sail through. The projected-cost
        # BOUND must instead look at the size of the NEXT call specifically.
        cheap_entries = [_entry(session_id="s1", month="2026-08", status="actual", actual=0.02, turn_index=i) for i in range(5)]
        avg_cost_per_call = sum(e["actual_cost_usd"] for e in cheap_entries) / len(cheap_entries)
        self.assertAlmostEqual(avg_cost_per_call, 0.02, places=6)

        # Turn 20's history has grown large (800k tokens resent) -- the real
        # cost of THIS call, projected honestly, is far above the average.
        projected = bl.project_call_cost_usd(
            current_history_tokens=800_000, expected_tool_result_tokens=0, max_tokens=4096, max_searches_per_turn=0
        )
        self.assertGreater(projected, 1.0, "test setup sanity: this call should be expensive")

        result = bl.pre_call_check(cheap_entries, session_id="s1", projected_cost_usd=projected, session_budget=1.50, now=datetime(2026, 8, 15, tzinfo=timezone.utc))
        self.assertFalse(result.allowed)
        self.assertIn(bl.REASON_SESSION_EXHAUSTED, result.reason)

        # Sanity check on the failure mode this test guards against: an
        # average-derived margin (spent-so-far + avg_cost_per_call) would
        # have WRONGLY allowed this same call.
        spent_so_far = sum(e["actual_cost_usd"] for e in cheap_entries)
        self.assertLess(spent_so_far + avg_cost_per_call, 1.50, "an average-based bound would have (wrongly) allowed this call")


class ReserveThenReconcileTest(unittest.TestCase):
    def test_real_per_call_costs_including_all_four_usage_fields_sum_correctly(self) -> None:
        now = datetime(2026, 8, 15, tzinfo=timezone.utc)
        reserved = bl.reserve_entry(session_id="s1", turn_index=0, projected_cost_usd=0.50, now=now)
        self.assertEqual(reserved["status"], bl.STATUS_RESERVED)

        usage = {
            "input_tokens": 10_000,
            "cache_creation_input_tokens": 5_000,
            "cache_read_input_tokens": 20_000,
            "output_tokens": 1_000,
            "server_tool_use": {"web_search_requests": 2},
        }
        reconciled = bl.reconcile_entry(reserved, usage, now=now)
        self.assertEqual(reconciled["status"], bl.STATUS_ACTUAL)
        self.assertEqual(reconciled["entry_id"], reserved["entry_id"])  # same entry, updated

        from nero_core.eve.cost import call_cost_usd_with_tools

        expected_cost = call_cost_usd_with_tools(usage)
        self.assertAlmostEqual(reconciled["actual_cost_usd"], expected_cost, places=6)
        self.assertEqual(reconciled["usage"]["cache_creation_input_tokens"], 5_000)
        self.assertEqual(reconciled["usage"]["cache_read_input_tokens"], 20_000)
        self.assertEqual(reconciled["usage"]["web_search_requests"], 2)

    def test_reconcile_does_not_mutate_the_original_entry(self) -> None:
        reserved = bl.reserve_entry(session_id="s1", turn_index=0, projected_cost_usd=0.50)
        bl.reconcile_entry(reserved, {"input_tokens": 100, "output_tokens": 100})
        self.assertEqual(reserved["status"], bl.STATUS_RESERVED)  # unchanged


class UtcMonthFreshAllowanceTest(unittest.TestCase):
    def test_a_new_utc_month_starts_a_fresh_allowance_without_losing_prior_months_history(self) -> None:
        entries = [_entry(session_id="s1", month="2026-07", status="actual", actual=19.99)]
        # July is nearly at the ceiling...
        july_spent = bl.month_spent_usd(entries, "2026-07")
        self.assertAlmostEqual(july_spent, 19.99, places=6)
        # ...but August starts completely fresh, with July's entry still present.
        august_spent = bl.month_spent_usd(entries, "2026-08")
        self.assertAlmostEqual(august_spent, 0.0, places=6)
        self.assertEqual(len(entries), 1, "prior month's entry must never be deleted")

        result = bl.pre_call_check(entries, session_id="s2", projected_cost_usd=0.05, now=datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc))
        self.assertTrue(result.allowed)


class OrphanedReservedEntryTest(unittest.TestCase):
    def test_an_orphaned_reserved_entry_is_counted_as_spend_on_next_startup(self) -> None:
        # Simulates a crash between issuing a call and reconciling it: the
        # ledger, freshly loaded ("on next startup"), still has one
        # "reserved" entry that was never flipped to "actual".
        orphaned = [_entry(session_id="s1", month="2026-08", status="reserved", projected=0.75)]
        spent = bl.month_spent_usd(orphaned, "2026-08")
        self.assertAlmostEqual(spent, 0.75, places=6, msg="orphaned reserved entry must count at its projected value")

        session_spent = bl.session_spent_usd(orphaned, "s1")
        self.assertAlmostEqual(session_spent, 0.75, places=6)

        # And it correctly constrains a subsequent pre-call check.
        result = bl.pre_call_check(orphaned, session_id="s1", projected_cost_usd=1.0, session_budget=1.50, now=datetime(2026, 8, 15, tzinfo=timezone.utc))
        self.assertFalse(result.allowed)


class ReleaseEntryTest(unittest.TestCase):
    """A 401/403/429 is REJECTED before token processing -- confirmed $0
    real cost, not an unknown outcome (see OrphanedReservedEntryTest above,
    which is the genuinely-unknown-outcome case: those two must NOT be
    treated the same way, or repeated auth failures would burn real budget
    on calls that never ran)."""

    def test_released_entry_counts_as_zero_not_projected_value(self) -> None:
        now = datetime(2026, 8, 15, tzinfo=timezone.utc)
        reserved = bl.reserve_entry(session_id="s1", turn_index=0, projected_cost_usd=1.20, now=now)
        released = bl.release_entry(reserved, reason="HTTP 401: Unauthorized", now=now)

        self.assertEqual(released["status"], bl.STATUS_RELEASED)
        self.assertEqual(released["actual_cost_usd"], 0.0)
        self.assertEqual(released["entry_id"], reserved["entry_id"])

        entries = [released]
        self.assertEqual(bl.month_spent_usd(entries, "2026-08"), 0.0)
        self.assertEqual(bl.session_spent_usd(entries, "s1"), 0.0)

    def test_released_entry_never_blocks_a_subsequent_call_the_way_a_reserved_one_would(self) -> None:
        # Same projected cost, same session/month -- the ONLY difference is
        # released vs reserved. A reserved entry this size correctly blocks
        # a follow-up call (OrphanedReservedEntryTest proves that); a
        # released one must not, since it is confirmed $0, not unknown.
        now = datetime(2026, 8, 15, tzinfo=timezone.utc)
        reserved = bl.reserve_entry(session_id="s1", turn_index=0, projected_cost_usd=1.0, now=now)
        released = bl.release_entry(reserved, reason="HTTP 429: Too Many Requests", now=now)

        result = bl.pre_call_check([released], session_id="s1", projected_cost_usd=0.4, session_budget=1.50, now=now)
        self.assertTrue(result.allowed)

    def test_release_does_not_mutate_the_original_entry(self) -> None:
        reserved = bl.reserve_entry(session_id="s1", turn_index=0, projected_cost_usd=0.50)
        bl.release_entry(reserved, reason="HTTP 403: Forbidden")
        self.assertEqual(reserved["status"], bl.STATUS_RESERVED)  # unchanged

    def test_release_reason_is_recorded(self) -> None:
        reserved = bl.reserve_entry(session_id="s1", turn_index=0, projected_cost_usd=0.50)
        released = bl.release_entry(reserved, reason="HTTP 401: Unauthorized")
        self.assertIn("401", released["release_reason"])

    def test_repeated_auth_failures_never_accumulate_spend(self) -> None:
        # The exact scenario this fix exists to prevent: N released entries
        # from N repeated 401s must never sum to nonzero spend, unlike N
        # orphaned reserved entries (which correctly WOULD sum, conservatively).
        now = datetime(2026, 8, 15, tzinfo=timezone.utc)
        released_entries = [
            bl.release_entry(bl.reserve_entry(session_id="s1", turn_index=i, projected_cost_usd=1.0, now=now), reason="HTTP 401", now=now)
            for i in range(5)
        ]
        self.assertEqual(bl.month_spent_usd(released_entries, "2026-08"), 0.0)
        self.assertEqual(bl.session_spent_usd(released_entries, "s1"), 0.0)


class SessionBudgetEnvVarTest(unittest.TestCase):
    def test_defaults_when_unset(self) -> None:
        self.assertEqual(bl.session_budget_usd(env={}), bl.DEFAULT_SESSION_BUDGET_USD)

    def test_reads_env_var(self) -> None:
        self.assertAlmostEqual(bl.session_budget_usd(env={"EVE_SESSION_BUDGET_USD": "2.75"}), 2.75, places=6)

    def test_falls_back_on_unparseable_value(self) -> None:
        self.assertEqual(bl.session_budget_usd(env={"EVE_SESSION_BUDGET_USD": "not-a-number"}), bl.DEFAULT_SESSION_BUDGET_USD)


class LedgerPersistenceTest(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile
        from pathlib import Path

        self._tmpdir = tempfile.TemporaryDirectory()
        self.ledger_path = Path(self._tmpdir.name) / "eve_budget_ledger.json"
        from unittest.mock import patch

        self._patch = patch("nero_core.eve.storage.DEFAULT_BUDGET_LEDGER_PATH", self.ledger_path)
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmpdir.cleanup()

    def test_append_then_update_roundtrip(self) -> None:
        reserved = bl.reserve_entry(session_id="s1", turn_index=0, projected_cost_usd=0.30)
        bl.append_entry(reserved, path=self.ledger_path)

        loaded = bl.load_ledger(path=self.ledger_path)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["status"], bl.STATUS_RESERVED)

        reconciled = bl.reconcile_entry(reserved, {"input_tokens": 100, "output_tokens": 100})
        bl.update_entry(reserved["entry_id"], reconciled, path=self.ledger_path)

        loaded_again = bl.load_ledger(path=self.ledger_path)
        self.assertEqual(len(loaded_again), 1, "update must replace, not append")
        self.assertEqual(loaded_again[0]["status"], bl.STATUS_ACTUAL)

    def test_update_unknown_entry_id_raises(self) -> None:
        with self.assertRaises(ValueError):
            bl.update_entry("does-not-exist", {}, path=self.ledger_path)


if __name__ == "__main__":
    unittest.main()
