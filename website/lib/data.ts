import type {
  GraveyardEntry,
  LedgerExport,
  SiteSummary,
  StatsExport,
  StrategiesExport,
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
