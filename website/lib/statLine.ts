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

  if (!match || match.resolved_trades <= 0) {
    return AWAITING_FIRST_SIGNAL;
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
