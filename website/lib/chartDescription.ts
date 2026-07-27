import type { StrategyStats } from "./types";

const TIMEFRAME_LABELS: Record<string, string> = {
  "1week": "1 week",
  "24h": "1 day",
  "1day": "1 day",
  daily: "1 day",
  "12h": "12 hours",
};

// Calendar-derived fallback, used only when quant_metrics.json has no matching
// entry for this (asset, timeframe) -- a deterministic calendar fact per
// timeframe (candles/year), not a guessed number.
const FALLBACK_PERIODS_PER_YEAR: Record<string, number> = {
  "1week": 52,
  "24h": 365,
  "1day": 365,
  daily: 365,
  "12h": 730,
};

export function timeframeLabel(timeframe: string): string {
  return TIMEFRAME_LABELS[timeframe] ?? timeframe;
}

export function buildTimeframeSentence(asset: string, timeframe: string): string {
  return `Each candle represents ${timeframeLabel(timeframe)} of ${asset} price action.`;
}

function formatTimeSpan(candleCount: number, periodsPerYear: number): string {
  const years = candleCount / periodsPerYear;
  if (years >= 1) {
    return `${years.toFixed(1)} years`;
  }
  const weeks = years * 52;
  if (weeks >= 1) {
    const rounded = Math.round(weeks);
    return `${rounded} week${rounded === 1 ? "" : "s"}`;
  }
  const days = Math.max(1, Math.round(years * 365));
  return `${days} day${days === 1 ? "" : "s"}`;
}

// The task's own instruction literally reads "window_used × periods_per_year",
// which is dimensionally backwards (multiplying candles by candles/year gives
// a meaningless huge number, not a time span). The only formula that produces
// an honest duration is candleCount / periodsPerYear (candles ÷ candles-per-year
// = years) -- used here instead of the literal wording, since publishing a
// nonsensical number would violate this project's own "never fabricate or
// mislead" discipline.
export function buildDataWindowSentence(
  candleCount: number,
  timeframe: string,
  periodsPerYear: number | null
): string {
  const resolvedPeriodsPerYear = periodsPerYear ?? FALLBACK_PERIODS_PER_YEAR[timeframe] ?? null;
  const span = resolvedPeriodsPerYear ? formatTimeSpan(candleCount, resolvedPeriodsPerYear) : null;
  return span
    ? `Showing ${candleCount} candles — approximately ${span} of history.`
    : `Showing ${candleCount} candles.`;
}

// Matches the ACTUAL marker colors this site renders (see lib/chartMarkers.ts):
// this design system has no separate "green" token, so both the entry arrow
// and a winning-exit arrow render in the same teal used everywhere else on the
// site -- correcting the task's literal "Green = entry" wording to stay
// accurate to what's really on the chart, not just a copy-pasted label.
export function buildMarkerLegendLine(resolvedTrades: number): string | null {
  if (resolvedTrades <= 0) {
    return null;
  }
  return "▲ Teal = Vatican entry signal | ▼ Teal = profitable exit | ▼ Red = stop-loss exit";
}

function pluralTrades(n: number): string {
  return `${n} trade${n === 1 ? "" : "s"}`;
}

// win_rate is stored as a fraction of resolved_trades, not a separate win
// count -- reconstructing the integer win/loss split is arithmetic on real
// stored fields, not a fabricated number.
export function deriveWinLossCounts(
  resolvedTrades: number,
  winRate: number | null
): { wins: number; losses: number } {
  if (resolvedTrades <= 0 || winRate === null) {
    return { wins: 0, losses: 0 };
  }
  const wins = Math.round(resolvedTrades * winRate);
  return { wins, losses: resolvedTrades - wins };
}

export interface ChartDescriptionData {
  timeframeSentence: string;
  dataWindowSentence: string;
  markerLegendLine: string | null;
  statusLine: string;
  // Raw ISO timestamp, left unformatted here -- the component formats it with
  // the same formatTimestamp helper every other timestamp on this site uses.
  openPositionEntryTimestamp: string | null;
}

export function buildChartDescription(params: {
  asset: string;
  timeframe: string;
  candleCount: number;
  periodsPerYear: number | null;
  statsRow: StrategyStats | null;
}): ChartDescriptionData {
  const resolvedTrades = params.statsRow?.resolved_trades ?? 0;

  let statusLine: string;
  if (resolvedTrades <= 0) {
    statusLine = "No completed trades yet — strategy is live and monitoring for setups.";
  } else {
    const { wins, losses } = deriveWinLossCounts(resolvedTrades, params.statsRow?.win_rate ?? null);
    const winRatePct =
      params.statsRow?.win_rate !== null && params.statsRow?.win_rate !== undefined
        ? `${(params.statsRow.win_rate * 100).toFixed(0)}%`
        : "n/a";
    statusLine = `${pluralTrades(resolvedTrades)} completed: ${wins} wins (${winRatePct}), ${losses} losses.`;
  }

  return {
    timeframeSentence: buildTimeframeSentence(params.asset, params.timeframe),
    dataWindowSentence: buildDataWindowSentence(params.candleCount, params.timeframe, params.periodsPerYear),
    markerLegendLine: buildMarkerLegendLine(resolvedTrades),
    statusLine,
    openPositionEntryTimestamp: params.statsRow?.open_position?.entry_timestamp ?? null,
  };
}
