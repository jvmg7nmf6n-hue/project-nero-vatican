"use client";

import { useState } from "react";
import CandlestickChart, { type ChartOverlayToggles } from "./CandlestickChart";
import EquityCurveChart from "./EquityCurveChart";
import type { Candle } from "@/lib/candleData";
import type { ChartMarker } from "@/lib/chartMarkers";
import type { EquityCurve } from "@/lib/equityCurve";

// CC-1 Part D2: overlay toggles, off by default -- the raw candlestick chart
// stays the default view, overlays are opt-in.
const OVERLAY_LABELS: Record<keyof ChartOverlayToggles, string> = {
  ma: "MA20",
  ema: "EMA20",
  bollinger: "Bollinger Bands",
  vwap: "VWAP",
};

type ChartTab = "price" | "equity";
export type PriceChartUnavailableReason = "missing" | "error" | null;

export interface ChartTabsProps {
  candles: Candle[] | null;
  markers: ChartMarker[];
  equityCurve: EquityCurve | null;
  priceChartUnavailableReason?: PriceChartUnavailableReason;
}

const TAB_LABELS: Record<ChartTab, string> = {
  price: "Price Chart",
  equity: "Equity Curve",
};

// Toggle between the candlestick chart (Day 2) and the pre-existing equity curve --
// neither replaces the other. Defaults to whichever view actually has content, so a
// strategy with trade history but no chart data yet doesn't open on an empty
// placeholder tab.
export default function ChartTabs({
  candles,
  markers,
  equityCurve,
  priceChartUnavailableReason = null,
}: ChartTabsProps) {
  const hasPriceChart = candles !== null && candles.length > 0;
  const [activeTab, setActiveTab] = useState<ChartTab>(hasPriceChart ? "price" : "equity");
  const [overlays, setOverlays] = useState<ChartOverlayToggles>({});

  const toggleOverlay = (key: keyof ChartOverlayToggles) => {
    setOverlays((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  return (
    <div>
      <div data-testid="chart-tabs" className="mb-4 flex gap-2">
        {(Object.keys(TAB_LABELS) as ChartTab[]).map((tab) => (
          <button
            key={tab}
            type="button"
            data-testid={`tab-${tab === "price" ? "price-chart" : "equity-curve"}`}
            aria-pressed={activeTab === tab}
            onClick={() => setActiveTab(tab)}
            className={`rounded-md px-4 py-2 text-sm font-medium transition ${
              activeTab === tab
                ? "bg-gold text-ink"
                : "border border-gold/30 text-muted hover:text-parchment"
            }`}
          >
            {TAB_LABELS[tab]}
          </button>
        ))}
      </div>

      {activeTab === "price" ? (
        hasPriceChart ? (
          <>
            <div data-testid="chart-overlay-toggles" className="mb-3 flex flex-wrap gap-3 text-xs text-muted">
              {(Object.keys(OVERLAY_LABELS) as (keyof ChartOverlayToggles)[]).map((key) => (
                <label key={key} className="flex items-center gap-1.5 cursor-pointer">
                  <input
                    type="checkbox"
                    data-testid={`overlay-toggle-${key}`}
                    checked={Boolean(overlays[key])}
                    onChange={() => toggleOverlay(key)}
                    className="accent-gold"
                  />
                  {OVERLAY_LABELS[key]}
                </label>
              ))}
            </div>
            <CandlestickChart candles={candles as Candle[]} markers={markers} overlays={overlays} />
          </>
        ) : (
          <p data-testid="price-chart-unavailable" className="text-muted">
            {priceChartUnavailableReason === "error"
              ? "Price data temporarily unavailable."
              : "Price chart coming soon."}
          </p>
        )
      ) : equityCurve ? (
        <EquityCurveChart curve={equityCurve} />
      ) : (
        <p data-testid="equity-curve-awaiting" className="text-muted">
          Awaiting first trade for chart.
        </p>
      )}
    </div>
  );
}
