"""Shared entry-rule DSL for the Research Agent (Tasks 2 and 4).

NOT in the original task prompt -- added because frequency_gate.py (trigger
counting only, no P&L) and auto_tester.py (full backtest) both need to
evaluate a hypothesis's `entry_rule` against historical candles, and if each
module parsed that rule independently, they could silently diverge: the gate
could count triggers for one interpretation of the rule while the tester
backtests a different one, so a hypothesis could be classified FAST/VIABLE
against a trigger count that has nothing to do with what actually got
backtested. This module is the ONE place `entry_rule` is parsed and
evaluated; both callers import the same functions rather than each writing
their own interpretation. See test_research_agent_rule_dsl_consistency.py for
the test proving gate and tester actually agree, not just "should" by
construction.

DESIGN: a StructuredRule is a list of Condition objects, ANDed together --
this project's hypotheses are single-trigger mechanisms (e.g. "z-score below
-2", "close crosses above MA200"); OR/nesting is out of scope, and a rule that
needs it is exactly the ambiguous case handled below, not something to
force-fit into this DSL.

REQUIREMENT 1 -- never guess: anything this DSL cannot express raises
RuleAmbiguousError (unsupported field, unsupported op, missing/empty
`conditions`, a non-numeric threshold). Callers MUST route that to
UNMEASURABLE (frequency_gate) / UNTESTABLE (auto_tester) -- never silently
fall back to a "closest reasonable" interpretation of an ambiguous rule. This
is deliberately narrow (10 fields, 7 ops) rather than extensible-by-guessing.

FIELD-VS-FIELD COMPARISON (added 2026-07-30, after a real diagnostic run
found the original field-vs-constant-only design couldn't express even a
simple moving-average crossover): a condition's right-hand side is either a
fixed `value` (a number) or a `compare_to_field` (another name from
ALLOWED_FIELDS) -- exactly one of the two, never both, never neither. This
makes "ma20 crosses above ma50" (a golden cross) expressible as
{"field": "ma20", "op": "cross_above", "compare_to_field": "ma50"}, the same
way "zscore20 < -2" is expressed with `value`. Both sides read from the SAME
per-row indicator frame, so a field-vs-field condition costs nothing extra
computationally -- it just doesn't collapse the right-hand side to a
constant.

NO LOOKAHEAD: every field below is a rolling/causal computation over closed
candles up to and including the evaluation row (see compute_indicator_frame).
`cross_above`/`cross_below` look at exactly one prior row, never a future one.

EXIT PLAN (added for auto_tester.py, Task 4): an entry_rule alone isn't enough
to run a real backtest -- computing an R-multiple needs a stop and a target
too. ExitPlan/parse_exit_plan apply the exact same "never guess" principle
(REQUIREMENT 1 above) to that other half of a testable trade definition: a
hypothesis's exit_rule/stop_rule free text is REJECTED as UNTESTABLE unless it
also has this fixed, machine-checkable shape -- stop distance as EITHER a
multiple of ATR OR a fixed fraction of entry price (stop_pct_of_entry, added
for feature/philosophy-hypotheses-dsl-check -- for a hypothesis whose own
stated risk is a literal percentage, not an ATR-derived distance), plus
EITHER a target as a multiple of that same risk (an R-multiple, the original,
still-default shape), a dynamic target that moves with a named indicator
(re-evaluated every closed candle, e.g. "close >= ma20" -- for a strategy
whose target is a moving average rather than a fixed price), OR a fixed
fraction of entry price (target_pct_of_entry, same percentage-shape addition),
plus an OPTIONAL regime-break exit (a condition that must hold for N
CONSECUTIVE closed candles, e.g. "adx14 >= 28 for 2 bars" -- a hysteresis exit
independent of price touching stop or target), plus an OPTIONAL maximum
holding period in hours (omitted entirely means no time-based exit at all --
some strategies, e.g. RANGE_MEAN_REVERSION, are deliberately fully
regime/reversion/stop-driven with no time cap; see ExitPlan's own docstring).
This mirrors this project's own established ATR-stop/target/max-holding-hours
convention (see nero_core.strategies.mean_reversion.evaluate_exit, which
auto_tester.py reuses UNMODIFIED for a plan using none of the extended
fields -- see auto_tester._make_exit_evaluator).
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from nero_core.strategies.mean_reversion import rsi as _mean_reversion_rsi
from nero_core.strategies.range_mean_reversion import adx as _range_mean_reversion_adx

# rsi14 added 2026-07-30: RSI is MEAN_REVERSION's own core indicator (this
# project's first-ever ported strategy) -- its earlier absence meant any
# RSI-based hypothesis got rejected UNMEASURABLE, indistinguishable from a
# genuinely ambiguous rule, purely because of an incomplete field list.
#
# adx14/bb_lower/bb_upper added for feature/exitplan-dynamic-target-and-hysteresis
# (RMR_LONG_ONLY_EURUSD_4H blocker): adx14 reuses range_mean_reversion.adx()
# UNCHANGED -- the canonical ADX implementation this codebase already reuses
# elsewhere (trend_pullback_adx_gated.py). Unlike rsi14, adx() has no .fillna()
# step to undo during warmup -- every rolling() call in it leaves genuine NaN
# until enough history exists, which already matches this module's own
# "warmup = NaN = does not fire" convention (see evaluate_condition), so no
# re-masking is needed here. bb_lower/bb_upper use the SAME period/std/ddof
# convention as range_mean_reversion.add_indicators (bollinger_period=20,
# bollinger_std=2.0, ddof=0 -- population std, NOT this module's own zscore20
# sample std) -- computed inline below (reusing this module's own ma20 column
# as the SMA) rather than importing that whole function, since Bollinger bands
# have no standalone reusable function there the way adx()/rsi() do.
# hour_of_day / high20 / low20 / vol_ma20 added (CC-1 directive, 2026-08-06):
# hour_of_day is DAILY_HOUR_SEASONALITY_BTC_4H's own real blocker (a
# wall-clock-hour trigger with no prior DSL field); high20/low20/vol_ma20
# are VOLCONFIRM_CHANNEL_BREAKOUT_ETH_4H's own real blocker -- that
# hypothesis needed BOTH a rolling price-channel field AND a volume moving
# average, confirmed by reading its own recorded text (docs/site_data/
# agent_hypotheses.json): "highest close of the prior 20 candles" / "lowest
# close of the prior 20 candles" / "20-period average volume" -- sizing
# either field alone would have understated this one real case. high20/
# low20 are named after this codebase's existing rolling-channel precedent
# (nero_core.strategies.breakout_momentum.py/donchian_breakout_bracket.py's
# own `.shift(1).rolling(N).max()`/`.min()`), but -- unlike that precedent,
# which channels the HIGH/LOW columns -- these are computed from CLOSE (see
# compute_indicator_frame), matching this specific hypothesis's own literal
# wording ("highest CLOSE," not "highest high"); computing from high/low
# instead would not actually have fixed the real blocking case. Fixed-
# period only (matching the ma20/ma50/ma200 convention), no arbitrary-
# period support -- deferred per this directive's own explicit scope note.
# real_yield_10y_chg20/dxy_chg20/vix_chg20/funding_rate_bps (CC-1 master directive,
# 2026-08-07, Part B Rung 2): the ONLY 4 Bellwether-real macro fields wired into this
# DSL -- see docs/bellwether_stage2_report.md's Rung 2 section for the full B2a
# reasoning. real_yield_10y/dxy/vix are their 20-BUSINESS-DAY CHANGE, not their raw
# level -- matching MACRO_RISK_ON's own already-vetted dfii10_change_20d/
# dollar_change_20d convention (a level's "neutral" anchor drifts across multi-year
# macro regimes; a change is regime-agnostic) and Rung 1's own correlation-matrix
# finding that the 20-day-change relationships are the economically relevant ones for
# a condition that reacts to MOVEMENT. funding_rate_bps is its raw LEVEL, deliberately
# NOT a change -- it's naturally mean-reverting around 0 with occasional spikes, and
# every existing real consumer (risk.py's `> 6 bps`, derivatives_etf.py's own
# threshold) already treats the LEVEL, not its own change, as the economically
# meaningful reading. See compute_indicator_frame's own attach_macro parameter and
# _attach_macro_condition_fields for exactly how each is fetched/lagged/aligned --
# every one of these is REAL-fetch-or-absent, never a synthetic/guessed value (a
# fetch failure leaves the column simply absent, which this DSL's own pre-existing
# "NaN = does not fire" convention already handles with no new logic).
ALLOWED_FIELDS = (
    "close", "ma20", "ma50", "ma200", "zscore20", "atr14", "rsi14", "adx14",
    "bb_lower", "bb_upper", "ret_1", "volume", "hour_of_day", "high20",
    "low20", "vol_ma20", "real_yield_10y_chg20", "dxy_chg20", "vix_chg20",
    "funding_rate_bps",
)

MACRO_CONDITION_FIELDS = ("real_yield_10y_chg20", "dxy_chg20", "vix_chg20", "funding_rate_bps")
ALLOWED_OPS = ("gt", "gte", "lt", "lte", "eq", "cross_above", "cross_below")

# CC-1 master directive (2026-08-07), Part B Rung 2, B2b: structural enforcement --
# a field cannot enter ALLOWED_FIELDS without an explicit provenance declaration
# here, and a field declared SYNTHETIC/UNAVAILABLE can never be one of them. Checked
# by validate_field_provenance() at MODULE IMPORT TIME below (not only in a test) --
# a future edit that adds a field to ALLOWED_FIELDS without a matching entry here, or
# that (by mistake) marks a live macro field's real-data path as having regressed to
# synthetic/unavailable while leaving it in ALLOWED_FIELDS, fails the import itself,
# not just a test file that happens to get run. Every non-macro field is DERIVED
# (computed purely from the candle's own OHLCV, e.g. via compute_indicator_frame) --
# no external-data dependency, so no real/synthetic distinction applies to it at all.
FIELD_PROVENANCE_DERIVED = "derived"
FIELD_PROVENANCE_REAL = "real"
FIELD_PROVENANCE_SYNTHETIC = "synthetic"
FIELD_PROVENANCE_UNAVAILABLE = "unavailable"

FIELD_PROVENANCE: dict[str, str] = {
    "close": FIELD_PROVENANCE_DERIVED, "ma20": FIELD_PROVENANCE_DERIVED, "ma50": FIELD_PROVENANCE_DERIVED,
    "ma200": FIELD_PROVENANCE_DERIVED, "zscore20": FIELD_PROVENANCE_DERIVED, "atr14": FIELD_PROVENANCE_DERIVED,
    "rsi14": FIELD_PROVENANCE_DERIVED, "adx14": FIELD_PROVENANCE_DERIVED, "bb_lower": FIELD_PROVENANCE_DERIVED,
    "bb_upper": FIELD_PROVENANCE_DERIVED, "ret_1": FIELD_PROVENANCE_DERIVED, "volume": FIELD_PROVENANCE_DERIVED,
    "hour_of_day": FIELD_PROVENANCE_DERIVED, "high20": FIELD_PROVENANCE_DERIVED, "low20": FIELD_PROVENANCE_DERIVED,
    "vol_ma20": FIELD_PROVENANCE_DERIVED,
    # The 4 real macro fields -- see ALLOWED_FIELDS' own comment above for the
    # per-field real data path each one traces to (FRED DFII10, yfinance DX-Y.NYB,
    # yfinance ^VIX, Binance funding rate). None may ever be downgraded to
    # FIELD_PROVENANCE_SYNTHETIC/FIELD_PROVENANCE_UNAVAILABLE here while remaining in
    # ALLOWED_FIELDS -- if a real data path is ever lost, remove the field from
    # ALLOWED_FIELDS in the SAME change that marks it here, not one without the other.
    "real_yield_10y_chg20": FIELD_PROVENANCE_REAL,
    "dxy_chg20": FIELD_PROVENANCE_REAL,
    "vix_chg20": FIELD_PROVENANCE_REAL,
    "funding_rate_bps": FIELD_PROVENANCE_REAL,
}


def validate_field_provenance(allowed_fields: tuple[str, ...], provenance: dict[str, str]) -> None:
    """Raises RuntimeError if `allowed_fields` contains any field missing from
    `provenance`, or any field whose declared provenance is SYNTHETIC/UNAVAILABLE --
    the actual enforcement mechanism, called against the REAL ALLOWED_FIELDS/
    FIELD_PROVENANCE at module import time below, and callable directly by a test
    with a deliberately-bad `provenance` dict to prove the check itself actually
    fires (not just that today's real data happens to pass it)."""
    missing = [f for f in allowed_fields if f not in provenance]
    if missing:
        raise RuntimeError(
            f"ALLOWED_FIELDS contains field(s) with no FIELD_PROVENANCE declaration: {missing} -- "
            f"every field must be classified derived/real before it can be added."
        )
    unvetted = [
        f for f in allowed_fields
        if provenance[f] in (FIELD_PROVENANCE_SYNTHETIC, FIELD_PROVENANCE_UNAVAILABLE)
    ]
    if unvetted:
        raise RuntimeError(
            f"ALLOWED_FIELDS contains field(s) marked {{synthetic, unavailable}}, which may never "
            f"reach this DSL: {unvetted} -- remove from ALLOWED_FIELDS or restore a confirmed-real "
            f"data path before re-adding."
        )


validate_field_provenance(ALLOWED_FIELDS, FIELD_PROVENANCE)

BOLLINGER_PERIOD = 20
BOLLINGER_STD = 2.0

RSI_PERIOD = 14

REQUIRED_CANDLE_COLUMNS = ("close_time", "close", "high", "low")


class RuleAmbiguousError(Exception):
    """Raised when a hypothesis's entry_rule has no machine-checkable
    structured form this DSL can evaluate: an unsupported field, an
    unsupported op, a missing/empty `conditions` list, or a non-numeric
    threshold. Callers MUST route this to UNMEASURABLE (frequency_gate) /
    UNTESTABLE (auto_tester) -- never guess a substitute (see module
    docstring, Requirement 1)."""


@dataclass(frozen=True)
class Condition:
    field: str
    op: str
    # Exactly one of the two is set -- see module docstring, FIELD-VS-FIELD
    # COMPARISON. `value` is a fixed numeric threshold; `compare_to_field` is
    # another ALLOWED_FIELDS name whose OWN per-row value is the threshold.
    value: float | None = None
    compare_to_field: str | None = None


@dataclass(frozen=True)
class StructuredRule:
    conditions: tuple[Condition, ...]  # ANDed together -- see module docstring


def _parse_condition(entry: object, *, allow_cross_ops: bool = True) -> Condition:
    """Shared per-condition parser -- used by both parse_structured_rule (entry
    rules, allow_cross_ops=True) and parse_exit_plan's dynamic_target_condition/
    regime_break_condition fields (allow_cross_ops=False). `allow_cross_ops=False`
    exists because those two ExitPlan fields are evaluated one row at a time by
    auto_tester's exit-evaluation closure (matching the shared evaluate_exit_fn
    (candle, state, params) contract every strategy's random-baseline simulation
    already uses) -- there is no prior-row access at that call site, so a
    cross_above/cross_below there would silently NEVER fire correctly rather than
    raising, which is exactly the kind of ambiguity Requirement 1 forbids passing
    through silently."""
    if not isinstance(entry, dict):
        raise RuleAmbiguousError(f"condition entry must be a dict, got {entry!r}")
    field = entry.get("field")
    op = entry.get("op")
    value = entry.get("value")
    compare_to_field = entry.get("compare_to_field")

    if field not in ALLOWED_FIELDS:
        raise RuleAmbiguousError(f"unsupported field {field!r} -- allowed: {sorted(ALLOWED_FIELDS)}")
    if op not in ALLOWED_OPS:
        raise RuleAmbiguousError(f"unsupported op {op!r} -- allowed: {sorted(ALLOWED_OPS)}")
    if not allow_cross_ops and op in ("cross_above", "cross_below"):
        raise RuleAmbiguousError(
            f"op {op!r} not supported here -- this condition is evaluated one closed candle at a "
            f"time with no access to the prior row, so a crossing check could never fire correctly; "
            f"use gt/gte/lt/lte/eq instead"
        )

    has_value = value is not None
    has_compare_field = compare_to_field is not None
    if has_value and has_compare_field:
        raise RuleAmbiguousError(f"condition must set exactly one of 'value'/'compare_to_field', got both: {entry!r}")
    if not has_value and not has_compare_field:
        raise RuleAmbiguousError(f"condition must set exactly one of 'value'/'compare_to_field': {entry!r}")

    if has_compare_field:
        if compare_to_field not in ALLOWED_FIELDS:
            raise RuleAmbiguousError(f"unsupported compare_to_field {compare_to_field!r} -- allowed: {sorted(ALLOWED_FIELDS)}")
        if compare_to_field == field:
            raise RuleAmbiguousError(f"compare_to_field cannot equal field ({field!r} compared to itself)")
        return Condition(field=field, op=op, value=None, compare_to_field=compare_to_field)

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuleAmbiguousError(f"condition value must be a number, got {value!r}")
    return Condition(field=field, op=op, value=float(value))


def parse_structured_rule(raw: object) -> StructuredRule:
    """Parses a hypothesis's structured entry_rule dict, e.g.:
        {"conditions": [{"field": "zscore20", "op": "lt", "value": -2.0}]}
    or, for a field-vs-field comparison (e.g. a moving-average crossover):
        {"conditions": [{"field": "ma20", "op": "cross_above", "compare_to_field": "ma50"}]}
    Raises RuleAmbiguousError (never returns a guessed/partial rule) if `raw`
    isn't a dict, `conditions` is missing/empty/not-a-list, a condition names
    an unsupported field/op, a condition sets both or neither of `value`/
    `compare_to_field`, `compare_to_field` isn't itself an allowed field, or
    `compare_to_field` names the same field as `field` (comparing a field to
    itself is never a meaningful trigger)."""
    if not isinstance(raw, dict):
        raise RuleAmbiguousError(f"entry_rule must be a dict with a 'conditions' list, got {type(raw).__name__}")

    conditions_raw = raw.get("conditions")
    if not isinstance(conditions_raw, list) or not conditions_raw:
        raise RuleAmbiguousError("entry_rule has no non-empty 'conditions' list -- nothing machine-checkable to evaluate")

    parsed = [_parse_condition(entry, allow_cross_ops=True) for entry in conditions_raw]
    return StructuredRule(conditions=tuple(parsed))


def parse_bidirectional_entry_rules(hypothesis: dict) -> tuple[StructuredRule, StructuredRule | None]:
    """DIRECTION DECLARATION (feature/short-side-support): the ONE place a
    hypothesis's entry rule(s) are read off the dict, for BOTH the long-only
    case (every hypothesis before this branch, and the overwhelming majority
    after it) and the new bidirectional case -- matching this module's own
    charter ("the ONE place entry_rule is parsed," see module docstring) so
    frequency_gate.py and auto_tester.py can never silently diverge on what a
    hypothesis's rule(s) even are, the identical reasoning that already
    justified this module's own existence.

    `hypothesis["structured_entry_rule"]` is always the LONG rule (required,
    parsed via parse_structured_rule UNCHANGED -- every existing hypothesis,
    scanner-sourced, web-search-sourced, or manually submitted, has exactly
    this one key and nothing else, so this call is byte-for-byte what already
    ran before this function existed). `hypothesis.get("structured_entry_
    rule_short")` is OPTIONAL and, when present, is ALSO parsed via
    parse_structured_rule UNCHANGED (the exact same StructuredRule/Condition
    shape, just a second, independent instance of it -- no new DSL surface
    at the condition level at all). A hypothesis becomes bidirectional purely
    by this second key's PRESENCE -- there is no separate "is_bidirectional"
    flag to fall out of sync with it, the same presence-implies-feature
    convention ExitPlan.regime_break_condition/regime_break_consecutive_bars
    already uses.

    Design alternatives considered and rejected (full reasoning in
    docs/short_side_support_closing_report.md): (1) a `direction` sub-field
    on individual Condition entries within one ANDed list -- rejected, breaks
    StructuredRule's clean "every condition ANDed together" contract by
    requiring OR-like special-casing inside what's currently a pure AND.
    (2) A single rule plus an auto-inferred "mirror rule" for the opposite
    direction -- rejected, auto-inferring e.g. "the short version of rsi14 <
    30" would be a GUESS (there's no unambiguous mirror for every condition
    shape), violating this module's own Requirement 1 ("never guess a
    substitute" -- see module docstring)."""
    long_rule = parse_structured_rule(hypothesis.get("structured_entry_rule"))
    short_rule_raw = hypothesis.get("structured_entry_rule_short")
    short_rule = parse_structured_rule(short_rule_raw) if short_rule_raw is not None else None
    return long_rule, short_rule


# gt/lt and gte/lte swap for the opposite direction's own comparison; eq has
# no meaningful direction to mirror (a level-touch means the same thing either
# way); cross_above/cross_below swap for the same reason gt/lt do. Every
# ALLOWED_OPS value has exactly one entry here -- see
# test_research_agent_rule_dsl_direction.py's own completeness check.
_OP_MIRROR = {
    "gt": "lt", "lt": "gt",
    "gte": "lte", "lte": "gte",
    "eq": "eq",
    "cross_above": "cross_below", "cross_below": "cross_above",
}


def mirror_condition(condition: Condition) -> Condition:
    """The SHORT-side mirror of a condition authored for LONG semantics --
    e.g. a dynamic_target_condition written as "close >= ma20" (LONG: target
    reached on the way up) mirrors to "close <= ma20" (SHORT: target reached
    on the way down), same fields, same threshold, only the comparison
    direction flips. This is why ExitPlan needs NO new fields for
    bidirectional support (see docs/short_side_support_closing_report.md):
    a hypothesis authors ONE dynamic_target_condition (implicitly LONG-
    shaped, matching every existing hypothesis exactly), and a SHORT trade's
    exit evaluator calls this function rather than requiring a second,
    separately-authored condition. regime_break_condition is deliberately
    NEVER passed through this function -- it describes a market-REGIME
    observation (e.g. "ADX >= 28"), not a price-vs-entry relationship, so it
    applies identically to both directions unchanged (confirmed directly
    against nero_core.strategies.range_mean_reversion.evaluate_exit, which
    checks its own regime-break condition identically for LONG and SHORT)."""
    return Condition(field=condition.field, op=_OP_MIRROR[condition.op], value=condition.value, compare_to_field=condition.compare_to_field)


@dataclass(frozen=True)
class ExitPlan:
    """stop_atr_multiple and (optionally) max_holding_hours are the only fields
    every plan shares. The target and the (optional) regime-break exit each have
    exactly-one-of-N shapes -- see parse_exit_plan's own validation.

    max_holding_hours=None means "no time-based exit at all" -- a real,
    deliberate mechanism in this codebase already (see
    nero_core.strategies.range_mean_reversion.RangeMeanReversionParameters's own
    "No max_holding_hours field" docstring, and DONCHIAN_TREND/MACRO_RISK_ON's
    same precedent), NOT an unlimited-via-large-number approximation. Every
    EXISTING hypothesis's structured_exit_plan supplies a real positive number
    here, so this is purely additive -- parse_exit_plan still requires the value
    to be a positive number whenever the key IS present, identical to before.

    Target: exactly one of target_r_multiple (a fixed R-multiple, entry's own
    stop distance times this factor -- the ORIGINAL, still-default shape),
    dynamic_target_condition (a Condition re-evaluated on every closed candle
    against the frame's OWN current-row indicator value, e.g. "close >= ma20"
    -- for a target that MOVES with the market rather than freezing at entry),
    or target_pct_of_entry (see below).

    Stop: exactly one of stop_atr_multiple (the ORIGINAL, still-default shape
    -- risk = this many ATRs at entry) or stop_pct_of_entry (see below).

    PERCENTAGE SHAPE (added for feature/philosophy-hypotheses-dsl-check,
    WISE_MAN_ASYMMETRIC_HOLD's blocker): stop_pct_of_entry / target_pct_of_entry
    express a stop/target as a fixed FRACTION of entry price (e.g. 0.03 for a
    3% stop), completely independent of ATR -- for a hypothesis whose own
    stated risk/reward is "entry -3%" / "entry +1%", not an ATR-derived
    distance. Converting a fixed percentage into an ATR-multiple was
    considered and rejected: ATR-as-%-of-price drifts with the volatility
    regime, so no single stop_atr_multiple equals exactly 3% of entry price on
    every trade -- only a genuine percentage-based field is faithful to a
    hypothesis that literally says "3%," not "roughly 3% on average." Exactly
    one of stop_atr_multiple/stop_pct_of_entry must be set, and exactly one of
    target_r_multiple/dynamic_target_condition/target_pct_of_entry must be
    set -- never both, never neither, matching every other exactly-one-of
    shape in this dataclass. A plan MAY freely mix bases (e.g.
    stop_pct_of_entry with target_r_multiple) -- auto_tester._size_entry_for_
    hypothesis computes risk_per_unit from whichever stop field is set, then
    computes target from whichever target field is set; the two are
    independent computations, not coupled the way an R-multiple is coupled to
    its OWN stop distance by definition. A stop_pct_of_entry plan does NOT
    require atr14 to be present on the entry candle (unlike stop_atr_multiple,
    which does) -- see _size_entry_for_hypothesis's own atr_is_valid gate,
    which is only consulted for the ATR-based stop shape.

    Regime-break exit (optional, both-or-neither with its bar count):
    regime_break_condition + regime_break_consecutive_bars -- exits when
    regime_break_condition has held true for that many CONSECUTIVE closed
    candles while a trade is open (e.g. adx14 >= 28 for 2 consecutive bars --
    a hysteresis exit against a trend/regime break, independent of price
    touching either the stop or the target)."""

    stop_atr_multiple: float | None = None
    target_r_multiple: float | None = None
    dynamic_target_condition: Condition | None = None
    max_holding_hours: float | None = None
    regime_break_condition: Condition | None = None
    regime_break_consecutive_bars: int | None = None
    stop_pct_of_entry: float | None = None
    target_pct_of_entry: float | None = None


def _parse_positive_number(raw: dict, key: str) -> float:
    value = raw.get(key)
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuleAmbiguousError(f"structured_exit_plan.{key} must be a number, got {value!r}")
    if value <= 0:
        raise RuleAmbiguousError(f"structured_exit_plan.{key} must be positive, got {value!r}")
    return float(value)


def parse_exit_plan(raw: object) -> ExitPlan:
    """Parses a hypothesis's structured_exit_plan dict. Original, still-default
    shape:
        {"stop_atr_multiple": 1.5, "target_r_multiple": 2.0, "max_holding_hours": 48.0}
    Extended shape (dynamic target + regime-break hysteresis + no time cap), e.g.
    RMR_LONG_ONLY_EURUSD_4H's own:
        {
            "stop_atr_multiple": 2.0,
            "dynamic_target_condition": {"field": "close", "op": "gte", "compare_to_field": "ma20"},
            "regime_break_condition": {"field": "adx14", "op": "gte", "value": 28.0},
            "regime_break_consecutive_bars": 2,
        }
    (max_holding_hours omitted above -- see ExitPlan's own docstring on why that
    means "no time-based exit," not a missing/invalid field.)
    Percentage shape (stop/target as a fixed fraction of entry price, e.g.
    WISE_MAN_ASYMMETRIC_HOLD's own -- target +1%, stop -3%, no time cap):
        {"stop_pct_of_entry": 0.03, "target_pct_of_entry": 0.01}

    Raises RuleAmbiguousError (never a guessed substitute) if `raw` isn't a
    dict; neither or both of stop_atr_multiple/stop_pct_of_entry are set (or
    the one that is set is non-numeric/non-positive); max_holding_hours (if
    present at all) is non-numeric/non-positive; not exactly one of
    target_r_multiple/dynamic_target_condition/target_pct_of_entry is set;
    dynamic_target_condition (if given) isn't itself a valid, non-crossing
    Condition; or regime_break_condition/regime_break_consecutive_bars are
    given one without the other, or either is malformed."""
    if not isinstance(raw, dict):
        raise RuleAmbiguousError(f"structured_exit_plan must be a dict, got {type(raw).__name__}")

    stop_atr_multiple_raw = raw.get("stop_atr_multiple")
    stop_pct_of_entry_raw = raw.get("stop_pct_of_entry")
    has_stop_atr = stop_atr_multiple_raw is not None
    has_stop_pct = stop_pct_of_entry_raw is not None
    if has_stop_atr and has_stop_pct:
        raise RuleAmbiguousError(
            "structured_exit_plan must set exactly one of 'stop_atr_multiple'/'stop_pct_of_entry', got both"
        )
    if not has_stop_atr and not has_stop_pct:
        raise RuleAmbiguousError("structured_exit_plan must set exactly one of 'stop_atr_multiple'/'stop_pct_of_entry'")

    stop_atr_multiple: float | None = None
    stop_pct_of_entry: float | None = None
    if has_stop_atr:
        stop_atr_multiple = _parse_positive_number(raw, "stop_atr_multiple")
    else:
        stop_pct_of_entry = _parse_positive_number(raw, "stop_pct_of_entry")

    max_holding_hours_raw = raw.get("max_holding_hours")
    if max_holding_hours_raw is None:
        max_holding_hours = None
    else:
        max_holding_hours = _parse_positive_number(raw, "max_holding_hours")

    target_r_multiple_raw = raw.get("target_r_multiple")
    dynamic_target_condition_raw = raw.get("dynamic_target_condition")
    target_pct_of_entry_raw = raw.get("target_pct_of_entry")
    target_shapes_set = sum(
        x is not None for x in (target_r_multiple_raw, dynamic_target_condition_raw, target_pct_of_entry_raw)
    )
    if target_shapes_set != 1:
        raise RuleAmbiguousError(
            "structured_exit_plan must set exactly one of 'target_r_multiple'/'dynamic_target_condition'/"
            f"'target_pct_of_entry', got {target_shapes_set}"
        )

    target_r_multiple: float | None = None
    dynamic_target_condition: Condition | None = None
    target_pct_of_entry: float | None = None
    if target_r_multiple_raw is not None:
        target_r_multiple = _parse_positive_number(raw, "target_r_multiple")
    elif dynamic_target_condition_raw is not None:
        dynamic_target_condition = _parse_condition(dynamic_target_condition_raw, allow_cross_ops=False)
    else:
        target_pct_of_entry = _parse_positive_number(raw, "target_pct_of_entry")

    regime_break_condition_raw = raw.get("regime_break_condition")
    regime_break_consecutive_bars_raw = raw.get("regime_break_consecutive_bars")
    has_regime_condition = regime_break_condition_raw is not None
    has_regime_bars = regime_break_consecutive_bars_raw is not None
    if has_regime_condition != has_regime_bars:
        raise RuleAmbiguousError(
            "structured_exit_plan.regime_break_condition and .regime_break_consecutive_bars must be "
            "set together or not at all"
        )

    regime_break_condition: Condition | None = None
    regime_break_consecutive_bars: int | None = None
    if has_regime_condition:
        regime_break_condition = _parse_condition(regime_break_condition_raw, allow_cross_ops=False)
        if isinstance(regime_break_consecutive_bars_raw, bool) or not isinstance(regime_break_consecutive_bars_raw, int):
            raise RuleAmbiguousError(
                f"structured_exit_plan.regime_break_consecutive_bars must be an integer, got {regime_break_consecutive_bars_raw!r}"
            )
        if regime_break_consecutive_bars_raw < 1:
            raise RuleAmbiguousError(
                f"structured_exit_plan.regime_break_consecutive_bars must be >= 1, got {regime_break_consecutive_bars_raw!r}"
            )
        regime_break_consecutive_bars = regime_break_consecutive_bars_raw

    return ExitPlan(
        stop_atr_multiple=stop_atr_multiple,
        target_r_multiple=target_r_multiple,
        dynamic_target_condition=dynamic_target_condition,
        max_holding_hours=max_holding_hours,
        regime_break_condition=regime_break_condition,
        regime_break_consecutive_bars=regime_break_consecutive_bars,
        stop_pct_of_entry=stop_pct_of_entry,
        target_pct_of_entry=target_pct_of_entry,
    )


def rule_references_macro_fields(rule: StructuredRule) -> bool:
    """True if any condition in `rule` reads or compares against one of
    MACRO_CONDITION_FIELDS. Callers (frequency_gate.py, auto_tester.py) use
    this to decide whether to pay the (cached, but non-zero) cost of
    fetching+attaching real macro data at all -- the overwhelming majority
    of hypotheses reference no macro field and must see zero behavior or
    performance change from Rung 2 (see docs/bellwether_stage2_report.md's
    Rung 2 section)."""
    for condition in rule.conditions:
        if condition.field in MACRO_CONDITION_FIELDS:
            return True
        if condition.compare_to_field in MACRO_CONDITION_FIELDS:
            return True
    return False


def _attach_macro_condition_fields(frame: pd.DataFrame) -> pd.DataFrame:
    """Best-effort attach of the 4 real MACRO_CONDITION_FIELDS onto `frame`
    (which must already carry a `date` column, e.g. from
    compute_indicator_frame's own close_time-derived one). Each field is
    fetched and merged INDEPENDENTLY -- a failure fetching one (missing API
    key, network error, yfinance/nero_core import failure) leaves that
    field's column simply ABSENT, never a guessed/synthetic value; this
    DSL's own pre-existing "NaN = does not fire" convention
    (evaluate_condition) already handles an absent field correctly with no
    new logic. real_yield_10y/dxy/vix reuse
    nero_core.data_sources.macro_data.compute_lagged_change/
    align_macro_to_daily_candles UNCHANGED -- the SAME functions
    MACRO_RISK_ON's own build_regime_frame uses, per this directive's own
    "reuse that logic directly" instruction, not a re-derived copy. funding
    reuses nero_core.data_sources.funding_data.load_funding_history
    UNCHANGED, resampled to a daily mean (matching
    vatican/bellwether/tools/correlation_matrix.py's own convention) before
    the same alignment call -- funding needs no extra lag beyond that
    (Binance's endpoint only ever returns already-settled events, per
    funding_data.py's own docstring)."""
    from nero_core.data_sources.macro_data import (
        DFII10_LAG_BUSINESS_DAYS,
        DXY_LAG_BUSINESS_DAYS,
        VIX_LAG_BUSINESS_DAYS,
        MacroDataUnavailableError,
        align_macro_to_daily_candles,
        compute_lagged_change,
        fetch_dfii10_daily,
        fetch_dxy_daily,
        fetch_vix_daily,
    )

    change_window_days = 20
    for fetch_fn, lag_days, column_name, level_series_name in (
        (fetch_dfii10_daily, DFII10_LAG_BUSINESS_DAYS, "real_yield_10y_chg20", "real_yield_10y"),
        (fetch_dxy_daily, DXY_LAG_BUSINESS_DAYS, "dxy_chg20", "dxy"),
        (fetch_vix_daily, VIX_LAG_BUSINESS_DAYS, "vix_chg20", "vix"),
    ):
        try:
            series, _source = fetch_fn()
        except (MacroDataUnavailableError, ImportError):
            continue
        changed = compute_lagged_change(series, change_window_days, lag_days)
        frame = align_macro_to_daily_candles(frame, changed, column_name)

    try:
        from nero_core.data_sources.funding_data import FundingDataUnavailableError, load_funding_history

        result = load_funding_history("BTC")
        settlements = result.settlements.copy()
        settlements["_date"] = pd.to_datetime(settlements["settlement_date"]).dt.tz_localize(None).dt.normalize()
        daily_funding_bps = settlements.groupby("_date")["funding_rate"].mean() * 10_000
        daily_funding_bps.index.name = "date"
        frame = align_macro_to_daily_candles(frame, daily_funding_bps, "funding_rate_bps")
    except (FundingDataUnavailableError, ImportError):
        pass

    return frame


def compute_indicator_frame(candles: pd.DataFrame, attach_macro: bool = False) -> pd.DataFrame:
    """Adds ma20/ma50/ma200/zscore20/atr14/rsi14/adx14/bb_lower/bb_upper/ret_1
    columns to a sorted copy of `candles` (which must carry close_time (epoch
    ms), close, high, low -- volume is optional, defaulted to NaN if absent).
    Every added column is a trailing rolling computation ending AT its own row
    -- no centering, no forward shift, so no future candle ever leaks into a
    value used to evaluate an earlier row (this project's no-lookahead-bias
    rule, CLAUDE.md).

    zscore20 uses the identical formula (trailing-20 mean/std, ddof=1) as
    nero_core.quant.quant_panel.rolling_zscore -- vectorized across the whole
    series here (rather than that function's single-latest-value-per-call
    shape) purely for performance across hundreds/thousands of candles, not a
    different definition.

    rsi14 reuses nero_core.strategies.mean_reversion.rsi UNCHANGED (this
    project's own oldest strategy's indicator, not re-derived), then re-masks
    the leading `RSI_PERIOD + 1` rows back to NaN: that function's own
    `.fillna(100.0)` is correct for ITS caller (a genuine "no losses in this
    window" reading legitimately IS RSI 100, not a warmup artifact), but
    applied during warmup -- before enough closes exist to compute a real
    reading at all -- it would fabricate a 100.0 that looks identical to a
    real extreme reading. This module's own convention (warmup = NaN = "does
    not fire," see evaluate_condition) requires undoing that specific
    conflation, not the whole function.
    """
    missing = [c for c in REQUIRED_CANDLE_COLUMNS if c not in candles.columns]
    if missing:
        raise ValueError(f"candles frame is missing required column(s): {missing}")

    frame = candles.sort_values("close_time").reset_index(drop=True).copy()
    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    prev_close = close.shift(1)

    frame["ma20"] = close.rolling(20).mean()
    frame["ma50"] = close.rolling(50).mean()
    frame["ma200"] = close.rolling(200).mean()
    frame["ret_1"] = close.pct_change()

    true_range = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    frame["atr14"] = true_range.rolling(14).mean()

    rolling_std_20 = close.rolling(20).std()
    frame["zscore20"] = (close - frame["ma20"]) / rolling_std_20.replace(0, float("nan"))

    enough_history_for_rsi = close.rolling(RSI_PERIOD + 1).count() >= RSI_PERIOD + 1
    frame["rsi14"] = _mean_reversion_rsi(close, RSI_PERIOD).where(enough_history_for_rsi)

    # adx() reads frame["high"]/["low"]/["close"] directly and assumes ascending
    # time order -- both already true of `frame` at this point (sorted above).
    frame["adx14"] = _range_mean_reversion_adx(frame, period=14)

    bollinger_std = close.rolling(BOLLINGER_PERIOD).std(ddof=0)
    frame["bb_lower"] = frame["ma20"] - BOLLINGER_STD * bollinger_std
    frame["bb_upper"] = frame["ma20"] + BOLLINGER_STD * bollinger_std

    # high20/low20 (CC-1 directive, 2026-08-06): rolling extreme of CLOSE
    # (see ALLOWED_FIELDS' own comment on why close, not the high/low
    # columns) over the PRIOR 20 candles -- shift(1) excludes the current
    # row, matching VOLCONFIRM_CHANNEL_BREAKOUT_ETH_4H's own "prior 20
    # candles" wording and this codebase's existing rolling-channel
    # precedent's identical shift(1) choice (a candle can't break out of a
    # channel that includes itself).
    frame["high20"] = close.shift(1).rolling(20).max()
    frame["low20"] = close.shift(1).rolling(20).min()

    frame["volume"] = frame["volume"].astype(float) if "volume" in frame.columns else float("nan")

    # vol_ma20 (CC-1 directive, 2026-08-06): a plain trailing 20-period
    # volume average, matching ma20's own convention exactly (no shift --
    # the real blocking hypothesis's own wording, "the 20-period average
    # volume," carries no "prior" qualifier, unlike high20/low20 above).
    frame["vol_ma20"] = frame["volume"].rolling(20).mean()

    # Matches every other candle schema in this codebase (e.g.
    # nero_core.data_sources.market_data.CANDLE_COLUMNS) -- added so
    # auto_tester.py can reuse mean_reversion.reset_daily_guard_if_needed /
    # tools.backtest_statistics.random_entry_baseline_single_asset unmodified,
    # both of which read candle["date"] directly.
    frame["date"] = pd.to_datetime(frame["close_time"], unit="ms", utc=True)

    # hour_of_day (CC-1 directive, 2026-08-06): UTC wall-clock hour of the
    # candle's own close_time -- real precedent nero_core.strategies.
    # funding_extreme.py's own `.dt.hour` comparison. No lookahead risk (a
    # property of the row's own timestamp, not a rolling computation).
    frame["hour_of_day"] = frame["date"].dt.hour

    if attach_macro:
        frame = _attach_macro_condition_fields(frame)

    return frame


def _threshold_at(condition: Condition, row: "pd.Series") -> float | None:
    """The right-hand side of `condition` at `row`: another field's own
    value if `compare_to_field` is set, else the fixed `value`. None if a
    field-vs-field threshold is itself still NaN (that field's own warmup)."""
    if condition.compare_to_field is not None:
        return row.get(condition.compare_to_field)
    return condition.value


def evaluate_condition(row: "pd.Series", condition: Condition, prev_row: "pd.Series | None") -> bool | None:
    """True/False if `condition` can be evaluated at `row`; None if the
    relevant field (or, for a field-vs-field condition, either side) is
    still NaN (indicator warmup, e.g. row 5 of a ma200 column) -- a warmup
    row is "does not fire," not an error and not the same as
    RuleAmbiguousError (which means the RULE itself, not one row, can't be
    evaluated at all)."""
    value = row.get(condition.field)
    if value is None or pd.isna(value):
        return None

    threshold = _threshold_at(condition, row)
    if threshold is None or pd.isna(threshold):
        return None

    if condition.op in ("cross_above", "cross_below"):
        if prev_row is None:
            return False
        prev_value = prev_row.get(condition.field)
        if prev_value is None or pd.isna(prev_value):
            return False
        prev_threshold = _threshold_at(condition, prev_row)
        if prev_threshold is None or pd.isna(prev_threshold):
            return False
        # For a fixed `value`, prev_threshold == threshold == condition.value (constant
        # across rows), reducing to the original single-level-crossing check; for a
        # compare_to_field, each row uses its OWN threshold (e.g. ma20 vs ma50 -- a
        # genuine two-series crossover, not a level crossing).
        if condition.op == "cross_above":
            return bool(prev_value <= prev_threshold and value > threshold)
        return bool(prev_value >= prev_threshold and value < threshold)

    if condition.op == "gt":
        return bool(value > threshold)
    if condition.op == "gte":
        return bool(value >= threshold)
    if condition.op == "lt":
        return bool(value < threshold)
    if condition.op == "lte":
        return bool(value <= threshold)
    if condition.op == "eq":
        return bool(value == threshold)
    raise RuleAmbiguousError(f"unsupported op {condition.op!r}")  # unreachable via parse_structured_rule; defensive


def rule_fires_at(frame: pd.DataFrame, index: int, rule: StructuredRule) -> bool:
    """True if every condition in `rule` fires at `frame.iloc[index]` (AND
    semantics -- see module docstring). `prev_row` is `frame.iloc[index - 1]`
    (None at index 0) for cross_above/cross_below conditions -- exactly one
    prior row, never a future one."""
    row = frame.iloc[index]
    prev_row = frame.iloc[index - 1] if index > 0 else None
    return all(evaluate_condition(row, condition, prev_row) is True for condition in rule.conditions)


def find_trigger_rows(frame: pd.DataFrame, rule: StructuredRule) -> list[int]:
    """Every row index where `rule` fires, in ascending order. THE canonical
    trigger list -- frequency_gate's trigger COUNTING and auto_tester's
    backtest ENTRY evaluation both call this (or find_trigger_timestamps
    below), not their own independent re-derivation. That is what makes the
    two mechanically incapable of diverging on the same (frame, rule) input --
    verified directly in test_research_agent_rule_dsl_consistency.py."""
    return [i for i in range(len(frame)) if rule_fires_at(frame, i, rule)]


def find_trigger_timestamps(frame: pd.DataFrame, rule: StructuredRule) -> list[int]:
    """close_time (epoch ms) of every triggering row, ascending."""
    return [int(frame["close_time"].iloc[i]) for i in find_trigger_rows(frame, rule)]


def count_triggers(frame: pd.DataFrame, rule: StructuredRule) -> int:
    """Trigger COUNT only -- frequency_gate's entire job (mechanical trigger
    counting, no P&L, no state, no sizing)."""
    return len(find_trigger_rows(frame, rule))
