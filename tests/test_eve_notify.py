from __future__ import annotations

import unittest
from unittest.mock import patch

from nero_core.eve import notify


class BuildSessionSummaryMessageTest(unittest.TestCase):
    def test_includes_every_required_field(self) -> None:
        message = notify.build_session_summary_message(
            session_id="eve-20260803T120000Z-abcd1234",
            terminated_because="end_session_called",
            n_proposed=3,
            n_testable=2,
            verdict_counts={"DIED": 1, "SURVIVED": 1},
            real_cost_usd=0.8765,
            session_file_path="docs/site_data/eve_sessions/eve-20260803T120000Z-abcd1234.json",
        )

        self.assertIn("eve-20260803T120000Z-abcd1234", message)
        self.assertIn("end_session_called", message)
        self.assertIn("Proposed 3 hypotheses", message)
        self.assertIn("2 testable", message)
        self.assertIn("DIED=1", message)
        self.assertIn("SURVIVED=1", message)
        self.assertIn("$0.8765", message)
        self.assertIn("docs/site_data/eve_sessions/eve-20260803T120000Z-abcd1234.json", message)

    def test_zero_testable_hypotheses_says_so_plainly(self) -> None:
        message = notify.build_session_summary_message(
            session_id="s1", terminated_because="end_session_called", n_proposed=1, n_testable=0,
            verdict_counts={}, real_cost_usd=0.1, session_file_path="x.json",
        )
        self.assertIn("(none testable)", message)


class BuildFailureMessageTest(unittest.TestCase):
    def test_includes_session_id_when_known(self) -> None:
        message = notify.build_failure_message("crash: RuntimeError: boom", session_id="eve-123", cost_hint_usd=0.02)
        self.assertIn("eve-123", message)
        self.assertIn("FAILED", message)
        self.assertIn("boom", message)
        self.assertIn("$0.0200", message)

    def test_omits_session_id_gracefully_when_unknown(self) -> None:
        message = notify.build_failure_message("crash: RuntimeError: boom before session_id was assigned")
        self.assertIn("FAILED", message)
        self.assertIn("before a session id was assigned", message)

    def test_unknown_cost_says_so_rather_than_fabricating_zero(self) -> None:
        message = notify.build_failure_message("crash: boom", session_id="eve-123", cost_hint_usd=None)
        self.assertIn("unknown", message)
        self.assertIn("eve_budget_ledger.json", message)


class SendFunctionsTest(unittest.TestCase):
    def test_send_session_summary_calls_the_real_ntfy_path_with_the_built_message(self) -> None:
        with patch.object(notify, "send_ntfy_notification", return_value=True) as mock_send:
            ok = notify.send_session_summary(
                session_id="s1", terminated_because="end_session_called", n_proposed=1, n_testable=1,
                verdict_counts={"DIED": 1}, real_cost_usd=0.5, session_file_path="x.json",
            )

        self.assertTrue(ok)
        mock_send.assert_called_once()
        (message,), kwargs = mock_send.call_args
        self.assertIn("s1", message)
        self.assertEqual(kwargs["url"], notify.NTFY_URL)

    def test_send_failure_calls_the_real_ntfy_path_with_the_built_message(self) -> None:
        with patch.object(notify, "send_ntfy_notification", return_value=True) as mock_send:
            ok = notify.send_failure("preflight_rejected: HTTP 401", cost_hint_usd=0.0)

        self.assertTrue(ok)
        mock_send.assert_called_once()
        (message,), kwargs = mock_send.call_args
        self.assertIn("preflight_rejected", message)
        self.assertEqual(kwargs["url"], notify.NTFY_URL)

    def test_send_failure_propagates_a_delivery_failure_as_false_never_raises(self) -> None:
        with patch.object(notify, "send_ntfy_notification", return_value=False):
            ok = notify.send_failure("some reason")
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
