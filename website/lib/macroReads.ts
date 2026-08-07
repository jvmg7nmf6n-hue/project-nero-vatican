import type { DataProvenanceLabel, MacroConflictFlagRecord, MacroReadRecord } from "./types";

/** Most recent read for an asset, or null if none exist yet. */
export function latestReadForAsset(reads: MacroReadRecord[], asset: "GOLD" | "BITCOIN"): MacroReadRecord | null {
  const matching = reads.filter((r) => r.asset === asset);
  if (matching.length === 0) return null;
  return matching.reduce((latest, r) => (r.timestamp > latest.timestamp ? r : latest));
}

export interface ProvenanceCounts {
  real: number;
  mixed: number;
  synthetic: number;
  unavailable: number;
  total: number;
}

export function provenanceCounts(breakdown: Record<string, DataProvenanceLabel>): ProvenanceCounts {
  const counts: ProvenanceCounts = { real: 0, mixed: 0, synthetic: 0, unavailable: 0, total: 0 };
  for (const label of Object.values(breakdown)) {
    counts[label] += 1;
    counts.total += 1;
  }
  return counts;
}

// CC-1 Part E: which agent reads which REAL data source, when its own
// provenance is real/mixed -- reference-only context (this project's own
// established sourcing, per docs/bellwether_stage2_report.md /
// vatican/bellwether/README_VATICAN.md), not derived from the export
// itself (which only carries a provenance LABEL, not a per-agent source
// string). Agents absent from this map have no real Vatican source at all
// yet -- their provenance is honestly always "synthetic".
export const AGENT_REAL_DATA_SOURCE: Record<string, string> = {
  monetary_policy: "FRED DFII10 (10y real yield, t+2 lag) + yfinance DX-Y.NYB (DXY)",
  liquidity: "yfinance ^VIX",
  derivatives_etf: "Binance BTC perp funding rate (fapi/v1/fundingRate)",
};

export const AGENT_DISPLAY_NAMES: Record<string, string> = {
  news_intelligence: "News Intelligence",
  economic_calendar: "Economic Calendar",
  geopolitical: "Geopolitical",
  monetary_policy: "Monetary Policy",
  liquidity: "Liquidity",
  onchain: "On-chain",
  derivatives_etf: "Derivatives / ETF",
  correlation: "Correlation",
  historical_analog: "Historical Analog",
  learning: "Learning",
  gold_analysis: "Gold Analysis (composite)",
  bitcoin_analysis: "Bitcoin Analysis (composite)",
  scenario: "Scenario",
  risk: "Risk",
  trade_recommendation: "Trade Recommendation (composite)",
};

export function flagsForAsset(flags: MacroConflictFlagRecord[], asset: string): MacroConflictFlagRecord[] {
  return flags.filter((f) => f.asset === asset);
}

export function conflictedFlags(flags: MacroConflictFlagRecord[]): MacroConflictFlagRecord[] {
  return flags.filter((f) => f.conflicted);
}
