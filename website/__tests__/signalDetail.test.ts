import { deriveSignalDetail } from "@/lib/signalDetail";
import type { LedgerRow, StrategyStats } from "@/lib/types";

const ENTRY = { name: "BREAKOUT_MOMENTUM", version: "breakout-momentum-v1.2.0-gold-calibrated-1week", asset: "GOLD" };

function makeRow(overrides: Partial<LedgerRow> = {}): LedgerRow {
  return {
    timestamp: "2026-07-26T00:00:00Z",
    strategy: ENTRY.name,
    strategy_version: ENTRY.version,
    asset: ENTRY.asset,
    signal_type: "ENTRY",
    entry_price: 100,
    exit_price: null,
    reasoning: "",
    candle_timestamp: "2026-07-26T00:00:00Z",
    ...overrides,
  };
}

function makeStats(overrides: Partial<StrategyStats> = {}): StrategyStats {
  return {
    strategy: ENTRY.name,
    strategy_version: ENTRY.version,
    asset: ENTRY.asset,
    resolved_trades: 0,
    win_rate: null,
    expectancy_r: null,
    avg_return_pct: null,
    signal_counts: { ENTRY: 0, EXIT: 0, WATCH: 0, NO_TRADE: 0 },
    open_position: null,
    ...overrides,
  };
}

describe("deriveSignalDetail", () => {
  it("returns null when there is no matching ledger row", () => {
    expect(deriveSignalDetail(ENTRY, [], [])).toBeNull();
  });

  it("returns null when the most recent matching row is WATCH or NO_TRADE", () => {
    expect(deriveSignalDetail(ENTRY, [makeRow({ signal_type: "WATCH" })], [])).toBeNull();
    expect(deriveSignalDetail(ENTRY, [makeRow({ signal_type: "NO_TRADE" })], [])).toBeNull();
  });

  it("returns null when the only matching row is for a different strategy_version", () => {
    // The RANGE_MEAN_REVERSION long-only/confirmation precedent: same name,
    // same asset, different version -- must not conflate.
    const rows = [makeRow({ strategy_version: "breakout-momentum-v9.9.9-different" })];
    expect(deriveSignalDetail(ENTRY, rows, [])).toBeNull();
  });

  it("returns entry price and timestamp for an ENTRY row", () => {
    const rows = [makeRow({ signal_type: "ENTRY", entry_price: 105, timestamp: "2026-07-26T12:00:00Z" })];
    const detail = deriveSignalDetail(ENTRY, rows, []);
    expect(detail).toEqual({
      entryPrice: 105,
      entryTimestamp: "2026-07-26T12:00:00Z",
      exitPrice: null,
      exitTimestamp: null,
      avgReturnPct: null,
      pnlPending: false,
    });
  });

  it("returns exit price, the preceding entry, and P&L for an EXIT row when stats are resolved", () => {
    const rows = [
      makeRow({ signal_type: "EXIT", exit_price: 110, timestamp: "2026-07-27T00:00:00Z" }),
      makeRow({ signal_type: "ENTRY", entry_price: 100, timestamp: "2026-07-20T00:00:00Z" }),
    ];
    const stats = [makeStats({ resolved_trades: 3, avg_return_pct: 2.5 })];
    const detail = deriveSignalDetail(ENTRY, rows, stats);
    expect(detail).toEqual({
      entryPrice: 100,
      entryTimestamp: "2026-07-20T00:00:00Z",
      exitPrice: 110,
      exitTimestamp: "2026-07-27T00:00:00Z",
      avgReturnPct: 2.5,
      pnlPending: false,
    });
  });

  it("marks P&L pending when stats.json has zero resolved trades for this config", () => {
    const rows = [makeRow({ signal_type: "EXIT", exit_price: 110 })];
    const stats = [makeStats({ resolved_trades: 0 })];
    const detail = deriveSignalDetail(ENTRY, rows, stats);
    expect(detail?.pnlPending).toBe(true);
  });

  it("marks P&L pending when there is no stats row for this config at all", () => {
    const rows = [makeRow({ signal_type: "EXIT", exit_price: 110 })];
    const detail = deriveSignalDetail(ENTRY, rows, []);
    expect(detail?.pnlPending).toBe(true);
  });

  it("gracefully omits the entry price/timestamp when the preceding ENTRY has rolled off the recent window", () => {
    const rows = [makeRow({ signal_type: "EXIT", exit_price: 110 })]; // no preceding ENTRY present at all
    const stats = [makeStats({ resolved_trades: 1, avg_return_pct: 1.1 })];
    const detail = deriveSignalDetail(ENTRY, rows, stats);
    expect(detail?.entryPrice).toBeNull();
    expect(detail?.entryTimestamp).toBeNull();
    expect(detail?.exitPrice).toBe(110);
  });
});
