import { conflictedFlags, flagsForAsset, latestReadForAsset, provenanceCounts } from "@/lib/macroReads";
import type { MacroConflictFlagRecord, MacroReadRecord } from "@/lib/types";

function read(overrides: Partial<MacroReadRecord> = {}): MacroReadRecord {
  return {
    run_id: "r1",
    timestamp: "2026-08-07T00:00:00Z",
    asset: "GOLD",
    bias: "NEUTRAL",
    confidence: 0.3,
    agreement: 0.2,
    coverage: 0.1,
    probability_up: 0.5,
    provenance_breakdown: { monetary_policy: "real", news_intelligence: "synthetic" },
    reasoning: "x",
    risks: [],
    alternative_scenarios: [],
    data_mode: "live",
    ...overrides,
  };
}

describe("latestReadForAsset", () => {
  it("returns null when no reads exist for the asset", () => {
    expect(latestReadForAsset([], "GOLD")).toBeNull();
    expect(latestReadForAsset([read({ asset: "BITCOIN" })], "GOLD")).toBeNull();
  });

  it("returns the most recent read by timestamp", () => {
    const older = read({ timestamp: "2026-08-01T00:00:00Z", bias: "BEARISH" });
    const newer = read({ timestamp: "2026-08-06T00:00:00Z", bias: "BULLISH" });
    expect(latestReadForAsset([older, newer], "GOLD")?.bias).toBe("BULLISH");
    expect(latestReadForAsset([newer, older], "GOLD")?.bias).toBe("BULLISH");
  });
});

describe("provenanceCounts", () => {
  it("counts each provenance label", () => {
    const counts = provenanceCounts({
      a: "real", b: "real", c: "mixed", d: "synthetic", e: "synthetic", f: "synthetic", g: "unavailable",
    });
    expect(counts).toEqual({ real: 2, mixed: 1, synthetic: 3, unavailable: 1, total: 7 });
  });

  it("handles an empty breakdown", () => {
    expect(provenanceCounts({})).toEqual({ real: 0, mixed: 0, synthetic: 0, unavailable: 0, total: 0 });
  });
});

describe("flagsForAsset / conflictedFlags", () => {
  const flags: MacroConflictFlagRecord[] = [
    { execution_log_id: 1, macro_read_id: 1, strategy: "ORDERFLOW_IMBALANCE", asset: "BTC", entry_direction: "LONG", conflicted: true, status: "evaluated", reason: "x", evaluated_at: "x" },
    { execution_log_id: 2, macro_read_id: null, strategy: "ORDERFLOW_IMBALANCE", asset: "BTC", entry_direction: "SHORT", conflicted: false, status: "insufficient_data", reason: "x", evaluated_at: "x" },
    { execution_log_id: 3, macro_read_id: 2, strategy: "ORDERFLOW_IMBALANCE", asset: "ETH", entry_direction: "LONG", conflicted: true, status: "evaluated", reason: "x", evaluated_at: "x" },
  ];

  it("filters by asset", () => {
    expect(flagsForAsset(flags, "BTC")).toHaveLength(2);
    expect(flagsForAsset(flags, "ETH")).toHaveLength(1);
  });

  it("filters to conflicted only", () => {
    expect(conflictedFlags(flags)).toHaveLength(2);
    expect(conflictedFlags(flags).every((f) => f.conflicted)).toBe(true);
  });
});
