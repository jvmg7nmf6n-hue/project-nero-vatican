import type { AgentPerformanceExport, EveHypothesisRecord, EveSessionRecord, EveSessionRegistryExport } from "./types";

// CC-1 overnight directive, Part 1 -- Learning Curve. Every function here is
// pure and real-data-only: no interpolation, no synthetic point, no
// fabricated trend. See docs/investigations/factory_loop_implementation_report.md's
// dated section for this directive for the full real-numbers audit trail.

export interface ReliabilityPoint {
  label: string; // session_id or run_at, real
  crashed: boolean;
  source: "eve_session_file" | "eve_registry_predates_crash_safety" | "adam_run_status";
}

// Eve's crash-safety mechanism (writes a real eve_sessions/<id>.json on
// every session, crashed or not) was added AFTER her first 6 real crashes
// (2026-08-03/04) -- confirmed directly: none of those 6 session_ids have a
// committed session file at all (`git log` on each returns nothing), only
// the 4 sessions that ran to completion do. Sourcing "crashed or not" purely
// from eve_sessions/*.json (per this directive's own instruction) would
// therefore silently show "4 real sessions, 0 crashes" -- true of the files
// that exist, but a materially misleading picture of Eve's real reliability
// history. The honest fix: use the auto-written session file as the
// authoritative, auto-updating source for any session that has one (every
// session from this point forward), and fall back to the registry's own
// `classification` ONLY for the 6 real historical crashes that predate the
// mechanism entirely and can never retroactively gain a file -- a one-time,
// disclosed exception, not a silent gap.
export function computeEveReliability(
  registry: EveSessionRegistryExport | null,
  sessionRecords: Map<string, EveSessionRecord | null>
): ReliabilityPoint[] {
  const sessions = registry?.sessions ?? [];
  return sessions
    .map((s): ReliabilityPoint => {
      if (s.classification === "crashed_before_completion") {
        return { label: s.session_id, crashed: true, source: "eve_registry_predates_crash_safety" };
      }
      const record = sessionRecords.get(s.session_id);
      const crashed = record ? record.terminated_because !== "end_session_called" || record.partial === true : false;
      return { label: s.session_id, crashed, source: "eve_session_file" };
    })
    .sort((a, b) => a.label.localeCompare(b.label));
}

export function computeAdamReliability(adamPerformance: AgentPerformanceExport | null): ReliabilityPoint[] {
  const runs = adamPerformance?.runs ?? [];
  const corrections = new Map((adamPerformance?.corrections ?? []).map((c) => [c.applies_to_run_at, c.inferred_status]));
  return runs.map((r) => {
    const status = r.status ?? corrections.get(r.run_at) ?? null;
    return { label: r.run_at, crashed: status === "error", source: "adam_run_status" as const };
  });
}

export interface HypothesisQualityPoint {
  label: string; // session_id (Eve) or run_at (Adam)
  totalCount: number;
  untestableCount: number;
}

// Real per-session aggregation -- NOT a stored value, grouped live from
// eve_hypotheses.json's own testability field. Only 4 of Eve's 10 real
// sessions ever produced a hypothesis record at all (the other 6 crashed
// before proposing anything) -- those 6 correctly have no point here, not a
// fabricated zero.
export function computeEveHypothesisQuality(hypotheses: EveHypothesisRecord[]): HypothesisQualityPoint[] {
  const bySession = new Map<string, { total: number; untestable: number }>();
  for (const h of hypotheses) {
    const entry = bySession.get(h.session_id) ?? { total: 0, untestable: 0 };
    entry.total += 1;
    if (h.testability === "UNTESTABLE_BY_DSL") entry.untestable += 1;
    bySession.set(h.session_id, entry);
  }
  return Array.from(bySession.entries())
    .map(([label, v]) => ({ label, totalCount: v.total, untestableCount: v.untestable }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

export function computeAdamHypothesisQuality(adamPerformance: AgentPerformanceExport | null): HypothesisQualityPoint[] {
  const runs = adamPerformance?.runs ?? [];
  return runs
    .filter((r) => (r.hypotheses_generated ?? 0) > 0)
    .map((r) => ({ label: r.run_at, totalCount: r.hypotheses_generated ?? 0, untestableCount: r.untestable ?? 0 }));
}

export interface NearMissFunnel {
  nearMissCount: number;
  referencedInDerivedFromCount: number;
  reachedForwardTrialCount: number;
  survivedCount: number;
  nearMissNames: string[];
}

function isNearMiss(h: EveHypothesisRecord): boolean {
  if (h.fdr_survives_is === true && h.fdr_survives_oos !== true) return true;
  return (h.verdict_is === "PROMISING-WATCHLIST" || h.verdict_is === "SURVIVED") && h.verdict_oos === "INSUFFICIENT_SAMPLE";
}

// Plain 4-stage funnel, real counts only -- no percentage (a percentage
// implies a denominator large enough to be meaningful; this funnel is not).
// `forwardTrialHypothesisNames` is the real set of hypothesis_names admitted
// to Forward Trial (forward_trial.json), passed in by the caller so this
// function stays a pure aggregation over already-fetched data, no new fetch.
export function computeNearMissFunnel(
  hypotheses: EveHypothesisRecord[],
  forwardTrialHypothesisNames: Set<string>
): NearMissFunnel {
  const nearMisses = hypotheses.filter(isNearMiss);
  const nearMissNames = nearMisses.map((h) => h.raw_hypothesis?.hypothesis_name).filter((n): n is string => Boolean(n));

  const referenced = hypotheses.filter((h) => {
    const parentName = h.raw_hypothesis?.derived_from?.parent_hypothesis_name;
    return Boolean(parentName && nearMissNames.includes(parentName));
  });
  const referencedNames = referenced.map((h) => h.raw_hypothesis?.hypothesis_name).filter((n): n is string => Boolean(n));

  const reachedForwardTrial = referencedNames.filter((n) => forwardTrialHypothesisNames.has(n));
  // "Survived" here means the refinement itself reached a real SURVIVED
  // verdict -- checked against the same referenced set, never the near-miss
  // itself (which by definition did NOT survive OOS).
  const survived = referenced.filter((h) => h.verdict_combined === "SURVIVED");

  return {
    nearMissCount: nearMisses.length,
    referencedInDerivedFromCount: referenced.length,
    reachedForwardTrialCount: reachedForwardTrial.length,
    survivedCount: survived.length,
    nearMissNames,
  };
}
