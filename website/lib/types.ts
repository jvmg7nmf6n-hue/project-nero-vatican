// Mirrors the shapes nero_core/execution/export_site_data.py writes to
// docs/site_data/*.json, and the two manually-curated files
// (docs/site_data/site_summary.json, docs/site_data/graveyard.json).

export type SignalType = "ENTRY" | "EXIT" | "WATCH" | "NO_TRADE";

export interface LedgerRow {
  timestamp: string;
  strategy: string;
  strategy_version: string;
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
  source_report: string | null;
}

// Manually-curated docs/site_data/strategy_descriptions.json -- keyed by strategy_id
// (the family name, e.g. "PEAD"), one entry per family, not per individual
// config/version/asset. verification_note is written honestly per family -- a
// weak or thin edge-over-random result says so, never spun to sound stronger.
export interface StrategyDescription {
  mechanism: string;
  verification_note: string;
}

export type StrategyDescriptions = Record<string, StrategyDescription>;

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
  strategy_families_verified: number;
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

// Day 6/7 Strategy Doctor -- manually-curated, same convention as graveyard.json
// (see docs/site_data/README.md): one entry per killed FAMILY (not per individual
// graveyard row), synthesized from reading every family's source_doc(s), never
// auto-scraped.
export type FailurePattern =
  | "regime-filter-only"
  | "grid-shift-artifact"
  | "edge-over-random-negative"
  | "sample-too-thin"
  | "data-blocked"
  | "mechanism-doesn't-transfer";

export interface FailurePatternEntry {
  name: string;
  family: string;
  failure_pattern: FailurePattern;
  fixable: boolean;
  // Present only when fixable is true -- the mechanism-justified improvement
  // that addresses the diagnosed weakness, never a vague "try again" note.
  fix_rationale?: string;
  source_doc: string;
}

// Day 6/7 Repair Workbench -- up to 3 mechanism-justified hypotheses registered
// as candidates (not yet backtested; that is a separate future batch, per the
// task's own instruction).
export type RepairCandidateStatus = "candidate" | "testing" | "watchlist" | "promoted";

export interface RepairCandidate {
  parent_strategy: string;
  failure_pattern: FailurePattern;
  diagnosis: string;
  proposed_fix: string;
  hypothesis_name: string;
  status: RepairCandidateStatus;
}

// Day 7 ChatBot -- one static FAQ entry (Part A). Answers are pre-computed
// server-side from strategy_descriptions.json + stats.json, never fetched live.
export interface FaqEntry {
  question: string;
  answer: string;
}

// Day 7 ChatBot -- a single turn in the live-chat exchange (Part B). Sent to
// and returned from website/app/api/chat/route.ts; kept to the last 6 entries
// (3 exchanges) per the task's own conversation-history rule.
export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

// Day 7 ChatBot -- resolved server-side (Server Component) from the same data
// every other panel on the strategy page already reads, then handed to the
// client ChatBot widget and forwarded to /api/chat so the system prompt can be
// built per-strategy. Never includes anything not already public on the page.
export interface StrategyChatContext {
  strategy_name: string;
  asset: string;
  timeframe: string;
  mechanism: string;
  verification_note: string;
  win_rate: number | null;
  current_signal: string;
}

// Written by nero_core/execution/heartbeat.py after every successful live
// scheduler run -- absence of this file (a fresh deploy, or the scheduler having
// never run) is a valid, non-error state, not something to fabricate a value for.
export interface HeartbeatStatus {
  last_successful_run: string;
  run_count_24h: number;
}

// Day 4/7 Quant Intelligence Panel, Part 1 -- one entry per candle FILE (i.e. per
// (asset, timeframe) pair, not per asset: GOLD and SILVER each have two files at
// two different timeframes with genuinely different metrics). Every metric is
// nullable independently -- insufficient history or an unrecognized timeframe
// nulls out just that field, never the whole entry, and never a fabricated
// number. There is deliberately no composite/overall score field here.
export interface QuantMetricsEntry {
  asset: string;
  timeframe: string;
  periods_per_year: number | null;
  window_used: number;
  rf_annual: number;
  rf_source: string;
  log_return_annualized: number | null;
  zscore_current: number | null;
  realized_vol_annualized: number | null;
  sharpe: number | null;
  sortino: number | null;
  computed_at: string;
}

export interface QuantMetricsExport {
  schema_version: number;
  last_updated: string;
  metrics: QuantMetricsEntry[];
}

// Day 5/7 Quant Intelligence Panel, Part 2 -- cross-asset relationships. No
// composite/overall score anywhere in this shape; each array is an independent
// descriptive statistic, per this panel's own research/education framing.
export interface CorrelationPair {
  asset_a: string;
  asset_b: string;
  timeframe: string;
  correlation: number | null;
  window_used: number;
  computed_at: string;
}

export interface VolatilityRegimeEntry {
  asset: string;
  timeframe: string;
  regime: "LOW" | "NORMAL" | "HIGH" | "EXTREME" | "NO_DATA";
  conditional_vol: number;
  vol_ratio: number;
  shock_score: number;
  model_used: string;
  computed_at: string;
}

export interface CointegrationEntry {
  asset_a: string;
  asset_b: string;
  timeframe_a: string;
  timeframe_b: string;
  pvalue: number | null;
  cointegrated: boolean | null;
  window_used: number;
  note: string;
  computed_at: string;
}

export interface LeadLagEntry {
  asset: string;
  benchmark: string;
  timeframe: string;
  best_lag: number | null;
  correlation: number | null;
  window_used: number;
  note: string;
  computed_at: string;
}

export interface QuantCrossAssetExport {
  schema_version: number;
  last_updated: string;
  correlation_matrix: CorrelationPair[];
  volatility_regimes: VolatilityRegimeEntry[];
  cointegration: CointegrationEntry[];
  lead_lag: LeadLagEntry[];
}
