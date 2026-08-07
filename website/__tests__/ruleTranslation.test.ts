import fs from "fs";
import path from "path";
import { FIELD_LABELS, OP_LABELS, translateEntryRule, translateExitPlan } from "@/lib/ruleTranslation";

describe("translateEntryRule", () => {
  it("translates a single-value condition into plain language", () => {
    expect(translateEntryRule({ conditions: [{ field: "zscore20", op: "lte", value: -2 }] })).toBe(
      "Enter when 20-period z-score is at or below -2."
    );
  });

  it("translates a field-vs-field condition", () => {
    expect(
      translateEntryRule({ conditions: [{ field: "ma20", op: "cross_above", compare_to_field: "ma50" }] })
    ).toBe("Enter when 20-period moving average crosses above 50-period moving average.");
  });

  it("joins multiple conditions with AND, matching the DSL's own ANDed semantics", () => {
    const result = translateEntryRule({
      conditions: [
        { field: "zscore20", op: "lte", value: -2 },
        { field: "rsi14", op: "lte", value: 30 },
      ],
    });
    expect(result).toBe("Enter when 20-period z-score is at or below -2 AND 14-period RSI is at or below 30.");
  });

  // Real case, docs/site_data/eve_hypotheses.json's own "Weekly Precious-Metals
  // Extreme Z-Score Reversion with RSI Confirmation" hypothesis (verified
  // 2026-08-08, structured_entry_rule read directly from the committed file).
  it("translates the real committed GOLD/1week z-score+RSI hypothesis correctly", () => {
    const real = {
      conditions: [
        { field: "zscore20", op: "lte", value: -2 },
        { field: "rsi14", op: "lte", value: 30 },
      ],
    };
    expect(translateEntryRule(real)).toBe(
      "Enter when 20-period z-score is at or below -2 AND 14-period RSI is at or below 30."
    );
  });

  it("returns null, never a fabricated rule, for a non-DSL-shaped input", () => {
    expect(translateEntryRule(null)).toBeNull();
    expect(translateEntryRule("not an object")).toBeNull();
    expect(translateEntryRule({ conditions: [] })).toBeNull();
    expect(translateEntryRule({})).toBeNull();
  });

  it("falls back to the raw field/op name rather than crashing on an unrecognized one", () => {
    expect(translateEntryRule({ conditions: [{ field: "made_up_field", op: "gt", value: 1 }] })).toBe(
      "Enter when made_up_field is above 1."
    );
  });
});

describe("translateExitPlan", () => {
  it("translates the original fixed-R-multiple shape", () => {
    expect(translateExitPlan({ stop_atr_multiple: 1.5, target_r_multiple: 2.0, max_holding_hours: 48 })).toBe(
      "Exit at whichever comes first: a stop-loss 1.5x ATR(14) from entry, or a target at 2x the initial risk (2R), or a maximum hold of 48 hours."
    );
  });

  // Real case, the same committed GOLD/1week z-score hypothesis's own
  // structured_exit_plan -- a dynamic (moving) target, not a fixed R-multiple.
  it("translates the real committed dynamic-target exit plan correctly", () => {
    const real = {
      stop_atr_multiple: 2.0,
      target: "dynamic_target_condition",
      dynamic_target_condition: { field: "close", op: "gte", compare_to_field: "ma20" },
      max_holding_hours: 2160,
    };
    expect(translateExitPlan(real)).toBe(
      "Exit at whichever comes first: a stop-loss 2x ATR(14) from entry, or a moving target: exit when price is at or above 20-period moving average, or a maximum hold of 2160 hours."
    );
  });

  it("translates the percentage-based shape", () => {
    expect(translateExitPlan({ stop_pct_of_entry: 0.03, target_pct_of_entry: 0.01 })).toBe(
      "Exit at whichever comes first: a stop-loss 3.0% from entry, or a target 1.0% from entry."
    );
  });

  it("includes a regime-break early exit when present", () => {
    const result = translateExitPlan({
      stop_atr_multiple: 2.0,
      dynamic_target_condition: { field: "close", op: "gte", compare_to_field: "ma20" },
      regime_break_condition: { field: "adx14", op: "gte", value: 28 },
      regime_break_consecutive_bars: 2,
    });
    expect(result).toContain("an early exit if 14-period ADX (trend strength) is at or above 28 for 2 consecutive bars");
  });

  it("omits the max-holding clause entirely when absent, per the DSL's own 'no time exit' convention", () => {
    const result = translateExitPlan({ stop_atr_multiple: 2.0, target_r_multiple: 3.0 });
    expect(result).not.toContain("maximum hold");
  });

  it("returns null, never a fabricated plan, for a non-DSL-shaped input", () => {
    expect(translateExitPlan(null)).toBeNull();
    expect(translateExitPlan({})).toBeNull();
    expect(translateExitPlan("not an object")).toBeNull();
  });
});

// CC-1 directive's own accuracy standard: this vocabulary must never silently
// drift from the real DSL it translates. Reads nero_core/research_agent/
// rule_dsl.py directly and asserts every real ALLOWED_FIELDS/ALLOWED_OPS
// entry has a translation -- a future field/op added to the DSL without a
// matching label here fails this test instead of silently falling back to
// its raw internal name on a real hypothesis's rendered page.
describe("rule vocabulary stays in sync with the real DSL", () => {
  const dslSource = fs.readFileSync(
    path.join(process.cwd(), "..", "nero_core", "research_agent", "rule_dsl.py"),
    "utf-8"
  );

  function extractTuple(constantName: string): string[] {
    // rule_dsl.py has CRLF line endings -- \r?\n, not just \n.
    const match = dslSource.match(new RegExp(`${constantName} = \\(([\\s\\S]*?)\\)\\r?\\n`));
    expect(match).not.toBeNull();
    return Array.from(match![1].matchAll(/"([a-z0-9_]+)"/g)).map((m) => m[1]);
  }

  it("every real ALLOWED_FIELDS entry has a translation label", () => {
    const realFields = extractTuple("ALLOWED_FIELDS");
    expect(realFields.length).toBeGreaterThan(0);
    for (const field of realFields) {
      expect(FIELD_LABELS).toHaveProperty(field);
    }
  });

  it("every real ALLOWED_OPS entry has a translation label", () => {
    const realOps = extractTuple("ALLOWED_OPS");
    expect(realOps.length).toBeGreaterThan(0);
    for (const op of realOps) {
      expect(OP_LABELS).toHaveProperty(op);
    }
  });
});
