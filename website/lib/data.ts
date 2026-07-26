import { candleFilename } from "./candleData";
import type { CandleFile } from "./candleData";
import type {
  GraveyardEntry,
  HeartbeatStatus,
  LedgerExport,
  QuantMetricsExport,
  SiteSummary,
  StatsExport,
  StrategiesExport,
  StrategyDescriptions,
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
