"""feature/philosophy-hypotheses-dsl-check, Task 1/2 expansion: risk-reward
variants of WISE_MAN_ASYMMETRIC_HOLD (percentage-shape ExitPlan, all sharing
the RANGE_MEAN_REVERSION entry) and regime-threshold variants of
ADX_GATED_RANGE_PERSISTENCE. Parse-ONLY validation, same as this branch's
first two hypotheses -- no frequency_gate/auto_tester call anywhere in this
file. No new DSL mechanism is exercised here; every variant reuses
stop_pct_of_entry/target_pct_of_entry (Task 1) or the regime_break_condition/
max_holding_hours combination (Task 2) exactly as already built and tested in
test_research_agent_exitplan_percentage_shape.py /
test_research_agent_philosophy_hypotheses_parsing.py.

DUPLICATE-DETECTION FINDING (see DuplicateDetectionDoesNotApplyToManuallyAuthored
HypothesesTest below): hypothesis_gen.check_duplicate is called from exactly one
function in this codebase -- hypothesis_gen.generate_hypotheses,
the scanner-driven LLM generation path (twice within it: a preflight check,
then the real per-finding check). It is never invoked for a manually
constructed hypothesis dict (there is no code path that would call it here).
Its matching key is also (scan_finding_type, asset, timeframe) -- the scan
finding's own ORIGIN metadata -- never structured_entry_rule/structured_
exit_plan content, so even a hypothetical caller feeding it manually-authored
records would not catch WISE_MAN_HOLD_V9 being numerically identical to
WISE_MAN_HOLD_V2/WISE_MAN_ASYMMETRIC_HOLD. This file's own manual duplicate
note (KNOWN_DUPLICATE_CLUSTERS below) is therefore the only mechanism that
currently catches this -- not a gap this branch is asked to close, just one
to report honestly.
"""
from __future__ import annotations

import unittest

from nero_core.research_agent.hypothesis_gen import check_duplicate
from nero_core.research_agent.rule_dsl import Condition, ExitPlan, StructuredRule, parse_exit_plan, parse_structured_rule
from nero_core.research_agent.scanner import ScanFinding
from tests.test_research_agent_philosophy_hypotheses_parsing import ADX_GATED_RANGE_PERSISTENCE, WISE_MAN_ASYMMETRIC_HOLD

# Shared by every WISE_MAN_HOLD_V* variant -- identical to WISE_MAN_ASYMMETRIC_HOLD's own
# entry (RANGE_MEAN_REVERSION's LONG entry: close < bb_lower AND adx14 < 25).
WISE_MAN_HOLD_ENTRY_RULE = {
    "conditions": [
        {"field": "close", "op": "lt", "compare_to_field": "bb_lower"},
        {"field": "adx14", "op": "lt", "value": 25.0},
    ],
}

# (name, target_pct_of_entry, stop_pct_of_entry). GROUP A: stop and target both vary.
# GROUP B: target fixed at 1%, stop varies. V2 is numerically identical to the already-
# built WISE_MAN_ASYMMETRIC_HOLD (target 1%, stop 3%); V9 is numerically identical to V2
# -- see KNOWN_DUPLICATE_CLUSTERS below, both deliberate per this branch's own task spec,
# not an authoring mistake.
_WISE_MAN_HOLD_SPECS = [
    ("WISE_MAN_HOLD_V1", 0.008, 0.040),
    ("WISE_MAN_HOLD_V2", 0.010, 0.030),
    ("WISE_MAN_HOLD_V3", 0.015, 0.030),
    ("WISE_MAN_HOLD_V4", 0.020, 0.020),
    ("WISE_MAN_HOLD_V5", 0.030, 0.015),
    ("WISE_MAN_HOLD_V6", 0.010, 0.010),
    ("WISE_MAN_HOLD_V7", 0.010, 0.015),
    ("WISE_MAN_HOLD_V8", 0.010, 0.020),
    ("WISE_MAN_HOLD_V9", 0.010, 0.030),
    ("WISE_MAN_HOLD_V10", 0.010, 0.040),
]

WISE_MAN_HOLD_VARIANTS = {
    name: {
        "hypothesis_name": name,
        "structured_entry_rule": WISE_MAN_HOLD_ENTRY_RULE,
        "structured_exit_plan": {"stop_pct_of_entry": stop_pct, "target_pct_of_entry": target_pct},
        # max_holding_hours omitted on every variant -- no time cap, same as WISE_MAN_ASYMMETRIC_HOLD.
    }
    for name, target_pct, stop_pct in _WISE_MAN_HOLD_SPECS
}

# Manually-authored duplicate note (see module docstring) -- no automated mechanism
# catches this for hand-built records. Both directions recorded so either name can be
# looked up.
KNOWN_DUPLICATE_CLUSTERS = {
    "WISE_MAN_HOLD_V2": ["WISE_MAN_HOLD_V9", "WISE_MAN_ASYMMETRIC_HOLD"],
    "WISE_MAN_HOLD_V9": ["WISE_MAN_HOLD_V2", "WISE_MAN_ASYMMETRIC_HOLD"],
}

# (name, adx14 entry threshold). V2 (< 20) is numerically identical to the already-built
# ADX_GATED_RANGE_PERSISTENCE -- CORRECTION to the task spec's own labeling: that
# hypothesis's entry is adx14 < 20 (matching this scheme's V2), not adx14 < 25 (V3) --
# the < 25 value in the built version is regime_break_condition's EXIT threshold, not the
# entry threshold. Flagged rather than silently renumbered.
_ADX_RANGE_SPECS = [
    ("ADX_RANGE_V1", 15.0),
    ("ADX_RANGE_V2", 20.0),
    ("ADX_RANGE_V3", 25.0),
    ("ADX_RANGE_V4", 30.0),
]

ADX_RANGE_VARIANTS = {
    name: {
        "hypothesis_name": name,
        "structured_entry_rule": {"conditions": [{"field": "adx14", "op": "lt", "value": entry_threshold}]},
        "structured_exit_plan": {
            "stop_atr_multiple": 2.0,
            "target_r_multiple": 50.0,  # PROXY, not a real profit target -- see ADX_GATED_RANGE_PERSISTENCE's own note.
            "regime_break_condition": {"field": "adx14", "op": "gte", "value": 25.0},
            "regime_break_consecutive_bars": 1,
            "max_holding_hours": 480.0,
        },
        "proxy_test_of": ADX_GATED_RANGE_PERSISTENCE["proxy_test_of"],
    }
    for name, entry_threshold in _ADX_RANGE_SPECS
}


class WiseManHoldVariantsParseTest(unittest.TestCase):
    def test_all_ten_variants_parse(self) -> None:
        for name, record in WISE_MAN_HOLD_VARIANTS.items():
            with self.subTest(hypothesis=name):
                rule = parse_structured_rule(record["structured_entry_rule"])
                self.assertEqual(
                    rule,
                    StructuredRule(conditions=(
                        Condition(field="close", op="lt", compare_to_field="bb_lower"),
                        Condition(field="adx14", op="lt", value=25.0),
                    )),
                )
                plan = parse_exit_plan(record["structured_exit_plan"])
                self.assertIsNone(plan.max_holding_hours)
                self.assertIsNone(plan.stop_atr_multiple)
                self.assertIsNone(plan.target_r_multiple)

    def test_variant_stop_and_target_values_match_the_spec(self) -> None:
        expected = {name: (target_pct, stop_pct) for name, target_pct, stop_pct in _WISE_MAN_HOLD_SPECS}
        for name, record in WISE_MAN_HOLD_VARIANTS.items():
            with self.subTest(hypothesis=name):
                plan = parse_exit_plan(record["structured_exit_plan"])
                expected_target, expected_stop = expected[name]
                self.assertEqual(plan.target_pct_of_entry, expected_target)
                self.assertEqual(plan.stop_pct_of_entry, expected_stop)

    def test_all_ten_hypothesis_names_are_unique(self) -> None:
        names = [record["hypothesis_name"] for record in WISE_MAN_HOLD_VARIANTS.values()]
        self.assertEqual(len(names), 10)
        self.assertEqual(len(set(names)), 10)

    def test_v9_is_numerically_identical_to_v2_and_to_the_original_built_hypothesis(self) -> None:
        plan_v2 = parse_exit_plan(WISE_MAN_HOLD_VARIANTS["WISE_MAN_HOLD_V2"]["structured_exit_plan"])
        plan_v9 = parse_exit_plan(WISE_MAN_HOLD_VARIANTS["WISE_MAN_HOLD_V9"]["structured_exit_plan"])
        plan_original = parse_exit_plan(WISE_MAN_ASYMMETRIC_HOLD["structured_exit_plan"])
        self.assertEqual(plan_v2, plan_v9)
        self.assertEqual(plan_v2, plan_original)
        self.assertEqual(plan_v2, ExitPlan(stop_pct_of_entry=0.03, target_pct_of_entry=0.01))
        # Different NAMES, identical parsed shape -- exactly the case an automated
        # content-based dedup would catch and this codebase's actual mechanism does not.
        self.assertNotEqual(
            WISE_MAN_HOLD_VARIANTS["WISE_MAN_HOLD_V2"]["hypothesis_name"],
            WISE_MAN_HOLD_VARIANTS["WISE_MAN_HOLD_V9"]["hypothesis_name"],
        )


class AdxRangeVariantsParseTest(unittest.TestCase):
    def test_all_four_variants_parse(self) -> None:
        for name, record in ADX_RANGE_VARIANTS.items():
            with self.subTest(hypothesis=name):
                rule = parse_structured_rule(record["structured_entry_rule"])
                plan = parse_exit_plan(record["structured_exit_plan"])
                self.assertEqual(plan.stop_atr_multiple, 2.0)
                self.assertEqual(plan.target_r_multiple, 50.0)
                self.assertEqual(plan.regime_break_condition, Condition(field="adx14", op="gte", value=25.0))
                self.assertEqual(plan.regime_break_consecutive_bars, 1)
                self.assertEqual(plan.max_holding_hours, 480.0)
                self.assertEqual(rule.conditions, (Condition(field="adx14", op="lt", value=self._threshold_for(name)),))

    @staticmethod
    def _threshold_for(name: str) -> float:
        return {"ADX_RANGE_V1": 15.0, "ADX_RANGE_V2": 20.0, "ADX_RANGE_V3": 25.0, "ADX_RANGE_V4": 30.0}[name]

    def test_proxy_label_carried_through_on_every_variant(self) -> None:
        for name, record in ADX_RANGE_VARIANTS.items():
            with self.subTest(hypothesis=name):
                self.assertIn("proxy_test_of", record)
                self.assertIn("NOT a genuine", record["proxy_test_of"])

    def test_v2_entry_threshold_matches_the_already_built_adx_gated_range_persistence(self) -> None:
        # Confirms the naming correction in this module's docstring: the already-built
        # hypothesis's entry is adx14 < 20, matching V2 here -- NOT adx14 < 25 (V3), which
        # is what the task spec's own labeling assumed.
        built_rule = parse_structured_rule(ADX_GATED_RANGE_PERSISTENCE["structured_entry_rule"])
        v2_rule = parse_structured_rule(ADX_RANGE_VARIANTS["ADX_RANGE_V2"]["structured_entry_rule"])
        self.assertEqual(built_rule, v2_rule)
        built_plan = parse_exit_plan(ADX_GATED_RANGE_PERSISTENCE["structured_exit_plan"])
        v2_plan = parse_exit_plan(ADX_RANGE_VARIANTS["ADX_RANGE_V2"]["structured_exit_plan"])
        self.assertEqual(built_plan, v2_plan)


class DuplicateDetectionDoesNotApplyToManuallyAuthoredHypothesesTest(unittest.TestCase):
    """Answers the branch's own question directly: does check_duplicate catch
    WISE_MAN_HOLD_V9 vs V2? No, for two independent reasons, both proven below."""

    def _finding(self, finding_type: str, asset: str, timeframe: str) -> ScanFinding:
        return ScanFinding(
            finding_type=finding_type, asset=asset, timeframe=timeframe, description="test",
            magnitude=2.5, measured_frequency_per_year=10.0, measurement_note="test",
            detected_at="2026-08-01T00:00:00+00:00",
        )

    def test_reason_1_manually_authored_records_carry_no_scan_finding_metadata(self) -> None:
        # check_duplicate's key is built from scan_finding_type/asset/timeframe on the
        # EXISTING hypothesis dict (see _mechanism_family_key) -- fields that only exist
        # because generate_hypotheses stamped them from a real ScanFinding.
        # Every hand-authored variant in this file has neither.
        for record in {**WISE_MAN_HOLD_VARIANTS, **ADX_RANGE_VARIANTS}.values():
            self.assertNotIn("scan_finding_type", record)

    def test_reason_2_the_matching_key_ignores_rule_content_entirely(self) -> None:
        # Two hypotheses with the SAME (scan_finding_type, asset, timeframe) but totally
        # DIFFERENT structured_entry_rule/structured_exit_plan: flagged as a duplicate
        # anyway (the key doesn't look at the rule at all).
        existing_same_origin_different_rule = [{
            "hypothesis_name": "SOME_OTHER_MECHANISM",
            "scan_finding_type": "extreme_zscore", "asset": "EUR/USD", "timeframe": "4h",
            "structured_entry_rule": {"conditions": [{"field": "rsi14", "op": "lt", "value": 10.0}]},
            "structured_exit_plan": {"stop_atr_multiple": 5.0, "target_r_multiple": 0.5},
        }]
        finding = self._finding("extreme_zscore", "EUR/USD", "4h")
        result = check_duplicate(finding, existing_same_origin_different_rule)
        self.assertTrue(result.is_duplicate)

        # The inverse: two hypotheses with IDENTICAL structured_entry_rule/structured_
        # exit_plan (exactly WISE_MAN_HOLD_V2's own shape) but a DIFFERENT origin tuple --
        # NOT flagged, despite being rule-for-rule the same hypothesis. This is precisely
        # V2-vs-V9's situation if either had ever gone through this function at all.
        v2_shaped_existing = [{
            "hypothesis_name": "WISE_MAN_HOLD_V2",
            "scan_finding_type": "extreme_zscore", "asset": "EUR/USD", "timeframe": "4h",
            "structured_entry_rule": WISE_MAN_HOLD_ENTRY_RULE,
            "structured_exit_plan": {"stop_pct_of_entry": 0.03, "target_pct_of_entry": 0.01},
        }]
        different_origin_same_rule_finding = self._finding("regime_transition", "GOLD", "24h")
        result2 = check_duplicate(different_origin_same_rule_finding, v2_shaped_existing)
        self.assertFalse(result2.is_duplicate)

    def test_check_duplicate_is_only_ever_called_from_generate_hypotheses(self) -> None:
        # Documents, rather than re-derives at runtime, the grep-confirmed fact this
        # branch's investigation relied on: hypothesis_gen.generate_hypotheses_for_
        # findings is the ONLY function anywhere in nero_core that calls check_duplicate
        # -- twice within itself (a preflight "any non-duplicate finding at all?" check,
        # then the real per-finding check) -- there is no path from a manually-
        # constructed hypothesis dict (this file, test_research_agent_philosophy_
        # hypotheses_parsing.py) into either call.
        import inspect

        from nero_core.research_agent import hypothesis_gen

        module_source = inspect.getsource(hypothesis_gen)
        # +1 for the def check_duplicate(...) line itself, +2 for its two call sites.
        self.assertEqual(module_source.count("check_duplicate("), 3)

        function_lines, _ = inspect.getsourcelines(hypothesis_gen.generate_hypotheses)
        function_source = "".join(function_lines)
        self.assertEqual(function_source.count("check_duplicate("), 2)

        # And confirm no OTHER function in the module calls it at all.
        other_source = module_source.replace(function_source, "")
        self.assertEqual(other_source.count("check_duplicate("), 1)  # only the def line remains


if __name__ == "__main__":
    unittest.main()
