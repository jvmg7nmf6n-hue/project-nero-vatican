"use client";

import { useEffect, useState } from "react";
import { formatCountdown, nextCandleBoundaryMs } from "@/lib/marketStatus";
import type { MarketSignalStatus } from "@/lib/marketStatus";
import { REGIME_COLOR } from "@/lib/quantCrossAsset";
import type { VolatilityRegimeEntry } from "@/lib/types";

// Tailwind's content scanner only reads app/**/*.{ts,tsx} and
// components/**/*.{ts,tsx} (not lib/), so this lookup table -- like
// StrategyCard.tsx's SIGNAL_STATE_STYLES -- lives here, not in lib/marketStatus.ts.
const SIGNAL_PILL_STYLES: Record<MarketSignalStatus, string> = {
  "ENTRY ACTIVE": "bg-teal/20 text-teal border-teal/50",
  WATCHING: "bg-muted/10 text-muted border-muted/40",
  "NO SIGNAL": "bg-muted/5 text-muted/70 border-muted/20",
};

export interface MarketStatusWidgetProps {
  priceDisplay: string | null;
  changePercent: number | null;
  regime: VolatilityRegimeEntry | null;
  lastCandleTimeSeconds: number | null;
  timeframe: string;
  signalStatus: MarketSignalStatus;
}

export default function MarketStatusWidget({
  priceDisplay,
  changePercent,
  regime,
  lastCandleTimeSeconds,
  timeframe,
  signalStatus,
}: MarketStatusWidgetProps) {
  const [now, setNow] = useState<number>(() => Date.now());

  useEffect(() => {
    const intervalId = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(intervalId);
  }, []);

  const boundaryMs = lastCandleTimeSeconds !== null ? nextCandleBoundaryMs(lastCandleTimeSeconds, timeframe) : null;
  const countdownLabel = boundaryMs !== null ? formatCountdown(boundaryMs - now) : null;

  const regimeValue = regime?.regime ?? "NO_DATA";
  const changeColorClass = changePercent === null ? "text-muted" : changePercent >= 0 ? "text-teal" : "text-loss";

  return (
    <div
      data-testid="market-status-widget"
      className="flex flex-wrap items-center gap-x-6 gap-y-2 rounded-lg border border-gold/20 px-4 py-3 text-sm"
    >
      <div data-testid="status-price" className="font-serif text-parchment">
        {priceDisplay ?? "—"}
      </div>
      <div data-testid="status-change" className={changeColorClass}>
        {changePercent === null ? "—" : `${changePercent >= 0 ? "+" : ""}${changePercent.toFixed(2)}%`}
      </div>
      <div data-testid="status-regime" data-regime={regimeValue} className="flex items-center gap-1.5">
        <span aria-hidden="true" style={{ color: REGIME_COLOR[regimeValue] }}>
          ●
        </span>
        <span className="text-muted">{regimeValue === "NO_DATA" ? "NO DATA" : regimeValue}</span>
      </div>
      <div data-testid="status-countdown" className="text-muted">
        {countdownLabel ? `Next candle: ${countdownLabel}` : "—"}
      </div>
      <span
        data-testid="status-signal-pill"
        data-status={signalStatus}
        className={`rounded-full border px-2 py-0.5 text-xs font-medium ${SIGNAL_PILL_STYLES[signalStatus]}`}
      >
        {signalStatus}
      </span>
    </div>
  );
}
