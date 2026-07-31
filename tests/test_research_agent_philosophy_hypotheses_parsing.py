"""feature/philosophy-hypotheses-dsl-check: parse-ONLY validation of the two
candidate hypotheses cleared to build this round (WISE_MAN_ASYMMETRIC_HOLD,
ADX_GATED_RANGE_PERSISTENCE). Deliberately does NOT call frequency_gate.
measure_entry_frequency or auto_tester.test_hypothesis on either -- per this
branch's own instructions, only DSL-fit is being confirmed here (does the
structured_entry_rule/structured_exit_plan parse into a real StructuredRule/
ExitPlan with the expected shape), not whether either hypothesis actually
survives a backtest against real candle data. Running either through the full
pipeline is a separate, later step.

VOLATILITY_CONTRACTION_RANGE_HOLD (Candidate 1) is deliberately absent from
this file -- it's parked (see docs/backlog -- new atr_percentile_252 indicator,
new entry-frozen-range ExitPlan shape, non-P&L evaluation approach, and the
200-row CANDLE_COUNT export cap all still needed first).
"""
from __future__ import annotations

import unittest

from nero_core.research_agent.rule_dsl import Condition, ExitPlan, StructuredRule, parse_exit_plan, parse_structured_rule

# WISE_MAN_ASYMMETRIC_HOLD (Candidate 3): reuses RANGE_MEAN_REVERSION's own LONG
# entry (close < bb_lower AND adx14 < 25 -- see nero_core.strategies.range_mean_
# reversion.evaluate_entry, and RMR_LONG_ONLY_EURUSD_4H's identical condition)
# against the user's own stated exit discipline: target +1%, stop -3%, no time cap.
WISE_MAN_ASYMMETRIC_HOLD = {
    "hypothesis_name": "WISE_MAN_ASYMMETRIC_HOLD",
    "structured_entry_rule": {
        "conditions": [
            {"field": "close", "op": "lt", "compare_to_field": "bb_lower"},
            {"field": "adx14", "op": "lt", "value": 25.0},
        ],
    },
    "structured_exit_plan": {
        "stop_pct_of_entry": 0.03,
        "target_pct_of_entry": 0.01,
        # max_holding_hours omitted -- "no time cap" per the hypothesis's own exit rule.
    },
}

# ADX_GATED_RANGE_PERSISTENCE (Candidate 2): entry ADX(14) < 20 (deep range-bound
# regime). Exit is regime_break_condition (adx14 >= 25, 1 consecutive bar -- an
# immediate regime-change exit, no hysteresis needed since the hypothesis itself
# only asks "has the regime changed," not "has it changed AND persisted") OR
# max_holding_hours=480 (20 days * 24h -- "20 days pass with no regime change").
# target_r_multiple=50.0 is a clearly-artificial, practically-unreachable target
# required only because ExitPlan mandates exactly one target shape -- see this
# module's own PROXY_TARGET_JUSTIFICATION below. This run's expectancy/R-multiple
# numbers describe how that artificial target interacts with the REAL exits
# (REGIME_BREAK/TIME/SL), NOT a genuine profit-target strategy -- see this
# hypothesis's own "proxy_test_of" field, which any report surfacing this
# hypothesis's results MUST display, not bury in a code comment.
PROXY_TARGET_JUSTIFICATION = (
    "target_r_multiple=50.0 against stop_atr_multiple=2.0 means price would have to move "
    "100x the entry-candle's own ATR before TARGET could ever be the resolving exit reason -- "
    "on a 4h chart this is an implausibly large move to happen within the 480h (20-day) "
    "max_holding_hours window this same plan already enforces, let alone before ADX moves "
    "5+ points from <20 to >=25 (a regime shift that historically resolves in single-digit "
    "days on 4h charts, not weeks). In practice every resolved trade under this plan should "
    "exit via REGIME_BREAK, SL, or TIME -- never TARGET -- which is exactly what makes it a "
    "safe, inert placeholder rather than a real profit objective."
)
ADX_GATED_RANGE_PERSISTENCE = {
    "hypothesis_name": "ADX_GATED_RANGE_PERSISTENCE",
    "structured_entry_rule": {
        "conditions": [{"field": "adx14", "op": "lt", "value": 20.0}],
    },
    "structured_exit_plan": {
        "stop_atr_multiple": 2.0,
        "target_r_multiple": 50.0,  # PROXY, not a real profit target -- see PROXY_TARGET_JUSTIFICATION above.
        "regime_break_condition": {"field": "adx14", "op": "gte", "value": 25.0},
        "regime_break_consecutive_bars": 1,
        "max_holding_hours": 480.0,
    },
    "proxy_test_of": (
        "Does the market stay in a persistent low-ADX regime? This is NOT a genuine "
        "profit-target strategy -- the target_r_multiple=50.0 exit is a practically "
        "unreachable placeholder required only because ExitPlan mandates a target shape. "
        "Any expectancy/R-multiple numbers this hypothesis produces describe the placeholder "
        "target's interaction with the real REGIME_BREAK/SL/TIME exits, not the thesis itself."
    ),
}


class WiseManAsymmetricHoldParsesTest(unittest.TestCase):
    def test_entry_rule_parses(self) -> None:
        rule = parse_structured_rule(WISE_MAN_ASYMMETRIC_HOLD["structured_entry_rule"])
        self.assertEqual(
            rule,
            StructuredRule(conditions=(
                Condition(field="close", op="lt", compare_to_field="bb_lower"),
                Condition(field="adx14", op="lt", value=25.0),
            )),
        )

    def test_exit_plan_parses(self) -> None:
        plan = parse_exit_plan(WISE_MAN_ASYMMETRIC_HOLD["structured_exit_plan"])
        self.assertEqual(
            plan,
            ExitPlan(stop_pct_of_entry=0.03, target_pct_of_entry=0.01),
        )
        self.assertIsNone(plan.max_holding_hours)
        self.assertIsNone(plan.stop_atr_multiple)
        self.assertIsNone(plan.target_r_multiple)
        self.assertIsNone(plan.dynamic_target_condition)
        self.assertIsNone(plan.regime_break_condition)


class AdxGatedRangePersistenceParsesTest(unittest.TestCase):
    def test_entry_rule_parses(self) -> None:
        rule = parse_structured_rule(ADX_GATED_RANGE_PERSISTENCE["structured_entry_rule"])
        self.assertEqual(rule, StructuredRule(conditions=(Condition(field="adx14", op="lt", value=20.0),)))

    def test_exit_plan_parses(self) -> None:
        plan = parse_exit_plan(ADX_GATED_RANGE_PERSISTENCE["structured_exit_plan"])
        self.assertEqual(plan.stop_atr_multiple, 2.0)
        self.assertEqual(plan.target_r_multiple, 50.0)
        self.assertIsNone(plan.dynamic_target_condition)
        self.assertIsNone(plan.target_pct_of_entry)
        self.assertEqual(plan.regime_break_condition, Condition(field="adx14", op="gte", value=25.0))
        self.assertEqual(plan.regime_break_consecutive_bars, 1)
        self.assertEqual(plan.max_holding_hours, 480.0)

    def test_proxy_target_label_is_present_on_the_hypothesis_record(self) -> None:
        # The label itself is the point of this test, not just the exit plan's numbers --
        # per this branch's instructions, the PROXY nature must be documented on the
        # hypothesis record, not just in a comment a report-reader would never see.
        self.assertIn("proxy_test_of", ADX_GATED_RANGE_PERSISTENCE)
        self.assertIn("NOT a genuine", ADX_GATED_RANGE_PERSISTENCE["proxy_test_of"])


if __name__ == "__main__":
    unittest.main()
