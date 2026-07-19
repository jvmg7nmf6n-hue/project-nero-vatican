// Mirrors the shapes nero_core/execution/export_site_data.py writes to
// docs/site_data/*.json, and the two manually-curated files
// (docs/site_data/site_summary.json, docs/site_data/graveyard.json).

export type SignalType = "ENTRY" | "EXIT" | "WATCH" | "NO_TRADE";

export interface LedgerRow {
  timestamp: string;
  strategy: string;
  asset: string;
  signal_type: SignalType;
  entry_price: number | null;
  exit_price: number | null;
  reasoning: string;
  candle_timestamp: string;
}

export interface LedgerExport {
  schema_version: number;
  last_updated: string;
  rows: LedgerRow[];
}

export interface StrategyRosterEntry {
  name: string;
  version: string;
  asset: string;
  timeframe: string;
  verification_status: string;
}

export interface StrategiesExport {
  schema_version: number;
  last_updated: string;
  strategies: StrategyRosterEntry[];
}

export interface OpenPosition {
  entry_price: number | null;
  entry_timestamp: string;
  candle_timestamp: string;
}

export interface StrategyStats {
  strategy: string;
  strategy_version: string;
  asset: string;
  resolved_trades: number;
  win_rate: number | null;
  expectancy_r: number | null;
  avg_return_pct: number | null;
  signal_counts: Record<string, number>;
  open_position: OpenPosition | null;
}

export interface StatsExport {
  schema_version: number;
  last_updated: string;
  strategies: StrategyStats[];
}

export interface SiteSummary {
  configs_tested: number;
  strategies_survived: number;
  tracking_since: string;
  last_curated: string;
}

export interface GraveyardEntry {
  name: string;
  family: string;
  what_was_tested: string;
  why_it_died: string;
  source_doc: string;
}
