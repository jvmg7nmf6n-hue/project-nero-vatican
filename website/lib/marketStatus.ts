import { classifyAsset } from "./assetClass";
import type { Candle } from "./candleData";
import type { SignalState } from "./signalState";

const MS_PER_MINUTE = 60_000;

export function latestPrice(candles: Candle[]): number | null {
  return candles.length > 0 ? candles[candles.length - 1].close : null;
}

export function priceChangePercent(candles: Candle[]): number | null {
  if (candles.length < 2) {
    return null;
  }
  const last = candles[candles.length - 1].close;
  const prev = candles[candles.length - 2].close;
  if (prev === 0) {
    return null;
  }
  return ((last - prev) / prev) * 100;
}

// Format rule is by ASSET CLASS, not by price magnitude -- GOLD (~$3,287) and
// BTC (~$65,432) are both four-plus-digit prices but the task's own examples
// want different precision for each, so this can't be a price-threshold rule.
export function formatPrice(asset: string, price: number): string {
  const { assetClass } = classifyAsset(asset);
  if (assetClass === "Forex") {
    return price.toFixed(4);
  }
  if (assetClass === "Crypto") {
    return `$${Math.round(price).toLocaleString("en-US")}`;
  }
  return `$${price.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

// Only the 3 timeframes an actual candle file can carry (see
// nero_core/execution/export_candle_data.py's IN_SCOPE_PAIRS cadence values)
// have a well-defined "next candle" boundary rule here -- anything else
// returns null rather than guessing a boundary that was never specified.
const SUPPORTED_COUNTDOWN_TIMEFRAMES = new Set(["1week", "24h", "12h"]);

export function nextCandleBoundaryMs(lastCandleTimeSeconds: number, timeframe: string): number | null {
  if (!SUPPORTED_COUNTDOWN_TIMEFRAMES.has(timeframe)) {
    return null;
  }
  const last = new Date(lastCandleTimeSeconds * 1000);
  const startOfDay = Date.UTC(last.getUTCFullYear(), last.getUTCMonth(), last.getUTCDate());

  if (timeframe === "1week") {
    const dayOfWeek = new Date(startOfDay).getUTCDay(); // 0=Sun .. 6=Sat, Monday=1
    let daysUntilMonday = (1 - dayOfWeek + 7) % 7;
    if (daysUntilMonday === 0) {
      daysUntilMonday = 7; // already exactly on a Monday boundary -- next one is a full week away
    }
    return startOfDay + daysUntilMonday * 24 * 60 * MS_PER_MINUTE;
  }

  if (timeframe === "12h") {
    const hour = last.getUTCHours();
    return hour < 12 ? startOfDay + 12 * 60 * MS_PER_MINUTE : startOfDay + 24 * 60 * MS_PER_MINUTE;
  }

  // "24h"
  return startOfDay + 24 * 60 * MS_PER_MINUTE;
}

export function formatCountdown(remainingMs: number): string {
  if (remainingMs <= 0) {
    return "due now";
  }
  const totalMinutes = Math.floor(remainingMs / MS_PER_MINUTE);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return hours === 0 ? `${minutes}m` : `${hours}h ${minutes}m`;
}

export type MarketSignalStatus = "ENTRY ACTIVE" | "WATCHING" | "NO SIGNAL";

// "exit" (just closed a position) and "watching" (evaluated, no position) both
// read as "monitoring, nothing open right now" to a visitor -- the same
// collapse WATCHING already gets in lib/signalState.ts for WATCH/NO_TRADE.
export function mapSignalStateToMarketStatus(state: SignalState): MarketSignalStatus {
  if (state === "entry") {
    return "ENTRY ACTIVE";
  }
  if (state === "no_signal_yet") {
    return "NO SIGNAL";
  }
  return "WATCHING";
}
