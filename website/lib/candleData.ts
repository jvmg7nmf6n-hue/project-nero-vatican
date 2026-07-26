export interface Candle {
  time: number; // Unix seconds UTC -- matches lightweight-charts' expected format directly
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null; // null where the source doesn't provide real volume -- see
  // nero_core/execution/export_candle_data.py's own "VOLUME HONESTY" docstring section
}

export interface CandleFile {
  schema_version: number;
  asset: string;
  timeframe: string;
  last_updated: string;
  candles: Candle[];
}

// "EUR/USD" -> "EURUSD" -- the EXACT rule documented in Day 1's closing report
// (docs/candle_export_day1_closing_report.md) and implemented in
// nero_core/execution/export_candle_data.py::sanitize_asset_for_filename. Must stay
// byte-identical to that Python function, or this frontend will look up the wrong
// filename for every forex pair.
export function sanitizeAssetForFilename(asset: string): string {
  return asset.replace("/", "");
}

// NEWS_SENTIMENT's own roster metadata calls its timeframe "daily", but Day 1's
// export pipeline treats that as the same real candle series as "24h" and writes it
// under the "24h" filename (see export_candle_data.py's IN_SCOPE_PAIRS -- GOLD's
// "daily"-labeled entry is exported as GOLD_24h.json, not a separate GOLD_daily.json).
// Every other roster timeframe string already matches its candle file's own
// timeframe component exactly. "snapshot" (ORDERFLOW_IMBALANCE) has no alias --
// deliberately: no candle file will ever exist for it, since an order-book snapshot
// has no OHLCV concept, and the lookup should correctly keep missing forever, not
// silently redirect to some other config's data.
const TIMEFRAME_FILE_ALIASES: Record<string, string> = {
  daily: "24h",
};

export function candleFileTimeframe(rosterTimeframe: string): string {
  return TIMEFRAME_FILE_ALIASES[rosterTimeframe] ?? rosterTimeframe;
}

export function candleFilename(asset: string, rosterTimeframe: string): string {
  return `${sanitizeAssetForFilename(asset)}_${candleFileTimeframe(rosterTimeframe)}.json`;
}
