import type { LedgerRow } from "./types";

// CC-1 directive, "every strategy page must show entry/exit rules and trade
// frequency": real, measured live-trading frequency for a live-scheduler
// strategy, computed from ledger_full.json's own real rows -- already
// fetched on /strategy/[id] for other panels, no new data source. Never
// fabricates a rate: 0 or 1 real ENTRY rows report a count, not a computed
// rate (a rate needs a real time span between two or more points).
export interface TradeFrequencyResult {
  entryCount: number;
  sinceIso: string | null; // earliest real ledger row for this exact (strategy, version, asset) -- "monitoring since," not necessarily a trade.
  ratePerYear: number | null; // null unless 2+ real ENTRY rows exist.
  spanDays: number | null;
}

export function computeTradeFrequency(
  rows: LedgerRow[],
  strategy: string,
  strategyVersion: string,
  asset: string
): TradeFrequencyResult {
  const scoped = rows.filter(
    (r) => r.strategy === strategy && r.strategy_version === strategyVersion && r.asset === asset
  );
  const sinceIso = scoped.length > 0 ? scoped.map((r) => r.timestamp).sort()[0] : null;

  const entries = scoped.filter((r) => r.signal_type === "ENTRY");
  if (entries.length < 2) {
    return { entryCount: entries.length, sinceIso, ratePerYear: null, spanDays: null };
  }

  const timestamps = entries.map((r) => new Date(r.timestamp).getTime()).sort((a, b) => a - b);
  const spanDays = (timestamps[timestamps.length - 1] - timestamps[0]) / (1000 * 60 * 60 * 24);
  if (spanDays <= 0) {
    return { entryCount: entries.length, sinceIso, ratePerYear: null, spanDays: null };
  }

  return {
    entryCount: entries.length,
    sinceIso,
    ratePerYear: (entries.length / spanDays) * 365.25,
    spanDays,
  };
}
