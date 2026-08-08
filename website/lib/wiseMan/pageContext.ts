// Wise Man's server-side page-context resolver (CC-1 directive v3, Sec 5).
//
// The client sends only a page-type IDENTIFIER + route params (e.g.
// {page: "strategy", id: "RC-CHANNEL..."}) -- never free-text "facts". The
// server resolves that identifier to real data itself, via the SAME
// lib/data.ts fetchers every page already uses to render, and formats a
// short, deterministic (no model call) text summary. Client-supplied
// context is never pasted into the prompt verbatim -- that would let
// anyone inject arbitrary "facts" into Wise Man's mouth, which is exactly
// what this design avoids (Sec 5's own explicit requirement).
//
// PUBLISHED-DATA-ONLY BOUNDARY (Sec 11.4): every function below calls only
// the existing lib/data.ts fetchers, which read committed docs/site_data/
// JSON. Per GATE A finding 1.6, the one file in this repo with a
// draft/published split (graveyard_distillation_drafts.json's
// review_status field) is not fetched by ANY existing page.tsx and is
// therefore not reachable from this module either -- if a future export
// ever adds review_status-bearing data to a fetcher this module calls,
// filtering on review_status becomes this module's responsibility too.
//
// CAP: PAGE_CONTEXT_MAX_CHARS. Overlong summaries are truncated at the last
// complete line under the cap (never mid-JSON, never mid-sentence),
// deterministically, with a trailing marker -- see truncateAtLineBoundary.

import {
  fetchSiteSummary,
  fetchStrategies,
  fetchStats,
  fetchGraveyard,
  fetchStrategyDescriptions,
  fetchFactoryLoopStatus,
  fetchAgentPerformance,
  fetchMacroReads,
  fetchQuantCrossAsset,
  fetchTrialEntries,
  fetchLedgerFull,
} from "../data";

export const PAGE_CONTEXT_MAX_CHARS = 4000;

export type PageContextIdentifier =
  | { page: "home" }
  | { page: "strategy"; id: string }
  | { page: "agents" }
  | { page: "factory-loop" }
  | { page: "graveyard" }
  | { page: "heatmap" }
  | { page: "lab" }
  | { page: "ledger" }
  | { page: "macro" }
  | { page: "methodology" }
  | { page: "pricing" }
  | { page: "quant" }
  | { page: "signals" };

export function truncateAtLineBoundary(text: string, maxChars: number): string {
  if (text.length <= maxChars) return text;
  const slice = text.slice(0, maxChars);
  const lastNewline = slice.lastIndexOf("\n");
  const cut = lastNewline > 0 ? slice.slice(0, lastNewline) : slice;
  return `${cut}\n[...page context truncated at ${maxChars} characters...]`;
}

async function resolveHome(): Promise<string> {
  const [summary, strategies] = await Promise.all([fetchSiteSummary(), fetchStrategies()]);
  const lines = ["Home page context:"];
  if (summary) {
    lines.push(
      `- ${summary.configs_tested} configs tested, ${summary.strategies_survived} survived, ${summary.strategy_families_verified} strategy families verified.`,
      `- Tracking since ${summary.tracking_since}, last curated ${summary.last_curated}.`,
    );
  }
  if (strategies) {
    lines.push(`- ${strategies.strategies.length} strategies on the roster.`);
  }
  return lines.join("\n");
}

async function resolveStrategy(id: string): Promise<string> {
  const [strategies, stats, descriptions] = await Promise.all([
    fetchStrategies(),
    fetchStats(),
    fetchStrategyDescriptions(),
  ]);
  const roster = strategies?.strategies.find((s) => s.name === id);
  const statRow = stats?.strategies.find((s) => s.strategy === id);
  const description = descriptions?.[id];
  const lines = [`Strategy detail page context for ${id}:`];
  if (roster) {
    lines.push(`- Version ${roster.version}, asset ${roster.asset}, timeframe ${roster.timeframe}, verification_status=${roster.verification_status}.`);
  }
  if (statRow) {
    lines.push(
      `- ${statRow.resolved_trades} resolved trades, win_rate=${statRow.win_rate ?? "n/a"}, expectancy_r=${statRow.expectancy_r ?? "n/a"}.`,
    );
  }
  if (description?.mechanism) {
    lines.push(`- Published mechanism: ${description.mechanism}`);
  }
  if (lines.length === 1) lines.push("- No data found for this strategy id.");
  return lines.join("\n");
}

async function resolveAgents(): Promise<string> {
  const [performance, factoryLoop] = await Promise.all([fetchAgentPerformance(), fetchFactoryLoopStatus()]);
  const lines = ["Agents page context:"];
  if (performance) {
    lines.push(
      `- ${performance.runs.length} recorded runs, cumulative performance data present, last_updated=${performance.last_updated ?? "n/a"}.`,
    );
  }
  if (factoryLoop) {
    lines.push(`- Factory Loop last_updated=${factoryLoop.last_updated}.`);
  }
  return lines.join("\n");
}

async function resolveFactoryLoop(): Promise<string> {
  const status = await fetchFactoryLoopStatus();
  return status
    ? `Factory Loop page context:\n- last_updated=${status.last_updated}. Forward trial, graveyard, and repair status sections are all present.`
    : "Factory Loop page context: no status data available.";
}

async function resolveGraveyard(): Promise<string> {
  const graveyard = await fetchGraveyard();
  if (!graveyard) return "Graveyard page context: no data available.";
  const families = new Set(graveyard.map((g) => g.family));
  const lines = [
    `Graveyard page context:`,
    `- ${graveyard.length} killed hypotheses across ${families.size} families.`,
    ...graveyard.slice(0, 15).map((g) => `- ${g.name} (${g.family}): ${g.why_it_died}`),
  ];
  return lines.join("\n");
}

async function resolveHeatmap(): Promise<string> {
  const [strategies, stats] = await Promise.all([fetchStrategies(), fetchStats()]);
  return `Heatmap page context:\n- ${strategies?.strategies.length ?? 0} strategies, ${stats?.strategies.length ?? 0} with stats.`;
}

async function resolveLab(): Promise<string> {
  const graveyard = await fetchGraveyard();
  return `Lab page context:\n- Research lab tracking ${graveyard?.length ?? 0} graveyard entries alongside active experiments.`;
}

async function resolveLedger(): Promise<string> {
  const [ledger, summary] = await Promise.all([fetchLedgerFull(), fetchSiteSummary()]);
  const lines = ["Ledger page context:"];
  if (ledger) lines.push(`- ${ledger.rows.length} rows in the full published ledger.`);
  if (summary) lines.push(`- ${summary.configs_tested} configs tested overall.`);
  return lines.join("\n");
}

async function resolveMacro(): Promise<string> {
  const macro = await fetchMacroReads();
  return macro ? `Macro page context:\n- Macro reads data present.` : "Macro page context: no data available.";
}

async function resolveQuant(): Promise<string> {
  const crossAsset = await fetchQuantCrossAsset();
  return crossAsset ? `Quant page context:\n- Cross-asset quant data present.` : "Quant page context: no data available.";
}

async function resolveSignals(): Promise<string> {
  const trials = await fetchTrialEntries();
  return trials
    ? `Signals page context:\n- ${trials.entries.length} trial entries.`
    : "Signals page context: no data available.";
}

/**
 * Server-side resolution: identifier in, deterministic text summary out.
 * NO model call happens in this function (Sec 5's explicit requirement).
 */
export async function resolvePageContext(identifier: PageContextIdentifier): Promise<string> {
  let text: string;
  switch (identifier.page) {
    case "home":
      text = await resolveHome();
      break;
    case "strategy":
      text = await resolveStrategy(identifier.id);
      break;
    case "agents":
      text = await resolveAgents();
      break;
    case "factory-loop":
      text = await resolveFactoryLoop();
      break;
    case "graveyard":
      text = await resolveGraveyard();
      break;
    case "heatmap":
      text = await resolveHeatmap();
      break;
    case "lab":
      text = await resolveLab();
      break;
    case "ledger":
      text = await resolveLedger();
      break;
    case "macro":
      text = await resolveMacro();
      break;
    case "quant":
      text = await resolveQuant();
      break;
    case "signals":
      text = await resolveSignals();
      break;
    case "methodology":
    case "pricing":
      // Static prose pages, no data export exists or is needed (GATE A finding 1.6).
      text = `${identifier.page} page context: static content, no live data to summarize.`;
      break;
    default: {
      const exhaustive: never = identifier;
      throw new Error(`unhandled page identifier: ${JSON.stringify(exhaustive)}`);
    }
  }
  return truncateAtLineBoundary(text, PAGE_CONTEXT_MAX_CHARS);
}
