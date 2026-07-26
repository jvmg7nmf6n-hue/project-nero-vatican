import { candleFileTimeframe } from "./candleData";
import type { QuantMetricsEntry } from "./types";

// Matches a strategy's own (asset, roster timeframe) to its quant_metrics.json
// entry -- entries are keyed by the exact same (asset, FILE timeframe) pair Day 2's
// candle lookup already uses (see candleFileTimeframe's "daily" -> "24h" alias,
// e.g. NEWS_SENTIMENT/GOLD), so two strategies sharing that same pair (e.g.
// RANGE_MEAN_REVERSION's two BTC/24h versions) correctly resolve to the identical
// entry -- these metrics are per-asset(+timeframe), never per-strategy.
export function findQuantMetricsForAsset(
  metrics: QuantMetricsEntry[],
  asset: string,
  rosterTimeframe: string
): QuantMetricsEntry | null {
  const fileTimeframe = candleFileTimeframe(rosterTimeframe);
  return metrics.find((entry) => entry.asset === asset && entry.timeframe === fileTimeframe) ?? null;
}

export interface QuantMetricCard {
  key: string;
  label: string;
  value: string | null; // null -> render a muted em-dash, never a fabricated number
  explanation: string;
}

function formatSigned(value: number, digits: number, suffix: string = ""): string {
  const sign = value >= 0 ? "+" : "";
  return `${sign}${value.toFixed(digits)}${suffix}`;
}

// Five independent cards, never a composite/rank/"overall" figure -- each line
// is written to be understandable on its own, matching this panel's research/
// education framing (Vatican does not place orders; this is analytical context).
export function buildQuantMetricCards(entry: QuantMetricsEntry): QuantMetricCard[] {
  return [
    {
      key: "log_return_annualized",
      label: "Annualized Return",
      value: entry.log_return_annualized === null ? null : formatSigned(entry.log_return_annualized * 100, 1, "%"),
      explanation: "Mean per-period log return, scaled to a one-year rate -- the trailing trend's pace, not a forecast.",
    },
    {
      key: "zscore_current",
      label: "Price Z-Score",
      value: entry.zscore_current === null ? null : formatSigned(entry.zscore_current, 2),
      explanation:
        "How many standard deviations the latest close sits from its own trailing average -- a stretch reading, not a statistical test (price trends, so it isn't stationary).",
    },
    {
      key: "realized_vol_annualized",
      label: "Realized Volatility",
      value: entry.realized_vol_annualized === null ? null : `${entry.realized_vol_annualized.toFixed(1)}%`,
      explanation: "Annualized standard deviation of per-period returns over the trailing window -- higher means bigger typical price swings.",
    },
    {
      key: "sharpe",
      label: "Sharpe",
      value: entry.sharpe === null ? null : entry.sharpe.toFixed(2),
      explanation: `Excess return per unit of total volatility over the trailing window (risk-free rate ${(entry.rf_annual * 100).toFixed(2)}%).`,
    },
    {
      key: "sortino",
      label: "Sortino",
      value: entry.sortino === null ? null : entry.sortino.toFixed(2),
      explanation: "Same excess return, but only downside (below-target) volatility counts against it -- upside swings aren't penalized.",
    },
  ];
}
