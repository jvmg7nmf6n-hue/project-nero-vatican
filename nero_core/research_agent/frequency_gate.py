"""Task 2 -- Frequency Gate. THE most important module in this package.

An audit CONFIRMED that 25 of Vatican's 27 live configs have an expected
time-to-30-resolved-trades of 3-25 YEARS, because their intrinsic backtest
frequency is 1.2-3.2 trades/year -- fixing the scheduler does not change that
number (nero_core.execution.replay.py's catch-up mechanism confirms this).
Vatican's real bottleneck is HYPOTHESIS SELECTION, not scheduling. This gate
exists to stop slow hypotheses from ever reaching the full statistical
harness (bootstrap CI, random-entry baseline, grid-shift in
tools.backtest_statistics / tools.backtest_train_test_split /
tools.grid_shift_robustness_audit) -- auto_tester.py (Task 4) only ever
receives a hypothesis this gate classified FAST or VIABLE.

MECHANICAL ONLY: this measures trigger COUNT, never P&L. It reuses
nero_core.research_agent.rule_dsl (Condition/StructuredRule parsing and
trigger counting) -- the exact same parser and evaluator auto_tester.py uses
for its own entry logic, so the gate and the tester can never silently
disagree about what the rule even means. See rule_dsl.py's own docstring and
test_research_agent_rule_dsl_consistency.py.

Classification (measured trades/year -> expected months to
TARGET_RESOLVED_TRADES resolved trades):
  FAST         <= FAST_MAX_MONTHS
  VIABLE       FAST_MAX_MONTHS < months <= VIABLE_MAX_MONTHS
  TOO_SLOW     > VIABLE_MAX_MONTHS -- REJECTED. HARD RULE: must never reach
               the harness, no matter how strong the mechanism looks.
  UNMEASURABLE -- entry_rule has no machine-checkable structured form (see
               rule_dsl.RuleAmbiguousError), or there isn't enough eligible
               history to trust a rate at all -- REJECTED, never guessed.

LOOKAHEAD PROTECTION (critical): `generated_at` is the hypothesis's own
generation timestamp. Only candles with close_time STRICTLY BEFORE that
timestamp are ever counted. Measuring frequency against data from AFTER the
hypothesis was generated would be circular -- the scan finding that prompted
the hypothesis is itself drawn from recent data, so "how often does this
condition happen" measured on data including and after that same window would
partly be measuring the very observation that triggered the hypothesis, not
an independent historical base rate. This cutoff is enforced INSIDE
measure_entry_frequency itself (not trusted from any caller) --
see test_frequency_gate_lookahead_protection and the HARD TEST in
test_research_agent_frequency_gate.py.

LLM se frequency POOCHEIN NAHI -- HISAAB KAREIN: this module never asks the
LLM for a frequency estimate. Every number here is computed directly from
historical candle data.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd

from nero_core.research_agent.rule_dsl import RuleAmbiguousError, compute_indicator_frame, count_triggers, parse_structured_rule

FAST = "FAST"
VIABLE = "VIABLE"
TOO_SLOW = "TOO_SLOW"
UNMEASURABLE = "UNMEASURABLE"

TARGET_RESOLVED_TRADES = 30
FAST_MAX_MONTHS = 6.0
VIABLE_MAX_MONTHS = 12.0

# Below this many eligible (pre-cutoff) candles, an annualized rate isn't
# trustworthy enough to gate a real decision on -- REJECTED as UNMEASURABLE,
# not computed anyway with a giant error bar.
MIN_CANDLES_FOR_MEASUREMENT = 60


@dataclass(frozen=True)
class FrequencyMeasurement:
    classification: str  # FAST | VIABLE | TOO_SLOW | UNMEASURABLE
    measured_trades_per_year: float | None
    expected_months_to_30_trades: float | None
    triggers_counted: int
    eligible_candle_count: int
    span_days: float | None
    reason: str  # human-readable, always includes the measured number(s) that drove the verdict


def _span_days(frame: pd.DataFrame) -> float:
    if len(frame) < 2:
        return 0.0
    span_ms = float(frame["close_time"].iloc[-1] - frame["close_time"].iloc[0])
    return span_ms / 86_400_000.0


def measure_entry_frequency(
    candles: pd.DataFrame,
    structured_entry_rule: dict,
    generated_at: datetime,
) -> FrequencyMeasurement:
    """`candles` is the FULL available history (any timeframe, not
    pre-filtered by the caller) with close_time (epoch ms) + close/high/low
    columns; this function enforces the generated_at lookahead cutoff itself.
    `structured_entry_rule` is the hypothesis's machine-checkable entry_rule
    dict (see rule_dsl.parse_structured_rule)."""
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)
    cutoff_ms = int(generated_at.timestamp() * 1000)

    eligible = candles[candles["close_time"] < cutoff_ms].sort_values("close_time").reset_index(drop=True)
    if len(eligible) < MIN_CANDLES_FOR_MEASUREMENT:
        return FrequencyMeasurement(
            UNMEASURABLE, None, None, 0, len(eligible), None,
            f"Only {len(eligible)} candles available strictly before generated_at "
            f"(need >= {MIN_CANDLES_FOR_MEASUREMENT} to trust a rate) -- rejected as UNMEASURABLE.",
        )

    # CC-1 directive (2026-08-06): structured_entry_rule is None on purpose
    # for a real, non-trivial share of Adam's own real hypotheses (3/7 in
    # docs/site_data/agent_hypotheses.json as of this fix) -- hypothesis_gen.
    # py's own prompt explicitly instructs the model to set it to null
    # "If the entry condition genuinely cannot be expressed with these
    # fields/ops... do NOT force an approximate mapping." Before this fix,
    # that legitimate, deliberate null fell into the exact same generic
    # "entry_rule ambiguous: entry_rule must be a dict with a 'conditions'
    # list, got NoneType" message as any OTHER RuleAmbiguousError (a
    # malformed-but-present dict, e.g. Eve's own "condition must set exactly
    # one of value/compare_to_field" case) -- reading as an ambiguous DSL
    # bug when it's actually an honest, model-declared DSL-vocabulary
    # ceiling (no field for hour-of-day, rolling-max/highest-high, a
    # volume moving average, or a consecutive-candle streak count, as of
    # this writing). Checked here, BEFORE parse_structured_rule, so this
    # specific, common, non-bug case gets a distinct, accurate reason
    # string -- never silently merged back into the generic one below.
    if structured_entry_rule is None:
        return FrequencyMeasurement(
            UNMEASURABLE, None, None, 0, len(eligible), None,
            "structured_entry_rule is null -- the model explicitly reported this entry rule cannot be "
            "expressed in the current DSL's field/op vocabulary (see hypothesis_gen.py's own prompt "
            "instruction to set structured_entry_rule to null rather than force an approximate mapping). "
            "This is a DSL-expressiveness gap in the mechanism itself, not a data problem, and not a case "
            "where the model failed to comply with an achievable schema.",
        )

    try:
        rule = parse_structured_rule(structured_entry_rule)
        indicator_frame = compute_indicator_frame(eligible)
        triggers = count_triggers(indicator_frame, rule)
    except RuleAmbiguousError as exc:
        return FrequencyMeasurement(UNMEASURABLE, None, None, 0, len(eligible), None, f"entry_rule ambiguous: {exc}")

    span_days = _span_days(eligible)
    if span_days <= 0:
        return FrequencyMeasurement(
            UNMEASURABLE, None, None, triggers, len(eligible), span_days,
            "Zero or negative time span across eligible (pre-cutoff) candles -- cannot annualize a rate.",
        )

    trades_per_year = triggers / (span_days / 365.25)
    if trades_per_year <= 0:
        return FrequencyMeasurement(
            TOO_SLOW, trades_per_year, None, triggers, len(eligible), span_days,
            f"Measured 0 triggers over {span_days:.0f} days of eligible history -- this condition never fired.",
        )

    months_to_target = (TARGET_RESOLVED_TRADES / trades_per_year) * 12.0
    if months_to_target <= FAST_MAX_MONTHS:
        classification = FAST
    elif months_to_target <= VIABLE_MAX_MONTHS:
        classification = VIABLE
    else:
        classification = TOO_SLOW

    reason = (
        f"Measured {triggers} trigger(s) over {span_days:.0f} eligible days "
        f"({trades_per_year:.2f} trades/year) -> ~{months_to_target:.1f} months to "
        f"{TARGET_RESOLVED_TRADES} resolved trades -> {classification}."
    )
    return FrequencyMeasurement(classification, trades_per_year, months_to_target, triggers, len(eligible), span_days, reason)
