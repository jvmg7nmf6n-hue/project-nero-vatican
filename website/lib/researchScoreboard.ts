import { classifyTier } from "./tier";
import type { FailurePatternEntry, GraveyardEntry, StrategyRosterEntry, StrategyStats } from "./types";

export type ScoreboardStatus = "verified" | "watchlist" | "died" | "blocked";

export const SCOREBOARD_STATUS_ORDER: ScoreboardStatus[] = ["verified", "watchlist", "died", "blocked"];

export interface ScoreboardRow {
  name: string;
  family: string;
  asset: string | null;
  timeframe: string | null;
  status: ScoreboardStatus;
  winRate: number | null;
  sourceDoc: string | null;
}

// A killed family whose failure_patterns.json entry is tagged "data-blocked"
// renders as "blocked" rather than "died" -- a real distinction (no data source
// exists to even attempt a backtest, vs. a backtest ran and failed), joined on
// the shared "family" field since graveyard.json has multiple rows per family
// (e.g. 5 MACRO_RISK_ON rows) while failure_patterns.json has one.
function killedStatus(family: string, failurePatterns: FailurePatternEntry[]): "died" | "blocked" {
  const pattern = failurePatterns.find((entry) => entry.family === family);
  return pattern?.failure_pattern === "data-blocked" ? "blocked" : "died";
}

// classifyTier's three-tier grouping (verified/watchlist/experimental) collapses
// to this table's four fixed statuses by folding "experimental" into
// "watchlist" -- both mean "not yet verified, not dead," the same honest
// grouping classifyTier already applies to raw verification_status strings.
function liveStatus(verificationStatus: string): "verified" | "watchlist" {
  const tier = classifyTier(verificationStatus);
  return tier === "verified" ? "verified" : "watchlist";
}

export function buildResearchScoreboard(
  roster: StrategyRosterEntry[],
  stats: StrategyStats[],
  graveyard: GraveyardEntry[],
  failurePatterns: FailurePatternEntry[]
): ScoreboardRow[] {
  const liveRows: ScoreboardRow[] = roster.map((entry) => {
    const statRow = stats.find(
      (s) => s.strategy === entry.name && s.strategy_version === entry.version && s.asset === entry.asset
    );
    return {
      name: entry.name,
      // The live roster has no separate "family" concept distinct from name
      // (unlike graveyard.json's sometimes-grouped entries) -- using name here
      // is the honest value, not a stand-in for a field that doesn't exist.
      family: entry.name,
      asset: entry.asset,
      timeframe: entry.timeframe,
      status: liveStatus(entry.verification_status),
      winRate: statRow?.win_rate ?? null,
      sourceDoc: entry.source_report,
    };
  });

  const killedRows: ScoreboardRow[] = graveyard.map((entry) => ({
    name: entry.name,
    family: entry.family,
    // graveyard.json describes asset/timeframe scope in free-text prose
    // (e.g. "7 crypto assets x {2h, 4h, 12h}"), not a structured field --
    // null here is honest; a regex-guessed single value would not be.
    asset: null,
    timeframe: null,
    status: killedStatus(entry.family, failurePatterns),
    winRate: null,
    sourceDoc: entry.source_doc,
  }));

  return [...liveRows, ...killedRows];
}

export function filterScoreboardByStatus(
  rows: ScoreboardRow[],
  status: ScoreboardStatus | "All"
): ScoreboardRow[] {
  return status === "All" ? rows : rows.filter((row) => row.status === status);
}

// Rows with no win_rate (every killed row, and any live row with 0 resolved
// trades) always sort to the end regardless of direction -- "no data" is
// neither the best nor the worst result, so it must never rank first.
export function sortScoreboardByWinRate(
  rows: ScoreboardRow[],
  direction: "asc" | "desc"
): ScoreboardRow[] {
  const withRate = rows.filter((row): row is ScoreboardRow & { winRate: number } => row.winRate !== null);
  const withoutRate = rows.filter((row) => row.winRate === null);
  withRate.sort((a, b) => (direction === "desc" ? b.winRate - a.winRate : a.winRate - b.winRate));
  return [...withRate, ...withoutRate];
}
