"""Phase E of the CC-1 substitution investigation-only audit
(docs/investigations/phase_e_mirror_eq_boundary.md): does
_is_legitimate_direction_mirror correctly REJECT a proposed short rule that
keeps the "eq" op but changes its value? rule_dsl._OP_MIRROR maps
"eq" -> "eq" (an eq condition has no directional mirror), so a value change
on an eq condition should never be a legitimate mirror -- there is no
"short-side interpretation" of equality the way there is for gt/lt.

This is a NEW, additive test file -- it does not modify
nero_core/research_agent/rule_dsl.py or any existing rule_dsl test file."""
from __future__ import annotations

import unittest

from nero_core.research_agent.repair_lab import _is_legitimate_direction_mirror
from nero_core.research_agent.rule_dsl import Condition, StructuredRule


class MirrorEqBoundaryTest(unittest.TestCase):
    def test_an_eq_condition_with_a_changed_value_is_not_a_legitimate_mirror(self) -> None:
        """rsi14 eq 50.0 (original) vs. rsi14 eq 30.0 (proposed short) --
        same field, same op, DIFFERENT value. eq has no directional mirror
        (_OP_MIRROR["eq"] == "eq"), so this is a threshold change smuggled
        in under the direction_add_mirror label, not a legitimate mirror of
        the same mechanism on the opposite side. This must be REJECTED."""
        long_rule = StructuredRule(conditions=(Condition(field="rsi14", op="eq", value=50.0),))
        proposed_short = StructuredRule(conditions=(Condition(field="rsi14", op="eq", value=30.0),))

        result = _is_legitimate_direction_mirror(long_rule, proposed_short)
        self.assertFalse(
            result,
            "An eq condition with a changed value has no legitimate directional mirror "
            "(eq maps to eq in _OP_MIRROR) and must be rejected, not approved.",
        )

    def test_an_eq_condition_with_the_same_value_is_still_a_legitimate_mirror(self) -> None:
        """Sanity check the other direction: eq unchanged (a shared gate,
        the ONLY legitimate use of eq in a mirrored rule) must still be
        approved -- this phase is about the value-CHANGE case specifically,
        not about eq conditions being unmirrorable in general."""
        long_rule = StructuredRule(conditions=(Condition(field="rsi14", op="eq", value=50.0),))
        proposed_short = StructuredRule(conditions=(Condition(field="rsi14", op="eq", value=50.0),))

        result = _is_legitimate_direction_mirror(long_rule, proposed_short)
        self.assertTrue(result, "An eq condition left completely unchanged must still be approved.")


if __name__ == "__main__":
    unittest.main()
