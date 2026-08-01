"""Repair Lab v1, Task 3: the cheap, chain-scoped duplicate check -- exact
StructuredRule/ExitPlan equality against the original hypothesis and every
prior attempt in the SAME chain, never a global cross-hypothesis check."""
from __future__ import annotations

import unittest

from nero_core.research_agent.repair_lab import check_in_chain_duplicate

ORIGINAL = {
    "hypothesis_name": "EXT_WISE_MAN_HOLD_V5_ETH_4H", "asset": "ETH", "timeframe": "4h",
    "structured_entry_rule": {
        "conditions": [
            {"field": "close", "op": "lt", "compare_to_field": "bb_lower"},
            {"field": "adx14", "op": "lt", "value": 25.0},
        ],
    },
    "structured_entry_rule_short": None,
    "structured_exit_plan": {"stop_pct_of_entry": 0.015, "target_pct_of_entry": 0.03},
}

ATTEMPT_1 = {
    "attempt_id": "RC-EXT_WISE_MAN_HOLD_V5_ETH_4H-001-A1",
    "structured_entry_rule": {
        "conditions": [
            {"field": "close", "op": "lt", "compare_to_field": "bb_lower"},
            {"field": "adx14", "op": "lt", "value": 20.0},  # retuned from 25.0
        ],
    },
    "structured_entry_rule_short": None,
    "structured_exit_plan": {"stop_pct_of_entry": 0.015, "target_pct_of_entry": 0.03},
}


class InChainDuplicateTest(unittest.TestCase):
    def test_a_genuinely_different_proposal_is_not_a_duplicate(self) -> None:
        proposal = {
            "structured_entry_rule": {
                "conditions": [
                    {"field": "close", "op": "lt", "compare_to_field": "bb_lower"},
                    {"field": "adx14", "op": "lt", "value": 15.0},
                ],
            },
            "structured_entry_rule_short": None,
            "structured_exit_plan": {"stop_pct_of_entry": 0.015, "target_pct_of_entry": 0.03},
        }
        result = check_in_chain_duplicate(proposal, ORIGINAL, [ATTEMPT_1])
        self.assertFalse(result.is_duplicate)

    def test_byte_identical_to_the_original_hypothesis_is_rejected(self) -> None:
        proposal = dict(ORIGINAL)  # same rule/exit as the original -- nothing changed
        result = check_in_chain_duplicate(proposal, ORIGINAL, [])
        self.assertTrue(result.is_duplicate)
        self.assertEqual(result.matched_attempt_id, "original")
        self.assertIn("byte-identical", result.reason)

    def test_byte_identical_to_a_prior_attempt_is_rejected(self) -> None:
        proposal = dict(ATTEMPT_1)
        result = check_in_chain_duplicate(proposal, ORIGINAL, [ATTEMPT_1])
        self.assertTrue(result.is_duplicate)
        self.assertEqual(result.matched_attempt_id, ATTEMPT_1["attempt_id"])

    def test_a_repeat_of_attempt_1_is_caught_even_when_attempt_2_exists_in_between(self) -> None:
        attempt_2 = {
            "attempt_id": "...-A2",
            "structured_entry_rule": ORIGINAL["structured_entry_rule"],
            "structured_entry_rule_short": {
                "conditions": [
                    {"field": "close", "op": "gt", "compare_to_field": "bb_upper"},
                    {"field": "adx14", "op": "lt", "value": 25.0},
                ],
            },
            "structured_exit_plan": ORIGINAL["structured_exit_plan"],
        }
        proposal_repeating_attempt_1 = dict(ATTEMPT_1)
        result = check_in_chain_duplicate(proposal_repeating_attempt_1, ORIGINAL, [ATTEMPT_1, attempt_2])
        self.assertTrue(result.is_duplicate)
        self.assertEqual(result.matched_attempt_id, ATTEMPT_1["attempt_id"])

    def test_differing_only_in_the_short_leg_is_not_a_duplicate(self) -> None:
        # ATTEMPT_1 has no short leg; adding one (even with the same long rule
        # threshold) is a genuinely different proposal -- must not be flagged.
        proposal = {
            "structured_entry_rule": ATTEMPT_1["structured_entry_rule"],
            "structured_entry_rule_short": {
                "conditions": [
                    {"field": "close", "op": "gt", "compare_to_field": "bb_upper"},
                    {"field": "adx14", "op": "lt", "value": 20.0},
                ],
            },
            "structured_exit_plan": ATTEMPT_1["structured_exit_plan"],
        }
        result = check_in_chain_duplicate(proposal, ORIGINAL, [ATTEMPT_1])
        self.assertFalse(result.is_duplicate)

    def test_differing_only_in_exit_plan_is_not_a_duplicate(self) -> None:
        proposal = {
            "structured_entry_rule": ORIGINAL["structured_entry_rule"],
            "structured_entry_rule_short": None,
            "structured_exit_plan": {"stop_pct_of_entry": 0.02, "target_pct_of_entry": 0.03},
        }
        result = check_in_chain_duplicate(proposal, ORIGINAL, [])
        self.assertFalse(result.is_duplicate)

    def test_an_unparseable_proposal_reports_cannot_compare_not_a_false_duplicate(self) -> None:
        proposal = {"structured_entry_rule": {"conditions": []}, "structured_entry_rule_short": None, "structured_exit_plan": {}}
        result = check_in_chain_duplicate(proposal, ORIGINAL, [ATTEMPT_1])
        self.assertFalse(result.is_duplicate)
        self.assertIn("cannot compare", result.reason)


if __name__ == "__main__":
    unittest.main()
