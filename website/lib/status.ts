import type { LedgerRow, StrategyRosterEntry } from "./types";

export const NO_SIGNAL_YET = "no signal yet";

// recentRows is expected newest-first (as ledger_recent.json is written by
// export_site_data.py), so the first match is the strategy's current status.
export function deriveCurrentStatus(
  entry: Pick<StrategyRosterEntry, "name" | "asset">,
  recentRows: LedgerRow[]
): string {
  const match = recentRows.find(
    (row) => row.strategy === entry.name && row.asset === entry.asset
  );

  return match ? match.signal_type : NO_SIGNAL_YET;
}
