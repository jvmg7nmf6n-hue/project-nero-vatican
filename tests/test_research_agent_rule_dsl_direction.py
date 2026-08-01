"""feature/short-side-support Task 5: dedicated tests for rule_dsl.py's new
direction-declaration mechanism (Task 1's design) -- parse_bidirectional_
entry_rules and mirror_condition. rule_dsl.py's own docstring for these two
functions already references this file by name (see mirror_condition's
"see test_research_agent_rule_dsl_direction.py's own completeness check")."""
from __future__ import annotations

import unittest

from nero_core.research_agent.rule_dsl import (
    ALLOWED_OPS,
    Condition,
    RuleAmbiguousError,
    StructuredRule,
    _OP_MIRROR,
    mirror_condition,
    parse_bidirectional_entry_rules,
    parse_structured_rule,
)

LONG_RULE_RAW = {
    "conditions": [
        {"field": "close", "op": "lt", "compare_to_field": "bb_lower"},
        {"field": "adx14", "op": "lt", "value": 25.0},
    ],
}
SHORT_RULE_RAW = {
    "conditions": [
        {"field": "close", "op": "gt", "compare_to_field": "bb_upper"},
        {"field": "adx14", "op": "lt", "value": 25.0},
    ],
}


class ParseBidirectionalEntryRulesTest(unittest.TestCase):
    def test_long_only_hypothesis_returns_the_parsed_long_rule_and_none_for_short(self) -> None:
        hypothesis = {"structured_entry_rule": LONG_RULE_RAW}
        long_rule, short_rule = parse_bidirectional_entry_rules(hypothesis)
        self.assertEqual(long_rule, parse_structured_rule(LONG_RULE_RAW))
        self.assertIsNone(short_rule)

    def test_explicit_none_short_key_is_treated_identically_to_the_key_being_absent(self) -> None:
        # tools/external_candidates_formal_test.py's 3 WISE_MAN candidates set
        # "structured_entry_rule_short": None explicitly (rather than omitting
        # the key) -- must behave exactly like omission, not raise.
        hypothesis = {"structured_entry_rule": LONG_RULE_RAW, "structured_entry_rule_short": None}
        long_rule, short_rule = parse_bidirectional_entry_rules(hypothesis)
        self.assertEqual(long_rule, parse_structured_rule(LONG_RULE_RAW))
        self.assertIsNone(short_rule)

    def test_bidirectional_hypothesis_parses_both_rules_independently(self) -> None:
        hypothesis = {"structured_entry_rule": LONG_RULE_RAW, "structured_entry_rule_short": SHORT_RULE_RAW}
        long_rule, short_rule = parse_bidirectional_entry_rules(hypothesis)
        self.assertEqual(long_rule, parse_structured_rule(LONG_RULE_RAW))
        self.assertEqual(short_rule, parse_structured_rule(SHORT_RULE_RAW))

    def test_an_ambiguous_long_rule_still_raises_exactly_as_parse_structured_rule_would(self) -> None:
        with self.assertRaises(RuleAmbiguousError):
            parse_bidirectional_entry_rules({"structured_entry_rule": {"conditions": []}})

    def test_an_ambiguous_short_rule_also_raises_not_silently_dropped(self) -> None:
        hypothesis = {
            "structured_entry_rule": LONG_RULE_RAW,
            "structured_entry_rule_short": {"conditions": [{"field": "not_a_real_field", "op": "gt", "value": 1.0}]},
        }
        with self.assertRaises(RuleAmbiguousError):
            parse_bidirectional_entry_rules(hypothesis)

    def test_missing_long_rule_key_raises_the_same_as_passing_none_to_parse_structured_rule(self) -> None:
        with self.assertRaises(RuleAmbiguousError):
            parse_bidirectional_entry_rules({})


class MirrorConditionTest(unittest.TestCase):
    def test_every_allowed_op_has_exactly_one_mirror_entry(self) -> None:
        self.assertEqual(set(_OP_MIRROR.keys()), set(ALLOWED_OPS))

    def test_mirroring_is_its_own_inverse_for_every_op(self) -> None:
        for op in ALLOWED_OPS:
            with self.subTest(op=op):
                self.assertEqual(_OP_MIRROR[_OP_MIRROR[op]], op)

    def test_gt_mirrors_to_lt_and_back(self) -> None:
        c = Condition(field="close", op="gt", value=100.0)
        mirrored = mirror_condition(c)
        self.assertEqual(mirrored, Condition(field="close", op="lt", value=100.0))
        self.assertEqual(mirror_condition(mirrored), c)

    def test_gte_mirrors_to_lte_and_back(self) -> None:
        c = Condition(field="adx14", op="gte", value=28.0)
        mirrored = mirror_condition(c)
        self.assertEqual(mirrored, Condition(field="adx14", op="lte", value=28.0))
        self.assertEqual(mirror_condition(mirrored), c)

    def test_eq_mirrors_to_itself(self) -> None:
        c = Condition(field="close", op="eq", value=100.0)
        self.assertEqual(mirror_condition(c), c)

    def test_cross_above_mirrors_to_cross_below_and_back(self) -> None:
        c = Condition(field="ma20", op="cross_above", compare_to_field="ma50")
        mirrored = mirror_condition(c)
        self.assertEqual(mirrored, Condition(field="ma20", op="cross_below", compare_to_field="ma50"))
        self.assertEqual(mirror_condition(mirrored), c)

    def test_mirroring_preserves_field_and_value_only_flips_op(self) -> None:
        c = Condition(field="close", op="gte", compare_to_field="ma20")
        mirrored = mirror_condition(c)
        self.assertEqual(mirrored.field, c.field)
        self.assertEqual(mirrored.compare_to_field, c.compare_to_field)
        self.assertIsNone(mirrored.value)
        self.assertNotEqual(mirrored.op, c.op)


if __name__ == "__main__":
    unittest.main()
