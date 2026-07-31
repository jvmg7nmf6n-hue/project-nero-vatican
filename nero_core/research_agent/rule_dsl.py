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
also has this fixed, machine-checkable shape -- stop distance in ATR
multiples, plus EITHER a target as a multiple of that same risk (an
R-multiple, the original, still-default shape) OR a dynamic target that moves
with a named indicator (re-evaluated every closed candle, e.g. "close >= ma20"
-- for a strategy whose target is a moving average rather than a fixed price),
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
ALLOWED_FIELDS = (
    "close", "ma20", "ma50", "ma200", "zscore20", "atr14", "rsi14", "adx14",
    "bb_lower", "bb_upper", "ret_1", "volume",
)
ALLOWED_OPS = ("gt", "gte", "lt", "lte", "eq", "cross_above", "cross_below")

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
    stop distance times this factor -- the ORIGINAL, still-default shape) or
    dynamic_target_condition (a Condition re-evaluated on every closed candle
    against the frame's OWN current-row indicator value, e.g. "close >= ma20"
    -- for a target that MOVES with the market rather than freezing at entry).

    Regime-break exit (optional, both-or-neither with its bar count):
    regime_break_condition + regime_break_consecutive_bars -- exits when
    regime_break_condition has held true for that many CONSECUTIVE closed
    candles while a trade is open (e.g. adx14 >= 28 for 2 consecutive bars --
    a hysteresis exit against a trend/regime break, independent of price
    touching either the stop or the target)."""

    stop_atr_multiple: float
    target_r_multiple: float | None = None
    dynamic_target_condition: Condition | None = None
    max_holding_hours: float | None = None
    regime_break_condition: Condition | None = None
    regime_break_consecutive_bars: int | None = None


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

    Raises RuleAmbiguousError (never a guessed substitute) if `raw` isn't a
    dict; stop_atr_multiple is missing/non-numeric/non-positive; max_holding_hours
    (if present at all) is non-numeric/non-positive; neither or both of
    target_r_multiple/dynamic_target_condition are set; dynamic_target_condition
    (if given) isn't itself a valid, non-crossing Condition; or
    regime_break_condition/regime_break_consecutive_bars are given one without
    the other, or either is malformed."""
    if not isinstance(raw, dict):
        raise RuleAmbiguousError(f"structured_exit_plan must be a dict, got {type(raw).__name__}")

    stop_atr_multiple = _parse_positive_number(raw, "stop_atr_multiple")

    max_holding_hours_raw = raw.get("max_holding_hours")
    if max_holding_hours_raw is None:
        max_holding_hours = None
    else:
        max_holding_hours = _parse_positive_number(raw, "max_holding_hours")

    target_r_multiple_raw = raw.get("target_r_multiple")
    dynamic_target_condition_raw = raw.get("dynamic_target_condition")
    has_target_r = target_r_multiple_raw is not None
    has_dynamic_target = dynamic_target_condition_raw is not None
    if has_target_r and has_dynamic_target:
        raise RuleAmbiguousError(
            "structured_exit_plan must set exactly one of 'target_r_multiple'/'dynamic_target_condition', got both"
        )
    if not has_target_r and not has_dynamic_target:
        raise RuleAmbiguousError("structured_exit_plan must set exactly one of 'target_r_multiple'/'dynamic_target_condition'")

    target_r_multiple: float | None = None
    dynamic_target_condition: Condition | None = None
    if has_target_r:
        target_r_multiple = _parse_positive_number(raw, "target_r_multiple")
    else:
        dynamic_target_condition = _parse_condition(dynamic_target_condition_raw, allow_cross_ops=False)

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
    )


def compute_indicator_frame(candles: pd.DataFrame) -> pd.DataFrame:
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

    frame["volume"] = frame["volume"].astype(float) if "volume" in frame.columns else float("nan")

    # Matches every other candle schema in this codebase (e.g.
    # nero_core.data_sources.market_data.CANDLE_COLUMNS) -- added so
    # auto_tester.py can reuse mean_reversion.reset_daily_guard_if_needed /
    # tools.backtest_statistics.random_entry_baseline_single_asset unmodified,
    # both of which read candle["date"] directly.
    frame["date"] = pd.to_datetime(frame["close_time"], unit="ms", utc=True)

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
