import type { Candle } from "./candleData";
import type { ResolvedTrade, TradeResult } from "./tradeHistory";

export type MarkerShape = "arrowUp" | "arrowDown";
export type MarkerPosition = "aboveBar" | "belowBar";

// Shape matches lightweight-charts' own SeriesMarker<Time> exactly (time/position/
// color/shape/text) -- defined independently here (not imported from the library)
// so this file stays a pure, framework-free unit -- testable with plain data, no
// canvas/DOM, no lightweight-charts import at all.
export interface ChartMarker {
  time: number;
  position: MarkerPosition;
  color: string;
  shape: MarkerShape;
  text: string;
}

// This design system has no separate "green" token -- teal (#2ec4b6) is its one
// positive/green color throughout (win-rate coloring, up-candles, etc.), so ENTRY
// ("green upward triangle") and a winning EXIT ("teal downward triangle") share the
// same teal, differing only in shape/position. Losing EXIT reuses the same loss-red
// (#d47a6a) used everywhere else on the site. "Flat" (a real ResolvedTrade.result
// value the task's two named cases don't cover -- e.g. COINTEGRATION_PAIRS-style
// exits) gets a neutral muted color rather than being silently dropped or guessed
// into a win/loss bucket it isn't.
const ENTRY_COLOR = "#2ec4b6";
const EXIT_COLOR_BY_RESULT: Record<TradeResult, string> = {
  win: "#2ec4b6",
  loss: "#d47a6a",
  flat: "#8a94ad",
};

function toUnixSeconds(iso: string): number | null {
  const ms = new Date(iso).getTime();
  return Number.isNaN(ms) ? null : Math.floor(ms / 1000);
}

// Builds ENTRY/EXIT markers for every resolved trade whose timestamp falls within
// the fetched candle window -- a trade older than the last 200 candles (or, in
// principle, newer than "now") is silently excluded, never an error and never
// clamped into a fake in-range position.
export function buildChartMarkers(trades: ResolvedTrade[], candles: Candle[]): ChartMarker[] {
  if (candles.length === 0) {
    return [];
  }
  const times = candles.map((c) => c.time);
  const minTime = Math.min(...times);
  const maxTime = Math.max(...times);
  const inRange = (t: number) => t >= minTime && t <= maxTime;

  const markers: ChartMarker[] = [];
  for (const trade of trades) {
    const entryTime = toUnixSeconds(trade.entryTimestamp);
    if (entryTime !== null && inRange(entryTime)) {
      markers.push({ time: entryTime, position: "belowBar", color: ENTRY_COLOR, shape: "arrowUp", text: "ENTRY" });
    }

    const exitTime = toUnixSeconds(trade.exitTimestamp);
    if (exitTime !== null && inRange(exitTime)) {
      markers.push({
        time: exitTime,
        position: "aboveBar",
        color: EXIT_COLOR_BY_RESULT[trade.result],
        shape: "arrowDown",
        text: "EXIT",
      });
    }
  }

  // lightweight-charts requires markers sorted ascending by time.
  return markers.sort((a, b) => a.time - b.time);
}
