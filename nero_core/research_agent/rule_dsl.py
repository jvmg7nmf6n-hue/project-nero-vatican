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
is deliberately narrow (8 fields, 7 ops) rather than extensible-by-guessing.

NO LOOKAHEAD: every field below is a rolling/causal computation over closed
candles up to and including the evaluation row (see compute_indicator_frame).
`cross_above`/`cross_below` look at exactly one prior row, never a future one.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

ALLOWED_FIELDS = ("close", "ma20", "ma50", "ma200", "zscore20", "atr14", "ret_1", "volume")
ALLOWED_OPS = ("gt", "gte", "lt", "lte", "eq", "cross_above", "cross_below")

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
    value: float


@dataclass(frozen=True)
class StructuredRule:
    conditions: tuple[Condition, ...]  # ANDed together -- see module docstring


def parse_structured_rule(raw: object) -> StructuredRule:
    """Parses a hypothesis's structured entry_rule dict, e.g.:
        {"conditions": [{"field": "zscore20", "op": "lt", "value": -2.0}]}
    Raises RuleAmbiguousError (never returns a guessed/partial rule) if `raw`
    isn't a dict, `conditions` is missing/empty/not-a-list, or any single
    condition names an unsupported field/op or a non-numeric value."""
    if not isinstance(raw, dict):
        raise RuleAmbiguousError(f"entry_rule must be a dict with a 'conditions' list, got {type(raw).__name__}")

    conditions_raw = raw.get("conditions")
    if not isinstance(conditions_raw, list) or not conditions_raw:
        raise RuleAmbiguousError("entry_rule has no non-empty 'conditions' list -- nothing machine-checkable to evaluate")

    parsed: list[Condition] = []
    for entry in conditions_raw:
        if not isinstance(entry, dict):
            raise RuleAmbiguousError(f"condition entry must be a dict, got {entry!r}")
        field = entry.get("field")
        op = entry.get("op")
        value = entry.get("value")
        if field not in ALLOWED_FIELDS:
            raise RuleAmbiguousError(f"unsupported field {field!r} -- allowed: {sorted(ALLOWED_FIELDS)}")
        if op not in ALLOWED_OPS:
            raise RuleAmbiguousError(f"unsupported op {op!r} -- allowed: {sorted(ALLOWED_OPS)}")
        if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
            raise RuleAmbiguousError(f"condition value must be a number, got {value!r}")
        parsed.append(Condition(field=field, op=op, value=float(value)))

    return StructuredRule(conditions=tuple(parsed))


def compute_indicator_frame(candles: pd.DataFrame) -> pd.DataFrame:
    """Adds ma20/ma50/ma200/zscore20/atr14/ret_1 columns to a sorted copy of
    `candles` (which must carry close_time (epoch ms), close, high, low --
    volume is optional, defaulted to NaN if absent). Every added column is a
    trailing rolling computation ending AT its own row -- no centering, no
    forward shift, so no future candle ever leaks into a value used to
    evaluate an earlier row (this project's no-lookahead-bias rule, CLAUDE.md).

    zscore20 uses the identical formula (trailing-20 mean/std, ddof=1) as
    nero_core.quant.quant_panel.rolling_zscore -- vectorized across the whole
    series here (rather than that function's single-latest-value-per-call
    shape) purely for performance across hundreds/thousands of candles, not a
    different definition.
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

    frame["volume"] = frame["volume"].astype(float) if "volume" in frame.columns else float("nan")

    return frame


def evaluate_condition(row: "pd.Series", condition: Condition, prev_row: "pd.Series | None") -> bool | None:
    """True/False if `condition` can be evaluated at `row`; None if the
    relevant field is still NaN (indicator warmup, e.g. row 5 of a ma200
    column) -- a warmup row is "does not fire," not an error and not the same
    as RuleAmbiguousError (which means the RULE itself, not one row, can't be
    evaluated at all)."""
    value = row.get(condition.field)
    if value is None or pd.isna(value):
        return None

    if condition.op in ("cross_above", "cross_below"):
        if prev_row is None:
            return False
        prev_value = prev_row.get(condition.field)
        if prev_value is None or pd.isna(prev_value):
            return False
        threshold = condition.value
        if condition.op == "cross_above":
            return bool(prev_value <= threshold < value)
        return bool(prev_value >= threshold > value)

    threshold = condition.value
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
