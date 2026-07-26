import type { LedgerRow, StrategyRosterEntry, StrategyStats } from "./types";

export interface SignalDetail {
  entryPrice: number | null;
  entryTimestamp: string | null;
  exitPrice: number | null;
  exitTimestamp: string | null;
  avgReturnPct: number | null;
  pnlPending: boolean;
}

function matchesConfig(
  row: LedgerRow,
  entry: Pick<StrategyRosterEntry, "name" | "version" | "asset">
): boolean {
  return row.strategy === entry.name && row.strategy_version === entry.version && row.asset === entry.asset;
}

// Matched by the EXACT (strategy, strategy_version, asset) triple -- not just
// (strategy, asset) the way the existing deriveCurrentStatus is -- since two
// different registered versions can share an asset (e.g. RANGE_MEAN_REVERSION
// long-only/confirmation, both BTC) and conflating them here would show one
// config's trade context on the other's card. Returns null whenever the most
// recent matching row isn't itself an ENTRY or EXIT (nothing to show), so the
// card can safely fall back to "no signal yet" rather than ever rendering an
// EXIT label with no backing detail.
export function deriveSignalDetail(
  entry: Pick<StrategyRosterEntry, "name" | "version" | "asset">,
  recentRows: LedgerRow[],
  stats: StrategyStats[]
): SignalDetail | null {
  const matching = recentRows.filter((row) => matchesConfig(row, entry));
  const mostRecent = matching[0];
  if (!mostRecent || (mostRecent.signal_type !== "ENTRY" && mostRecent.signal_type !== "EXIT")) {
    return null;
  }

  if (mostRecent.signal_type === "ENTRY") {
    return {
      entryPrice: mostRecent.entry_price,
      entryTimestamp: mostRecent.timestamp,
      exitPrice: null,
      exitTimestamp: null,
      avgReturnPct: null,
      pnlPending: false,
    };
  }

  // EXIT: best-effort find the entry it closed (the nearest earlier ENTRY row
  // for this same config, if still within the ledger_recent.json window) --
  // never fabricated if it has rolled off; the exit price/P&L below don't
  // depend on finding it.
  const precedingEntry = matching.slice(1).find((row) => row.signal_type === "ENTRY");
  const statsRow = stats.find(
    (s) => s.strategy === entry.name && s.strategy_version === entry.version && s.asset === entry.asset
  );

  return {
    entryPrice: precedingEntry?.entry_price ?? null,
    entryTimestamp: precedingEntry?.timestamp ?? null,
    exitPrice: mostRecent.exit_price,
    exitTimestamp: mostRecent.timestamp,
    avgReturnPct: statsRow?.avg_return_pct ?? null,
    pnlPending: !statsRow || statsRow.resolved_trades <= 0,
  };
}
