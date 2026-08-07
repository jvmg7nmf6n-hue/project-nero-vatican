// CC-1 Master Directive, Phase 2 -- pure derivation functions for
// app/agents/page.tsx, kept separate and testable in isolation (matching
// lib/researchScoreboard.ts's own precedent), rather than computed inline
// in the page component.
import type { AgentPerformanceExport, AgentRunSummary, EveBudgetLedgerEntry, EveHypothesisRecord, EveSessionRegistryExport } from "./types";

// The pre-registered bar itself (nero_core.eve session count) -- this
// number is a human commitment recorded in eve_session_registry.json's own
// prose (pre_registration.sessions_budgeted, pre_registration.kill_criterion),
// not re-derived here; PRE_REGISTERED_SESSION_COUNT exists ONLY to compute
// "M remaining", and is kept in exact sync with that prose by
// __tests__/agentsPage.test.ts's own cross-check against the real committed
// registry file.
export const PRE_REGISTERED_SESSION_COUNT = 8;

export interface PreRegistrationProgress {
  sessionsCounted: number;
  sessionsRemaining: number;
  survivedCount: number;
  eveRecordedUsd: number;
  eveUnknownCount: number;
  eveUnknownProjectedUsd: number;
  adamRecordedUsd: number;
  adamUnknownCount: number;
  sessionsBudgetedText: string;
}

export function computePreRegistrationProgress(
  registry: EveSessionRegistryExport | null,
  hypotheses: EveHypothesisRecord[],
  ledger: EveBudgetLedgerEntry[],
  adamPerformance: AgentPerformanceExport | null
): PreRegistrationProgress {
  const sessionsCounted = registry ? registry.sessions.filter((s) => s.counts_toward_pre_registered_8).length : 0;
  const survivedCount = hypotheses.filter((h) => h.verdict_combined === "SURVIVED").length;

  const eveRecordedUsd = ledger.filter((e) => e.status === "actual").reduce((sum, e) => sum + (e.actual_cost_usd ?? 0), 0);
  const eveOrphaned = ledger.filter((e) => e.status === "reserved");
  const eveUnknownProjectedUsd = eveOrphaned.reduce((sum, e) => sum + e.projected_cost_usd, 0);

  const adamCumulative = adamPerformance?.cumulative ?? null;

  return {
    sessionsCounted,
    sessionsRemaining: Math.max(0, PRE_REGISTERED_SESSION_COUNT - sessionsCounted),
    survivedCount,
    eveRecordedUsd,
    eveUnknownCount: eveOrphaned.length,
    eveUnknownProjectedUsd,
    adamRecordedUsd: adamCumulative?.total_llm_cost_usd ?? 0,
    adamUnknownCount: adamCumulative?.calls_with_unknown_cost ?? 0,
    sessionsBudgetedText: registry?.pre_registration.sessions_budgeted ?? "",
  };
}

export interface AgentFunnel {
  label: string;
  proposed: number;
  dslValid: number;
  reachedHarness: number;
  survived: number;
  tooSlowCount: number;
  selfDerivativeCount: number;
}

// Eve's funnel is scoped to ONE session -- the countable one (or the most
// recent, if none counts yet) -- deliberately not an all-sessions total:
// Session 0 (4/4 UNTESTABLE_BY_DSL, a since-fixed spec defect) and Session
// 0-B (6/6 TESTABLE but 0/6 scored, a different since-fixed spec defect)
// would silently distort a pooled funnel with two already-corrected gaps
// that no longer describe the current system. See this branch's own
// closing report for the real numbers this produces against the committed
// data.
export function computeEveFunnel(hypotheses: EveHypothesisRecord[], sessionId: string | null): AgentFunnel {
  const records = sessionId ? hypotheses.filter((h) => h.session_id === sessionId) : [];
  const dslValid = records.filter((r) => r.testability === "TESTABLE" || r.testability === "UNTESTABLE_BY_HARNESS");
  const reachedHarness = records.filter((r) => r.verdict_combined !== null && r.verdict_combined !== "SKIPPED" && r.verdict_combined !== "UNTESTABLE");
  const survived = records.filter((r) => r.verdict_combined === "SURVIVED");
  const tooSlow = records.filter((r) => r.frequency_classification === "TOO_SLOW");
  const selfDerivative = records.filter((r) => r.contamination_tags.some((t) => t.tag === "SELF_DERIVATIVE"));

  return {
    label: "Eve",
    proposed: records.length,
    dslValid: dslValid.length,
    reachedHarness: reachedHarness.length,
    survived: survived.length,
    tooSlowCount: tooSlow.length,
    selfDerivativeCount: selfDerivative.length,
  };
}

// Adam's own equivalent, from the SAME committed exports the /lab page's
// ResearchAgentPanel already reads (agent_performance.json's cumulative
// block) -- no separate per-hypothesis DSL-valid signal exists for Adam the
// way testability does for Eve (Adam's scanner/web-search prompts already
// constrain the shape at generation time), so dslValid is reported equal to
// proposed, honestly: every one of Adam's 2 real hypotheses DID reach the
// frequency gate, meaning both parsed.
export function computeAdamFunnel(adamPerformance: AgentPerformanceExport | null): AgentFunnel {
  const cumulative = adamPerformance?.cumulative ?? null;
  const proposed = cumulative?.hypotheses_generated ?? 0;
  const tooSlow = cumulative?.too_slow_rejected ?? 0;
  const tested = cumulative?.tested ?? 0;
  const survived = cumulative?.survived ?? 0;

  return {
    label: "Adam",
    proposed,
    dslValid: proposed,
    reachedHarness: tested,
    survived,
    tooSlowCount: tooSlow,
    selfDerivativeCount: 0,
  };
}

export interface EveDslGapStats {
  untestableCount: number;
  totalCount: number;
  ratePct: number | null;
}

// CC-1 directive, "Detailed Adam/Eve briefing": the real DSL-vocabulary-gap
// rate, computed live from every Eve hypothesis on file rather than
// hardcoded -- it moved (40% -> 25% -> 19%) as more sessions ran after the
// same-day 2026-08-03 fix, so a static number would already be stale.
// Adam has no equivalent gap in his own real history (0 UNTESTABLE
// verdicts across every committed test result) -- his own count is read
// directly from agent_performance.json's cumulative.untestable field,
// not computed here.
export function computeEveDslGapRate(hypotheses: EveHypothesisRecord[]): EveDslGapStats {
  const totalCount = hypotheses.length;
  const untestableCount = hypotheses.filter((h) => h.testability === "UNTESTABLE_BY_DSL").length;
  return {
    untestableCount,
    totalCount,
    ratePct: totalCount > 0 ? (100 * untestableCount) / totalCount : null,
  };
}

export interface EveCrashStats {
  crashedCount: number;
  totalCount: number;
}

export function computeEveCrashStats(registry: EveSessionRegistryExport | null): EveCrashStats {
  const sessions = registry?.sessions ?? [];
  return {
    crashedCount: sessions.filter((s) => s.classification === "crashed_before_completion").length,
    totalCount: sessions.length,
  };
}

export interface EveSessionCostStats {
  averageUsd: number | null;
  completedSessionCount: number;
}

// "Completed" here means the registry's own classification says so, NOT
// "has at least one actual-status ledger entry" -- 3 of the 6 crashed
// sessions also have a real actual_cost_usd entry for turns that
// succeeded before the crash, so that alone would misclassify them.
export function computeEveSessionCostStats(
  ledger: EveBudgetLedgerEntry[],
  registry: EveSessionRegistryExport | null
): EveSessionCostStats {
  const completedSessionIds = new Set(
    (registry?.sessions ?? []).filter((s) => s.classification !== "crashed_before_completion").map((s) => s.session_id)
  );
  const totalsBySession = new Map<string, number>();
  for (const entry of ledger) {
    if (entry.status !== "actual" || !completedSessionIds.has(entry.session_id)) continue;
    totalsBySession.set(entry.session_id, (totalsBySession.get(entry.session_id) ?? 0) + (entry.actual_cost_usd ?? 0));
  }
  const completedSessionCount = totalsBySession.size;
  const sum = Array.from(totalsBySession.values()).reduce((a, b) => a + b, 0);
  return {
    averageUsd: completedSessionCount > 0 ? sum / completedSessionCount : null,
    completedSessionCount,
  };
}

export interface FrequencyClaim {
  hypothesisName: string;
  claimedPerYear: number;
  measuredPerYear: number;
}

// Sourced from agent_run_summaries.json's own `too_slow` entries (real,
// committed, per-hypothesis names -- see the CC-1 Factory Loop rollout
// closeout's own item 4a wiring) across every run summary on file, not
// hardcoded -- if a future run adds a third TOO_SLOW rejection, it appears
// here automatically.
export function extractFrequencyClaims(runSummaries: AgentRunSummary[]): FrequencyClaim[] {
  const claims: FrequencyClaim[] = [];
  for (const summary of runSummaries) {
    for (const entry of summary.too_slow ?? []) {
      claims.push({
        hypothesisName: entry.hypothesis_name,
        claimedPerYear: entry.llm_claimed_trades_per_year,
        measuredPerYear: entry.measured_trades_per_year,
      });
    }
  }
  return claims;
}
