import type { ResolvedTrade, TradeResult } from "./tradeHistory";

export type EquityCurveUnit = "r_multiple" | "pct_return";

export interface EquityCurvePoint {
  index: number;
  cumulativeValue: number;
  tradeResult: TradeResult;
}

export interface EquityCurve {
  unit: EquityCurveUnit;
  points: EquityCurvePoint[];
}

// Prefers cumulative R-multiple (the honest, risk-normalized unit this project
// uses everywhere else) when every resolved trade has one; falls back to
// cumulative % return (exit vs entry price) when any trade doesn't -- e.g.
// COINTEGRATION_PAIRS' reasoning never carries an r_multiple (see
// lib/tradeHistory.ts) -- mirroring the same fallback nero_core.execution.
// export_site_data.py's own stats computation already uses. Never mixes the two
// units within one curve.
export function buildEquityCurve(trades: ResolvedTrade[]): EquityCurve {
  // buildTradeHistory returns newest-first; a cumulative curve needs chronological order.
  const chronological = [...trades].reverse();
  const unit: EquityCurveUnit = chronological.every((trade) => trade.rMultiple !== null)
    ? "r_multiple"
    : "pct_return";

  let cumulative = 0;
  const points: EquityCurvePoint[] = chronological.map((trade, i) => {
    const value =
      unit === "r_multiple"
        ? (trade.rMultiple as number)
        : trade.entryPrice !== null && trade.exitPrice !== null && trade.entryPrice !== 0
          ? ((trade.exitPrice - trade.entryPrice) / trade.entryPrice) * 100
          : 0;
    cumulative += value;
    return { index: i + 1, cumulativeValue: cumulative, tradeResult: trade.result };
  });

  return { unit, points };
}
