import { buildHypothesisRuleLookup } from "@/lib/hypothesisRules";
import type { AgentHypothesis, EveHypothesisRecord } from "@/lib/types";

function agentHypothesis(overrides: Partial<AgentHypothesis> = {}): AgentHypothesis {
  return {
    scan_finding: "x",
    scan_finding_type: "x",
    hypothesis_name: "ADAM_ONE",
    mechanism: "x",
    entry_rule: "x",
    structured_entry_rule: { conditions: [{ field: "close", op: "gt", value: 1 }] },
    exit_rule: "x",
    stop_rule: "x",
    structured_exit_plan: { stop_atr_multiple: 1.5, target_r_multiple: 2.0 },
    asset: "BTC",
    timeframe: "4h",
    differs_from_graveyard: "x",
    expected_frequency_claim: null,
    generated_at: "x",
    cost_usd: 0,
    source: "scanner",
    ...overrides,
  };
}

function eveHypothesis(overrides: Partial<EveHypothesisRecord> = {}): EveHypothesisRecord {
  return {
    session_id: "s1",
    raw_hypothesis: {
      hypothesis_name: "EVE_ONE",
      mechanism: "x",
      structured_entry_rule: { conditions: [{ field: "zscore20", op: "lte", value: -2 }] },
      structured_exit_plan: { stop_atr_multiple: 2.0, target_r_multiple: 3.0 },
    },
    testability: "TESTABLE",
    verdict_combined: "DIED",
    frequency_classification: "VIABLE",
    measured_trades_per_year: 10,
    contamination_tags: [],
    ...overrides,
  };
}

describe("buildHypothesisRuleLookup", () => {
  it("looks up an Adam hypothesis by name", () => {
    const lookup = buildHypothesisRuleLookup([agentHypothesis()], []);
    const rules = lookup.get("ADAM_ONE");
    expect(rules?.structured_entry_rule).toEqual({ conditions: [{ field: "close", op: "gt", value: 1 }] });
  });

  it("looks up an Eve hypothesis by name, reading from raw_hypothesis", () => {
    const lookup = buildHypothesisRuleLookup([], [eveHypothesis()]);
    const rules = lookup.get("EVE_ONE");
    expect(rules?.structured_entry_rule).toEqual({ conditions: [{ field: "zscore20", op: "lte", value: -2 }] });
  });

  it("combines both sources into one lookup, real names never colliding", () => {
    const lookup = buildHypothesisRuleLookup([agentHypothesis()], [eveHypothesis()]);
    expect(lookup.size).toBe(2);
    expect(lookup.has("ADAM_ONE")).toBe(true);
    expect(lookup.has("EVE_ONE")).toBe(true);
  });

  it("skips a record with no hypothesis_name rather than crashing", () => {
    const lookup = buildHypothesisRuleLookup([agentHypothesis({ hypothesis_name: "" })], []);
    expect(lookup.size).toBe(0);
  });
});
