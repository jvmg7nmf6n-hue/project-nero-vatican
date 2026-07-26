import type { LedgerRow, StrategyRosterEntry } from "./types";

export type TradeResult = "win" | "loss" | "flat";

export interface ResolvedTrade {
  entryTimestamp: string;
  entryPrice: number | null;
  exitTimestamp: string;
  exitPrice: number | null;
  result: TradeResult;
  rMultiple: number | null;
}

const R_MULTIPLE_PATTERN = /r_multiple=([-+]?\d*\.?\d+)/;

// Mirrors nero_core.execution.notify_ntfy._extract_r_multiple's convention: not
// every strategy's EXIT reasoning carries a parseable r_multiple (e.g.
// COINTEGRATION_PAIRS never does -- see that module's own docstring), so null
// here means "not available," never a guessed 0.
function extractRMultiple(reasoning: string): number | null {
  const match = reasoning.match(R_MULTIPLE_PATTERN);
  return match ? parseFloat(match[1]) : null;
}

function resultFor(entryPrice: number | null, exitPrice: number | null, rMultiple: number | null): TradeResult {
  if (rMultiple !== null) {
    if (rMultiple > 0) return "win";
    if (rMultiple < 0) return "loss";
    return "flat";
  }
  if (entryPrice !== null && exitPrice !== null) {
    if (exitPrice > entryPrice) return "win";
    if (exitPrice < entryPrice) return "loss";
  }
  return "flat";
}

// Mirrors nero_core.execution.export_site_data._pair_round_trips: within one
// (strategy, strategy_version, asset) group sorted chronologically, each ENTRY
// pairs with the next EXIT that follows it -- this project's live scheduler only
// ever holds one open position per config at a time, so ENTRY/EXIT rows already
// alternate cleanly. A trailing, unpaired ENTRY (an open position) and a leading,
// unpaired EXIT (no preceding ENTRY in this data window) are both dropped rather
// than fabricated into a fake round trip. Returns newest-first, matching this
// site's other trade/ledger displays.
export function buildTradeHistory(
  entry: Pick<StrategyRosterEntry, "name" | "version" | "asset">,
  ledgerRows: LedgerRow[]
): ResolvedTrade[] {
  const matching = ledgerRows.filter(
    (row) => row.strategy === entry.name && row.strategy_version === entry.version && row.asset === entry.asset
  );

  const chronological = [...matching].sort(
    (a, b) => new Date(a.candle_timestamp).getTime() - new Date(b.candle_timestamp).getTime()
  );

  const trades: ResolvedTrade[] = [];
  let pendingEntry: LedgerRow | null = null;

  for (const row of chronological) {
    if (row.signal_type === "ENTRY") {
      pendingEntry = row;
    } else if (row.signal_type === "EXIT" && pendingEntry) {
      const rMultiple = extractRMultiple(row.reasoning);
      trades.push({
        entryTimestamp: pendingEntry.timestamp,
        entryPrice: pendingEntry.entry_price,
        exitTimestamp: row.timestamp,
        exitPrice: row.exit_price,
        result: resultFor(pendingEntry.entry_price, row.exit_price, rMultiple),
        rMultiple,
      });
      pendingEntry = null;
    }
  }

  return trades.reverse();
}
