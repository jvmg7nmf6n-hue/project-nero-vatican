import { candleFilename } from "./candleData";
import type { CandleFile } from "./candleData";
import type {
  AgentHypothesis,
  AgentPerformanceExport,
  AgentRunSummary,
  AgentTestResult,
  EveBudgetLedgerEntry,
  EveSessionRecord,
  EveHypothesisRecord,
  EveSessionRegistryExport,
  FactoryLoopStatusExport,
  FailurePatternEntry,
  ForwardTrialRecord,
  GraveyardEntry,
  HeartbeatStatus,
  LedgerExport,
  QuantCrossAssetExport,
  QuantMetricsExport,
  RepairCandidate,
  SiteSummary,
  MacroReadsExport,
  NewsSentimentExport,
  StatsExport,
  StrategiesExport,
  StrategyDescriptions,
  SurvivorDistanceExport,
  FactoryLoopScoreboard,
  TrialEntriesExport,
} from "./types";

export const GITHUB_RAW_BASE =
  "https://raw.githubusercontent.com/jvmg7nmf6n-hue/project-nero-vatican/main/docs/site_data";

export const REVALIDATE_SECONDS = 300;

// Never throws: returns null on network failure, a non-ok response, or a
// JSON body that fails to parse, so pages can render an honest fallback
// instead of crashing when the live data isn't reachable.
export async function fetchJson<T>(filename: string): Promise<T | null> {
  try {
    const response = await fetch(`${GITHUB_RAW_BASE}/${filename}`, {
      next: { revalidate: REVALIDATE_SECONDS },
    });

    if (!response.ok) {
      return null;
    }

    return (await response.json()) as T;
  } catch {
    return null;
  }
}

export function fetchLedgerRecent(): Promise<LedgerExport | null> {
  return fetchJson<LedgerExport>("ledger_recent.json");
}

export function fetchLedgerFull(): Promise<LedgerExport | null> {
  return fetchJson<LedgerExport>("ledger_full.json");
}

export function fetchStrategies(): Promise<StrategiesExport | null> {
  return fetchJson<StrategiesExport>("strategies.json");
}

export function fetchStats(): Promise<StatsExport | null> {
  return fetchJson<StatsExport>("stats.json");
}

export function fetchSiteSummary(): Promise<SiteSummary | null> {
  return fetchJson<SiteSummary>("site_summary.json");
}

export function fetchGraveyard(): Promise<GraveyardEntry[] | null> {
  return fetchJson<GraveyardEntry[]>("graveyard.json");
}

// Day 6/7 Strategy Doctor -- manually-curated, same convention as fetchGraveyard.
export function fetchFailurePatterns(): Promise<FailurePatternEntry[] | null> {
  return fetchJson<FailurePatternEntry[]>("failure_patterns.json");
}

// Day 6/7 Repair Workbench -- manually-curated, same convention as fetchGraveyard.
export function fetchRepairCandidates(): Promise<RepairCandidate[] | null> {
  return fetchJson<RepairCandidate[]>("repair_candidates.json");
}

// null is expected (not an error) until the scheduler's first successful run
// after this file was introduced, or on any fetch failure -- callers must treat
// null as "no status to show," never as "down."
export function fetchHeartbeat(): Promise<HeartbeatStatus | null> {
  return fetchJson<HeartbeatStatus>("heartbeat.json");
}

// Manually-curated (see docs/site_data/README.md) -- a missing entry for a given
// strategy_id is expected for any family not yet written up, never treated as an
// error; callers fall back to a generic "no description yet" message.
export function fetchStrategyDescriptions(): Promise<StrategyDescriptions | null> {
  return fetchJson<StrategyDescriptions>("strategy_descriptions.json");
}

// Day 4/7 Quant Intelligence Panel data -- null (not an error) until the
// scheduler's export_quant_metrics step has run at least once, same convention
// as fetchHeartbeat.
export function fetchQuantMetrics(): Promise<QuantMetricsExport | null> {
  return fetchJson<QuantMetricsExport>("quant_metrics.json");
}

// Day 5/7 Quant Intelligence Panel, Part 2 (cross-asset). Same "null until the
// scheduler's export step has run" convention as fetchQuantMetrics.
export function fetchQuantCrossAsset(): Promise<QuantCrossAssetExport | null> {
  return fetchJson<QuantCrossAssetExport>("quant_cross_asset.json");
}

// Research Agent (feature/research-agent) -- append-only hypothesis log
// written by nero_core.research_agent.hypothesis_gen. null (not an error)
// until the pipeline has generated at least one hypothesis.
export function fetchAgentHypotheses(): Promise<AgentHypothesis[] | null> {
  return fetchJson<AgentHypothesis[]>("agent_hypotheses.json");
}

// One entry per hypothesis tested or gate-rejected, written by
// nero_core.research_agent.auto_tester. Same null convention as above.
export function fetchAgentTestResults(): Promise<AgentTestResult[] | null> {
  return fetchJson<AgentTestResult[]>("agent_test_results.json");
}

// Cumulative + per-run Research Agent metrics, written by
// nero_core.research_agent.performance after every enabled pipeline run.
export function fetchAgentPerformance(): Promise<AgentPerformanceExport | null> {
  return fetchJson<AgentPerformanceExport>("agent_performance.json");
}

// CC-1 Factory Loop closeout, item 4a: committed on every research_agent_manual.yml
// run (unlike agent_hypotheses.json above) -- see AgentRunSummary's own
// docstring in lib/types.ts. null (not an error) until the workflow has run
// at least once, same convention as the fetchers above.
export function fetchAgentRunSummaries(): Promise<AgentRunSummary[] | null> {
  return fetchJson<AgentRunSummary[]>("agent_run_summaries.json");
}

// CC-1 Factory Loop directive, item 9 -- written by
// tools/factory_loop_status_summary.py. null (not an error) until that
// script has run at least once, same convention as fetchHeartbeat/
// fetchAgentPerformance -- callers must render an honest "not yet running"
// fallback, never treat null as "down."
export function fetchFactoryLoopStatus(): Promise<FactoryLoopStatusExport | null> {
  return fetchJson<FactoryLoopStatusExport>("factory_loop_status.json");
}

// CC-1 directive, item 1c/5f: the per-record file (see ForwardTrialRecord's
// own docstring in lib/types.ts) -- null (not an error) until at least one
// hypothesis has been admitted, same convention as every fetcher above.
export function fetchForwardTrial(): Promise<ForwardTrialRecord[] | null> {
  return fetchJson<ForwardTrialRecord[]>("forward_trial.json");
}

// CC-1 Part D6: genuine Forward Trial ENTRY events (nero_core.execution.
// export_trial_entries.py) -- distinct from fetchForwardTrial above, which
// reflects Trial ADMISSION status, not a live market position. Null until
// the export has run at least once.
export function fetchTrialEntries(): Promise<TrialEntriesExport | null> {
  return fetchJson<TrialEntriesExport>("trial_entries.json");
}

// CC-1 overnight directive, Part 4: every real news_sentiment_log row, all
// time (nero_core.execution.export_news_sentiment.py) -- scoped previously,
// never built until this directive; real signals since 2026-07-18 that no
// visitor could see.
export function fetchNewsSentiment(): Promise<NewsSentimentExport | null> {
  return fetchJson<NewsSentimentExport>("news_sentiment.json");
}

// CC-1 Part E: Bellwether's own macro reads + conflict-flag audit trail.
export function fetchMacroReads(): Promise<MacroReadsExport | null> {
  return fetchJson<MacroReadsExport>("macro_reads.json");
}

// CC-1 Master Directive, Phase 2.1: Eve's own three fetchable files -- see
// EveHypothesisRecord/EveSessionRegistryExport/EveBudgetLedgerEntry's own
// docstring in lib/types.ts for the plumbing finding (all three already
// live under docs/site_data/, no export step needed).
export function fetchEveHypotheses(): Promise<EveHypothesisRecord[] | null> {
  return fetchJson<EveHypothesisRecord[]>("eve_hypotheses.json");
}

export function fetchEveSessionRegistry(): Promise<EveSessionRegistryExport | null> {
  return fetchJson<EveSessionRegistryExport>("eve_session_registry.json");
}

// CC-1 overnight directive, Part 1.1 (Learning Curve, Reliability chart):
// the real, auto-written per-session record (one file per real session,
// under docs/site_data/eve_sessions/<id>.json) -- NOT eve_session_registry.json,
// whose `classification` field is manually curated and carries a real
// stale-risk for a future session run from the Operator Panel. Fetched by
// session_id (known from the registry's own session list), one request per
// session -- there are only a handful of these, ever.
export function fetchEveSessionRecord(sessionId: string): Promise<EveSessionRecord | null> {
  return fetchJson<EveSessionRecord>(`eve_sessions/${sessionId}.json`);
}

export function fetchEveBudgetLedger(): Promise<EveBudgetLedgerEntry[] | null> {
  return fetchJson<EveBudgetLedgerEntry[]>("eve_budget_ledger.json");
}

export function fetchSurvivorDistance(): Promise<SurvivorDistanceExport | null> {
  return fetchJson<SurvivorDistanceExport>("survivor_distance.json");
}

export function fetchFactoryLoopScoreboard(): Promise<FactoryLoopScoreboard | null> {
  return fetchJson<FactoryLoopScoreboard>("factory_loop_scoreboard.json");
}

export type CandleFetchResult =
  | { status: "ok"; data: CandleFile }
  | { status: "not_found" }
  | { status: "error" };

// Deliberately does NOT reuse fetchJson: every other JSON file on this site treats
// "missing" and "fetch failed" identically (both -> null), but Day 2's strategy page
// needs to tell them apart -- "Price chart coming soon" (this asset/timeframe was
// never in Day 1's export scope, e.g. ORDERFLOW_IMBALANCE's "snapshot" timeframe) vs
// "Price data temporarily unavailable" (the file exists but this fetch failed) are
// two different, honest messages, not the same fallback.
export async function fetchCandleData(asset: string, rosterTimeframe: string): Promise<CandleFetchResult> {
  const filename = candleFilename(asset, rosterTimeframe);
  try {
    const response = await fetch(`${GITHUB_RAW_BASE}/candles/${filename}`, {
      next: { revalidate: REVALIDATE_SECONDS },
    });

    if (response.status === 404) {
      return { status: "not_found" };
    }
    if (!response.ok) {
      return { status: "error" };
    }

    const data = (await response.json()) as CandleFile;
    return { status: "ok", data };
  } catch {
    return { status: "error" };
  }
}
