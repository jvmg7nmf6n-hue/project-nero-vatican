import type { StrategyRosterEntry, StrategyStats } from "./types";

export const AWAITING_FIRST_SIGNAL = "awaiting first signal";

// stats.json keys resolve by (strategy, strategy_version, asset) -- the same
// exact key discipline verification_status.py uses -- so a strategy with two
// live versions against the same asset can't be conflated.
export function deriveStatLine(
  entry: Pick<StrategyRosterEntry, "name" | "version" | "asset">,
  stats: StrategyStats[]
): string {
  const match = stats.find(
    (row) =>
      row.strategy === entry.name &&
      row.strategy_version === entry.version &&
      row.asset === entry.asset
  );
  const unverifiedTrades = match?.unverified_trades ?? 0;
  const unverifiedOpenEntries = match?.unverified_open_entries ?? 0;

  if (!match || (match.resolved_trades <= 0 && unverifiedTrades <= 0 && unverifiedOpenEntries <= 0)) {
    return AWAITING_FIRST_SIGNAL;
  }

  // Trades happened (round trips exist in the raw ledger) but none survived
  // the export's quarantine filter yet -- an honest "we don't know" instead
  // of either fabricating a stat from unverified data or claiming no signal
  // has happened at all. See nero_core.execution.export_site_data's
  // unverified_trades docstring for the incident this state exists to fix.
  if (match.resolved_trades <= 0 && unverifiedTrades > 0) {
    return `${unverifiedTrades} trade${unverifiedTrades === 1 ? "" : "s"} pending source verification`;
  }

  // Phase 1 Fix A (docs/investigations/phase_a_pead_ledger_anomaly.md): same
  // honesty pattern, for a currently-OPEN entry whose source can't be
  // confirmed yet (no resolved round trip exists at all, unlike the case
  // above). Checked after unverifiedTrades so a strategy with both a past
  // unverified round trip and a new unverified open entry still leads with
  // the resolved-trade message.
  if (match.resolved_trades <= 0 && unverifiedOpenEntries > 0) {
    const entryWord = unverifiedOpenEntries === 1 ? "entry" : "entries";
    return `${unverifiedOpenEntries} ${entryWord} pending source verification`;
  }

  const trades = `${match.resolved_trades} resolved trade${
    match.resolved_trades === 1 ? "" : "s"
  }`;

  if (match.win_rate === null) {
    return trades;
  }

  const winRatePct = Math.round(match.win_rate * 1000) / 10;
  return `${trades} · ${winRatePct}% win rate`;
}
