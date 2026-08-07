// CC-1 directive, "every strategy page must show entry/exit rules and trade
// frequency": translates a real structured_entry_rule/structured_exit_plan
// (nero_core/research_agent/rule_dsl.py's own DSL -- the exact shapes
// documented in that module's parse_structured_rule/parse_exit_plan
// docstrings) into plain, human-readable text. Pure, reusable across every
// page that shows a Forward Trial hypothesis's real rule -- not duplicated
// per page. Vocabulary here (FIELD_LABELS/OP_LABELS) is a direct transcription
// of rule_dsl.py's own ALLOWED_FIELDS/ALLOWED_OPS -- see
// __tests__/ruleTranslation.test.ts's own sync-check test.

// Exported so a sync test (__tests__/ruleTranslation.test.ts) can assert
// directly against the real DSL vocabulary rather than reasoning indirectly
// through translated string content (a field whose correct label happens to
// equal its raw name, e.g. "volume", would make an indirect check pass
// vacuously).
export const FIELD_LABELS: Record<string, string> = {
  close: "price",
  ma20: "20-period moving average",
  ma50: "50-period moving average",
  ma200: "200-period moving average",
  zscore20: "20-period z-score",
  atr14: "14-period ATR (volatility)",
  rsi14: "14-period RSI",
  adx14: "14-period ADX (trend strength)",
  bb_lower: "lower Bollinger Band",
  bb_upper: "upper Bollinger Band",
  ret_1: "1-period return",
  volume: "volume",
  hour_of_day: "hour of day",
  high20: "20-period high",
  low20: "20-period low",
  vol_ma20: "20-period average volume",
  real_yield_10y_chg20: "20-day change in the 10-year real yield",
  dxy_chg20: "20-day change in the US Dollar Index",
  vix_chg20: "20-day change in the VIX",
  funding_rate_bps: "funding rate (bps)",
};

export const OP_LABELS: Record<string, string> = {
  gt: "is above",
  gte: "is at or above",
  lt: "is below",
  lte: "is at or below",
  eq: "equals",
  cross_above: "crosses above",
  cross_below: "crosses below",
};

function fieldLabel(field: unknown): string {
  return typeof field === "string" ? FIELD_LABELS[field] ?? field : "an unrecognized field";
}

function opLabel(op: unknown): string {
  return typeof op === "string" ? OP_LABELS[op] ?? op : "an unrecognized comparison";
}

interface RawCondition {
  field?: unknown;
  op?: unknown;
  value?: unknown;
  compare_to_field?: unknown;
}

function translateCondition(condition: RawCondition): string {
  const field = fieldLabel(condition.field);
  const op = opLabel(condition.op);
  if (condition.compare_to_field !== undefined && condition.compare_to_field !== null) {
    return `${field} ${op} ${fieldLabel(condition.compare_to_field)}`;
  }
  return `${field} ${op} ${condition.value ?? "an unspecified value"}`;
}

// Real DSL shape (rule_dsl.parse_structured_rule): {"conditions": [...]},
// every condition ANDed together. Returns null (never a fabricated
// placeholder) if `raw` isn't the real shape at all -- a hypothesis that
// failed DSL validation upstream (UNTESTABLE_BY_DSL) may carry null/garbage
// here, and this must read as "no rule to show," not a guessed one.
export function translateEntryRule(raw: unknown): string | null {
  if (!raw || typeof raw !== "object" || !("conditions" in raw)) return null;
  const conditions = (raw as { conditions?: unknown }).conditions;
  if (!Array.isArray(conditions) || conditions.length === 0) return null;
  const parts = conditions.map((c) => translateCondition(c as RawCondition));
  return `Enter when ${parts.join(" AND ")}.`;
}

interface RawExitPlan {
  stop_atr_multiple?: unknown;
  stop_pct_of_entry?: unknown;
  target_r_multiple?: unknown;
  target_pct_of_entry?: unknown;
  dynamic_target_condition?: unknown;
  max_holding_hours?: unknown;
  regime_break_condition?: unknown;
  regime_break_consecutive_bars?: unknown;
}

function stopClause(plan: RawExitPlan): string | null {
  if (typeof plan.stop_atr_multiple === "number") {
    return `a stop-loss ${plan.stop_atr_multiple}x ATR(14) from entry`;
  }
  if (typeof plan.stop_pct_of_entry === "number") {
    return `a stop-loss ${(plan.stop_pct_of_entry * 100).toFixed(1)}% from entry`;
  }
  return null;
}

function targetClause(plan: RawExitPlan): string | null {
  if (typeof plan.target_r_multiple === "number") {
    return `a target at ${plan.target_r_multiple}x the initial risk (${plan.target_r_multiple}R)`;
  }
  if (typeof plan.target_pct_of_entry === "number") {
    return `a target ${(plan.target_pct_of_entry * 100).toFixed(1)}% from entry`;
  }
  if (plan.dynamic_target_condition && typeof plan.dynamic_target_condition === "object") {
    return `a moving target: exit when ${translateCondition(plan.dynamic_target_condition as RawCondition)}`;
  }
  return null;
}

// Real DSL shape (rule_dsl.parse_exit_plan). Returns null (never a
// fabricated placeholder) if `raw` isn't a real exit-plan-shaped object.
export function translateExitPlan(raw: unknown): string | null {
  if (!raw || typeof raw !== "object") return null;
  const plan = raw as RawExitPlan;
  const clauses = [stopClause(plan), targetClause(plan)].filter((c): c is string => c !== null);
  if (clauses.length === 0) return null;

  if (typeof plan.max_holding_hours === "number") {
    clauses.push(`a maximum hold of ${plan.max_holding_hours} hours`);
  }
  if (plan.regime_break_condition && typeof plan.regime_break_condition === "object") {
    const bars = typeof plan.regime_break_consecutive_bars === "number" ? plan.regime_break_consecutive_bars : "several";
    clauses.push(
      `an early exit if ${translateCondition(plan.regime_break_condition as RawCondition)} for ${bars} consecutive bars`
    );
  }

  return `Exit at whichever comes first: ${clauses.join(", or ")}.`;
}
