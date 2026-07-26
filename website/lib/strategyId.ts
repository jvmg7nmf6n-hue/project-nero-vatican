import type { StrategyRosterEntry } from "./types";

function slugifyPart(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

// Embeds (name, asset, version) -- the exact unique key this project uses
// everywhere else (verification_status.py, source_reports.py, stats.json's own
// grouping) -- so the slug can never collide between two different registered
// configs, including the RANGE_MEAN_REVERSION long-only/confirmation pair that
// share both a name AND an asset (BTC) but differ by version.
export function buildStrategyId(
  entry: Pick<StrategyRosterEntry, "name" | "asset" | "version">
): string {
  return [slugifyPart(entry.name), slugifyPart(entry.asset), slugifyPart(entry.version)].join("--");
}

export function findEntryByStrategyId(
  roster: StrategyRosterEntry[],
  id: string
): StrategyRosterEntry | undefined {
  return roster.find((entry) => buildStrategyId(entry) === id);
}
