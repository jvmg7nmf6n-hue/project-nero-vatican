from __future__ import annotations

import unittest
from datetime import datetime, timezone

from nero_core.eve import scoring


class DerivativeTagTest(unittest.TestCase):
    def test_near_identical_mechanism_text_is_flagged(self) -> None:
        raw = {"hypothesis_name": "ZSCORE_REVERSION_BTC", "mechanism": "price reverts to the mean after an extreme zscore deviation on high volume"}
        adam_history = [{"hypothesis_name": "ZSCORE_MEAN_REVERT_BTC", "mechanism": "price reverts to the mean after an extreme zscore deviation on high volume"}]
        flags = scoring.tag_derivative(raw, adam_history)
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0]["tag"], "DERIVATIVE")
        self.assertEqual(flags[0]["matched_hypothesis_name"], "ZSCORE_MEAN_REVERT_BTC")

    def test_unrelated_mechanism_text_is_not_flagged(self) -> None:
        raw = {"hypothesis_name": "FUNDING_EXTREME", "mechanism": "perpetual funding rate reaches an extreme, forcing leveraged unwind"}
        adam_history = [{"hypothesis_name": "SEASONAL_TURN_OF_MONTH", "mechanism": "calendar effect around month-end rebalancing flows"}]
        flags = scoring.tag_derivative(raw, adam_history)
        self.assertEqual(flags, [])

    def test_empty_history_never_flags_anything(self) -> None:
        raw = {"hypothesis_name": "X", "mechanism": "anything at all"}
        self.assertEqual(scoring.tag_derivative(raw, []), [])

    def test_threshold_is_respected(self) -> None:
        raw = {"hypothesis_name": "A", "mechanism": "one two three four five"}
        adam_history = [{"hypothesis_name": "B", "mechanism": "one two three six seven"}]
        flags_strict = scoring.tag_derivative(raw, adam_history, threshold=0.99)
        flags_loose = scoring.tag_derivative(raw, adam_history, threshold=0.1)
        self.assertEqual(flags_strict, [])
        self.assertGreaterEqual(len(flags_loose), 1)

    def test_never_gates_only_informational(self) -> None:
        # tag_derivative returns tags; it has no return value that could be
        # interpreted as "reject this hypothesis" -- confirmed structurally:
        # it always returns a list, never raises, never returns a bool.
        raw = {"hypothesis_name": "X", "mechanism": "identical text"}
        adam_history = [{"hypothesis_name": "Y", "mechanism": "identical text"}]
        result = scoring.tag_derivative(raw, adam_history)
        self.assertIsInstance(result, list)


class ApplyDerivativeTagsTest(unittest.TestCase):
    def test_tags_attached_to_correct_record(self) -> None:
        records = [
            {"raw_hypothesis": {"hypothesis_name": "A", "mechanism": "shared exact text here"}, "contamination_tags": []},
            {"raw_hypothesis": {"hypothesis_name": "B", "mechanism": "completely different unrelated content xyz"}, "contamination_tags": []},
        ]
        adam_history = [{"hypothesis_name": "PRIOR", "mechanism": "shared exact text here"}]
        updated = scoring.apply_derivative_tags(records, adam_history)
        self.assertTrue(any(t["tag"] == "DERIVATIVE" for t in updated[0]["contamination_tags"]))
        self.assertEqual(updated[1]["contamination_tags"], [])

    def test_does_not_mutate_input(self) -> None:
        records = [{"raw_hypothesis": {"hypothesis_name": "A", "mechanism": "x"}, "contamination_tags": []}]
        scoring.apply_derivative_tags(records, [])
        self.assertEqual(records[0]["contamination_tags"], [])


class SelfDerivativeTagTest(unittest.TestCase):
    """CC-1 review, item 1: confirmed gap -- eve_hypotheses.json was
    write-only, tag_derivative was only ever called with adam_history, and
    nothing stopped Eve re-proposing her own past idea and having it
    counted as a fresh independent data point. apply_self_derivative_tags
    reuses tag_derivative (and its 0.6 threshold) byte-identically, only
    the tag_name and the history source differ."""

    def test_near_identical_own_prior_hypothesis_is_flagged_self_derivative(self) -> None:
        raw = {"hypothesis_name": "ZSCORE_REVERSION_BTC_V2", "mechanism": "price reverts to the mean after an extreme zscore deviation on high volume"}
        eve_history = [{"hypothesis_name": "ZSCORE_REVERSION_BTC", "mechanism": "price reverts to the mean after an extreme zscore deviation on high volume"}]
        flags = scoring.tag_derivative(raw, eve_history, tag_name=scoring.SELF_DERIVATIVE_TAG_NAME)
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0]["tag"], "SELF_DERIVATIVE")
        self.assertEqual(flags[0]["matched_hypothesis_name"], "ZSCORE_REVERSION_BTC")

    def test_uses_the_same_threshold_constant_as_the_adam_check(self) -> None:
        # "REUSING tag_derivative and the same 0.6 lexical threshold
        # byte-identically -- same discipline as WEB_SEARCH_TOOL's reuse.
        # Do not reinvent the similarity method." -- explicit instruction.
        import inspect

        sig = inspect.signature(scoring.tag_derivative)
        self.assertEqual(sig.parameters["threshold"].default, 0.6)
        self.assertEqual(scoring.DERIVATIVE_SIMILARITY_THRESHOLD, 0.6)

    def test_adam_derivative_and_self_derivative_are_distinct_tag_names(self) -> None:
        self.assertNotEqual(scoring.DERIVATIVE_TAG_NAME, scoring.SELF_DERIVATIVE_TAG_NAME)
        self.assertEqual(scoring.DERIVATIVE_TAG_NAME, "DERIVATIVE")
        self.assertEqual(scoring.SELF_DERIVATIVE_TAG_NAME, "SELF_DERIVATIVE")


class ApplySelfDerivativeTagsTest(unittest.TestCase):
    def test_tags_attached_to_correct_record_with_self_derivative_name(self) -> None:
        records = [
            {"raw_hypothesis": {"hypothesis_name": "A", "mechanism": "shared exact text here"}, "contamination_tags": []},
            {"raw_hypothesis": {"hypothesis_name": "B", "mechanism": "completely different unrelated content xyz"}, "contamination_tags": []},
        ]
        eve_history = [{"hypothesis_name": "MY_OWN_PRIOR_IDEA", "mechanism": "shared exact text here"}]
        updated = scoring.apply_self_derivative_tags(records, eve_history)
        self.assertTrue(scoring.is_self_derivative(updated[0]))
        self.assertEqual(updated[0]["contamination_tags"][0]["tag"], "SELF_DERIVATIVE")
        self.assertEqual(updated[0]["contamination_tags"][0]["matched_hypothesis_name"], "MY_OWN_PRIOR_IDEA")
        self.assertFalse(scoring.is_self_derivative(updated[1]))

    def test_does_not_mutate_input(self) -> None:
        records = [{"raw_hypothesis": {"hypothesis_name": "A", "mechanism": "x"}, "contamination_tags": []}]
        scoring.apply_self_derivative_tags(records, [])
        self.assertEqual(records[0]["contamination_tags"], [])

    def test_hypothesis_never_flagged_against_unrelated_eve_history(self) -> None:
        records = [{"raw_hypothesis": {"hypothesis_name": "FUNDING_EXTREME", "mechanism": "perpetual funding rate reaches an extreme"}, "contamination_tags": []}]
        eve_history = [{"hypothesis_name": "SEASONAL_TURN_OF_MONTH", "mechanism": "calendar effect around month-end rebalancing flows"}]
        updated = scoring.apply_self_derivative_tags(records, eve_history)
        self.assertFalse(scoring.is_self_derivative(updated[0]))

    def test_can_coexist_with_a_real_adam_derivative_tag_on_the_same_record(self) -> None:
        # A hypothesis can converge with BOTH Adam's history and Eve's own
        # -- the two tags are independent and both must be able to appear.
        records = [{"raw_hypothesis": {"hypothesis_name": "X", "mechanism": "shared text everywhere"}, "contamination_tags": []}]
        adam_history = [{"hypothesis_name": "ADAM_PRIOR", "mechanism": "shared text everywhere"}]
        eve_history = [{"hypothesis_name": "EVE_PRIOR", "mechanism": "shared text everywhere"}]
        with_adam = scoring.apply_derivative_tags(records, adam_history)
        with_both = scoring.apply_self_derivative_tags(with_adam, eve_history)
        tags = {t["tag"] for t in with_both[0]["contamination_tags"]}
        self.assertEqual(tags, {"DERIVATIVE", "SELF_DERIVATIVE"})


class LookaheadRiskTagTest(unittest.TestCase):
    def _session_with_search_result(self, page_age: str) -> dict:
        return {
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
            ]
        }

    def test_source_dated_after_window_start_is_flagged(self) -> None:
        session_record = self._session_with_search_result("2027-01-01")
        flags = scoring.tag_lookahead_risk(session_record, backtest_window_start=datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0]["tag"], "LOOKAHEAD_RISK")
        self.assertEqual(flags[0]["url"], "https://example.com/a")

    def test_source_dated_before_window_start_is_not_flagged(self) -> None:
        session_record = self._session_with_search_result("2020-01-01")
        flags = scoring.tag_lookahead_risk(session_record, backtest_window_start=datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(flags, [])

    def test_unparseable_date_is_never_flagged_or_crashed_on(self) -> None:
        session_record = self._session_with_search_result("sometime last year")
        flags = scoring.tag_lookahead_risk(session_record, backtest_window_start=datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(flags, [])

    def test_session_with_no_search_results_returns_no_flags(self) -> None:
        session_record = {"turns": [{"turn_index": 0, "raw_response": {"content": [{"type": "text", "text": "no search here"}]}}]}
        flags = scoring.tag_lookahead_risk(session_record, backtest_window_start=datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(flags, [])

    def test_flags_never_discard_only_flag(self) -> None:
        # Structural guarantee: tag_lookahead_risk only ever returns
        # ADDITIONAL information (a list of flags) -- it has no code path
        # that removes or alters the session_record it's given.
        session_record = self._session_with_search_result("2027-01-01")
        original = dict(session_record)
        scoring.tag_lookahead_risk(session_record, backtest_window_start=datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(session_record, original)


if __name__ == "__main__":
    unittest.main()
