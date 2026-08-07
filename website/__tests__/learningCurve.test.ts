import {
  computeAdamHypothesisQuality,
  computeAdamReliability,
  computeEveHypothesisQuality,
  computeEveReliability,
  computeNearMissFunnel,
} from "@/lib/learningCurve";
import type { AgentPerformanceExport, EveHypothesisRecord, EveSessionRecord, EveSessionRegistryExport } from "@/lib/types";

function registry(overrides: Partial<EveSessionRegistryExport> = {}): EveSessionRegistryExport {
  return {
    pre_registration: { sessions_budgeted: "x", eve_must_clear: "x", kill_criterion: "x" },
    sessions: [
      { session_id: "eve-crash-1", counts_toward_pre_registered_8: false, classification: "crashed_before_completion", reason: "x" },
      { session_id: "eve-done-1", counts_toward_pre_registered_8: true, classification: "session_1_of_8", reason: "x" },
    ],
    next_countable_session_number: 2,
    ...overrides,
  };
}

function hyp(overrides: Partial<EveHypothesisRecord> = {}): EveHypothesisRecord {
  return {
    session_id: "eve-done-1",
    raw_hypothesis: { hypothesis_name: "X" },
    testability: "TESTABLE",
    verdict_combined: "DIED",
    frequency_classification: "VIABLE",
    measured_trades_per_year: 10,
    contamination_tags: [],
    ...overrides,
  };
}

describe("computeEveReliability", () => {
  it("sources a crashed session from the registry when it predates the crash-safety mechanism (no session file exists)", () => {
    const result = computeEveReliability(registry(), new Map());
    const crashPoint = result.find((r) => r.label === "eve-crash-1");
    expect(crashPoint?.crashed).toBe(true);
    expect(crashPoint?.source).toBe("eve_registry_predates_crash_safety");
  });

  it("sources a completed session's real status from its own auto-written session file", () => {
    const sessionRecords = new Map<string, EveSessionRecord | null>([
      ["eve-done-1", { session_id: "eve-done-1", terminated_because: "end_session_called" }],
    ]);
    const result = computeEveReliability(registry(), sessionRecords);
    const donePoint = result.find((r) => r.label === "eve-done-1");
    expect(donePoint?.crashed).toBe(false);
    expect(donePoint?.source).toBe("eve_session_file");
  });

  it("treats a partial session file as crashed even if terminated_because looks otherwise", () => {
    const sessionRecords = new Map<string, EveSessionRecord | null>([
      ["eve-done-1", { session_id: "eve-done-1", terminated_because: "crashed_mid_session", partial: true }],
    ]);
    const result = computeEveReliability(registry(), sessionRecords);
    expect(result.find((r) => r.label === "eve-done-1")?.crashed).toBe(true);
  });

  it("never fabricates a point from a null registry", () => {
    expect(computeEveReliability(null, new Map())).toEqual([]);
  });

  it("matches the real committed state as of 2026-08-08: 10 sessions, 6 crashed via registry, 4 via session file", () => {
    const realRegistry = registry({
      sessions: [
        { session_id: "eve-20260803T074058Z-df7df0f9", counts_toward_pre_registered_8: false, classification: "crashed_before_completion", reason: "x" },
        { session_id: "eve-20260803T075102Z-2b98a5f0", counts_toward_pre_registered_8: false, classification: "crashed_before_completion", reason: "x" },
        { session_id: "eve-20260803T080243Z-29f48c2e", counts_toward_pre_registered_8: false, classification: "crashed_before_completion", reason: "x" },
        { session_id: "eve-20260803T080720Z-12e60677", counts_toward_pre_registered_8: false, classification: "crashed_before_completion", reason: "x" },
        { session_id: "eve-20260803T081007Z-b7568699", counts_toward_pre_registered_8: false, classification: "crashed_before_completion", reason: "x" },
        { session_id: "eve-20260804T015806Z-243d095f", counts_toward_pre_registered_8: false, classification: "crashed_before_completion", reason: "x" },
        { session_id: "eve-20260803T095520Z-394385c7", counts_toward_pre_registered_8: false, classification: "session_0_proof_run", reason: "x" },
        { session_id: "eve-20260803T142519Z-718833c9", counts_toward_pre_registered_8: false, classification: "session_0_b_asset_universe_gap", reason: "x" },
        { session_id: "eve-20260804T020749Z-4cf6e4c9", counts_toward_pre_registered_8: true, classification: "session_1_of_8", reason: "x" },
        { session_id: "eve-20260806T180819Z-e777cdef", counts_toward_pre_registered_8: true, classification: "session_2_of_8", reason: "x" },
      ],
    });
    const sessionRecords = new Map<string, EveSessionRecord | null>(
      ["eve-20260803T095520Z-394385c7", "eve-20260803T142519Z-718833c9", "eve-20260804T020749Z-4cf6e4c9", "eve-20260806T180819Z-e777cdef"].map(
        (id) => [id, { session_id: id, terminated_because: "end_session_called" }]
      )
    );
    const result = computeEveReliability(realRegistry, sessionRecords);
    expect(result.length).toBe(10);
    expect(result.filter((r) => r.crashed).length).toBe(6);
    expect(result.filter((r) => !r.crashed).length).toBe(4);
  });
});

describe("computeAdamReliability", () => {
  it("applies the real corrections for the two pre-instrumentation runs", () => {
    const perf: AgentPerformanceExport = {
      schema_version: 1, last_updated: "x",
      cumulative: {} as AgentPerformanceExport["cumulative"],
      runs: [
        { run_at: "r0", enabled: true, reason: "", status: undefined as never, errors: [], hypotheses_generated: 0, duplicates_skipped: 0, too_slow_rejected: 0, unmeasurable_rejected: 0, tested: 0, survived: 0, promising_watchlist: 0, died: 0, untestable: 0, no_candles_available: 0, llm_calls_made: 0, total_llm_cost_usd: 0, cost_limit_hit: false },
        { run_at: "r1", enabled: true, reason: "", status: undefined as never, errors: [], hypotheses_generated: 0, duplicates_skipped: 0, too_slow_rejected: 0, unmeasurable_rejected: 0, tested: 0, survived: 0, promising_watchlist: 0, died: 0, untestable: 0, no_candles_available: 0, llm_calls_made: 0, total_llm_cost_usd: 0, cost_limit_hit: false },
      ],
      corrections: [
        { correction_id: "c0", applies_to_run_at: "r0", corrected_at: "x", reason_field_absent: "x", inferred_status: "clean", inferred_status_basis: "x", note: "x" },
        { correction_id: "c1", applies_to_run_at: "r1", corrected_at: "x", reason_field_absent: "x", inferred_status: "error", inferred_status_basis: "x", note: "x" },
      ],
    };
    const result = computeAdamReliability(perf);
    expect(result[0].crashed).toBe(false);
    expect(result[1].crashed).toBe(true);
  });

  it("never fabricates a point from null performance data", () => {
    expect(computeAdamReliability(null)).toEqual([]);
  });
});

describe("computeEveHypothesisQuality", () => {
  it("groups by session, matching the real committed shape (Session 0: 4/4 UNTESTABLE_BY_DSL)", () => {
    const hyps = [
      hyp({ session_id: "session-0", testability: "UNTESTABLE_BY_DSL" }),
      hyp({ session_id: "session-0", testability: "UNTESTABLE_BY_DSL" }),
      hyp({ session_id: "session-1", testability: "TESTABLE" }),
    ];
    const result = computeEveHypothesisQuality(hyps);
    const session0 = result.find((r) => r.label === "session-0");
    expect(session0).toEqual({ label: "session-0", totalCount: 2, untestableCount: 2 });
    const session1 = result.find((r) => r.label === "session-1");
    expect(session1).toEqual({ label: "session-1", totalCount: 1, untestableCount: 0 });
  });

  it("produces no point at all for a crashed session with zero hypotheses, never a fabricated zero-point", () => {
    const result = computeEveHypothesisQuality([hyp({ session_id: "session-1" })]);
    expect(result.find((r) => r.label === "crashed-session-with-nothing")).toBeUndefined();
  });
});

describe("computeAdamHypothesisQuality", () => {
  it("only includes runs that actually generated a hypothesis", () => {
    const perf: AgentPerformanceExport = {
      schema_version: 1, last_updated: "x", cumulative: {} as AgentPerformanceExport["cumulative"],
      runs: [
        { run_at: "r0", enabled: true, reason: "", status: "clean", errors: [], hypotheses_generated: 0, duplicates_skipped: 0, too_slow_rejected: 0, unmeasurable_rejected: 0, tested: 0, survived: 0, promising_watchlist: 0, died: 0, untestable: 0, no_candles_available: 0, llm_calls_made: 0, total_llm_cost_usd: 0, cost_limit_hit: false },
        { run_at: "r1", enabled: true, reason: "", status: "clean", errors: [], hypotheses_generated: 3, duplicates_skipped: 0, too_slow_rejected: 0, unmeasurable_rejected: 1, tested: 2, survived: 0, promising_watchlist: 0, died: 2, untestable: 0, no_candles_available: 0, llm_calls_made: 3, total_llm_cost_usd: 1.5, cost_limit_hit: true },
      ],
    };
    const result = computeAdamHypothesisQuality(perf);
    expect(result).toEqual([{ label: "r1", totalCount: 3, untestableCount: 0 }]);
  });
});

describe("computeNearMissFunnel", () => {
  it("matches the real committed state as of 2026-08-08: 1 near-miss, 0 referenced, 0 in Forward Trial, 0 survived", () => {
    const hyps = [
      hyp({ raw_hypothesis: { hypothesis_name: "BTC_MOMENTUM_IGNITION" }, verdict_is: "DIED", verdict_oos: "PROMISING-WATCHLIST", fdr_survives_is: true, fdr_survives_oos: false }),
      hyp({ raw_hypothesis: { hypothesis_name: "CHANNEL_BREAKOUT_HIGH20_BTC_4H", derived_from: { parent_hypothesis_name: "VOL_CONFIRMED_CHANNEL_BREAKOUT_BTC_4H" } } }),
    ];
    const result = computeNearMissFunnel(hyps, new Set());
    expect(result.nearMissCount).toBe(1);
    expect(result.nearMissNames).toEqual(["BTC_MOMENTUM_IGNITION"]);
    expect(result.referencedInDerivedFromCount).toBe(0); // declared parent is a DIFFERENT hypothesis, not the near-miss.
    expect(result.reachedForwardTrialCount).toBe(0);
    expect(result.survivedCount).toBe(0);
  });

  it("counts a real refinement of a real near-miss through the funnel", () => {
    const hyps = [
      hyp({ raw_hypothesis: { hypothesis_name: "NEAR_MISS_ONE" }, verdict_is: "SURVIVED", verdict_oos: "INSUFFICIENT_SAMPLE" }),
      hyp({ raw_hypothesis: { hypothesis_name: "REFINED_ONE", derived_from: { parent_hypothesis_name: "NEAR_MISS_ONE" } }, verdict_combined: "SURVIVED" }),
    ];
    const result = computeNearMissFunnel(hyps, new Set(["REFINED_ONE"]));
    expect(result.nearMissCount).toBe(1);
    expect(result.referencedInDerivedFromCount).toBe(1);
    expect(result.reachedForwardTrialCount).toBe(1);
    expect(result.survivedCount).toBe(1);
  });

  it("never fabricates a funnel stage from an empty hypothesis list", () => {
    const result = computeNearMissFunnel([], new Set());
    expect(result).toEqual({ nearMissCount: 0, referencedInDerivedFromCount: 0, reachedForwardTrialCount: 0, survivedCount: 0, nearMissNames: [] });
  });
});
