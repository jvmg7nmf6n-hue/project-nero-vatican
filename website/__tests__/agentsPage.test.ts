import fs from "fs";
import path from "path";
import {
  PRE_REGISTERED_SESSION_COUNT,
  computeAdamFunnel,
  computeEveCrashStats,
  computeEveDslGapRate,
  computeEveFunnel,
  computeEveSessionCostStats,
  computePreRegistrationProgress,
  extractFrequencyClaims,
} from "@/lib/agentsPage";
import type { AgentPerformanceExport, AgentRunSummary, EveBudgetLedgerEntry, EveHypothesisRecord, EveSessionRegistryExport } from "@/lib/types";

function hypothesis(overrides: Partial<EveHypothesisRecord> = {}): EveHypothesisRecord {
  return {
    session_id: "s1",
    raw_hypothesis: { hypothesis_name: "X" },
    testability: "TESTABLE",
    verdict_combined: "DIED",
    frequency_classification: "VIABLE",
    measured_trades_per_year: 40,
    contamination_tags: [],
    ...overrides,
  };
}

function ledgerEntry(overrides: Partial<EveBudgetLedgerEntry> = {}): EveBudgetLedgerEntry {
  return {
    session_id: "s1",
    status: "actual",
    actual_cost_usd: 0.1,
    projected_cost_usd: 0.1,
    month: "2026-08",
    ...overrides,
  };
}

function registry(overrides: Partial<EveSessionRegistryExport> = {}): EveSessionRegistryExport {
  return {
    pre_registration: {
      sessions_budgeted: "8 Eve sessions + 8 Adam runs (~$14)",
      eve_must_clear: "5% OOS survival, FDR-corrected PER SESSION",
      kill_criterion: "if Eve does not clear 5% after 8 (countable) sessions...",
    },
    sessions: [
      { session_id: "s0", counts_toward_pre_registered_8: false, classification: "crashed_before_completion", reason: "boom" },
      { session_id: "s1", counts_toward_pre_registered_8: true, classification: "session_1_of_8", reason: "ran to completion" },
    ],
    next_countable_session_number: 2,
    ...overrides,
  };
}

function adamPerformance(overrides: Partial<AgentPerformanceExport["cumulative"]> = {}): AgentPerformanceExport {
  return {
    schema_version: 1,
    last_updated: "x",
    cumulative: {
      hypotheses_generated: 2,
      duplicates_skipped: 0,
      too_slow_rejected: 2,
      unmeasurable_rejected: 0,
      tested: 0,
      survived: 0,
      promising_watchlist: 0,
      died: 0,
      untestable: 0,
      no_candles_available: 0,
      llm_calls_made: 9,
      total_llm_cost_usd: 0.55804,
      survival_rate: null,
      calls_with_unknown_cost: 4,
      ...overrides,
    },
    runs: [],
  };
}

describe("computePreRegistrationProgress", () => {
  it("counts sessions, survivals, and cost from real committed shapes", () => {
    const hyps = [hypothesis({ verdict_combined: "DIED" }), hypothesis({ verdict_combined: "SURVIVED" })];
    const ledger = [
      ledgerEntry({ status: "actual", actual_cost_usd: 0.5 }),
      ledgerEntry({ status: "actual", actual_cost_usd: 0.3 }),
      ledgerEntry({ status: "reserved", projected_cost_usd: 0.2 }),
    ];
    const progress = computePreRegistrationProgress(registry(), hyps, ledger, adamPerformance());

    expect(progress.sessionsCounted).toBe(1);
    expect(progress.sessionsRemaining).toBe(PRE_REGISTERED_SESSION_COUNT - 1);
    expect(progress.survivedCount).toBe(1);
    expect(progress.eveRecordedUsd).toBeCloseTo(0.8);
    expect(progress.eveUnknownCount).toBe(1);
    expect(progress.eveUnknownProjectedUsd).toBeCloseTo(0.2);
    expect(progress.adamRecordedUsd).toBeCloseTo(0.55804);
    expect(progress.adamUnknownCount).toBe(4);
  });

  it("never fabricates a count from a null registry", () => {
    const progress = computePreRegistrationProgress(null, [], [], null);
    expect(progress.sessionsCounted).toBe(0);
    expect(progress.sessionsRemaining).toBe(PRE_REGISTERED_SESSION_COUNT);
    expect(progress.sessionsBudgetedText).toBe("");
  });

  it("crashed (reserved) reservations are counted separately from recorded spend, never merged into one total", () => {
    const ledger = [ledgerEntry({ status: "reserved", projected_cost_usd: 1.27371 })];
    const progress = computePreRegistrationProgress(registry(), [], ledger, null);
    expect(progress.eveRecordedUsd).toBe(0);
    expect(progress.eveUnknownProjectedUsd).toBeCloseTo(1.27371);
    expect(progress.eveUnknownCount).toBe(1);
  });
});

describe("computeEveFunnel", () => {
  it("derives proposed/DSL-valid/reached-harness/survived from real per-record fields", () => {
    const hyps = [
      hypothesis({ session_id: "s1", testability: "TESTABLE", verdict_combined: "DIED" }),
      hypothesis({ session_id: "s1", testability: "TESTABLE", verdict_combined: "SKIPPED", frequency_classification: "TOO_SLOW" }),
      hypothesis({
        session_id: "s1",
        testability: "TESTABLE",
        verdict_combined: "DIED",
        contamination_tags: [{ tag: "SELF_DERIVATIVE" }],
      }),
      hypothesis({ session_id: "OTHER_SESSION", verdict_combined: "SURVIVED" }),
    ];
    const funnel = computeEveFunnel(hyps, "s1");

    expect(funnel.proposed).toBe(3);
    expect(funnel.dslValid).toBe(3);
    expect(funnel.reachedHarness).toBe(2); // the TOO_SLOW/SKIPPED one never reached the harness
    expect(funnel.survived).toBe(0);
    expect(funnel.tooSlowCount).toBe(1);
    expect(funnel.selfDerivativeCount).toBe(1);
  });

  it("matches the real Eve Session 1 shape from the directive's own reference numbers", () => {
    // Real committed shape, docs/site_data/eve_hypotheses.json, session
    // eve-20260804T020749Z-4cf6e4c9: 6 proposed, 6 TESTABLE, 1 TOO_SLOW
    // (never reaches the harness) -> 5 reached harness, 0 SURVIVED, 2
    // distinct hypotheses carry a SELF_DERIVATIVE tag.
    const hyps = [
      hypothesis({ session_id: "s1", verdict_combined: "DIED" }),
      hypothesis({ session_id: "s1", verdict_combined: "DIED", contamination_tags: [{ tag: "SELF_DERIVATIVE" }, { tag: "SELF_DERIVATIVE" }] }),
      hypothesis({ session_id: "s1", verdict_combined: "DIED", contamination_tags: [{ tag: "SELF_DERIVATIVE" }] }),
      hypothesis({ session_id: "s1", verdict_combined: "SKIPPED", frequency_classification: "TOO_SLOW" }),
      hypothesis({ session_id: "s1", verdict_combined: "DIED" }),
      hypothesis({ session_id: "s1", verdict_combined: "DIED" }),
    ];
    const funnel = computeEveFunnel(hyps, "s1");

    expect(funnel.proposed).toBe(6);
    expect(funnel.dslValid).toBe(6);
    expect(funnel.reachedHarness).toBe(5);
    expect(funnel.survived).toBe(0);
    expect(funnel.tooSlowCount).toBe(1);
    expect(funnel.selfDerivativeCount).toBe(2);
  });

  it("returns all zeros, never a fabricated funnel, when no session id is known yet", () => {
    const funnel = computeEveFunnel([hypothesis()], null);
    expect(funnel.proposed).toBe(0);
  });
});

describe("computeAdamFunnel", () => {
  it("reads cumulative counts directly, honestly reporting reachedHarness as 0 when both rejections were TOO_SLOW", () => {
    const funnel = computeAdamFunnel(adamPerformance());
    expect(funnel.proposed).toBe(2);
    expect(funnel.dslValid).toBe(2);
    expect(funnel.reachedHarness).toBe(0);
    expect(funnel.survived).toBe(0);
    expect(funnel.tooSlowCount).toBe(2);
  });

  it("never fabricates a count from null performance data", () => {
    const funnel = computeAdamFunnel(null);
    expect(funnel.proposed).toBe(0);
  });
});

describe("extractFrequencyClaims", () => {
  it("flattens too_slow entries across every run summary, real names only", () => {
    const summaries: AgentRunSummary[] = [
      { run_at: "r1", too_slow: null },
      {
        run_at: "r2",
        too_slow: [
          { hypothesis_name: "RSI2_TREND_PULLBACK_PAXG_4H", measured_trades_per_year: 0.498181404864742, llm_claimed_trades_per_year: 35.0 },
          { hypothesis_name: "ADX_REGIME_IGNITION_SOL_4H", measured_trades_per_year: 16.93816776540123, llm_claimed_trades_per_year: 45.0 },
        ],
      },
    ];
    const claims = extractFrequencyClaims(summaries);
    expect(claims).toHaveLength(2);
    expect(claims[0].hypothesisName).toBe("RSI2_TREND_PULLBACK_PAXG_4H");
    expect(claims[0].claimedPerYear).toBe(35.0);
    expect(claims[0].measuredPerYear).toBeCloseTo(0.498181404864742);
  });

  it("never crashes on a null too_slow entry", () => {
    expect(extractFrequencyClaims([{ run_at: "r1", too_slow: null }])).toEqual([]);
  });
});

describe("computeEveDslGapRate", () => {
  it("computes the real UNTESTABLE_BY_DSL rate from every hypothesis on file, not a fixed number", () => {
    const hyps = [
      hypothesis({ testability: "UNTESTABLE_BY_DSL" }),
      hypothesis({ testability: "UNTESTABLE_BY_DSL" }),
      hypothesis({ testability: "TESTABLE" }),
      hypothesis({ testability: "TESTABLE" }),
    ];
    const stats = computeEveDslGapRate(hyps);
    expect(stats.untestableCount).toBe(2);
    expect(stats.totalCount).toBe(4);
    expect(stats.ratePct).toBeCloseTo(50);
  });

  it("matches the real committed docs/site_data/eve_hypotheses.json shape as of 2026-08-07 (4/21, 19.0%)", () => {
    const hyps = [
      ...Array.from({ length: 4 }, () => hypothesis({ testability: "UNTESTABLE_BY_DSL" })),
      ...Array.from({ length: 17 }, () => hypothesis({ testability: "TESTABLE" })),
    ];
    const stats = computeEveDslGapRate(hyps);
    expect(stats.untestableCount).toBe(4);
    expect(stats.totalCount).toBe(21);
    expect(stats.ratePct).toBeCloseTo(19.047619, 5);
  });

  it("never divides by zero", () => {
    expect(computeEveDslGapRate([]).ratePct).toBeNull();
  });
});

describe("computeEveCrashStats", () => {
  it("counts crashed_before_completion sessions against the real total, live from the registry", () => {
    const reg = registry({
      sessions: [
        { session_id: "a", counts_toward_pre_registered_8: false, classification: "crashed_before_completion", reason: "x" },
        { session_id: "b", counts_toward_pre_registered_8: false, classification: "crashed_before_completion", reason: "x" },
        { session_id: "c", counts_toward_pre_registered_8: true, classification: "session_1_of_8", reason: "x" },
      ],
    });
    const stats = computeEveCrashStats(reg);
    expect(stats.crashedCount).toBe(2);
    expect(stats.totalCount).toBe(3);
  });

  it("never fabricates a count from a null registry", () => {
    expect(computeEveCrashStats(null)).toEqual({ crashedCount: 0, totalCount: 0 });
  });
});

describe("computeEveSessionCostStats", () => {
  it("averages actual cost per completed session, excluding crashed sessions' partial actual entries", () => {
    const reg = registry({
      sessions: [
        { session_id: "crashed-1", counts_toward_pre_registered_8: false, classification: "crashed_before_completion", reason: "x" },
        { session_id: "done-1", counts_toward_pre_registered_8: true, classification: "session_1_of_8", reason: "x" },
        { session_id: "done-2", counts_toward_pre_registered_8: true, classification: "session_2_of_8", reason: "x" },
      ],
    });
    const ledger = [
      // A crashed session can still have a real actual-cost entry for a turn
      // that succeeded before the crash -- must NOT count toward the average.
      ledgerEntry({ session_id: "crashed-1", status: "actual", actual_cost_usd: 0.21 }),
      ledgerEntry({ session_id: "crashed-1", status: "reserved", projected_cost_usd: 0.36 }),
      ledgerEntry({ session_id: "done-1", status: "actual", actual_cost_usd: 0.4 }),
      ledgerEntry({ session_id: "done-2", status: "actual", actual_cost_usd: 0.6 }),
    ];
    const stats = computeEveSessionCostStats(ledger, reg);
    expect(stats.completedSessionCount).toBe(2);
    expect(stats.averageUsd).toBeCloseTo(0.5);
  });

  it("never fabricates an average with no completed sessions", () => {
    expect(computeEveSessionCostStats([], null)).toEqual({ averageUsd: null, completedSessionCount: 0 });
  });
});

describe("PRE_REGISTERED_SESSION_COUNT stays in sync with the real committed registry", () => {
  it("matches the real docs/site_data/eve_session_registry.json's own stated session count", () => {
    const realPath = path.join(process.cwd(), "..", "docs", "site_data", "eve_session_registry.json");
    const real = JSON.parse(fs.readFileSync(realPath, "utf-8"));
    expect(real.pre_registration.sessions_budgeted).toContain("8 Eve sessions");
    expect(PRE_REGISTERED_SESSION_COUNT).toBe(8);
  });
});
